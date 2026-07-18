from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, settings
from app.services.bid_type import TECHNICAL_BID_TYPE, require_bid_type
from app.services.identity import build_project_material_scope
from app.services.opencode_client import OpencodeClient
from app.services.technical_appendix_source_matrix import load_appendix_source_matrix_for_project
from app.services.technical_gap_domain import recompute_technical_gap_decisions, summarize_technical_gap_plan
from app.services.technical_material_store import technical_material_store
from app.services.turbine_models import project_turbine_model
from app.services.workspace_artifacts import legacy_workspace_roots, technical_workspace_dir, technical_workspace_stage_dir

logger = logging.getLogger(__name__)


TECHNICAL_GAP_PLAN_SCHEMA_VERSION = "bid-tech-gap-plan-v1"
TECHNICAL_GAP_PLANNER_SKILL_NAME = "bid-tech-gap-planner"
TECHNICAL_TABLE_FILL_SKILL_NAME = "bid-tech-table-filler"
TECHNICAL_WORD_FILL_SKILL_NAME = "bid-tech-word-placeholder-filler"
GAP_PLANNER_RUNNER = BASE_DIR / "opencode" / "skills" / TECHNICAL_GAP_PLANNER_SKILL_NAME / "scripts" / "run_from_manifest.py"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _object_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _load_planner_segment_helpers() -> Any:
    """importlib 加载 planner skill 脚本，复用其确定性片段召回函数。

    与 run_from_manifest 同源（纯 stdlib），避免在 service 里重写一套打分逻辑。
    加载失败时返回 None，后处理整体跳过（不阻断缺口识别）。
    """
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location("tech_gap_planner_runner", GAP_PLANNER_RUNNER)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001 - 加载失败不应阻断主流程
        logger.warning("加载 planner 片段召回脚本失败，跳过证据片段后处理", exc_info=True)
        return None


def _attach_evidence_segments_to_plan(plan: dict[str, Any], material_index: list[dict[str, Any]]) -> int:
    """给 plan 里「非附表正文缺口」的候选素材补段落级证据片段（确定性后处理）。

    无论 plan 由 opencode agent 还是本地 fallback 脚本产出，都统一在此挂片段，
    使生产主路径（agent）也能拿到 evidenceSegments。规则：
    - 只处理 decision == fill_required 且无 appendixTasks 的项（正文类）。
    - 附表项（有 appendixTasks）与来源矩阵路径完全不碰。
    - 候选素材按 id 对齐 material_index 取回其 evidenceSegments，再调用 planner 的
      attach_recalled_segments 做打分召回，回填进 candidateMaterials。
    返回被增强的缺口项数。
    """
    helpers = _load_planner_segment_helpers()
    if helpers is None or not hasattr(helpers, "attach_recalled_segments"):
        return 0

    segments_by_id: dict[str, list[dict[str, Any]]] = {}
    for material in material_index:
        if not isinstance(material, dict):
            continue
        mid = str(material.get("id") or "").strip()
        segs = material.get("evidenceSegments")
        if mid and isinstance(segs, list) and segs:
            segments_by_id[mid] = segs

    if not segments_by_id:
        return 0

    enriched = 0
    for item in _object_items(plan.get("items")):
        if str(item.get("decision") or "") != "fill_required":
            continue
        if _object_items(item.get("appendixTasks")):
            continue  # 附表分支不动
        candidates = _object_items(item.get("candidateMaterials"))
        if not candidates:
            continue
        # 候选若本身未带片段，按 id 从 material_index 回填，再做召回。
        for candidate in candidates:
            if not candidate.get("evidenceSegments"):
                mid = str(candidate.get("id") or candidate.get("materialId") or "").strip()
                if mid in segments_by_id:
                    candidate["evidenceSegments"] = segments_by_id[mid]
        title = str(item.get("title") or "")
        recalled = helpers.attach_recalled_segments(candidates, title)
        if any(material.get("recalledSegments") for material in recalled):
            item["candidateMaterials"] = recalled
            enriched += 1
    if enriched:
        logger.info("技术标缺口识别：为 %d 个正文缺口补充了证据片段召回", enriched)
    return enriched


