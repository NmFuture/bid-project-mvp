from __future__ import annotations

"""技术标项目事实表维护（方案 B，T5/T6 后端侧）。

职责：
1. 组装 bid-tech-fact-curator skill 的 manifest（全量字段 + 招标文件解析产物路径 + 相关素材路径）；
2. 调用 opencode 运行 skill；
3. 回收逐字段建议并落表——硬约束：
   - 建议值直接可用（状态由有无取值决定），sourceRefs 追加 type=factCurator 留痕；
   - 绝不覆盖人工写过的字段（sourceRefs 带人工标记或已标不适用）；
   - 找不到值的字段保持 unextracted 并在 notes 写原因。

产品裁决 2026-08-10：取消「AI 建议需人工点确认」这道闸门。规则抽取同样不保证准确，
两者都是机器给的候选，一视同仁直接落值；不对由人在页面上改，改过即带人工标记。
"""

import copy
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.core.config import BASE_DIR, settings
from app.services.opencode_client import OpencodeClient
from app.services.technical_fact_spec_global import resolve_fact_specs
from app.services.technical_fact_material_classes import (
    build_fact_material_check,
    classify_material,
    material_class_of,
    material_home_project,
)
from app.services.technical_gap_fact_table import (
    FACT_MATERIAL_USAGE_CURATE,
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_NOT_APPLICABLE,
    FACT_STATUS_UNEXTRACTED,
    fact_label_key,
    is_human_authored_fact_field,
    normalize_fact_source_refs,
    normalize_fact_status,
    project_fact_material_index,
    project_fact_material_work_dir,
    summarize_project_fact_fields,
)
from app.services.project_fact_materials import project_fact_material_cached_path
from app.services.turbine_models import material_model_fit, project_turbine_model
from app.services.workspace_artifacts import technical_workspace_dir, technical_workspace_parse_dir

logger = logging.getLogger(__name__)

FACT_CURATE_SCHEMA_VERSION = "bid-tech-fact-curate-v1"
TECHNICAL_FACT_CURATOR_SKILL_NAME = "bid-tech-fact-curator"
FACT_CURATOR_RUNNER = (
    BASE_DIR / "opencode" / "skills" / TECHNICAL_FACT_CURATOR_SKILL_NAME / "scripts" / "run_from_manifest.py"
)
FACT_CURATOR_SOURCE_REF_TYPE = "factCurator"

CURATE_ACTION_FILL = "fill"
CURATE_ACTION_FIX = "fix"
CURATE_ACTIONS = {CURATE_ACTION_FILL, CURATE_ACTION_FIX}

# 字段全部了结（有值或人工标不适用）时表级才是 confirmed，否则降回 draft。
_FACT_TERMINAL_STATUSES = {
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_NOT_APPLICABLE,
}

# manifest 中带给 skill 的素材清单上限：清单只有元数据（约 370B/条），正文由 skill 按
# materialFetch 现取，所以按覆盖三层素材范围来设，而不是按 prompt 体积压缩
_CURATOR_MATERIAL_LIMIT = 200

# 缺失类别注入的跨项目候选每类上限（占用 _CURATOR_MATERIAL_LIMIT 额度，本项目素材优先）
_CURATOR_CROSS_PROJECT_LIMIT = 3


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _curator_work_dir(project: dict[str, Any]) -> Path:
    work_dir = technical_workspace_dir(str(project.get("id") or "")) / "s4_gap_workdir" / "fact_curate"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _curator_run_dir(project: dict[str, Any]) -> Path:
    """为单次维护任务创建隔离目录，避免同项目并发任务互相覆盖产物。"""
    run_dir = _curator_work_dir(project) / f"run-{uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _tender_sources(project: dict[str, Any]) -> list[dict[str, str]]:
    """招标文件解析产物路径：只放真实存在的文件。"""
    parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
    candidates = [
        ("combinedText", parse_storage.get("combinedTextPath")),
        ("structured", parse_storage.get("structuredResultPath")),
        ("parseManifest", parse_storage.get("skillManifestPath") or parse_storage.get("manifestPath")),
    ]
    # 工作区 parse 目录兜底（parse_storage 缺键时）
    parse_dir = technical_workspace_parse_dir(str(project.get("id") or ""))
    candidates.append(("combinedText", parse_dir / "combined.txt"))
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for kind, raw_path in candidates:
        path_text = str(raw_path or "").strip()
        if not path_text or path_text in seen:
            continue
        path = Path(path_text)
        if not path.is_file():
            continue
        seen.add(path_text)
        sources.append({"kind": kind, "path": path_text})
    return sources


def _cross_project_curator_candidates(
    project: dict[str, Any],
    gap_state: dict[str, Any],
    own_materials: list[dict[str, Any]],
    remaining: int,
) -> list[dict[str, Any]]:
    """预检缺失类别的跨项目候选（每类最多 _CURATOR_CROSS_PROJECT_LIMIT 份，占用剩余额度）。"""
    if remaining <= 0:
        return []
    try:
        check = build_fact_material_check(project, gap_state)
    except Exception:
        logger.exception("事实表维护跨项目候选查询失败，按无候选继续")
        return []
    own_ids = {str(material.get("id") or "") for material in own_materials}
    candidates: list[dict[str, Any]] = []
    for material_class in check.get("classes") or []:
        if not isinstance(material_class, dict) or not material_class.get("missing"):
            continue
        for candidate in (material_class.get("crossProjectCandidates") or [])[:_CURATOR_CROSS_PROJECT_LIMIT]:
            if remaining <= 0:
                return candidates
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("id") or "")
            if not candidate_id or candidate_id in own_ids:
                continue
            own_ids.add(candidate_id)
            candidates.append(dict(candidate))
            remaining -= 1
    return candidates


