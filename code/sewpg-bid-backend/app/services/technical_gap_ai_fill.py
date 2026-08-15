"""技术标 AI 填写门面：skill runner、质量报告、产物构建、compute/apply 主流程。

素材备料（下载落地 / Excel 原件回源 / PDF OCR sidecar / 待插入嵌入备料）已迁至
technical_fill_materials（纯搬迁），此处 re-export 保持
app.services.technical_gap_ai_fill.<符号> 可解析、可 patch。
"""
from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.core.config import BASE_DIR, settings
# 模块符号保留：facade re-export，既有测试经本模块 patch 这些单例
# （ai_fill.minio_client / ai_fill.ocr_service / ai_fill.technical_material_store）。
from app.services.minio_client import minio_client
from app.services.ocr_service import ocr_service
from app.services.technical_material_store import technical_material_store
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.file_utils import run_awaitable_sync, safe_filename, run_local_skill_runner
from app.services.technical_gap_domain import (
    FILL_QUALITY_ACCEPTED_STATUSES,
    summarize_technical_gap_plan,
    technical_gap_artifact_onlyoffice_payload,
)
from app.services.technical_fact_spec_global import resolve_fact_specs
from app.services.technical_gap_state import legacy_technical_gap_items_from_plan
from app.services.turbine_models import project_turbine_model
from app.services.workspace_artifacts import technical_workspace_dir
from app.services.bid_runtime_state import now_iso
# 拆分搬迁：素材备料与 OCR sidecar 族实现已移至 technical_fill_materials，门面 re-export。
from app.services.technical_fill_materials import (
    _AI_FILL_OCR_PREP_MAX_ROUNDS,
    _EMBED_NORM_RE,
    _EMBED_PLACEHOLDER_RE,
    _EMBED_TIER_PRIORITY,
    _EMBED_UNSUPPORTED_SUFFIXES,
    _FILL_ORIGINAL_SUFFIXES,
    _OCR_BUDGET_SKIPPED_STATUS,
    _allowed_technical_material_index,
    _atomic_write_text,
    _dedupe_material_summaries,
    _downloadable_technical_fill_source_payload,
    _downloadable_technical_word_payload,
    _embed_norm,
    _embed_sources_for_fill,
    _ensure_pdf_ocr_sidecar,
    _ensure_pdf_ocr_sidecars_batch,
    _material_index_for_fill,
    _material_key,
    _material_may_have_excel_original,
    _material_summary,
    _object_items,
    _original_technical_fill_source_payload,
    _pick_most_specific_material,
    _prepare_fill_materials_with_ocr,
    _prepare_material_index_files,
    _prepare_word_blank_source,
    _project_tender_documents_for_fill,
    _reference_materials_for_fill,
    _resolve_original_material_file,
    _run_async,
    _scan_embed_placeholders,
    _selected_reference_material_ids,
    _string_items,
    effective_source_routing,
)


TABLE_FILL_SCHEMA_VERSION = "bid-tech-table-fill-v1"
WORD_FILL_SCHEMA_VERSION = "bid-tech-word-placeholder-fill-v1"
TECHNICAL_TABLE_FILL_SKILL_NAME = "bid-tech-table-filler"
TECHNICAL_WORD_FILL_SKILL_NAME = "bid-tech-word-placeholder-filler"
WORD_FILL_RUNNER = BASE_DIR / "opencode" / "skills" / TECHNICAL_WORD_FILL_SKILL_NAME / "scripts" / "run_from_manifest.py"


def _project_dir(project: dict[str, Any]) -> Path:
    project_id = str(project.get("id") or "")
    project_dir = technical_workspace_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


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


def enrich_fact_table_with_spec_columns(
    fact_table: dict[str, Any],
    gap_state: dict[str, Any],
) -> dict[str, Any]:
    """给事实表字段补上清单第 2/3 列（待填写文件 / 原占位符位置）。

    这两列是随「按清单定位」一起加的，改动前生成并存进 gap_state 的事实表没有它们，
    正文填写会误判成「清单未下发」而回退到旧的模糊匹配链路（起 agent + 跑 OCR，单条
    几十秒）。这里按 specKey 从项目当前生效清单现补，只补元数据不碰任何取值，
    也就不需要用户重建事实表——重建会重跑规则抽取，动到已确认的值。
    """
    fields = fact_table.get("fields")
    if not isinstance(fields, list) or not fields:
        return fact_table
    specs, _meta = resolve_fact_specs()
    specs_by_key = {str(spec.get("key") or ""): spec for spec in specs if isinstance(spec, dict) and spec.get("key")}
    if not specs_by_key:
        return fact_table
    enriched = copy.deepcopy(fact_table)
    for field in enriched.get("fields") or []:
        if not isinstance(field, dict):
            continue
        if str(field.get("placeholder") or "").strip() or str(field.get("targetFile") or "").strip():
            continue
        spec = specs_by_key.get(str(field.get("specKey") or ""))
        if not spec:
            continue
        field["placeholder"] = str(spec.get("placeholder") or "")
        field["targetFile"] = str(spec.get("targetFile") or "")
    return enriched


def fact_table_spec_coverage(fact_table: dict[str, Any]) -> tuple[int, int]:
    """事实表字段总数，以及其中带清单第 2/3 列（待填写文件 / 原占位符位置）的字段数。"""
    fields = _object_items(fact_table.get("fields"))
    covered = sum(
        1
        for field in fields
        if str(field.get("placeholder") or "").strip() or str(field.get("targetFile") or "").strip()
    )
    return len(fields), covered