def _attach_topic_recall_to_plan(plan: dict[str, Any], material_index: list[dict[str, Any]]) -> int:
    """对「正文缺口但候选为空 → material_required」的项，用弱关联召回兜底补候选。

    覆盖 opencode agent 主路径：agent 产出的 plan 同样绕过本地 planner 的候选组装，
    对「主题相关但文件名对不上」的章节会判 material_required。这里用 planner 的
    weak_recall_materials（主题+近名+片段三路，金标反评 D1/D2）补 top-4 候选，
    命中则改判为 fill_required（material_match / AI 填写），并挂上片段召回。
    三路全空的项保持 material_required（人工补料），不硬塞。
    """
    helpers = _load_planner_segment_helpers()
    if helpers is None or not hasattr(helpers, "topic_match_materials"):
        return 0
    if not material_index:
        return 0
    recall = getattr(helpers, "weak_recall_materials", None) or helpers.topic_match_materials

    items = _object_items(plan.get("items"))

    def _is_leaf(index: int) -> bool:
        # toc 顺序 + level 判叶子：下一项层级更深即为容器。编号前缀判断不可靠
        # （章号"第3章"与子节号"3.1"不构成前缀关系）。
        if index + 1 >= len(items):
            return True
        current_level = int(items[index].get("level") or 1)
        next_level = int(items[index + 1].get("level") or 1)
        return next_level <= current_level

    enriched = 0
    for index, item in enumerate(items):
        # 兜底两类项（附表/已有候选不碰）：
        # 1) 判了人工补料的正文缺口；
        # 2) 无子节的结构项（金标反评 D5：附表1/2/3 类成果表在正式标书里有实质内容，
        #    不该直接跳过）——ready 且无 matched、非父章覆盖、是叶子。
        decision = str(item.get("decision") or "")
        is_missing = decision == "material_required"
        is_structural_leaf = (
            decision == "ready"
            and not _object_items(item.get("matchedMaterials"))
            and not _object_items(item.get("resolvedArtifacts"))
            and not _object_items(item.get("fillTasks"))
            and not str(item.get("coveredByParent") or "")
            and _is_leaf(index)
        )
        if not (is_missing or is_structural_leaf):
            continue
        if _object_items(item.get("appendixTasks")):
            continue
        if _object_items(item.get("candidateMaterials")):
            continue
        title = str(item.get("title") or "")
        gap_id = str(item.get("id") or "")
        # 复用 skill 的统一路由（含模板可信度门槛：金标反评发现的错误模板路由防护）。
        route = getattr(helpers, "route_weak_recall", None)
        routed = route(item, material_index, title, gap_id) if route else None
        if not routed:
            if is_structural_leaf and str(item.get("number") or "").startswith(("附表", "技术附表")):
                # 附表类空叶子：正式标书里通常需要填写（哪怕内容为「无」），不该静默判结构项。
                item["decision"] = "material_required"
                item["status"] = "needs_input"
                item["gapReason"] = "附表类目录项在正式标书中通常需填写（哪怕为「无」），素材库无对应来源，请人工确认或上传。"
                item["nextActions"] = ["manual_upload", "select_material", "ignore"]
                enriched += 1
            continue  # 其余召回全空 → 保持原判，不硬塞
        item["decision"] = routed["decision"]
        item["status"] = routed["status"]
        item["usage"] = routed["usage"]
        item["candidateMaterials"] = routed["alternatives"]
        if routed["fill_tasks"]:
            item["fillTasks"] = routed["fill_tasks"]
        item["gapReason"] = routed["gap_reason"]
        item["nextActions"] = routed["next_actions"]
        enriched += 1
    if enriched:
        logger.info("技术标缺口识别：为 %d 个正文缺口弱召回兜底补候选", enriched)
    return enriched