def _material_fetch_endpoint(project_id: str) -> dict[str, str]:
    """素材按需拉取入口：以 {materialId} 占位，skill 替换后 POST 即得本地路径。"""
    base = settings.bid_internal_api_base_url.rstrip("/")
    return {
        "method": "POST",
        "url": f"{base}/api/technical/projects/{project_id}/gaps/facts/materials/{{materialId}}/fetch",
        "responseField": "path",
    }


def _curator_materials(project: dict[str, Any], gap_state: dict[str, Any]) -> list[dict[str, Any]]:
    """相关素材清单：复用事实表构建的素材索引，已落地的给路径，其余留给 skill 按需拉取。

    每条素材标注 materialClass / homeProject / crossProject（homeProject 非空且 ≠ 本项目名）；
    预检缺失的类别追加跨项目候选（占用 _CURATOR_MATERIAL_LIMIT 额度，本项目素材优先），
    供 skill 定向读取。清单只带元数据，正文由 skill 按需取，不在构造 manifest 时全量下载。
    """
    materials = project_fact_material_index(project, gap_state, usage=FACT_MATERIAL_USAGE_CURATE)
    own = materials[:_CURATOR_MATERIAL_LIMIT]
    candidates = _cross_project_curator_candidates(
        project, gap_state, own, _CURATOR_MATERIAL_LIMIT - len(own)
    )
    if not own and not candidates:
        return []
    cache_dir = project_fact_material_work_dir(project) / "material_index"
    project_name = str(project.get("name") or "")
    turbine_model = project_turbine_model(project)
    result: list[dict[str, Any]] = []
    for material in [*own, *candidates]:
        if not isinstance(material, dict):
            continue
        material_id = str(material.get("id") or material.get("materialId") or "")
        if not material_id:
            continue
        # 明确属于别的机型的素材直接不给：本项目选了上置，下置的认证证书之类没有可用性。
        # material_model_fit 只在素材带了型号且与本项目布局相反时才判 conflict，
        # 通用素材（generic）照常保留。
        if turbine_model and material_model_fit(material, turbine_model) == "conflict":
            continue
        home_project = str(material.get("homeProject") or "") or material_home_project(material)
        # 空值一律不输出。实测 175 份素材里 crossProject 全是 false、materialClass 只有
        # 24 份非空、homeProject 只有 29 份、path 只有 60 份——空值白占 22 KB（约 5500
        # token），而分批并发后每一批都要付一遍。
        item: dict[str, Any] = {
            "id": material_id,
            "name": str(material.get("name") or material.get("cleanedFileName") or ""),
        }
        for key, value in (
            ("folderPath", str(material.get("folderPath") or "")),
            ("materialTier", str(material.get("materialTier") or "")),
            ("materialClass", classify_material(material) or ""),
            ("homeProject", home_project),
        ):
            if value:
                item[key] = value
        if home_project and home_project != project_name:
            item["crossProject"] = True
        # build 阶段已落地的素材直接给路径；未落地的不带 path，由 skill 按 materialFetch 现取
        cached = project_fact_material_cached_path(cache_dir, material_id)
        if cached is None:
            existing = str(material.get("path") or "").strip()
            if existing and Path(existing).is_file():
                cached = Path(existing)
        if cached is not None:
            item["path"] = str(cached)
        result.append(item)
    return result


# 不参与 AI 补抽的来源类别：模板占位（无需取值）、平台输入（人工录入）、自动生成（代码计算）
_NO_FILL_SOURCE_KINDS = {"template", "platform", "derived"}

# 硬门禁的来源类别：值由模板占位或代码推导确定，没有复核余地。
# 平台输入**不在**其中——它有复核价值（实测 AI 从这里抓出「台数 6 台 vs 招标要求 60 台」
# 和「基础形式填成了塔筒型式」两个真实错误），只是不许静默覆盖，改走冲突通道。
_READONLY_SOURCE_KINDS = {"template", "derived"}

def _is_platform_authored_field(field: dict[str, Any]) -> bool:
    """人在建项目时**真的填了值**的字段（投标机型、机组台数、基础形式……）。

    判据是建表时打的 platformAuthored 标记，只在平台值非空时才打。

    两条更省事的判据都不成立：
    - 只看 sourceKind：它由清单「来源文件」列前缀推出，实测 61 个字段里 platform 类
      一个都没有——「投标机型」的来源列写着「项目定制…」被归成 material，
      「机组台数」「基础形式」连 specKey 都是空的（不在清单里，是建表时派生的）。
    - 看有没有 projectTurbineModel 来源标记：那圈字段不论平台值空不空都会挂上它。
      实测 hubHeightM / ratedPowerKw / rotorDiameterM 都是空的，值其实抽自素材，
      误判成平台输入会把 AI 的正确修正降级成"建议"——让「轮毂高度」停在跨列串行
      脏值「池建昌」上，反倒把错值锁死了。
    """
    if field.get("platformAuthored"):
        return True
    return str(field.get("sourceKind") or "") == "platform"


def _is_curator_readonly_field(field: dict[str, Any]) -> bool:
    """AI 复核员不许碰的字段。

    两类：人工写过的（值和口径已由人定案）；模板占位 / 自动生成的（取值由系统推导
    确定，不是从文档里"抽"出来的，没有复核余地）。

    三态收敛前这两类都靠 status==confirmed 一并挡住；现在规则抽取的值也是
    confirmed，必须按来源显式区分。

    平台输入不走这条门禁：它要留在 fix 桶里接受核对，只是落表时不覆盖值，
    见 _is_platform_authored_field 与 apply 侧的冲突分支。
    """
    if is_human_authored_fact_field(field):
        return True
    return str(field.get("sourceKind") or "") in _READONLY_SOURCE_KINDS


