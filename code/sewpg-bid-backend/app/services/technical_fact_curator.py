from __future__ import annotations

"""技术标项目事实表维护（方案 B，T5/T6 后端侧）。

职责：
1. 组装 bid-tech-fact-curator skill 的 manifest（全量字段 + 招标文件解析产物路径 + 相关素材路径）；
2. 调用 opencode 运行 skill；
3. 回收逐字段建议并落表——硬约束：
   - 建议值一律置 pending_confirmation，sourceRefs 追加 type=factCurator；
   - 绝不写 confirmed；绝不覆盖已 confirmed 字段的值和状态；
   - 找不到值的字段保持 unextracted 并在 notes 写原因。
"""

import copy
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import BASE_DIR
from app.services.opencode_client import OpencodeClient
from app.services.technical_fact_spec_versions import resolve_project_specs
from app.services.technical_fact_material_classes import (
    build_fact_material_check,
    classify_material,
    material_class_of,
    material_home_project,
)
from app.services.technical_gap_fact_table import (
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_EXTRACTED,
    FACT_STATUS_MISSING_SOURCE,
    FACT_STATUS_NOT_APPLICABLE,
    FACT_STATUS_PENDING_CONFIRMATION,
    FACT_STATUS_UNEXTRACTED,
    fact_label_key,
    normalize_fact_source_refs,
    project_fact_material_index,
    prepare_project_fact_materials,
    summarize_project_fact_fields,
)
from app.services.turbine_models import project_turbine_model
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
CURATE_ACTION_CONFIRM_ADVICE = "confirm-advice"
CURATE_ACTIONS = {CURATE_ACTION_FILL, CURATE_ACTION_FIX, CURATE_ACTION_CONFIRM_ADVICE}

# 与 technical_gap_service.PROJECT_FACT_FIELD_TERMINAL_STATUSES 同源：
# 表级 confirmed 后又有字段被 curator 改回待确认时，表级状态要跟着降回 draft。
_FACT_TERMINAL_STATUSES = {
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_NOT_APPLICABLE,
    FACT_STATUS_MISSING_SOURCE,
}

# manifest 中带给 skill 的相关素材上限，避免长尾项目把 prompt 撑爆
_CURATOR_MATERIAL_LIMIT = 40

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


def _curator_materials(project: dict[str, Any], gap_state: dict[str, Any]) -> list[dict[str, Any]]:
    """相关素材路径：复用事实表构建的素材索引与落地逻辑，只保留本地可读文件。

    每条素材标注 materialClass / homeProject / crossProject（homeProject 非空且 ≠ 本项目名）；
    预检缺失的类别追加跨项目候选（走 prepare_project_fact_materials 落地，
    占用 _CURATOR_MATERIAL_LIMIT 额度且本项目素材优先），供 skill 定向读取。
    """
    materials = project_fact_material_index(project, gap_state)
    own = materials[:_CURATOR_MATERIAL_LIMIT]
    candidates = _cross_project_curator_candidates(
        project, gap_state, own, _CURATOR_MATERIAL_LIMIT - len(own)
    )
    if not own and not candidates:
        return []
    prepared = prepare_project_fact_materials(project, [*own, *candidates])
    project_name = str(project.get("name") or "")
    result: list[dict[str, Any]] = []
    for material in prepared:
        if not isinstance(material, dict):
            continue
        path_text = str(material.get("path") or "").strip()
        if not path_text or not Path(path_text).is_file():
            continue
        home_project = str(material.get("homeProject") or "") or material_home_project(material)
        result.append(
            {
                "id": str(material.get("id") or material.get("materialId") or ""),
                "name": str(material.get("name") or material.get("cleanedFileName") or ""),
                "path": path_text,
                "folderPath": str(material.get("folderPath") or ""),
                "materialTier": str(material.get("materialTier") or ""),
                "materialClass": classify_material(material) or "",
                "homeProject": home_project,
                "crossProject": bool(home_project and home_project != project_name),
            }
        )
    return result


# 不参与 AI 补抽的来源类别：模板占位（无需取值）、平台输入（人工录入）、自动生成（代码计算）
_NO_FILL_SOURCE_KINDS = {"template", "platform", "derived"}


def _curate_targets(fields: list[dict[str, Any]]) -> dict[str, list[str]]:
    """按方案 B 的三件事给字段分桶，桶内只放 fieldKey。"""
    targets: dict[str, list[str]] = {"fill": [], "fix": [], "confirmAdvice": []}
    for field in fields:
        field_key = str(field.get("key") or "").strip()
        if not field_key:
            continue
        status = str(field.get("status") or "")
        # 补抽范围：招标类 + 素材/证书类未提取字段（模板/平台/自动生成类不交 AI 填）
        if status == FACT_STATUS_UNEXTRACTED and str(field.get("sourceKind") or "") not in _NO_FILL_SOURCE_KINDS:
            targets["fill"].append(field_key)
        if status == FACT_STATUS_EXTRACTED:
            targets["fix"].append(field_key)
        if field.get("needsConfirmation") and status != FACT_STATUS_CONFIRMED:
            targets["confirmAdvice"].append(field_key)
    return targets


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