def _augment_fill_candidates(plan: dict[str, Any], material_index: list[dict[str, Any]]) -> int:
    """正文 AI 填写项的参考候选并入弱召回现成素材（ready/fill 路径此前都不跑弱召回）。

    金标反评：5.16 设备运行和维护专题的答案尾段来自库内成品《技术服务及售后服务》，
    弱召回能找到（同义词组 0.5+）但填写项候选池没有入口。top-4 + 项目素材追加。
    附表填写项（来源矩阵驱动）不动。
    """
    helpers = _load_planner_segment_helpers()
    recall = getattr(helpers, "weak_recall_materials", None) if helpers else None
    if recall is None or not material_index:
        return 0
    augmented = 0
    for item in _object_items(plan.get("items")):
        if str(item.get("decision") or "") != "fill_required":
            continue
        if _object_items(item.get("appendixTasks")):
            continue
        if not _object_items(item.get("fillTasks")):
            continue  # 无 fillTask 的 material_match 语义项走别的路径
        title = str(item.get("title") or "")
        weak_ready = [m for m in recall(material_index, title) if not helpers.material_requires_fill(m)]
        if not weak_ready:
            continue
        merged = {str(c.get("id") or c.get("name") or ""): c for c in _object_items(item.get("candidateMaterials"))}
        before = len(merged)
        for extra in weak_ready:
            merged.setdefault(str(extra.get("id") or extra.get("name") or ""), extra)
        if len(merged) == before:
            continue
        candidates = helpers.attach_recalled_segments(list(merged.values()), title)
        candidates.sort(key=lambda m: float(m.get("matchScore") or 0), reverse=True)
        project_extras = [
            c for c in candidates[4:]
            if str(c.get("materialTier") or c.get("libraryScope") or "").lower() == "project"
        ][:4]
        item["candidateMaterials"] = candidates[:4] + project_extras
        augmented += 1
    if augmented:
        logger.info("技术标缺口识别：%d 个正文填写项候选并入弱召回素材", augmented)
    return augmented


def _link_duplicate_title_items(plan: dict[str, Any]) -> int:
    """同名目录项互链（金标反评：同一张表在目录两处出现，如 附表3 与 附表G.1.2）。

    无任务/素材的叶子一侧指向有解决路径的一侧（mirrorsGapId），转人工确认复用其
    产出，不再静默判空章节。只处理叶子（容器章头的内容归子节，不参与互链）。
    """
    helpers = _load_planner_segment_helpers()
    if helpers is None:
        return 0
    norm = helpers._tech_normalize_text
    items = _object_items(plan.get("items"))

    def _has_resolution(it: dict[str, Any]) -> bool:
        return bool(
            _object_items(it.get("appendixTasks"))
            or _object_items(it.get("fillTasks"))
            or _object_items(it.get("matchedMaterials"))
            or _object_items(it.get("candidateMaterials"))
        )

    def _is_leaf(index: int) -> bool:
        if index + 1 >= len(items):
            return True
        return int(items[index + 1].get("level") or 1) <= int(items[index].get("level") or 1)

    by_title: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for idx, it in enumerate(items):
        key = norm(str(it.get("title") or ""))
        if len(key) >= 4:
            by_title.setdefault(key, []).append((idx, it))

    linked = 0
    for group in by_title.values():
        if len(group) < 2:
            continue
        primaries = [it for _, it in group if _has_resolution(it)]
        if not primaries:
            continue
        primary = primaries[0]
        for idx, it in group:
            if it is primary or _has_resolution(it):
                continue
            if str(it.get("decision") or "") not in ("ready", "material_required"):
                continue
            if _object_items(it.get("resolvedArtifacts")) or not _is_leaf(idx):
                continue
            it["mirrorsGapId"] = str(primary.get("id") or "")
            it["decision"] = "material_required"
            it["status"] = "needs_input"
            it["gapReason"] = (
                f"与「{primary.get('number')} {primary.get('title')}」为同一张表/同名章节，"
                "请在其完成后复用产出，或上传同表。"
            )
            it["nextActions"] = ["manual_upload", "select_material"]
            linked += 1
    if linked:
        logger.info("技术标缺口识别：%d 个同名目录项已互链（复用同表产出）", linked)
    return linked