def _curate_targets(fields: list[dict[str, Any]], *, fill_only: bool = False) -> dict[str, list[str]]:
    """按方案 B 的两件事给字段分桶，桶内只放 fieldKey。

    fill_only=True 是「AI补空」：只补还没有值的字段，已有的值一律不碰，fix 桶留空。
    """
    targets: dict[str, list[str]] = {"fill": [], "fix": []}
    for field in fields:
        field_key = str(field.get("key") or "").strip()
        if not field_key:
            continue
        if _is_curator_readonly_field(field):
            continue
        # 归一后再分桶：旧项目的 gap_state 里还留着七态，重建前也要分对
        status = normalize_fact_status(field.get("status"), has_value=bool(str(field.get("value") or "").strip()))
        # 补抽范围：招标类 + 素材/证书类未提取字段（模板/平台/自动生成类不交 AI 填）。
        # 平台字段没值是人还没填，AI 不替人做主。
        if status == FACT_STATUS_UNEXTRACTED and not _is_platform_authored_field(field):
            targets["fill"].append(field_key)
        # 脏数据校验只针对从招标文件/素材抽出来的值。平台字段也进这一桶——它要接受
        # 核对，只是落表时走冲突通道不覆盖值。
        if status == FACT_STATUS_CONFIRMED and not fill_only:
            targets["fix"].append(field_key)
    return targets