def fact_table_drives_placeholders(fact_table: dict[str, Any]) -> bool:
    """事实表字段是否带清单第 2/3 列（待填写文件 / 原占位符位置）。

    带了就说明正文填写能按占位符精确查表定位字段，不再需要参考素材做模糊匹配。
    """
    return fact_table_spec_coverage(fact_table)[1] > 0


def require_spec_driven_fact_table(fact_table: dict[str, Any]) -> None:
    """正文填写前置校验：事实表必须能驱动占位符定位，否则直接失败。

    以前清单元数据缺失会静默回退到旧的模糊匹配链路（上下文规则 + 全库相似度 + 从素材
    抽事实 + 起 agent + 跑 OCR），单条几十秒且是错值的主要来源，而界面上只表现为「慢」，
    用户无从知道自己走错了路。这里改成显式报错并给出修复动作。

    只判零覆盖：部分字段缺列时，缺列的那些会在填写报告里记成 not_in_spec 并标黄，
    可见且不会填错值，不需要在入口拦截。
    """
    total, covered = fact_table_spec_coverage(fact_table)
    if not total:
        raise RuntimeError("正文填写需要项目事实表，当前项目还没有可用的事实表字段，请先抽取并确认事实表。")
    if not covered:
        raise RuntimeError(
            f"事实表 {total} 个字段都缺少清单的「待填写文件」「原占位符位置」两列，"
            "正文填写无法定位字段，请重新上传项目事实表清单后再填写。"
        )