def _cap_plan_candidates(plan: dict[str, Any], *, limit: int = 4) -> int:
    """非附表项候选统一 top-N 截断（金标反评 D3：每章最多 4 个候选人工勾选）。

    覆盖 agent 主路径产出的超长候选列表（如 Wiki 映射整目录 30+ 条）；
    附表项的推荐来源列表（按附表逐个推荐）与「章节同名目录素材」
    （literalFolderHit，确定相关的拼装候选）不在此截断。
    """
    capped = 0
    for item in _object_items(plan.get("items")):
        if _object_items(item.get("appendixTasks")):
            continue
        candidates = _object_items(item.get("candidateMaterials"))
        if len(candidates) <= limit:
            continue
        if any(bool(c.get("literalFolderHit")) for c in candidates):
            continue
        candidates.sort(key=lambda m: float(m.get("matchScore") or m.get("confidence") or 0), reverse=True)
        # 项目素材不占 top-N 名额（金标反评 B 类），追加在后、另设上限防洪。
        project_extras = [
            c for c in candidates[limit:]
            if str(c.get("materialTier") or c.get("libraryScope") or "").lower() == "project"
        ][:limit]
        item["candidateMaterials"] = candidates[:limit] + project_extras
        capped += 1
    if capped:
        logger.info("技术标缺口识别：%d 个目录项候选截断至 top-%d", capped, limit)
    return capped


def _normalize_literal_matches(plan: dict[str, Any], material_index: list[dict[str, Any]]) -> int:
    """固定素材通道收紧（金标反评后续）：自动定案只信文件名命中。

    覆盖 agent 主路径产出的 plan：
    - 已选定素材的文件名命中章节标题 → 保留固定素材，并补同目录兄弟为备选（top-4）；
    - 命中仅来自「目录名撞章节名」→ 撤销自动定案，转素材匹配，同名目录下全部
      现成素材进候选（literalFolderHit 豁免截断），人工选用拼装。
    已有人工产物（resolvedArtifacts）或父章覆盖的项不动。
    """
    helpers = _load_planner_segment_helpers()
    if helpers is None or not hasattr(helpers, "title_matches_file_name"):
        return 0
    by_id = {
        str(m.get("id") or ""): m
        for m in material_index
        if isinstance(m, dict) and str(m.get("id") or "")
    }
    changed = 0
    for item in _object_items(plan.get("items")):
        if str(item.get("decision") or "") != "ready":
            continue
        matched = _object_items(item.get("matchedMaterials"))
        if not matched:
            continue
        if _object_items(item.get("resolvedArtifacts")) or str(item.get("coveredByParent") or ""):
            continue
        title = str(item.get("title") or "")
        primary = by_id.get(str(matched[0].get("id") or matched[0].get("materialId") or "")) or matched[0]
        if helpers.title_matches_file_name(primary, title):
            # 真整章素材：备选并入同目录兄弟 + 弱召回现成素材（承诺函族这类近主题
            # 素材靠同义词组召回，ready 路径此前从不跑弱召回是盲区），
            # top-4 + 项目素材追加不占名额。
            recall = getattr(helpers, "weak_recall_materials", None)
            weak_ready = [
                m for m in (recall(material_index, title) if recall else [])
                if not helpers.material_requires_fill(m)
            ]
            extra_pool = helpers.sibling_folder_materials(primary, material_index, title) + weak_ready
            if extra_pool:
                primary_id = str(primary.get("id") or "")
                merged = {str(c.get("id") or c.get("name") or ""): c for c in _object_items(item.get("candidateMaterials"))}
                for extra in extra_pool:
                    merged.setdefault(str(extra.get("id") or extra.get("name") or ""), extra)
                merged.pop(primary_id, None)
                candidates = helpers.attach_recalled_segments(list(merged.values()), title)
                candidates.sort(key=lambda m: float(m.get("matchScore") or 0), reverse=True)
                project_extras = [
                    c for c in candidates[4:]
                    if str(c.get("materialTier") or c.get("libraryScope") or "").lower() == "project"
                ][:4]
                item["candidateMaterials"] = candidates[:4] + project_extras
            continue
        folder_prefix = helpers.folder_prefix_for_title(primary, title)
        if not folder_prefix:
            continue  # 命中来自其他文本特征，保守不动
        members = helpers.folder_member_materials(material_index, folder_prefix, title)
        if not members:
            continue
        candidates = helpers.attach_recalled_segments(members, title)
        for candidate in candidates:
            candidate["literalFolderHit"] = True
        item["decision"] = "fill_required"
        item["status"] = "needs_input"
        item["usage"] = "section_fill"
        item["matchedMaterials"] = []
        item["candidateMaterials"] = candidates
        item["gapReason"] = (
            f"章节与素材目录「{folder_prefix.rsplit('/', 1)[-1]}」同名，"
            f"目录下 {len(candidates)} 份素材需人工选用拼装，不自动定案。"
        )
        item["nextActions"] = ["select_reference_material", "manual_upload"]
        changed += 1
    if changed:
        logger.info("技术标缺口识别：%d 个「目录名命中」项撤销自动定案，转人工选用拼装", changed)
    return changed