def split_curate_targets(
    targets: dict[str, list[str]],
    fields: list[dict[str, Any]],
    *,
    max_batches: int,
) -> list[dict[str, list[str]]]:
    """把目标字段聚类切批，每批一个 opencode 会话。

    **聚类**按 materialClass：同类字段读同一批素材，聚在一起省掉重复翻文件，也让
    「定向取数」那条铁律在批内仍然成立。

    **切批大小是算出来的，不设固定阈值。** 清单条数会变（实测这版 59 个，换一版可能
    150 个），写死「单批 N 个字段」会让批数跟着字段数线性涨——批数一超过并发槽位就
    要多跑一波，反而更慢。这里反过来：先由并发能力定批数上限，再按总量均分出批大小。

    只按类别切也不行：实测分布是 tender 25 / wind_resource 20 / none 7 / cert 3 /
    未指定 2 / production_base 2，前两类占 76%，整轮耗时会被最大那批卡死。

    **批数绝不能超过上限**，多出来的一批就是多出来的一整波。实测代价极大：上限 4 时
    早先的实现切出了 5 批，第 5 批只有 4 个字段却让整轮从预期的约 5 分钟变成 10分43秒
    ——4 并发跑 5 批，前 4 批并行完，第 5 批只能等槽位，等于在后面串行接了一整批。
    所以这里对固定的 limit 个桶做装箱：零头塞进最空的桶，不新开批次。

    每批保留 fill / fix 两个桶的结构，落表侧的 action 校验不用改。
    """
    class_of: dict[str, str] = {}
    for field in fields:
        key = str(field.get("key") or "").strip()
        if key:
            class_of[key] = str(field.get("materialClass") or "") or "(未指定)"

    grouped: dict[str, list[tuple[str, str]]] = {}
    total = 0
    for bucket in ("fill", "fix"):
        for raw_key in targets.get(bucket) or []:
            key = str(raw_key or "").strip()
            if not key:
                continue
            grouped.setdefault(class_of.get(key, "(未指定)"), []).append((bucket, key))
            total += 1
    if not total:
        return []

    # 桶数取「上限」与「每桶至少 3 个字段」的较小值。下限 3 是防退化不是调参旋钮：
    # 每个会话的固定开销是实打实的（建会话、读 SKILL.md + rules.md 约 240 行、跑一次
    # factcurate 实测 6.2 秒、写回建议文件），字段少时切碎全在付开销。
    bin_count = max(1, min(int(max_batches), -(-total // 3)))
    bins: list[list[tuple[str, str]]] = [[] for _ in range(bin_count)]
    capacity = -(-total // bin_count)  # ceil，各桶目标容量

    # 大类在前依次装箱：整类装得下就整类进同一个桶（同类字段读同一批素材，聚在一起
    # 能省重复翻文件）；装不下的按容量拆开，碎片一律进当前最空的桶，不新开桶。
    for _, entries in sorted(grouped.items(), key=lambda item: -len(item[1])):
        for start in range(0, len(entries), capacity):
            piece = entries[start : start + capacity]
            target = min(range(bin_count), key=lambda index: len(bins[index]))
            bins[target].extend(piece)

    batches: list[dict[str, list[str]]] = []
    for chunk in bins:
        if not chunk:
            continue
        batch: dict[str, list[str]] = {"fill": [], "fix": []}
        for bucket, key in chunk:
            batch[bucket].append(key)
        batches.append(batch)
    return batches


def _spec_reference_maps(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    """spec 索引：按 key 精确匹配为主，按 seq 兜底（字段 dict 里有 specKey 和 specSeq）。"""
    by_key: dict[str, dict[str, Any]] = {}
    by_seq: dict[int, dict[str, Any]] = {}
    for spec in specs:
        key = str(spec.get("key") or "")
        if key and key not in by_key:
            by_key[key] = spec
        try:
            seq = int(spec.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if seq and seq not in by_seq:
            by_seq[seq] = spec
    return by_key, by_seq


# 交给 agent 的目标字段属性：SKILL.md 输入契约声明的那些。表里每个字段实际带 28 个属性，
# 其余（confirmedBy / updatedAt / sourcePriority / turbineGroup / platformAuthored…）是
# 后端内部账，塞进 prompt 只是噪音。
_TARGET_FIELD_KEYS = (
    "key", "label", "reviewLabel", "value", "unit", "status",
    "sourceKind", "specKey", "specSeq", "referenceFile", "materialClass", "notes",
)
# 非本批目标的字段只给「叫什么、现在是什么值」——够 agent 做交叉印证（知道
# 「投标机型=EW10.0-220」才能校验单机容量、分清场址要求安全等级与机型认证安全等级），
# 不给 sourceRefs/alternatives 那些它用不上的。实测 61 个字段全量 65.4 KB，精简后 5.2 KB。
_CONTEXT_FIELD_KEYS = ("key", "label", "value", "unit")


def _manifest_field(field: dict[str, Any], *, is_target: bool) -> dict[str, Any]:
    if not is_target:
        # 上下文名录：空值直接省掉，它只是给 agent 认路用的
        return {
            key: copy.deepcopy(field.get(key))
            for key in _CONTEXT_FIELD_KEYS
            if field.get(key) not in (None, "")
        } or {"key": str(field.get("key") or ""), "label": str(field.get("label") or "")}
    # 目标字段按 SKILL.md 输入契约给全键位，空值也保留成空串——契约里写着
    # 「value：当前值，可空」，键位缺失会让 agent 分不清「没这个属性」和「属性是空」
    trimmed: dict[str, Any] = {}
    for key in _TARGET_FIELD_KEYS:
        value = field.get(key)
        trimmed[key] = copy.deepcopy(value) if value is not None else ""
    # sourceRefs 只保留类型：agent 要判断的是「这值哪来的」，不需要每条 ref 的完整
    # payload（实测单个字段挂了 9 条）
    refs = field.get("sourceRefs") if isinstance(field.get("sourceRefs"), list) else []
    trimmed["sourceRefTypes"] = sorted(
        {str(ref.get("type") or "") for ref in refs if isinstance(ref, dict) and ref.get("type")}
    )
    return trimmed


def enrich_fields_with_spec_reference(
    table: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """给事实表字段补 referenceFile / materialClass，返回 (字段副本, 规则版本快照)。

    按项目绑定的规则版本关联 spec（R06-B04-02：不再读系统公共清单；项目无绑定时
    resolve_fact_specs 回落系统默认）。skill 靠 materialClass 定向找素材、靠
    referenceFile 分辨招标文件字段；并行切批也靠 materialClass 聚类，所以抽出来共用。
    """
    fields = [copy.deepcopy(field) for field in (table.get("fields") or []) if isinstance(field, dict)]
    project_specs, fact_specs_meta = resolve_fact_specs()
    spec_by_key, spec_by_seq = _spec_reference_maps(project_specs)
    for field in fields:
        spec = spec_by_key.get(str(field.get("specKey") or ""))
        if spec is None:
            try:
                spec = spec_by_seq.get(int(field.get("specSeq") or 0))
            except (TypeError, ValueError):
                spec = None
        field["referenceFile"] = str(spec.get("referenceFile") or "") if spec else ""
        field["materialClass"] = material_class_of(spec) if spec else ""
    return fields, fact_specs_meta


def build_fact_curator_manifest(
    project: dict[str, Any],
    gap_state: dict[str, Any],
    data: dict[str, Any],
    *,
    targets_override: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], Path]:
    """组装 curator manifest 并落盘，返回 (manifest, manifest_path)。

    targets_override 是并行分批用的：**只换 targets，projectFactTable.fields 仍是全表**。
    切分只切「这一批负责哪些字段」，不切「能看见哪些字段」——实测 agent 靠同时看到多个
    相关字段才分得清「招标场址要求安全等级」和「机型认证安全等级」、分得清「功率曲线
    取值的湍流度」和「认证 Iref」。把可见范围也切掉，这种辨析能力就没了。
    """
    table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    fields, fact_specs_meta = enrich_fields_with_spec_reference(table)
    targets = (
        targets_override
        if isinstance(targets_override, dict)
        else _curate_targets(fields, fill_only=bool(data.get("fillOnly")))
    )
    target_keys = {
        str(key or "").strip()
        for bucket in ("fill", "fix")
        for key in (targets.get(bucket) or [])
    }
    work_dir = _curator_run_dir(project)
    manifest = {
        "schemaVersion": FACT_CURATE_SCHEMA_VERSION,
        "projectId": str(project.get("id") or ""),
        "projectName": str(project.get("name") or ""),
        "projectTurbineModel": project_turbine_model(project),
        "operator": str(data.get("operator") or "当前用户"),
        "projectFactTable": {
            "schemaVersion": str(table.get("schemaVersion") or ""),
            # 全表都在，但只有本批负责的字段给完整属性，其余压成「叫什么、什么值」
            "fields": [
                _manifest_field(field, is_target=str(field.get("key") or "").strip() in target_keys)
                for field in fields
            ],
        },
        "targets": targets,
        "tenderSources": _tender_sources(project),
        "materials": _curator_materials(project, gap_state),
        # 素材按需拉取入口：materials 里没有 path 的条目，读取前先取一次拿到本地路径
        "materialFetch": _material_fetch_endpoint(str(project.get("id") or "")),
        # 本次维护任务实际使用的规则版本快照（审计追溯）
        "factSpecsRef": fact_specs_meta,
        "briefFile": str(work_dir / "fact_curate_brief.json"),
        "outputFile": str(work_dir / "fact_curate_suggestions.json"),
    }
    manifest_path = work_dir / "fact_curate_input.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest, manifest_path


def _build_fact_curator_prompt(manifest_path: Path) -> str:
    return f"""
Use the {TECHNICAL_FACT_CURATOR_SKILL_NAME} skill.

你现在在做技术标项目事实表维护（长尾补抽 / 脏数据清洗 / 口径建议）。后端已经准备好 manifest，其中包含事实表全量字段、招标文件解析产物路径和相关素材路径。

manifest：{manifest_path}

请先调用一次 Bash 工具执行下面命令生成证据简报，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径：

factcurate {manifest_path}

然后按 SKILL.md 的流程阅读简报与原文，把逐字段建议写入 manifest 指定的 outputFile。注意：本环境没有 read / write / edit 工具，绝对不要调用它们——读文件用 Bash（grep -n 定位、sed -n 或 cat 取内容）；写建议文件必须用 Bash heredoc 先写 outputFile.tmp（内容多时分段 cat >> 追加），确认 JSON 完整后再 mv -f 改名为 outputFile，绝对不要直接写 outputFile（后端检测到完整文件会立即回收，写一半会被截断收走）。最后只返回小型 JSON（schema、suggestionsPath、counts），不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def run_technical_fact_curator_skill(manifest_path: Path) -> dict[str, Any]:
    """opencode 调用隔离点：测试 patch 本函数即可mock 全链路。"""
    prompt = _build_fact_curator_prompt(manifest_path)
    # early_tool_command 只用于轮询 idle 监管；factcurate 不走提前返回——
    # 建议文件由 LLM 多轮迭代写出（先草稿后填值），「脚本完成/文件落地」都不代表终稿，
    # 提前返回会回收草稿并把会话孤儿化（实测三轮三种竞态），必须等会话自然完成
    return OpencodeClient().run_bid_tech_fact_curator_with_trace(
        prompt,
        early_tool_command="factcurate",
    )


def load_fact_curator_suggestions(result: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """回收逐字段建议：优先读 outputFile（agent 落盘，确定性），兜底取返回 JSON 内联 suggestions。"""
    raw_suggestions: Any = None
    output_path = Path(str(manifest.get("outputFile") or ""))
    if output_path.is_file():
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            raw_suggestions = payload.get("suggestions")
    if raw_suggestions is None:
        raw_suggestions = result.get("suggestions")
    suggestions: list[dict[str, Any]] = []
    for raw in raw_suggestions if isinstance(raw_suggestions, list) else []:
        if not isinstance(raw, dict):
            continue
        field_key = str(raw.get("fieldKey") or "").strip()
        if not field_key:
            continue
        # action 原样保留：非法值在 apply 侧计入 ignored（带原因），不静默降级为 fill
        action = str(raw.get("action") or "").strip()
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        suggestions.append(
            {
                "fieldKey": field_key,
                "suggestedValue": str(raw.get("suggestedValue") or "").strip(),
                "unit": str(raw.get("unit") or "").strip(),
                "evidence": str(raw.get("evidence") or "").strip(),
                "confidence": confidence,
                "action": action,
            }
        )
    return suggestions


def _cross_origin_note(suggestion: dict[str, Any], cross_materials: list[dict[str, Any]] | None) -> str:
    """建议 evidence 引用 crossProject 素材（按素材 id 或素材名匹配）时，给 notes 标注文案。"""
    evidence = str(suggestion.get("evidence") or "")
    if not evidence:
        return ""
    for material in cross_materials or []:
        if not isinstance(material, dict):
            continue
        material_id = str(material.get("id") or "")
        name = str(material.get("name") or "")
        if (material_id and material_id in evidence) or (name and name in evidence):
            home_project = str(material.get("homeProject") or "")
            return f"跨项目来源：{home_project}/{name}" if home_project else f"跨项目来源：{name}"
    return ""


def apply_fact_curator_suggestions(
    table: dict[str, Any],
    suggestions: list[dict[str, Any]],
    *,
    operator: str,
    saved_at: str,
    cross_materials: list[dict[str, Any]] | None = None,
    targets: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """把 curator 建议落到事实表。返回 (更新后的表, 回收报告)。

    cross_materials：manifest 中 crossProject=true 的素材；建议 evidence 引用它们时
    落表 notes 追加「跨项目来源：{homeProject}/{素材名}」。落表状态规则不变（一律 pending_confirmation）。
    """
    table = copy.deepcopy(table)
    fields = [field for field in (table.get("fields") or []) if isinstance(field, dict)]
    # 防御性归一匹配：agent 回传的 fieldKey 可能不是表字段的真实 key
    # （如骨架键 spec-090 被意译成别名、大小写差异）。by_key 两遍登记——
    # 先精确键（key/id/specKey 及其小写形），再 label 的 fact_label_key 归一键；
    # suggestion 侧也按 精确 → 小写 → fact_label_key 顺序回查，仍落空才进 ignored。
    by_key: dict[str, dict[str, Any]] = {}

    def _register(key: str, field: dict[str, Any]) -> None:
        if key and key not in by_key:
            by_key[key] = field

    for field in fields:
        for candidate in (field.get("key"), field.get("id"), field.get("specKey")):
            key = str(candidate or "").strip()
            _register(key, field)
            _register(key.lower(), field)
    for field in fields:
        _register(fact_label_key(field.get("label")), field)

    def _lookup(field_key: str) -> dict[str, Any] | None:
        return (
            by_key.get(field_key)
            or by_key.get(field_key.lower())
            or by_key.get(fact_label_key(field_key))
        )

    actions_by_target: dict[str, set[str]] = {}
    if isinstance(targets, dict):
        for bucket, action in (
            ("fill", CURATE_ACTION_FILL),
            ("fix", CURATE_ACTION_FIX),
        ):
            for target_key in targets.get(bucket) or []:
                key = str(target_key or "").strip()
                if key:
                    actions_by_target.setdefault(key, set()).add(action)

    report: dict[str, Any] = {
        "filled": [],
        "fixed": [],
        "notFound": [],
        "skippedConfirmed": [],
        "ignored": [],
        # 平台输入字段与 AI 查证结果不一致：值保持人选的那个，分歧记在这里等人裁决
        "conflicts": [],
    }
    # 本轮真正写过的字段的**表内规范 key**（不是 agent 回传的 fieldKey，后者可能是别名或
    # 大小写变体）。落表时按它逐字段合并进最新的表，见 merge_curator_fields_into_table。
    touched_keys: set[str] = set()
    for suggestion in suggestions:
        field_key = suggestion["fieldKey"]
        field = _lookup(field_key)
        if field is None:
            report["ignored"].append({"fieldKey": field_key, "reason": "fieldKey 与事实表字段不匹配"})
            continue
        action = suggestion["action"]
        if action not in CURATE_ACTIONS:
            report["ignored"].append({"fieldKey": field_key, "reason": f"非法 action：{action or '空'}"})
            continue
        # 硬门禁优先于目标桶校验：即使 agent 越界回传，只读字段也不许动。
        if _is_curator_readonly_field(field):
            report["skippedConfirmed"].append(field_key)
            continue
        target_key = str(field.get("key") or "").strip()
        allowed_actions = actions_by_target.get(target_key)
        if targets is not None and (not allowed_actions or action not in allowed_actions):
            report["ignored"].append(
                {"fieldKey": field_key, "reason": f"action {action} 与本轮目标桶不匹配"}
            )
            continue
        value = suggestion["suggestedValue"]
        ref = {
            "type": FACT_CURATOR_SOURCE_REF_TYPE,
            "action": action,
            "evidence": suggestion["evidence"],
            "confidence": suggestion["confidence"],
        }
        if not value:
            # 找不到值：保持 unextracted 并在 notes 写原因，不硬填
            if str(field.get("status") or "") == FACT_STATUS_UNEXTRACTED:
                reason = suggestion["evidence"] or "招标文件与素材中未找到取值"
                note = f"事实表维护Skill未找到值：{reason}"
                notes = str(field.get("notes") or "")
                if note not in notes:
                    field["notes"] = f"{notes}；{note}" if notes else note
                report["notFound"].append(field_key)
                touched_keys.add(str(field.get("key") or ""))
            else:
                report["ignored"].append(field_key)
            continue

        old_value_now = str(field.get("value") or "").strip()
        if _is_platform_authored_field(field):
            # 平台输入是人在建项目时选的，AI 不许静默覆盖——但也不能不管：实测它从这里
            # 抓出过「台数 6 台 vs 招标要求 60 台」，那个错会一路进标书。折中是把分歧
            # 显出来：值保持人选的，AI 的候选进 alternatives，原因进 notes，打 hasConflict
            # 供页面标红，由人在页面上裁决改不改。
            if value == old_value_now:
                report["skippedConfirmed"].append(field_key)
                continue
            alternatives = field.setdefault("alternatives", [])
            existing_values = [str(item.get("value") or "") for item in alternatives if isinstance(item, dict)]
            if value not in existing_values:
                alternatives.append({"value": value, "source": copy.deepcopy(ref)})
            note = f"AI 查证与项目信息不一致：建议「{value}」，{suggestion['evidence'] or '未给出理由'}"
            notes = str(field.get("notes") or "")
            if note not in notes:
                field["notes"] = f"{notes}；{note}" if notes else note
            field["hasConflict"] = True
            report["conflicts"].append(
                {
                    "fieldKey": field_key,
                    "label": str(field.get("label") or ""),
                    "currentValue": old_value_now,
                    "suggestedValue": value,
                    "evidence": suggestion["evidence"],
                    "confidence": suggestion["confidence"],
                }
            )
            touched_keys.add(str(field.get("key") or ""))
            continue

        touched_keys.add(str(field.get("key") or ""))
        field["sourceRefs"] = normalize_fact_source_refs([*(field.get("sourceRefs") or []), ref])
        # 跨项目素材证据：notes 追加来源标注，人工确认时可追溯
        origin_note = _cross_origin_note(suggestion, cross_materials)
        if origin_note:
            notes = str(field.get("notes") or "")
            if origin_note not in notes:
                field["notes"] = f"{notes}；{origin_note}" if notes else origin_note
        old_value = str(field.get("value") or "").strip()
        if old_value and old_value != value:
            # 脏数据修正：旧值进 alternatives 留痕
            alternatives = field.setdefault("alternatives", [])
            existing_values = [str(item.get("value") or "") for item in alternatives if isinstance(item, dict)]
            if old_value not in existing_values:
                alternatives.append({"value": old_value, "source": (field.get("sourceRefs") or [{}])[0]})
            report["fixed"].append(field_key)
        else:
            report["filled"].append(field_key)
        field["value"] = value
        if suggestion["unit"]:
            field["unit"] = suggestion["unit"]
        field["status"] = FACT_STATUS_CONFIRMED
        field["confidence"] = suggestion["confidence"]
        field["updatedAt"] = saved_at
        field["updatedBy"] = operator

    table["fields"] = fields
    # specTotal 沿用建表时的口径（项目绑定版本的条数），不被系统默认清单条数覆盖
    previous_summary = table.get("summary") if isinstance(table.get("summary"), dict) else {}
    table["summary"] = summarize_project_fact_fields(
        fields, spec_total=previous_summary.get("specTotal")
    )
    table["updatedAt"] = saved_at
    # curator 绝不写 confirmed；已 confirmed 的表出现新的非终态字段时降回 draft 待人工
    if str(table.get("status") or "") == "confirmed" and not all(
        str(field.get("status") or "") in _FACT_TERMINAL_STATUSES for field in fields
    ):
        table["status"] = "draft"
        table["confirmedAt"] = ""
        table["confirmedBy"] = ""
    report["counts"] = {key: len(value) for key, value in report.items() if isinstance(value, list)}
    # counts 统计完再挂，否则 touchedKeys 会混进前端展示的计数里
    report["touchedKeys"] = sorted(key for key in touched_keys if key)
    return table, report


_REPORT_LIST_KEYS = (
    "filled", "fixed", "notFound", "skippedConfirmed", "ignored", "conflicts", "touchedKeys",
)


def _new_curate_report() -> dict[str, Any]:
    report: dict[str, Any] = {key: [] for key in _REPORT_LIST_KEYS}
    # 分批并发时哪几批失败了要如实带出来，不能只看总数对不对
    report["batchErrors"] = []
    report["manifestPaths"] = []
    report["suggestionCount"] = 0
    return report


def _accumulate_curate_report(merged: dict[str, Any], batch: dict[str, Any]) -> None:
    """把一批的报告并进总报告。counts 由调用方在全部批次收完后统一算。"""
    for key in _REPORT_LIST_KEYS:
        values = batch.get(key)
        if isinstance(values, list):
            merged[key].extend(values)
    merged["suggestionCount"] += int(batch.get("suggestionCount") or 0)
    path = str(batch.get("manifestPath") or "").strip()
    if path:
        merged["manifestPaths"].append(path)


def merge_curator_fields_into_table(
    latest_table: dict[str, Any],
    curated_table: dict[str, Any],
    touched_keys: list[str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """把本轮 curator 写过的字段并进**最新**的事实表，返回 (合并后的表, 被丢弃的字段)。

    不做整表快照对比：AI 一轮要跑十几分钟，期间只要表被动过一个字节，整表比对就把
    整轮结果作废（实测 16 分钟白跑）。这里只搬 touched_keys 点名的字段，其余一律保留
    最新值；每个字段写入前拿**最新那份**重过一次只读门禁，人工在此期间填写或裁定过的
    自动让位，不需要靠"禁止任何人动表"来保证安全。

    丢弃项带原因返回，由调用方写进报告——静默少写几个字段比整轮失败更难排查。
    """
    merged = copy.deepcopy(latest_table)
    latest_fields = [field for field in (merged.get("fields") or []) if isinstance(field, dict)]
    latest_index_by_key: dict[str, int] = {}
    for index, field in enumerate(latest_fields):
        key = str(field.get("key") or "").strip()
        if key and key not in latest_index_by_key:
            latest_index_by_key[key] = index
    curated_by_key: dict[str, dict[str, Any]] = {}
    for field in curated_table.get("fields") or []:
        if not isinstance(field, dict):
            continue
        key = str(field.get("key") or "").strip()
        if key and key not in curated_by_key:
            curated_by_key[key] = field

    dropped: list[dict[str, str]] = []
    for raw_key in touched_keys:
        key = str(raw_key or "").strip()
        if not key:
            continue
        curated = curated_by_key.get(key)
        if curated is None:
            dropped.append({"fieldKey": key, "reason": "本轮结果里找不到该字段"})
            continue
        index = latest_index_by_key.get(key)
        if index is None:
            dropped.append({"fieldKey": key, "reason": "字段已不在最新事实表中（期间重建过或换了清单）"})
            continue
        if _is_curator_readonly_field(latest_fields[index]):
            dropped.append({"fieldKey": key, "reason": "AI 匹配期间该字段已由人工填写或裁定，保留人工结果"})
            continue
        latest_fields[index] = copy.deepcopy(curated)

    merged["fields"] = latest_fields
    previous_summary = merged.get("summary") if isinstance(merged.get("summary"), dict) else {}
    merged["summary"] = summarize_project_fact_fields(latest_fields, spec_total=previous_summary.get("specTotal"))
    merged["updatedAt"] = _now_iso()
    # 与 apply_fact_curator_suggestions 同一条规则：出现非终态字段就把表降回 draft 待人工
    if str(merged.get("status") or "") == "confirmed" and not all(
        str(field.get("status") or "") in _FACT_TERMINAL_STATUSES for field in latest_fields
    ):
        merged["status"] = "draft"
        merged["confirmedAt"] = ""
        merged["confirmedBy"] = ""
    return merged, dropped


def run_fact_curator_for_project(
    project: dict[str, Any],
    gap_state: dict[str, Any],
    data: dict[str, Any],
    *,
    on_phase: Callable[[str, str], None] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """同步重活入口（由后台任务调用）：组 manifest → 调 skill → 回收落表。

    on_phase(phase, message) 在阶段切换时回调，供任务层写进度；不传则静默执行。
    on_progress({batchTotal, batchDone, batchRunning}) 报结构化分批进度，供前端画进度条——
    只有文字的话前端画不出条，而按批完成才更新的话头几分钟看着像卡死。
    """

    def notify(phase: str, message: str = "") -> None:
        if on_phase is None:
            return
        try:
            on_phase(phase, message)
        except Exception:  # noqa: BLE001 - 进度上报失败不该中断主流程
            logger.warning("事实表维护进度上报失败：%s", phase)

    table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    if not table.get("fields"):
        raise ValueError("项目事实表为空，请先构建事实表再运行维护 Skill。")
    notify("组装素材清单", "正在按素材范围组装候选清单。")
    manifest, manifest_path = build_fact_curator_manifest(project, gap_state, data)
    # 清掉上一轮产物：会话未能写出新建议文件时，残留的上一轮回 outputFile 会被
    # load_fact_curator_suggestions 当作本轮结果回收（表现为建议数与上次完全相同）
    for artifact_key in ("outputFile", "briefFile"):
        artifact_text = str(manifest.get(artifact_key) or "").strip()
        if artifact_text:
            artifact = Path(artifact_text)
            if artifact.is_file():
                artifact.unlink()
    targets = manifest.get("targets") if isinstance(manifest.get("targets"), dict) else {}
    target_total = sum(len(targets.get(key) or []) for key in ("fill", "fix"))
    if not target_total:
        # 没有目标字段还开会话，就是白等一轮（实测一轮约 8 分钟）。「AI补空」在表已填满时
        # 最容易撞上这种情况，直接如实返回空报告。
        empty_report = {
            "filled": [],
            "fixed": [],
            "notFound": [],
            "skippedConfirmed": [],
            "ignored": [],
            "conflicts": [],
            "touchedKeys": [],
            "manifestPath": str(manifest_path),
            "suggestionCount": 0,
            "factSpecsRef": manifest.get("factSpecsRef") or {},
            "opencodeOutput": {},
        }
        empty_report["counts"] = {
            key: 0 for key, value in empty_report.items() if isinstance(value, list)
        }
        return copy.deepcopy(table), empty_report
    enriched_fields, _ = enrich_fields_with_spec_reference(table)
    workers = max(1, int(settings.fact_curate_concurrency or 1))
    batches = split_curate_targets(
        targets,
        enriched_fields,
        max_batches=workers * max(1, int(settings.fact_curate_batches_per_slot or 1)),
    )
    operator = str(data.get("operator") or "当前用户")

    # 进度用的计数器。线程池里加减，必须上锁——单看 running 少一个多一个不影响正确性，
    # 但进度条会跳。
    progress_lock = threading.Lock()
    progress = {"done": 0, "running": 0}

    def report_progress() -> None:
        if on_progress is None:
            return
        try:
            with progress_lock:
                snapshot = dict(progress)
            on_progress(
                {
                    "batchTotal": len(batches),
                    "batchDone": snapshot["done"],
                    "batchRunning": snapshot["running"],
                }
            )
        except Exception:  # noqa: BLE001 - 进度上报失败不该中断主流程
            logger.warning("事实表维护分批进度上报失败")

    def run_batch(index: int, batch_targets: dict[str, list[str]]) -> dict[str, Any]:
        """一批 = 一个 opencode 会话。慢活在这里跑，落表由调用方按完成顺序收口。"""
        with progress_lock:
            progress["running"] += 1
        # 开跑就报一次：只在完成时报的话，第一批跑完之前（实测 4 分半）进度纹丝不动，
        # 看着像卡死了
        report_progress()
        try:
            return _run_one_batch(index, batch_targets)
        finally:
            # 减法必须跟加法在同一个线程：放到主线程收口时再减的话，worker 算完到主线程
            # 收走之间有个窗口，槽位已经腾出来让下一批开跑、计数里前一批却还没减掉——
            # 实测显示过「4 并发却有 5 批进行中」
            with progress_lock:
                progress["running"] = max(0, progress["running"] - 1)
            report_progress()

    def _run_one_batch(index: int, batch_targets: dict[str, list[str]]) -> dict[str, Any]:
        batch_manifest, batch_path = build_fact_curator_manifest(
            project, gap_state, data, targets_override=batch_targets
        )
        for artifact_key in ("outputFile", "briefFile"):
            artifact_text = str(batch_manifest.get(artifact_key) or "").strip()
            if artifact_text and Path(artifact_text).is_file():
                Path(artifact_text).unlink()
        batch_result = run_technical_fact_curator_skill(batch_path)
        batch_suggestions = load_fact_curator_suggestions(batch_result, batch_manifest)
        cross = [
            material
            for material in (batch_manifest.get("materials") or [])
            if isinstance(material, dict) and material.get("crossProject")
        ]
        # 每批各自对着开跑时那份表 apply，批之间目标字段不相交，所以互不干扰；
        # 真正的收口由调用方按 touchedKeys 逐字段合并进最新的表
        batch_table, batch_report = apply_fact_curator_suggestions(
            table,
            batch_suggestions,
            operator=operator,
            saved_at=_now_iso(),
            cross_materials=cross,
            targets=batch_targets,
        )
        batch_report["manifestPath"] = str(batch_path)
        batch_report["suggestionCount"] = len(batch_suggestions)
        batch_report["opencodeOutput"] = batch_result.get("opencodeOutput") or {}
        return {"index": index, "table": batch_table, "report": batch_report}

    def collect_batch() -> None:
        """主线程收口时只加 done。running 已经在 worker 自己的 finally 里减过了。"""
        with progress_lock:
            progress["done"] += 1
        report_progress()

    notify(
        "AI 分析素材",
        f"AI 正在按 {target_total} 个目标字段查证素材，分 {len(batches)} 批并发（耗时较长）。",
    )
    merged_report = _new_curate_report()
    merged_report["batchTotal"] = len(batches)
    merged_report["factSpecsRef"] = manifest.get("factSpecsRef") or {}
    updated_table = copy.deepcopy(table)
    done = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fact-curate") as pool:
        futures = {
            pool.submit(run_batch, index, batch): index for index, batch in enumerate(batches, start=1)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001 - 单批失败不该带走整轮已有成果
                logger.exception("事实表维护第 %s 批失败", index)
                merged_report["batchErrors"].append({"batch": index, "message": str(exc) or "批次执行失败"})
                collect_batch()
                done += 1
                notify("AI 分析素材", f"已完成 {done}/{len(batches)} 批（第 {index} 批失败）。")
                continue
            # 增量落表：这一批的结果先并进来，后面的批还在跑。跑一半失败前面的成果还在。
            updated_table, _ = merge_curator_fields_into_table(
                updated_table, outcome["table"], outcome["report"].get("touchedKeys") or []
            )
            _accumulate_curate_report(merged_report, outcome["report"])
            collect_batch()
            done += 1
            # 还有批在跑时阶段仍是「AI 分析素材」，别让按钮显示成已经在收尾
            notify(
                "AI 分析素材" if done < len(batches) else "回收建议落表",
                f"已完成 {done}/{len(batches)} 批。",
            )

    errors = merged_report["batchErrors"]
    if errors and len(errors) == len(batches):
        # 部分批失败＝部分成功，这正是增量落表的意义；但全批失败要如实报错，
        # 否则前端看到的是「跑完了，一条建议都没有」，跟「AI 查了但没找到」分不开
        raise RuntimeError(f"事实表维护全部 {len(batches)} 批均失败：{errors[0]['message']}")
    # 字段名类的桶按批合并后去重：正常情况下各批目标不相交不会重复，但 agent 越界
    # 回传别批的字段时会被每一批各记一次，计数就虚高了。touchedKeys 尤其必须去重——
    # 它驱动落表合并。ignored/conflicts 是带原因的字典，重复项本身是信息，不动。
    for key in ("filled", "fixed", "notFound", "skippedConfirmed", "touchedKeys"):
        merged_report[key] = list(dict.fromkeys(merged_report[key]))
    merged_report["counts"] = {
        key: len(value) for key, value in merged_report.items() if isinstance(value, list)
    }
    merged_report["batchDone"] = done
    return updated_table, merged_report