def _appendix_task_for_fill(item: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    blank_source = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
    blank_id = str(blank_source.get("id") or "").strip()
    appendix_tasks = _object_items(item.get("appendixTasks"))
    for appendix_task in appendix_tasks:
        if blank_id and str(appendix_task.get("id") or "") == blank_id:
            return dict(appendix_task)
    return dict(appendix_tasks[0]) if appendix_tasks else {}


class AppendixSourceNotReadyError(RuntimeError):
    """附表来源规则未满足（manual_required/missing_source）：拒绝自动填写，提示待补资料。"""

    def __init__(self, reason: str, *, routing_status: str):
        super().__init__(reason)
        self.routing_status = routing_status
        self.code = f"APPENDIX_SOURCE_{routing_status.upper() or 'NOT_READY'}"


def source_routing_fill_block_reason(routing: dict[str, Any]) -> str:
    """manual_required / missing_source 的阻断原因；可自动填写返回空串。"""
    status = str(routing.get("status") or "")
    if status == "manual_required":
        return "附表来源规则要求人工收集资料（manual_required），请先补充素材后再发起填写。"
    if status == "missing_source":
        return "附表来源规则未匹配到可用来源（missing_source），请先补充素材或完善来源规则。"
    return ""


def source_routing_unmet_reason(routing: dict[str, Any]) -> str:
    """质量门禁口径：在阻断口径之上，matched 但命中为空同样判未满足。"""
    reason = source_routing_fill_block_reason(routing)
    if reason:
        return reason
    if str(routing.get("status") or "") == "matched" and not _object_items(routing.get("matchedMaterials")):
        return "附表来源规则状态为 matched，但规则命中素材为空，请补充素材后重填。"
    return ""


def fill_task_source_block_reason(item: dict[str, Any], task: dict[str, Any]) -> str:
    """该填写任务因附表来源规则待补资料时的原因；可填写（含正文任务）返回空串。"""
    if str(task.get("skill") or "") == TECHNICAL_WORD_FILL_SKILL_NAME:
        return ""
    return source_routing_fill_block_reason(effective_source_routing(item, _appendix_task_for_fill(item, task)))


def _field_key(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("key") or field.get("label") or field.get("title") or "").strip()


def _field_summary(field: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(field.get("id") or field.get("key") or field.get("label") or ""),
        "label": str(field.get("label") or field.get("title") or field.get("keyEntity") or field.get("id") or ""),
        "value": str(field.get("value") or field.get("keyValue") or ""),
        "sourceFile": str(field.get("sourceFile") or ""),
        "evidence": str(field.get("evidence") or ""),
        "evidenceLocation": str(field.get("evidenceLocation") or ""),
    }


def _parse_fields_for_fill(appendix_task: dict[str, Any], task: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = _object_items(appendix_task.get("availableParseFields")) + _object_items(appendix_task.get("fields"))
    requested = _string_items(data.get("parseFieldIds"))
    blank_source = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
    blank_id = str(blank_source.get("id") or "").strip()
    requested_field_ids = [item for item in requested if item != blank_id]
    if not requested_field_ids:
        return [_field_summary(field) for field in candidates]

    by_key: dict[str, dict[str, Any]] = {}
    for field in candidates:
        key = _field_key(field)
        if key:
            by_key[key] = field
    result: list[dict[str, Any]] = []
    for field_id in requested_field_ids:
        result.append(_field_summary(by_key.get(field_id) or {"id": field_id, "label": field_id}))
    return result


def _build_table_filler_llm_prompt(manifest_path: Path) -> str:
    return f"""
Use the {TECHNICAL_TABLE_FILL_SKILL_NAME} skill.

你现在在做技术标附表 AI 填写（LLM 判断模式）。后端已经准备好 manifest：待填写空表 Word、人工指定的参考素材、项目事实表、解析字段和输出路径都在其中。取值判断全部由你完成，脚本只做机械准备、计划校验和保格式写回。

manifest：{manifest_path}

严格按 SKILL.md 的流程执行：
1. 调用 Bash 工具执行下面命令生成填写简报 fill_brief.json，Bash 工具 timeout 必须设置为 1800000 毫秒或更高：

s4fill-prepare {manifest_path}

2. 阅读 fill_brief.json 的 targetFields / materials / factTableFields / rules，按需用 Bash 阅读素材原文后逐格判断取值。
3. 按 brief 的 planFile 路径写 fill_plan.json：先写 fill_plan.json.tmp，确认 JSON 完整后 mv -f 原子改名。
4. 调用 Bash 工具执行下面命令校验并执行填写：

s4fill-apply {manifest_path}

5. stdout 返回 validationErrors 时，修正 fill_plan.json 后重跑 s4fill-apply，最多重试 3 轮。

只返回 s4fill-apply stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def _run_table_filler_llm(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    """LLM 判断模式：agent 走 prepare→读素材→写 plan→apply 多轮流程。

    不传 early_tool_command——「脚本完成/文件落地」不代表终稿，提前收口会回收
    中间态并把会话孤儿化；等会话自然结束（对齐 factcurate 不提前返回的先例）。
    LLM 判断是附表填写的唯一模式，会话失败或产物缺失时显式抛出，由上层记录
    失败原因并标红目录项，不再回退任何脚本路径。
    """
    prompt = _build_table_filler_llm_prompt(manifest_path)
    timeout_sec = settings.s4_llm_fill_timeout_sec or settings.opencode_timeout_sec

    try:
        # 保留直建：显式传 opencode 专有 timeout_ms（S4 LLM 填写自定义超时），非「只要默认引擎」。
        result = run_awaitable_sync(OpencodeEngine(timeout_ms=int(timeout_sec * 1000)).run_bid_tech_table_filler_with_trace(
            prompt,
            stream_callback=(
                (lambda details: progress_callback("table_filler_delta", details))
                if progress_callback
                else None
            ),
            early_tool_command="",
        ))
    except Exception as exc:
        raise RuntimeError(f"LLM 附表填写会话失败：{exc}") from exc
    # 回收校验：stdout 摘要过 _extract_table_fill_json 后，outputFile 必须真实存在
    output_file = str(result.get("outputFile") or "").strip()
    if not output_file or not Path(output_file).exists():
        raise RuntimeError(f"LLM 附表填写未产出有效输出文件（outputFile={output_file or '缺失'}）。")
    return result


def run_technical_table_filler_skill(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    """附表填写只走 LLM 判断模式；失败直接抛出，由上层记 fillError 显式暴露。"""
    return _run_table_filler_llm(manifest_path, progress_callback)


def run_technical_word_placeholder_filler_skill(manifest_path: Path) -> dict[str, Any]:
    """正文填写：直接跑本地脚本。

    脚本是纯确定性查表（占位符原文 → 事实表字段），agent 在这条链路上只做一件事——
    转发一条 shell 命令，起会话的开销远大于执行本身。
    """
    return run_local_skill_runner(WORD_FILL_RUNNER, manifest_path, WORD_FILL_SCHEMA_VERSION)


def _numeric_report_value(report: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = report.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        if isinstance(value, str) and value.strip().isdigit():
            return max(0, int(value.strip()))
    return 0


def _merge_fill_sidecar_report(result: dict[str, Any], output_file: Path) -> dict[str, Any]:
    sidecar = output_file.with_suffix(".fill_report.json")
    if not sidecar.exists():
        return result
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return result
    if not isinstance(data, dict):
        return result
    merged = dict(result)
    for key in ("evidenceRefs", "filledFieldDetails", "unfilledFieldDetails", "unfilledFields"):
        sidecar_value = data.get(key)
        current_value = merged.get(key)
        if isinstance(sidecar_value, list) and (
            not isinstance(current_value, list) or len(sidecar_value) > len(current_value)
        ):
            merged[key] = sidecar_value
    sidecar_report = data.get("fillReport")
    if isinstance(sidecar_report, dict):
        current_report = merged.get("fillReport") if isinstance(merged.get("fillReport"), dict) else {}
        merged["fillReport"] = {**current_report, **sidecar_report}
    return merged


def _build_fill_quality_report(
    result: dict[str, Any],
    *,
    output_exists: bool,
    routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = result.get("fillReport") if isinstance(result.get("fillReport"), dict) else {}
    unfilled_fields = result.get("unfilledFields") if isinstance(result.get("unfilledFields"), list) else []
    evidence_refs = result.get("evidenceRefs") if isinstance(result.get("evidenceRefs"), list) else []
    failed_target_count = _numeric_report_value(report, "failedTargetCount")
    filled_count = _numeric_report_value(
        report,
        "filledFieldCount",
        "filledPlaceholderCount",
        "filledCellCount",
    )
    unfilled_count = max(
        _numeric_report_value(
            report,
            "unfilledFieldCount",
            "unfilledPlaceholderCount",
            "unfilledCellCount",
            "residualPlaceholderCount",
        ),
        len(unfilled_fields),
    )
    expected_count = _numeric_report_value(
        report,
        "targetFieldCount",
        "targetPlaceholderCount",
        "fieldCount",
        "placeholderCount",
        "totalFieldCount",
    )
    if expected_count <= 0:
        expected_count = filled_count + unfilled_count
    coverage_rate = filled_count / expected_count if expected_count else 0.0
    evidence_chain_rate = min(1.0, len(evidence_refs) / filled_count) if filled_count else 0.0
    semantic_check_count = _numeric_report_value(report, "semanticCheckCount")
    semantic_failed_count = _numeric_report_value(report, "semanticFailedCount")
    semantic_rate_value = report.get("semanticValidationRate")
    try:
        semantic_validation_rate = float(semantic_rate_value) if semantic_rate_value is not None else None
    except (TypeError, ValueError):
        semantic_validation_rate = None
    correctness_rate = (
        min(evidence_chain_rate, semantic_validation_rate)
        if semantic_check_count > 0 and semantic_validation_rate is not None
        else evidence_chain_rate
    )
    completeness_rate = 1.0 if output_exists and unfilled_count == 0 and coverage_rate >= 0.85 else min(coverage_rate, 1.0 if output_exists else 0.0)
    thresholds = {
        "coverageRate": 0.85,
        "correctnessRate": 0.85,
        "completenessRate": 0.85,
    }
    # 空白模板本身没有待填单元格（招标原文已写满，或整列留空即不限制）时，
    # 填 0 格是正确终态，不是缺口。按覆盖率会误判 needs_review 并混进缺口统计。
    no_fill_required = bool(report.get("noFillRequired")) and output_exists and filled_count == 0
    status = "no_fill_required" if no_fill_required else "passed" if (
        coverage_rate >= thresholds["coverageRate"]
        and correctness_rate >= thresholds["correctnessRate"]
        and completeness_rate >= thresholds["completenessRate"]
        and unfilled_count == 0
        and semantic_failed_count == 0
        and failed_target_count == 0
        and output_exists
    ) else "needs_review"
    # 来源规则未满足（待补资料，或 matched 但命中为空）时一律不通过，
    # 避免产物进入 s7Ready（下游按 FILL_QUALITY_ACCEPTED_STATUSES 判定）。
    source_unmet = source_routing_unmet_reason(routing) if routing else ""
    if source_unmet:
        status = "needs_review"
    source_coverage = report.get("sourceCoverage") if isinstance(report.get("sourceCoverage"), dict) else None
    return {
        "schemaVersion": "bid-fill-quality-report-v1",
        "status": status,
        "noFillRequired": no_fill_required,
        "sourceCoverage": source_coverage,
        "sourceRuleSatisfied": not source_unmet,
        "sourceRuleMessage": source_unmet,
        "coverageRate": round(coverage_rate, 4),
        "correctnessRate": round(correctness_rate, 4),
        "completenessRate": round(completeness_rate, 4),
        "evidenceChainRate": round(evidence_chain_rate, 4),
        "expectedFieldCount": expected_count,
        "filledFieldCount": filled_count,
        "unfilledFieldCount": unfilled_count,
        "evidenceRefCount": len(evidence_refs),
        "residualPlaceholderCount": unfilled_count,
        "semanticCheckCount": semantic_check_count,
        "semanticFailedCount": semantic_failed_count,
        "semanticValidationRate": round(semantic_validation_rate, 4) if semantic_validation_rate is not None else None,
        "failedTargetCount": failed_target_count,
        "thresholds": thresholds,
    }


def _path_from_result(value: Any, *, base_dir: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _fill_output_files(result: dict[str, Any], resolved_output: Path) -> list[Path]:
    raw_files = result.get("outputFiles")
    paths: list[Path] = []
    if isinstance(raw_files, list):
        for item in raw_files:
            text = str(item or "").strip()
            if not text:
                continue
            path = _path_from_result(text, base_dir=resolved_output.parent)
            if path.suffix.lower() == ".docx":
                paths.append(path)
    if not paths and resolved_output.suffix.lower() == ".docx":
        paths.append(resolved_output)

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _target_result_for_output(result: dict[str, Any], output_file: Path, index: int) -> dict[str, Any]:
    target_results = _object_items(result.get("targetResults"))
    output_key = str(output_file)
    for target in target_results:
        target_output = str(target.get("outputFile") or "").strip()
        if target_output and str(_path_from_result(target_output, base_dir=output_file.parent)) == output_key:
            return dict(target)
    if 0 <= index - 1 < len(target_results):
        return dict(target_results[index - 1])
    return {
        "schema_version": result.get("schema_version") or result.get("schemaVersion") or TABLE_FILL_SCHEMA_VERSION,
        "outputFile": str(output_file),
        "unfilledFields": list(result.get("unfilledFields") or []),
        "evidenceRefs": list(result.get("evidenceRefs") or []),
        "fillReport": dict(result.get("fillReport") or {}),
        "filledAt": result.get("filledAt") or now_iso(),
    }


def _build_ai_fill_artifacts(
    *,
    project_id: str,
    base_artifact_id: str,
    gap_id: str,
    task_id: str,
    item_title: str,
    skill_name: str,
    result: dict[str, Any],
    output_files: list[Path],
    batch_report_path: Path,
    created_at: str,
    operator: str,
    reference_materials: list[dict[str, Any]],
    recommended_materials: list[dict[str, Any]],
    parse_fields: list[dict[str, Any]],
    tender_documents: list[dict[str, Any]],
    manifest_path: Path,
    s7_ready: bool,
    source_routing: dict[str, Any] | None = None,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> list[dict[str, Any]]:
    batch_count = len(output_files)
    artifacts: list[dict[str, Any]] = []
    for index, output_file in enumerate(output_files, start=1):
        target_result = _target_result_for_output(result, output_file, index)
        target_result = _merge_fill_sidecar_report(target_result, output_file)
        target_report = target_result.get("fillReport") if isinstance(target_result.get("fillReport"), dict) else {}
        artifact_id = base_artifact_id if batch_count == 1 else f"{base_artifact_id}-{index:03d}"
        title = str(target_report.get("title") or item_title or output_file.stem)
        quality_report = _build_fill_quality_report(target_result, output_exists=output_file.exists(), routing=source_routing)
        artifact_s7_ready = s7_ready and quality_report["status"] in FILL_QUALITY_ACCEPTED_STATUSES
        artifacts.append(
            {
                "id": artifact_id,
                "source": "ai_fill",
                "skill": skill_name,
                "gapId": gap_id,
                "fillTaskId": task_id,
                "title": title,
                "fileName": output_file.name,
                "path": str(output_file),
                "createdAt": created_at,
                "operator": operator,
                "unfilledFields": list(target_result.get("unfilledFields") or []),
                "evidenceRefs": list(target_result.get("evidenceRefs") or []),
                "fillReport": target_report,
                "qualityReport": quality_report,
                "referenceMaterialIds": [
                    _material_key(material)
                    for material in reference_materials
                    if _material_key(material)
                ],
                "referenceMaterials": reference_materials,
                "recommendedMaterials": recommended_materials,
                "parseFields": parse_fields,
                "tenderDocuments": [
                    {
                        "id": str(document.get("id") or ""),
                        "name": str(document.get("name") or ""),
                        "sourceType": str(document.get("sourceType") or "project_tender_document"),
                    }
                    for document in tender_documents
                ],
                "manifestPath": str(manifest_path),
                "batchReportPath": str(batch_report_path) if batch_count > 1 else "",
                "batchTargetIndex": index if batch_count > 1 else 0,
                "batchTargetCount": batch_count if batch_count > 1 else 0,
                "opencodeOutput": result.get("opencodeOutput") or {},
                "onlyoffice": technical_gap_artifact_onlyoffice_payload(
                    project_id=project_id,
                    artifact_id=artifact_id,
                    file_name=output_file.name,
                    browser_base_url=browser_base_url,
                    onlyoffice_base_url=onlyoffice_base_url,
                ),
                "s7Ready": artifact_s7_ready,
                "qualityGate": "auto_passed" if artifact_s7_ready else "needs_review",
                "confirmed": artifact_s7_ready,
            }
        )
    return artifacts


def _compact_resolved_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    reference_materials = [
        {
            "id": _material_key(material),
            "name": str(material.get("name") or material.get("title") or material.get("fileName") or ""),
            "folderPath": str(material.get("folderPath") or ""),
            "materialTier": str(material.get("materialTier") or ""),
        }
        for material in _object_items(artifact.get("referenceMaterials"))
        if _material_key(material)
    ]
    return {
        "id": artifact.get("id"),
        "source": artifact.get("source"),
        "skill": artifact.get("skill"),
        "gapId": artifact.get("gapId"),
        "fillTaskId": artifact.get("fillTaskId"),
        "title": artifact.get("title"),
        "fileName": artifact.get("fileName"),
        "path": artifact.get("path"),
        "createdAt": artifact.get("createdAt"),
        "operator": artifact.get("operator"),
        "unfilledFields": list(artifact.get("unfilledFields") or []),
        "evidenceRefs": list(artifact.get("evidenceRefs") or []),
        "fillReport": artifact.get("fillReport") or {},
        "qualityReport": artifact.get("qualityReport") or {},
        "referenceMaterialIds": _string_items(
            artifact.get("referenceMaterialIds")
            or [_material_key(material) for material in reference_materials]
        ),
        "referenceMaterials": reference_materials,
        "tenderDocuments": _object_items(artifact.get("tenderDocuments")),
        "manifestPath": artifact.get("manifestPath"),
        "batchReportPath": artifact.get("batchReportPath") or "",
        "batchTargetIndex": artifact.get("batchTargetIndex") or 0,
        "batchTargetCount": artifact.get("batchTargetCount") or 0,
        "onlyoffice": artifact.get("onlyoffice") or {},
        "s7Ready": artifact.get("s7Ready", True),
        "qualityGate": str(artifact.get("qualityGate") or ""),
        "confirmed": bool(artifact.get("confirmed")),
        "confirmedAt": str(artifact.get("confirmedAt") or ""),
        "confirmedBy": str(artifact.get("confirmedBy") or ""),
        "referenceMaterialCount": len(artifact.get("referenceMaterials") or []),
        "tenderDocumentCount": len(artifact.get("tenderDocuments") or []),
        "recommendedMaterialCount": len(artifact.get("recommendedMaterials") or []),
    }


def _replace_resolved_artifacts(
    current: Any,
    artifacts: list[dict[str, Any]],
    *,
    fill_task_id: str,
    skill_name: str,
) -> list[dict[str, Any]]:
    compact_artifacts = [_compact_resolved_artifact(artifact) for artifact in artifacts]
    compact_ids = {str(artifact.get("id") or "").strip() for artifact in compact_artifacts}
    compact_names = {str(artifact.get("fileName") or "").strip() for artifact in compact_artifacts}
    kept: list[dict[str, Any]] = []
    for item in _object_items(current):
        item_id = str(item.get("id") or "").strip()
        item_task_id = str(item.get("fillTaskId") or "").strip()
        item_skill = str(item.get("skill") or "").strip()
        item_file_name = str(item.get("fileName") or "").strip()
        if item_id and item_id in compact_ids:
            continue
        if fill_task_id and item_task_id == fill_task_id:
            continue
        if not item_task_id and item_skill == skill_name and item_file_name in compact_names:
            continue
        kept.append(_compact_resolved_artifact(item))
    kept.extend(compact_artifacts)
    return kept[-24:]


def compute_technical_ai_fill(
    project_snapshot: dict[str, Any],
    gap_id: str,
    data: dict[str, Any],
    *,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> dict[str, Any]:
    """AI 填写的慢计算段：备素材、OCR、跑填写 skill、产物落盘并构建 artifacts。

    只在传入的私有快照（调用方深拷贝）上读写，不碰任何共享状态；返回可 JSON 化的
    结果包，由 :func:`apply_technical_ai_fill_result` 在 CAS 事务里纯状态写回。
    """
    project = project_snapshot
    gap_state = project.get("gap_state") or {}
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    project_fact_table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    project_fact_table = enrich_fact_table_with_spec_columns(project_fact_table, gap_state)
    normalize_technical_gap_plan_fill_task_skills(plan)
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    item = next((entry for entry in items if str(entry.get("id") or "") == gap_id), None)
    if item is None:
        raise KeyError(gap_id)

    fill_tasks = item.get("fillTasks") if isinstance(item.get("fillTasks"), list) else []
    requested_task_id = str(data.get("fillTaskId") or "")
    task = next(
        (
            entry
            for entry in fill_tasks
            if not requested_task_id or str(entry.get("id") or "") == requested_task_id
        ),
        None,
    )
    if task is None:
        raise ValueError("当前缺口没有可执行的 AI 填写任务。")

    skill_name = str(task.get("skill") or TECHNICAL_TABLE_FILL_SKILL_NAME)
    appendix_task = _appendix_task_for_fill(item, task)
    blank_source = dict(task.get("blankSource") or {}) if isinstance(task.get("blankSource"), dict) else {}
    # 正文填写只走清单定位（占位符原文 → 事实表字段），素材既不参与定位也不提供取值，
    # 因此不备素材、不跑 OCR、不起 agent；附表填写仍按原路准备素材。
    is_word_fill = skill_name == TECHNICAL_WORD_FILL_SKILL_NAME
    # 附表来源规则（#228）：manual_required / missing_source 拒绝自动填写，明确提示待补资料。
    # 单条与一键填写都汇聚到这里，拦截只需在这一层做一次。
    source_routing = {} if is_word_fill else effective_source_routing(item, appendix_task)
    if source_routing and not isinstance(appendix_task.get("sourceRouting"), dict):
        # 规则只挂在目录项级时回填到任务副本，招标原文与清单都按同一份规则走
        appendix_task = {**appendix_task, "sourceRouting": source_routing}
    block_reason = source_routing_fill_block_reason(source_routing)
    if block_reason:
        raise AppendixSourceNotReadyError(block_reason, routing_status=str(source_routing.get("status") or ""))
    if is_word_fill:
        require_spec_driven_fact_table(project_fact_table)
    selected_reference_ids = [] if is_word_fill else _selected_reference_material_ids(item, appendix_task, data)
    reference_materials = (
        [] if is_word_fill else _reference_materials_for_fill(item, appendix_task, data, selected_reference_ids)
    )
    blank_source_id = str(blank_source.get("id") or blank_source.get("materialId") or "").strip()
    reference_materials = [
        material
        for material in reference_materials
        if str(material.get("id") or material.get("materialId") or "").strip() != blank_source_id
    ]
    recommended_materials = list(reference_materials)
    material_index = (
        []
        if is_word_fill
        else _material_index_for_fill(
            project,
            plan,
            item,
            selected_reference_ids,
            reference_materials,
        )
    )
    parse_fields = _parse_fields_for_fill(appendix_task, task, data)
    tender_documents = _project_tender_documents_for_fill(project, appendix_task)
    if source_routing.get("useTenderParseFields") and not tender_documents:
        raise RuntimeError("附表填写规则要求读取招标文件，但项目当前没有可读取的原始文件或全文解析结果，请重新解析招标文件。")
    # 每次填写用独立运行目录（时间戳 + 短 uuid），同 gap 并发/重跑的 manifest 与输出互不覆盖；
    # 共享素材缓存 _material_index_cache 刻意跨任务复用，保持不动。
    run_id = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    work_dir = _project_dir(project) / "s4_gap_workdir" / "ai_fill" / gap_id / run_id
    work_dir.mkdir(parents=True, exist_ok=True)
    shared_material_cache_dir = _project_dir(project) / "s4_gap_workdir" / "ai_fill" / "_material_index_cache"
    # PDF 素材（认证证书等）三路都做 OCR sidecar：证书 PDF 通常只经 materialIndex
    # 关键词选源进入填表。sidecar 落在共享缓存跨缺口复用。
    # referenceMaterials/recommendedMaterials 只带素材库虚拟目录路径（如
    # "技术标/通用素材/.../证书.pdf"），不是本地可读路径；只下载过 material_index，
    # 这两路（尤其是路由命中的认证证书 PDF）从未落地过，table-filler 拿到手时
    # material_path() 解析不出真实文件，会静默丢弃——即使上游路由完全正确。
    # 单轮准备有 OCR 配额上限，这里在任务内部循环补齐，保证一次点击用全量素材。
    if not is_word_fill:
        material_index, reference_materials, recommended_materials = _prepare_fill_materials_with_ocr(
            material_index,
            reference_materials,
            recommended_materials,
            work_dir,
            cache_dir=shared_material_cache_dir,
        )
    artifact_task_id = safe_filename(str(task.get("id") or "task"), "task")
    artifact_id = f"ART-{gap_id}-{artifact_task_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    output_stem = safe_filename(str(item.get("title") or gap_id), gap_id)
    if len(fill_tasks) > 1:
        output_suffix = safe_filename(str(task.get("id") or blank_source_id or "task"), "task")
        output_file = work_dir / f"{output_stem}_{output_suffix}_AI填写.docx"
    else:
        output_file = work_dir / f"{output_stem}_AI填写.docx"
    manifest_name = "word_fill_input.json" if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME else "table_fill_input.json"
    if len(fill_tasks) > 1:
        # 同一目录项挂多个填写任务时会并发跑：manifest 名带任务 id，避免互踩
        manifest_name = f"{Path(manifest_name).stem}_{artifact_task_id}.json"
    manifest_path = work_dir / manifest_name
    embed_sources: list[dict[str, Any]] = []
    if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME:
        blank_source = _prepare_word_blank_source(blank_source, work_dir)
        embed_sources = _embed_sources_for_fill(project, Path(str(blank_source["docxPath"])), work_dir)
    manifest = {
        "schemaVersion": WORD_FILL_SCHEMA_VERSION if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME else TABLE_FILL_SCHEMA_VERSION,
        "projectId": str(project.get("id") or ""),
        "projectName": str(project.get("name") or ""),
        "projectIdentity": project.get("identity") or {},
        "customerName": str(project.get("customerName") or ""),
        "projectTurbineModel": project_turbine_model(project),
        "gapId": gap_id,
        "fillTaskId": str(task.get("id") or ""),
        "title": str(item.get("title") or ""),
        "gapItem": {
            "id": gap_id,
            "number": str(item.get("number") or item.get("section") or ""),
            "title": str(item.get("title") or ""),
            "decision": str(item.get("decision") or ""),
            "usage": str(item.get("usage") or ""),
            "gapReason": str(item.get("gapReason") or item.get("reason") or ""),
            "materialScope": item.get("materialScope") or {},
            "turbineCheck": item.get("turbineCheck") or {},
        },
        "appendixTask": {
            "id": str(appendix_task.get("id") or ""),
            "title": str(appendix_task.get("title") or ""),
            "sourceFile": str(appendix_task.get("sourceFile") or ""),
            "docxPath": str(appendix_task.get("docxPath") or ""),
            "workspacePath": str(appendix_task.get("workspacePath") or ""),
            "rowCount": appendix_task.get("rowCount") or 0,
            "sourceRouting": appendix_task.get("sourceRouting") if isinstance(appendix_task.get("sourceRouting"), dict) else {},
            "availableParseFields": parse_fields,
            "tenderDocuments": tender_documents,
        },
        "blankSource": blank_source,
        "embedSources": embed_sources,
        "referenceMaterialIds": selected_reference_ids,
        "referenceMaterials": reference_materials,
        "projectFactTable": project_fact_table,
        "materialIndex": material_index,
        "recommendedMaterials": recommended_materials,
        "parseFieldIds": _string_items(data.get("parseFieldIds")),
        "parseFields": parse_fields,
        "tenderDocuments": tender_documents,
        "constraints": str(data.get("constraints") or ""),
        "operator": str(data.get("operator") or "当前用户"),
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME:
        result = run_technical_word_placeholder_filler_skill(manifest_path)
    else:
        result = run_technical_table_filler_skill(manifest_path)
    resolved_output = Path(str(result.get("outputFile") or output_file))
    if not resolved_output.exists():
        raise RuntimeError(f"AI 填写未生成输出文件：{resolved_output}")
    output_files = _fill_output_files(result, resolved_output)
    if not output_files:
        raise RuntimeError("AI 填写未生成可预览 Word 输出文件。")
    missing_outputs = [path for path in output_files if not path.exists()]
    if missing_outputs:
        raise RuntimeError(f"AI 填写输出文件不存在：{missing_outputs[0]}")

    if len(output_files) == 1:
        result = _merge_fill_sidecar_report(result, output_files[0])
    quality_report = _build_fill_quality_report(
        result,
        output_exists=bool(output_files) and all(path.exists() for path in output_files),
        routing=source_routing,
    )
    created_at = now_iso()
    operator = str(data.get("operator") or "当前用户")
    artifacts = _build_ai_fill_artifacts(
        project_id=str(project.get("id") or ""),
        base_artifact_id=artifact_id,
        gap_id=gap_id,
        task_id=str(task.get("id") or ""),
        item_title=str(item.get("title") or resolved_output.stem),
        skill_name=skill_name,
        result=result,
        output_files=output_files,
        batch_report_path=resolved_output,
        created_at=created_at,
        operator=operator,
        reference_materials=reference_materials,
        recommended_materials=recommended_materials,
        parse_fields=parse_fields,
        tender_documents=tender_documents,
        manifest_path=manifest_path,
        s7_ready=quality_report["status"] in FILL_QUALITY_ACCEPTED_STATUSES,
        source_routing=source_routing,
        browser_base_url=browser_base_url,
        onlyoffice_base_url=onlyoffice_base_url,
    )
    artifact = artifacts[0]

    # 结果包必须可 JSON 化：跨线程传给主线程收口，排障时也可直接落盘查看
    return {
        "gapId": gap_id,
        "fillTaskId": str(task.get("id") or ""),
        "skill": skill_name,
        "artifact": artifact,
        "artifacts": artifacts,
        "qualityReport": quality_report,
        "unfilledFieldCount": len(result.get("unfilledFields") or []),
        "createdAt": created_at,
        "operator": operator,
    }


def apply_technical_ai_fill_result(project: dict[str, Any], fill_result: dict[str, Any]) -> dict[str, Any]:
    """把 compute 的结果包纯状态写回给定 project。

    只允许状态改动，必须可重放：CAS 冲突时 mutate 会基于最新状态重新执行本函数。
    幂等：同一结果包重复 apply（task 已带着同一产物 id、同一完成时间落库）直接
    返回现状，不重复追加 resolvedArtifacts/reviewNotes。
    """
    gap_state = project.get("gap_state") or {}
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    gap_id = str(fill_result.get("gapId") or "")
    item = next((entry for entry in items if str(entry.get("id") or "") == gap_id), None)
    if item is None:
        raise KeyError(gap_id)
    fill_tasks = item.get("fillTasks") if isinstance(item.get("fillTasks"), list) else []
    fill_task_id = str(fill_result.get("fillTaskId") or "")
    task = next(
        (
            entry
            for entry in fill_tasks
            if not fill_task_id or str(entry.get("id") or "") == fill_task_id
        ),
        None,
    )
    if task is None:
        raise ValueError("当前缺口没有可执行的 AI 填写任务。")
    artifacts = _object_items(fill_result.get("artifacts"))
    artifact = fill_result.get("artifact") if isinstance(fill_result.get("artifact"), dict) else {}
    quality_report = fill_result.get("qualityReport") if isinstance(fill_result.get("qualityReport"), dict) else {}
    created_at = str(fill_result.get("createdAt") or "")
    skill_name = str(fill_result.get("skill") or TECHNICAL_TABLE_FILL_SKILL_NAME)
    if (
        str(task.get("status") or "") == "completed"
        and str(task.get("outputArtifactId") or "") == str(artifact.get("id") or "")
        and str(task.get("completedAt") or "") == created_at
    ):
        # 同一结果包的重复 apply（CAS 重放）：首次写回已落库，直接返回现状
        return {"item": item, "artifact": artifact, "artifacts": artifacts, "gapPlan": plan}

    task["status"] = "completed"
    task["outputArtifactId"] = artifact["id"]
    task["outputArtifactIds"] = [entry["id"] for entry in artifacts]
    task["completedAt"] = created_at
    item["status"] = "resolved" if quality_report["status"] in FILL_QUALITY_ACCEPTED_STATUSES else "needs_input"
    item["qualityStatus"] = quality_report["status"]
    item["qualityReport"] = quality_report
    item["resolvedArtifacts"] = _replace_resolved_artifacts(
        item.get("resolvedArtifacts"),
        artifacts,
        fill_task_id=str(task.get("id") or ""),
        skill_name=skill_name,
    )
    item["resolvedAt"] = created_at
    item["resolvedSource"] = artifact["fileName"] if len(artifacts) == 1 else f"{len(artifacts)} 份AI填写产物"
    item["reviewNotes"] = list(item.get("reviewNotes") or [])
    unfilled_count = int(fill_result.get("unfilledFieldCount") or 0)
    if unfilled_count:
        item["reviewNotes"].append(f"AI 填写仍有未填字段：{unfilled_count} 项")
    if quality_report["status"] not in FILL_QUALITY_ACCEPTED_STATUSES:
        item["reviewNotes"].append("AI 填写质量验收未达标，请人工复核或补充事实表后重填。")

    plan["updatedAt"] = created_at
    plan["summary"] = summarize_technical_gap_plan(plan)
    gap_state["plan"] = plan
    gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
    gap_state["submittedForReview"] = False
    gap_state["reviewConfirmed"] = False
    gap_state["reviewedAt"] = ""
    return {"item": item, "artifact": artifact, "artifacts": artifacts, "gapPlan": plan}


def run_technical_ai_fill_for_gap(
    project: dict[str, Any],
    gap_id: str,
    data: dict[str, Any],
    *,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> dict[str, Any]:
    """单条 AI 填写入口：compute（慢计算）+ apply（纯状态写回）的薄封装。

    调用方传入的 project 视为私有快照，签名与返回结构和拆分前一致。
    """
    fill_result = compute_technical_ai_fill(
        project,
        gap_id,
        data,
        browser_base_url=browser_base_url,
        onlyoffice_base_url=onlyoffice_base_url,
    )
    return apply_technical_ai_fill_result(project, fill_result)