def _safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _project_dir(project: dict[str, Any]) -> Path:
    project_id = str(project.get("id") or "")
    project_dir = technical_workspace_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _run_async(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    loop_thread_id = getattr(loop, "_thread_id", None)
    if loop_thread_id is not None and threading.get_ident() == loop_thread_id:
        raise RuntimeError(
            "_run_async was called from the running event loop's own thread. "
            "Wrap the calling sync code with asyncio.to_thread or run it in a worker thread."
        )

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - re-raised in caller
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


def _evidence_segments_by_material_id() -> dict[str, list[dict[str, Any]]]:
    """从已落盘的技术标索引 JSON 里收集 {material_id: evidenceSegments}。

    片段由 A 层（technical_material_index 镜像/预览）确定性切分后挂在 file entry 上。
    planner 走 raw_files 取素材（不读索引 JSON），故这里按 material_id 建映射，
    供 _allowed_technical_material_index 回填。索引缺失/无片段时返回空映射，
    planner 退化为原有的文件名/标题匹配，不报错。
    """
    from app.services.technical_material_index import load_technical_material_index

    mapping: dict[str, list[dict[str, Any]]] = {}
    try:
        index = load_technical_material_index()
    except Exception:  # noqa: BLE001 - 索引读不到不应阻断缺口识别
        return mapping
    for tier in index.get("tiers") or []:
        if not isinstance(tier, dict):
            continue
        for folder in tier.get("folders") or []:
            if not isinstance(folder, dict):
                continue
            for file_entry in folder.get("files") or []:
                if not isinstance(file_entry, dict):
                    continue
                material_id = str(file_entry.get("id") or "").strip()
                segments = file_entry.get("evidenceSegments")
                if material_id and isinstance(segments, list) and segments:
                    mapping[material_id] = segments
    return mapping


def _allowed_technical_material_index(material_scope: dict[str, Any], turbine_model: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    segments_by_id = _evidence_segments_by_material_id()
    for scope in material_scope.get("readableScopes") or []:
        if not isinstance(scope, dict):
            continue
        folder_path = str(scope.get("path") or "").strip()
        if not folder_path:
            continue
        material_tier = str(scope.get("materialTier") or "").strip().lower()
        query_folder_path = folder_path
        if material_tier in {"customer", "project"}:
            path_parts = [part for part in folder_path.split("/") if part]
            query_folder_path = "/".join(path_parts[:2])
        payload = _run_async(
            technical_material_store.raw_files(
                folder_path=query_folder_path,
                project_id=str(scope.get("projectId") or "") if material_tier == "project" else "",
                customer_name=str(scope.get("customerName") or "") if material_tier == "customer" else "",
                material_tier=material_tier,
                turbine_model=turbine_model,
                recursive=True,
                page=1,
                page_size=1000,
            )
        )
        for raw in payload.get("items") or []:
            if not isinstance(raw, dict):
                continue
            material_id = str(raw.get("id") or "")
            if not material_id or material_id in seen:
                continue
            seen.add(material_id)
            entry = {
                "id": material_id,
                "name": str(raw.get("name") or ""),
                "folderPath": str(raw.get("folderPath") or ""),
                "materialTier": str(raw.get("materialTier") or scope.get("materialTier") or ""),
                "hasCleanedWord": bool(raw.get("hasCleanedWord")),
                "cleanedFileName": str(raw.get("cleanedFileName") or ""),
                "cleanStatus": str(raw.get("cleanStatus") or ""),
                "turbineModelLabel": str(raw.get("turbineModelLabel") or ""),
                "updatedAt": str(raw.get("updatedAt") or ""),
            }
            # 回填证据片段（A 层确定性切分），供 planner 非附表分支做段落级召回。
            segments = segments_by_id.get(material_id)
            if segments:
                entry["evidenceSegments"] = segments
            items.append(entry)
    return items


def _is_material_word_fill_task(item: dict[str, Any], task: dict[str, Any]) -> bool:
    blank = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
    source_type = str(blank.get("sourceType") or "")
    usage = str(item.get("usage") or "")
    try:
        placeholder_count = int(blank.get("placeholderCount") or 0)
    except (TypeError, ValueError):
        placeholder_count = 0
    material_id = str(blank.get("materialId") or blank.get("id") or "")
    return (
        source_type == "material_fill_template"
        or (
            usage in {"section_fill", "chapter_fill"}
            and placeholder_count > 0
            and material_id.startswith("RAW-")
        )
    )


def normalize_technical_gap_plan_fill_task_skills(plan: dict[str, Any]) -> int:
    repaired = 0
    for item in _object_items(plan.get("items")):
        for task in _object_items(item.get("fillTasks")):
            current = str(task.get("skill") or "")
            expected = TECHNICAL_WORD_FILL_SKILL_NAME if _is_material_word_fill_task(item, task) else ""
            if not expected or current == expected:
                continue
            task["skill"] = expected
            repaired += 1
    if repaired:
        plan["summary"] = summarize_technical_gap_plan(plan)
    return repaired


def _validate_technical_gap_plan_toc_coverage(plan: dict[str, Any], toc_json_path: Path) -> None:
    try:
        toc = json.loads(toc_json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - malformed workspace input
        raise RuntimeError(f"缺口识别无法读取审核目录：{toc_json_path}") from exc
    toc_items = _object_items(toc.get("items"))
    plan_items = _object_items(plan.get("items"))
    expected_count = len(toc_items)
    actual_count = len(plan_items)
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    summary_count = int(summary.get("totalTocItems") or 0)
    if expected_count == actual_count and (summary_count in (0, expected_count)):
        return
    raise RuntimeError(
        "缺口识别结果不完整："
        f"S2 审核目录有 {expected_count} 个目录项，"
        f"Skill 输出 {actual_count} 个目录项，"
        f"summary.totalTocItems={summary_count}。请重新运行 bid-tech-gap-planner。"
    )


def _outline_nodes_to_toc_items(nodes: list[dict[str, Any]], prefix: str = "", level: int = 1) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            continue
        fallback_number = f"{prefix}.{index}" if prefix else str(index)
        number = str(
            node.get("tocNumber")
            or node.get("toc_number")
            or node.get("number")
            or fallback_number
        ).strip()
        title = str(node.get("title") or "").strip()
        if number and title.startswith(number):
            suffix = title[len(number) :]
            if not suffix or suffix[:1].isspace() or suffix[:1] in "：:、.-":
                title = suffix.strip(" ：:、.-") or title
        items.append(
            {
                "order": len(items) + 1,
                "number": number,
                "title": title,
                "level": level,
                "annotation": str(node.get("annotation") or "保留"),
                "source": str(node.get("source") or "outline_state"),
                "reason": str(node.get("reason") or ""),
                "requiredStatus": str(node.get("requiredStatus") or node.get("required_status") or ""),
                "sourceText": str(node.get("sourceText") or node.get("source_text") or ""),
                "source_refs": list(node.get("sourceRefs") or node.get("source_refs") or []),
                "material_refs": list(node.get("materialRefs") or node.get("material_refs") or []),
            }
        )
        children = node.get("children") or []
        if isinstance(children, list):
            child_items = _outline_nodes_to_toc_items(children, number, level + 1)
            for child in child_items:
                child["order"] = len(items) + 1
                items.append(child)
    return items


def _resolve_toc_json(project: dict[str, Any], work_dir: Path) -> Path:
    project_id = str(project.get("id") or "")
    outline_state = project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {}
    outline_nodes = list(outline_state.get("nodes") or [])
    if outline_nodes:
        output = {
            "schema_version": "bid-toc-json-v1",
            "document_title": f"{project.get('name') or project_id}投标文件总目录",
            "project": {
                "owner": project.get("customerName") or "",
                "name": project.get("name") or project_id,
                "code": project.get("projectCode") or project_id,
            },
            "items": _outline_nodes_to_toc_items(outline_nodes),
        }
        target = work_dir / settings.s2_toc_output_file_name
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    parse_storage = project.get("parse_storage") or {}
    candidates = []
    directory_output = ((project.get("directory_state") or {}).get("opencodeOutput") or {})
    for value in (directory_output.get("tocJsonPath"), directory_output.get("outputFile")):
        if value:
            candidates.append(Path(str(value)))
    for root in legacy_workspace_roots(project_id, parse_storage):
        s2_work_dir = root / "s2_toc_workdir"
        candidates.extend(path for path in sorted(s2_work_dir.glob("*.json")) if "evidence" not in path.name.lower())
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".json":
            target = work_dir / settings.s2_toc_output_file_name
            shutil.copy2(candidate, target)
            return target

    output = {
        "schema_version": "bid-toc-json-v1",
        "document_title": f"{project.get('name') or project_id}投标文件总目录",
        "project": {
            "owner": project.get("customerName") or "",
            "name": project.get("name") or project_id,
            "code": project.get("projectCode") or project_id,
        },
        "items": _outline_nodes_to_toc_items(outline_nodes),
    }
    target = work_dir / settings.s2_toc_output_file_name
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _resolve_wiki_dir(project: dict[str, Any], project_dir: Path, work_dir: Path) -> Path | None:
    project_id = str(project.get("id") or "")
    parse_storage = project.get("parse_storage") or {}
    candidates = [root / "s2_toc_workdir" / "wiki" for root in legacy_workspace_roots(project_id, parse_storage)]
    for candidate in candidates:
        if (candidate / "卡片").exists():
            target = work_dir / "wiki"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(candidate, target, dirs_exist_ok=True)
            return target
    return None


def _run_local_skill_runner(runner: Path, manifest_path: Path, schema_version: str) -> dict[str, Any]:
    if not runner.exists():
        raise RuntimeError(f"Skill runner 不存在：{runner}")
    result = subprocess.run(
        [sys.executable, str(runner), "--manifest", str(manifest_path), "--response", "summary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
        raise RuntimeError(f"Skill runner 执行失败（{result.returncode}）：{detail}")
    payload = json.loads(result.stdout or "{}")
    payload.setdefault("schema_version", schema_version)
    payload.setdefault(
        "opencodeOutput",
        {
            "status": "received",
            "sessionId": str(manifest_path),
            "providerId": "local-skill",
            "modelId": runner.parent.parent.name,
            "receivedAt": _now_iso(),
            "parts": [{"type": "text", "text": result.stdout.strip()}],
        },
    )
    return payload


def _build_gap_planner_prompt(manifest_path: Path) -> str:
    return f"""
Use the {TECHNICAL_GAP_PLANNER_SKILL_NAME} skill.

你现在在做 S3 技术标缺口识别。后端已经准备好 manifest，其中包含人工确认后的目录 JSON、招标解析结构化结果、S2 素材 Wiki 副本、项目/客户/通用素材边界、素材索引、项目身份信息和人工确认的投标机型信息。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整 gap_plan.json 写入 manifest 指定路径，并只在 stdout 打印小型摘要 JSON：

s4gap {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schema_version": "{TECHNICAL_GAP_PLAN_SCHEMA_VERSION}",
  "outputFile": "/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/gap_plan.json",
  "summary": {{"totalTocItems": 0, "matchedCount": 0, "missingCount": 0, "resolvedCount": 0, "ignoredCount": 0, "structuralCount": 0, "fillableTaskCount": 0, "blockingCount": 0}},
  "itemCount": 0
}}
""".strip()


def run_technical_gap_planner_skill(manifest_path: Path) -> dict[str, Any]:
    prompt = _build_gap_planner_prompt(manifest_path)
    try:
        return OpencodeClient().run_bid_tech_gap_planner_with_trace(prompt)
    except Exception:
        return _run_local_skill_runner(GAP_PLANNER_RUNNER, manifest_path, TECHNICAL_GAP_PLAN_SCHEMA_VERSION)


def build_technical_gap_plan_for_project(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("id") or "")
    project_dir = _project_dir(project)
    work_dir = technical_workspace_stage_dir(project_id, "s4_gap_workdir")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    toc_json_path = _resolve_toc_json(project, work_dir)
    parse_result_path = work_dir / "parse_result.json"
    parse_result_path.write_text(
        json.dumps(project.get("parse_result") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_file = work_dir / "gap_plan.json"
    manifest_path = work_dir / "s4_gap_input.json"
    wiki_dir = _resolve_wiki_dir(project, project_dir, work_dir)
    turbine_model = project_turbine_model(project)
    material_scope = build_project_material_scope(project)
    material_index = _allowed_technical_material_index(material_scope, turbine_model)
    appendix_source_matrix = load_appendix_source_matrix_for_project(project)
    bid_type = require_bid_type(
        project.get("bidType"),
        error_message="技术标缺口规划必须显式传入技术标项目。",
    )
    manifest = {
        "projectId": project_id,
        "projectName": str(project.get("name") or project_id),
        "bidType": bid_type,
        "customerName": str(project.get("customerName") or ""),
        "workDir": str(work_dir),
        "tocJsonPath": str(toc_json_path),
        "wikiDir": str(wiki_dir) if wiki_dir else "",
        "parseResultPath": str(parse_result_path),
        "projectIdentity": project.get("identity") or {},
        "materialScope": material_scope,
        "materialIndex": material_index,
        "projectTurbineModel": turbine_model,
        "appendixSourceMatrixPath": str(appendix_source_matrix.get("path") or ""),
        "appendixSourceMatrix": appendix_source_matrix,
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_technical_gap_planner_skill(manifest_path)
    plan_path = Path(str(result.get("outputFile") or output_file))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _validate_technical_gap_plan_toc_coverage(plan, toc_json_path)
    plan["projectTurbineModel"] = turbine_model
    plan["planFile"] = str(plan_path)
    plan["manifestPath"] = str(manifest_path)
    plan["phase"] = "gap_detection"
    plan["scopeBoundary"] = material_scope
    # 确定性后处理：无论 plan 由 opencode agent 还是本地 fallback 脚本产出，都在这里
    # 给「非附表正文缺口」的候选素材补段落级证据片段（A 层 evidenceSegments）。
    # agent 负责召回哪些素材，这一步只做确定性的「片段挂载 + 打分」，不改附表路径。
    _attach_evidence_segments_to_plan(plan, material_index)
    # 弱关联召回兜底：对「正文缺口候选为空 → 误判人工补料」和「无子节结构项」的项补候选并修正决策。
    _attach_topic_recall_to_plan(plan, material_index)
    # 固定素材通道收紧：自动定案只信文件名命中；目录名撞章节名转人工选用拼装。
    _normalize_literal_matches(plan, material_index)
    # 正文 AI 填写项候选并入弱召回素材（参考素材盲区）。
    _augment_fill_candidates(plan, material_index)
    # 同名目录项互链：同一张表在目录两处出现时，空的一侧指向有解决路径的一侧。
    _link_duplicate_title_items(plan)
    # 非附表项候选统一 top-4（金标反评 D3；同名目录素材豁免）。
    _cap_plan_candidates(plan)
    normalize_technical_gap_plan_fill_task_skills(plan)
    # 决策终审：候选素材不等于决策，对齐商务标「选定/处理完才算数」的两层架构；
    # 未确认候选统一改判 review_required，不再等同于「已经可以走」。
    recompute_technical_gap_decisions(plan)
    plan["summary"] = summarize_technical_gap_plan(plan)
    plan["opencodeOutput"] = result.get("opencodeOutput") or {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": TECHNICAL_GAP_PLANNER_SKILL_NAME,
        "receivedAt": _now_iso(),
        "parts": [{"type": "text", "text": json.dumps({"outputFile": str(plan_path)}, ensure_ascii=False)}],
    }
    return plan