def build_fact_curator_manifest(
    project: dict[str, Any],
    gap_state: dict[str, Any],
    data: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    """组装 curator manifest 并落盘，返回 (manifest, manifest_path)。"""
    table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    fields = [copy.deepcopy(field) for field in (table.get("fields") or []) if isinstance(field, dict)]
    # 按项目绑定的规则版本关联 spec 补 referenceFile/materialClass（R06-B04-02：
    # 不再读系统公共清单；项目无绑定时 resolve_project_specs 回落系统默认），
    # 供 skill 按字段 materialClass 定向找素材、按 referenceFile 分辨招标文件字段
    project_specs, fact_specs_meta = resolve_project_specs(gap_state)
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
    work_dir = _curator_run_dir(project)
    manifest = {
        "schemaVersion": FACT_CURATE_SCHEMA_VERSION,
        "projectId": str(project.get("id") or ""),
        "projectName": str(project.get("name") or ""),
        "projectTurbineModel": project_turbine_model(project),
        "operator": str(data.get("operator") or "当前用户"),
        "projectFactTable": {
            "schemaVersion": str(table.get("schemaVersion") or ""),
            "fields": fields,
        },
        "targets": _curate_targets(fields),
        "tenderSources": _tender_sources(project),
        "materials": _curator_materials(project, gap_state),
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
            ("confirmAdvice", CURATE_ACTION_CONFIRM_ADVICE),
        ):
            for target_key in targets.get(bucket) or []:
                key = str(target_key or "").strip()
                if key:
                    actions_by_target.setdefault(key, set()).add(action)

    report: dict[str, Any] = {
        "filled": [],
        "fixed": [],
        "advised": [],
        "notFound": [],
        "skippedConfirmed": [],
        "ignored": [],
    }
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
        # 硬门禁优先于目标桶校验：即使 agent 越界回传，也明确记录为已确认跳过。
        if str(field.get("status") or "") == FACT_STATUS_CONFIRMED:
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
        if action == CURATE_ACTION_CONFIRM_ADVICE and str(field.get("value") or "").strip():
            # 口径判断针对现值本身，SKILL 约定 suggestedValue 留空；仍须保存判断证据。
            field["sourceRefs"] = normalize_fact_source_refs([*(field.get("sourceRefs") or []), ref])
            origin_note = _cross_origin_note(suggestion, cross_materials)
            if origin_note:
                notes = str(field.get("notes") or "")
                if origin_note not in notes:
                    field["notes"] = f"{notes}；{origin_note}" if notes else origin_note
            field["status"] = FACT_STATUS_PENDING_CONFIRMATION
            field["updatedAt"] = saved_at
            field["updatedBy"] = operator
            report["advised"].append(field_key)
            continue
        if not value:
            # 找不到值：保持 unextracted 并在 notes 写原因，不硬填
            if str(field.get("status") or "") == FACT_STATUS_UNEXTRACTED:
                reason = suggestion["evidence"] or "招标文件与素材中未找到取值"
                note = f"事实表维护Skill未找到值：{reason}"
                notes = str(field.get("notes") or "")
                if note not in notes:
                    field["notes"] = f"{notes}；{note}" if notes else note
                report["notFound"].append(field_key)
            else:
                report["ignored"].append(field_key)
            continue

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
        field["status"] = FACT_STATUS_PENDING_CONFIRMATION
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
    return table, report


def run_fact_curator_for_project(
    project: dict[str, Any],
    gap_state: dict[str, Any],
    data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """同步重活入口（由 service 经 asyncio.to_thread 调用）：组 manifest → 调 skill → 回收落表。"""
    table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    if not table.get("fields"):
        raise ValueError("项目事实表为空，请先构建事实表再运行维护 Skill。")
    manifest, manifest_path = build_fact_curator_manifest(project, gap_state, data)
    # 清掉上一轮产物：会话未能写出新建议文件时，残留的上一轮回 outputFile 会被
    # load_fact_curator_suggestions 当作本轮结果回收（表现为建议数与上次完全相同）
    for artifact_key in ("outputFile", "briefFile"):
        artifact_text = str(manifest.get(artifact_key) or "").strip()
        if artifact_text:
            artifact = Path(artifact_text)
            if artifact.is_file():
                artifact.unlink()
    result = run_technical_fact_curator_skill(manifest_path)
    suggestions = load_fact_curator_suggestions(result, manifest)
    saved_at = _now_iso()
    operator = str(data.get("operator") or "当前用户")
    cross_materials = [
        material
        for material in (manifest.get("materials") or [])
        if isinstance(material, dict) and material.get("crossProject")
    ]
    updated_table, report = apply_fact_curator_suggestions(
        table,
        suggestions,
        operator=operator,
        saved_at=saved_at,
        cross_materials=cross_materials,
        targets=manifest.get("targets") if isinstance(manifest.get("targets"), dict) else None,
    )
    report["manifestPath"] = str(manifest_path)
    report["suggestionCount"] = len(suggestions)
    report["factSpecsRef"] = manifest.get("factSpecsRef") or {}
    report["opencodeOutput"] = result.get("opencodeOutput") or {}
    return updated_table, report
