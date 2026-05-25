from __future__ import annotations

import asyncio
import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import BASE_DIR, settings
from app.services.bid_fill_generation_state import save_fill_generation_result_state
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.business_gap_fact_table import build_project_fact_table
from app.services.business_gap_planning import _business_template_index, _resolve_business_toc_json, _run_async
from app.services.business_material_store import business_material_store
from app.services.identity import build_project_material_scope
from app.services.minio_client import minio_client
from app.services.onlyoffice_documents import document_path
from app.services.opencode_client import OpencodeClient
from app.services.bid_runtime_state import now_iso
from app.services.workspace_project_access import (
    get_workspace_project_runtime_state,
    persist_workspace_project_state,
    require_workspace_project_for_update,
)
from app.services.workspace_artifacts import business_workspace_dir


BUSINESS_ASSEMBLER_SKILL_NAME = "bid-business-assembler"
BUSINESS_ASSEMBLER_SKILL_COMMAND = "businessassemble"
BUSINESS_ASSEMBLER_SKILL_DIR = BASE_DIR / "opencode" / "skill" / BUSINESS_ASSEMBLER_SKILL_NAME
BUSINESS_ASSEMBLER_RUNNER = BUSINESS_ASSEMBLER_SKILL_DIR / "scripts" / "run_from_manifest.py"
BUSINESS_FORMAT_CLEANER_SKILL_NAME = "bid-business-format-cleaner"
BUSINESS_FORMAT_CLEANER_SKILL_COMMAND = "businessformat"
BUSINESS_FORMAT_CLEANER_SKILL_DIR = BASE_DIR / "opencode" / "skill" / BUSINESS_FORMAT_CLEANER_SKILL_NAME
BUSINESS_FORMAT_CLEANER_RUNNER = BUSINESS_FORMAT_CLEANER_SKILL_DIR / "scripts" / "run_from_manifest.py"
WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
BUSINESS_FORMAT_PRESETS = {
    "standard": {
        "label": "标准商务标格式",
        "description": "默认商务标版式：标题、正文、表格、目录、页眉和分页统一规范化。",
    },
    "compact": {
        "label": "紧凑审阅格式",
        "description": "当前版本先复用标准清洗规则，保留紧凑格式意图供后续细化。",
    },
    "formal": {
        "label": "正式递交格式",
        "description": "当前版本先复用标准清洗规则，保留正式格式意图供后续细化。",
    },
    "custom": {
        "label": "自定义格式",
        "description": "按用户设置的字体、字号、行距、页边距、目录和页眉规则执行格式规范化。",
    },
}

def assemble_business_bid_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    project = get_workspace_project_runtime_state(
        project_id,
        bid_type=BUSINESS_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: ValueError("商务标生成标书仅支持商务标项目。"),
    )
    outline_state = copy.deepcopy(project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {})
    if outline_state.get("reviewStatus") != "confirmed":
        raise ValueError("请先完成商务目录确认后再生成标书。")
    business_gap_state = project.get("business_gap_state") if isinstance(project.get("business_gap_state"), dict) else {}
    plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
    if not plan:
        plan = _recover_business_gap_plan(project, business_gap_state)
    if not plan:
        raise ValueError("请先进入商务标 S3 页面完成素材匹配，再进入 S4 生成标书。")

    started_at = time.monotonic()
    work_dir = _prepare_work_dir(project_id)
    toc_json_path = _prepare_toc_json(project, work_dir)
    gap_plan_path = _prepare_gap_plan(plan, work_dir)
    fact_table_path = _prepare_project_fact_table(project, business_gap_state, work_dir)
    parse_result_path = _prepare_parse_result(project, work_dir)
    wiki_dir = _prepare_business_wiki_dir(project, work_dir)
    material_library_dir, exported_material_count = _export_business_material_library(project, work_dir / "materials")
    template_index = _business_template_index(project, work_dir)

    if progress_callback:
        progress_callback(
            "inputs_ready",
            {
                "tocJsonPath": str(toc_json_path),
                "wikiCardCount": _count_files(wiki_dir),
                "exportedMaterialCount": exported_material_count,
                "synthesizedMaterialCardCount": 0,
                "gapPlanMaterialCardCount": len(plan.get("tasks") or []),
            },
        )

    output_file = work_dir / f"{_safe_filename(str(project.get('name') or project_id), project_id)}_商务投标文件.docx"
    manifest_path = work_dir / "business_assembly_input.json"
    manifest = {
        "schemaVersion": "bid-business-assembly-manifest-v1",
        "projectId": project_id,
        "projectName": str(project.get("name") or project_id),
        "bidType": BUSINESS_BID_TYPE,
        "project": {
            "projectCode": str(project.get("projectCode") or ""),
            "customerName": str(project.get("customerName") or project.get("owner") or ""),
            "bidderName": str((data or {}).get("bidderName") or "上海电气风电集团股份有限公司"),
        },
        "workDir": str(work_dir),
        "tocJsonPath": str(toc_json_path),
        "businessGapPlanPath": str(gap_plan_path),
        "projectFactTablePath": str(fact_table_path),
        "parseResultPath": str(parse_result_path),
        "businessWikiDir": str(wiki_dir),
        "materialLibraryDir": str(material_library_dir),
        "templateIndex": template_index,
        "templateFile": "",
        "outputFile": str(output_file),
        "options": {
            "insertPlaceholdersForMissingFields": True,
            "preserveOriginalScans": True,
            "includeReviewList": True,
            "allowUnconfirmedGapTasks": True,
            "allowDraftProjectFacts": True,
            "includeBusinessScoring": True,
            "embedImagesAndPdfPages": True,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if progress_callback:
        progress_callback("calling_assembler", {"manifestPath": str(manifest_path), "workDir": str(work_dir)})

    result = _run_business_assembler_manifest(manifest_path, progress_callback=progress_callback)
    assembled_path = Path(str(result.get("outputFile") or output_file))
    if not assembled_path.exists():
        raise RuntimeError(f"商务标生成标书未生成输出文件：{assembled_path}")

    plan_path = Path(str(result.get("planFile") or work_dir / "business_assembly_plan.json"))
    report_path = Path(str(result.get("assemblyReport") or work_dir / "business_assembly_report.md"))
    review_path = Path(str(result.get("needsReview") or work_dir / "business_needs_review.md"))
    assembly_plan = _load_json_dict(plan_path)
    sections = _sections_from_business_assembly_plan(assembly_plan)
    coverage = _coverage_from_business_assembly_plan(assembly_plan)
    content = _build_fallback_content(report_path, review_path)

    if progress_callback:
        progress_callback(
            "assembling_result",
            {
                "sectionCount": len(sections),
                "usedMaterialCount": int(coverage.get("fullCover") or 0),
                "unassembledMaterialCount": int(coverage.get("noCover") or 0),
            },
        )

    format_clean = _run_business_format_cleaner_step(
        project=project,
        toc_json_path=toc_json_path,
        assembled_path=assembled_path,
        work_dir=work_dir,
        progress_callback=progress_callback,
    )
    final_output_path = Path(str(format_clean.get("outputFile") or assembled_path))
    if not final_output_path.exists():
        final_output_path = assembled_path

    target_path = document_path(project_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final_output_path, target_path)
    file_size_bytes = target_path.stat().st_size

    run_duration_sec = max(1, int(round(time.monotonic() - started_at)))
    filled_at = now_iso()

    opencode_output = result.get("opencodeOutput") if isinstance(result.get("opencodeOutput"), dict) else {}
    opencode_output.update(
        {
            "skill": BUSINESS_ASSEMBLER_SKILL_NAME,
            "workDir": str(work_dir),
            "manifestPath": str(manifest_path),
            "outputFile": str(final_output_path),
            "rawOutputFile": str(assembled_path),
            "assemblyReport": str(report_path),
            "needsReview": str(review_path),
            "coverage": {
                "usedMaterialCount": int(coverage.get("fullCover") or 0),
                "unassembledMaterialCount": int(coverage.get("noCover") or 0),
            },
            "formatClean": format_clean,
        }
    )
    if not opencode_output.get("parts"):
        opencode_output.update(
            {
                "status": "received",
                "sessionId": "",
                "providerId": "futurecode",
                "modelId": BUSINESS_ASSEMBLER_SKILL_NAME,
                "receivedAt": filled_at,
                "parts": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "skill": BUSINESS_ASSEMBLER_SKILL_NAME,
                                "manifestPath": str(manifest_path),
                                "outputFile": str(final_output_path),
                                "rawOutputFile": str(assembled_path),
                                "assemblyReport": str(report_path),
                                "needsReview": str(review_path),
                                "formatClean": format_clean,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            }
        )

    project_for_update = require_workspace_project_for_update(
        project_id,
        bid_type=BUSINESS_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: ValueError("商务标生成标书仅支持商务标项目。"),
    )
    payload = save_fill_generation_result_state(
        project_for_update,
        project_id=project_id,
        summary="商务标响应文件装配完成。",
        sections=sections,
        content=content,
        filled_at=filled_at,
        run_duration_sec=run_duration_sec,
        file_size_bytes=file_size_bytes,
        opencode_output=opencode_output,
        file_name=assembled_path.name,
        coverage=coverage,
        assembly={
            "skill": BUSINESS_ASSEMBLER_SKILL_NAME,
            "workDir": str(work_dir),
            "manifestPath": str(manifest_path),
            "tocJsonPath": str(toc_json_path),
            "businessGapPlanPath": str(gap_plan_path),
            "projectFactTablePath": str(fact_table_path),
            "parseResultPath": str(parse_result_path),
            "wikiDir": str(wiki_dir),
            "materialLibraryDir": str(material_library_dir),
            "outputFile": str(final_output_path),
            "rawOutputFile": str(assembled_path),
            "documentPath": str(target_path),
            "assemblyReport": str(report_path),
            "needsReview": str(review_path),
            "planFile": str(plan_path),
            "attachmentManifest": str(result.get("attachmentManifest") or work_dir / "attachment_manifest.json"),
            "fieldFillReport": str(result.get("fieldFillReport") or work_dir / "field_fill_report.json"),
            "formatClean": format_clean,
        },
    )
    persist_workspace_project_state(project_for_update)
    return payload


def _prepare_work_dir(project_id: str) -> Path:
    work_dir = business_workspace_dir(project_id) / "s4_assembly_workdir"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _recover_business_gap_plan(project: dict[str, Any], business_gap_state: dict[str, Any]) -> dict[str, Any]:
    """Recover S3 output when the persisted project payload has state but not the plan body."""
    project_id = str(project.get("id") or "")
    candidates: list[Path] = []
    plan_file = str(business_gap_state.get("planFile") or "").strip()
    if plan_file:
        candidates.append(Path(plan_file).expanduser())
    candidates.append(business_workspace_dir(project_id) / "gaps" / "business_gap_plan.json")

    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        plan = _load_json_dict(candidate)
        if str(plan.get("schemaVersion") or "") != "bid-business-gap-plan-v1":
            continue
        business_gap_state["plan"] = plan
        business_gap_state["planFile"] = str(candidate)
        business_gap_state["recognitionStatus"] = str(business_gap_state.get("recognitionStatus") or "completed")
        project["business_gap_state"] = business_gap_state
        project["updatedAt"] = now_iso()
        try:
            persist_workspace_project_state(project)
        except Exception:
            pass
        return plan
    return {}


def _prepare_toc_json(project: dict[str, Any], work_dir: Path) -> Path:
    return _resolve_business_toc_json(project, work_dir)


def _prepare_gap_plan(plan: dict[str, Any], work_dir: Path) -> Path:
    target = work_dir / "business_gap_plan.json"
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _prepare_project_fact_table(project: dict[str, Any], business_gap_state: dict[str, Any], work_dir: Path) -> Path:
    table = business_gap_state.get("projectFactTable") if isinstance(business_gap_state.get("projectFactTable"), dict) else {}
    if not table:
        table = build_project_fact_table(project, business_gap_state)
    target = work_dir / "project_fact_table.json"
    target.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _prepare_parse_result(project: dict[str, Any], work_dir: Path) -> Path:
    target = work_dir / "parse_result.json"
    target.write_text(json.dumps(project.get("parse_result") or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _prepare_business_wiki_dir(project: dict[str, Any], work_dir: Path) -> Path:
    target = work_dir / "wiki"
    target.mkdir(parents=True, exist_ok=True)
    project_id = str(project.get("id") or "")
    candidates = [business_workspace_dir(project_id) / "wiki", business_workspace_dir(project_id) / "materials-wiki"]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            shutil.copytree(candidate, target, dirs_exist_ok=True)
            return target
    return target


def _export_business_material_library(project: dict[str, Any], library_dir: Path) -> tuple[Path, int]:
    if library_dir.exists():
        shutil.rmtree(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)
    material_scope = build_project_material_scope(project)
    exported = 0
    seen: set[str] = set()
    for scope in material_scope.get("readableScopes") or []:
        if not isinstance(scope, dict):
            continue
        folder_path = str(scope.get("path") or "").strip()
        if not folder_path:
            continue
        try:
            payload = _run_async(
                business_material_store.raw_files(
                    folder_path=folder_path,
                    material_tier=str(scope.get("materialTier") or ""),
                    recursive=True,
                    page=1,
                    page_size=1000,
                )
            )
        except Exception:
            continue
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            material_id = str(item.get("id") or "")
            if not material_id or material_id in seen:
                continue
            seen.add(material_id)
            if _copy_business_material(item, library_dir):
                exported += 1
    return library_dir, exported


def _copy_business_material(item: dict[str, Any], library_dir: Path) -> bool:
    material_id = str(item.get("id") or "")
    if not material_id:
        return False
    try:
        try:
            payload = _run_async(business_material_store.raw_download_cleaned_content(material_id))
        except Exception:
            payload = _run_async(business_material_store.raw_download_content(material_id))
        file_name = _safe_filename(str(payload.get("fileName") or item.get("name") or f"{material_id}.bin"), f"{material_id}.bin")
        folder = _safe_filename(str(item.get("folderPath") or "素材"), "素材")
        target_path = library_dir / folder / file_name
        minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
        return target_path.exists()
    except Exception:
        return False


def _run_business_assembler_manifest(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    # S4 商务标正文装配是确定性 runner：直接执行本地 skill 脚本，避免 opencode bash
    # 会话出现“running 但子进程已退出”的假运行状态。
    if progress_callback:
        progress_callback(
            "assembler_session_ready",
            {
                "sessionId": str(manifest_path),
                "providerId": "local-skill",
                "modelId": BUSINESS_ASSEMBLER_SKILL_NAME,
            },
        )
    return _run_local_business_assembler(manifest_path)


def _run_local_business_assembler(manifest_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(BUSINESS_ASSEMBLER_RUNNER), "--manifest", str(manifest_path), "--response", "summary"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    parsed = json.loads(completed.stdout or "{}")
    parsed["opencodeOutput"] = {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": BUSINESS_ASSEMBLER_SKILL_NAME,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": completed.stdout or ""}],
    }
    return parsed


def _run_business_format_cleaner_step(
    *,
    project: dict[str, Any],
    toc_json_path: Path,
    assembled_path: Path,
    work_dir: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    manifest_path = work_dir / "business_format_clean_input.json"
    outline_path = _prepare_business_format_outline(toc_json_path, work_dir)
    output_path = assembled_path.with_name(f"{assembled_path.stem}.formatted.docx")
    manifest = {
        "inputFile": str(assembled_path),
        "outlineFile": str(outline_path),
        "outputFile": str(output_path),
        "projectName": str(project.get("name") or project.get("id") or "商务标项目"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if progress_callback:
        progress_callback("calling_format_cleaner", {"manifestPath": str(manifest_path), "inputFile": str(assembled_path)})

    try:
        result = _run_business_format_cleaner_manifest(manifest_path, progress_callback=progress_callback)
        formatted_path = Path(str(result.get("outputFile") or output_path)).expanduser()
        if not formatted_path.exists():
            raise RuntimeError(f"商务标格式规范化未生成输出文件：{formatted_path}")
        clean = {
            "status": "completed",
            "skill": BUSINESS_FORMAT_CLEANER_SKILL_NAME,
            "manifestPath": str(manifest_path),
            "inputFile": str(assembled_path),
            "outlineFile": str(outline_path),
            "outputFile": str(formatted_path),
            "reportFile": str(result.get("reportFile") or formatted_path.with_name("business_format_clean_report.md")),
            "summary": result.get("summary") if isinstance(result.get("summary"), dict) else {},
            "opencodeOutput": result.get("opencodeOutput") if isinstance(result.get("opencodeOutput"), dict) else {},
        }
        if progress_callback:
            progress_callback("format_cleaner_completed", {"summary": clean["summary"], "outputFile": clean["outputFile"]})
        return clean
    except Exception as exc:
        clean = {
            "status": "failed",
            "skill": BUSINESS_FORMAT_CLEANER_SKILL_NAME,
            "manifestPath": str(manifest_path),
            "inputFile": str(assembled_path),
            "outlineFile": str(outline_path),
            "outputFile": str(assembled_path),
            "error": str(exc),
        }
        if progress_callback:
            progress_callback("format_cleaner_failed", {"error": str(exc), "manifestPath": str(manifest_path)})
        return clean


def apply_business_document_format_preset(
    project_id: str,
    preset: str = "standard",
    style_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = get_workspace_project_runtime_state(
        project_id,
        bid_type=BUSINESS_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: ValueError("商务标格式切换仅支持商务标项目。"),
    )

    preset_key = preset if preset in BUSINESS_FORMAT_PRESETS else "standard"
    preset_info = BUSINESS_FORMAT_PRESETS[preset_key]
    source_path = document_path(project_id)
    if not source_path.exists():
        state = project.get("document_state") if isinstance(project.get("document_state"), dict) else {}
        raise FileNotFoundError(f"商务标正文文件不存在：{state.get('fileName') or source_path.name}")

    work_dir = business_workspace_dir(project_id) / "s4_format_switch_workdir"
    work_dir.mkdir(parents=True, exist_ok=True)
    toc_json_path = _prepare_toc_json(project, work_dir)
    outline_path = _prepare_business_format_outline(toc_json_path, work_dir)
    output_path = work_dir / f"{source_path.stem}.{preset_key}.formatted.docx"
    manifest_path = work_dir / f"business_format_{preset_key}_input.json"
    style_spec_path = _prepare_business_format_style_spec(preset_key, style_overrides or {}, work_dir)
    manifest = {
        "inputFile": str(source_path),
        "outlineFile": str(outline_path),
        "outputFile": str(output_path),
        "projectName": str(project.get("name") or project_id),
        "formatPreset": preset_key,
    }
    if style_spec_path is not None:
        manifest["styleSpecPath"] = str(style_spec_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = _run_local_business_format_cleaner(manifest_path)
    formatted_path = Path(str(result.get("outputFile") or output_path)).expanduser()
    if not formatted_path.exists():
        raise RuntimeError(f"商务标格式切换未生成输出文件：{formatted_path}")
    shutil.copy2(formatted_path, source_path)
    return {
        "preset": preset_key,
        "label": preset_info["label"],
        "description": preset_info["description"],
        "styleOverrides": copy.deepcopy(style_overrides or {}),
        "manifestPath": str(manifest_path),
        "outputFile": str(formatted_path),
        "summary": result.get("summary") if isinstance(result.get("summary"), dict) else {},
    }


def _prepare_business_format_style_spec(
    preset_key: str,
    style_overrides: dict[str, Any],
    work_dir: Path,
) -> Path | None:
    if preset_key != "custom" and not style_overrides:
        return None
    base_path = BUSINESS_FORMAT_CLEANER_SKILL_DIR / "references" / "business_heading_style.json"
    spec = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("商务标格式规范配置不是 JSON object。")
    spec = copy.deepcopy(spec)

    toc_cfg = spec.setdefault("toc", {})
    toc_cfg["style_spec_path"] = str((BUSINESS_FORMAT_CLEANER_SKILL_DIR / "references" / "business_toc_style.json").resolve())

    _apply_business_style_overrides(spec, style_overrides)
    style_path = work_dir / f"business_format_{preset_key}_style.json"
    style_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return style_path


def _apply_business_style_overrides(spec: dict[str, Any], overrides: dict[str, Any]) -> None:
    def text_value(key: str, default: str = "") -> str:
        value = str(overrides.get(key) or "").strip()
        return value or default

    def number_value(key: str, min_value: float, max_value: float) -> float | None:
        if key not in overrides or overrides.get(key) in (None, ""):
            return None
        try:
            value = float(overrides.get(key))
        except (TypeError, ValueError):
            return None
        return max(min_value, min(max_value, value))

    def bool_value(key: str) -> bool | None:
        if key not in overrides:
            return None
        return bool(overrides.get(key))

    body = spec.setdefault("body", {})
    if text_value("bodyZhFont"):
        body["zh_font"] = text_value("bodyZhFont")
    if text_value("bodyEnFont"):
        body["en_font"] = text_value("bodyEnFont")
    if (value := number_value("bodySizePt", 8, 22)) is not None:
        body["size_pt"] = value
    if (value := number_value("bodyLineSpacing", 1, 3)) is not None:
        body["line_spacing"] = value
    if (value := number_value("bodyFirstLineIndentChars", 0, 4)) is not None:
        body["first_line_indent_chars"] = value

    table = spec.setdefault("table_cell", {})
    if text_value("tableZhFont"):
        table["zh_font"] = text_value("tableZhFont")
    if text_value("tableEnFont"):
        table["en_font"] = text_value("tableEnFont")
    if (value := number_value("tableSizePt", 8, 16)) is not None:
        table["size_pt"] = value
    if (value := number_value("tableLineSpacing", 1, 2)) is not None:
        table["line_spacing"] = value

    page = spec.setdefault("page", {})
    for source_key, target_key in (
        ("pageTopCm", "top_cm"),
        ("pageBottomCm", "bottom_cm"),
        ("pageLeftCm", "left_cm"),
        ("pageRightCm", "right_cm"),
    ):
        if (value := number_value(source_key, 0.5, 6)) is not None:
            page[target_key] = value

    heading = spec.setdefault("heading", {})
    for level in range(1, 7):
        level_cfg = heading.setdefault(str(level), {})
        prefix = f"heading{level}"
        if text_value(f"{prefix}ZhFont"):
            level_cfg["zh_font"] = text_value(f"{prefix}ZhFont")
        if text_value(f"{prefix}EnFont"):
            level_cfg["en_font"] = text_value(f"{prefix}EnFont")
        if (value := number_value(f"{prefix}SizePt", 8, 26)) is not None:
            level_cfg["size_pt"] = value
        if (value := number_value(f"{prefix}LineSpacing", 1, 3)) is not None:
            level_cfg["line_spacing"] = value
        if f"{prefix}Bold" in overrides:
            level_cfg["bold"] = bool(overrides.get(f"{prefix}Bold"))
        align = text_value(f"{prefix}Align")
        if align in {"left", "center", "right", "both"}:
            level_cfg["align"] = align

    toc = spec.setdefault("toc", {})
    if (value := bool_value("insertToc")) is not None:
        toc["insert_when_missing"] = value
    if (value := bool_value("tocPageBreakAfter")) is not None:
        toc["page_break_after"] = value

    header = spec.setdefault("header", {})
    if text_value("headerTextTemplate"):
        header["text_template"] = text_value("headerTextTemplate")
    if text_value("headerZhFont"):
        header["zh_font"] = text_value("headerZhFont")
    if (value := number_value("headerSizePt", 6, 14)) is not None:
        header["size_pt"] = value


def _prepare_business_format_outline(toc_json_path: Path, work_dir: Path) -> Path:
    target = work_dir / "business_format_outline.json"
    toc = _load_json_dict(toc_json_path)

    outline = {
        "schema_version": "business_bid_outline.v1",
        "document_name": str(toc.get("document_title") or "商务标响应文件"),
        "sections": _business_format_sections_from_toc_items(toc.get("items") if isinstance(toc.get("items"), list) else []),
    }
    if not outline["sections"]:
        outline["sections"] = [{"id": "BIZ-FORMAT-0001", "title": "商务投标文件", "number": "", "level": 1, "children": []}]
    target.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _business_format_sections_from_toc_items(items: list[Any]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or "").strip()
        if not title:
            continue
        try:
            level = int(raw.get("level") or 1)
        except (TypeError, ValueError):
            level = 1
        level = max(1, min(level, 9))
        section = {
            "id": str(raw.get("itemId") or raw.get("nodeId") or raw.get("id") or f"BIZ-FORMAT-{index:04d}"),
            "title": title,
            "number": str(raw.get("number") or raw.get("tocNumber") or "").strip(),
            "level": level,
            "children": [],
        }
        while stack and int(stack[-1].get("level") or 1) >= level:
            stack.pop()
        if stack:
            stack[-1].setdefault("children", []).append(section)
        else:
            roots.append(section)
        stack.append(section)
    return roots


def _run_business_format_cleaner_manifest(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    prompt = _build_business_format_cleaner_prompt(manifest_path)
    try:
        return OpencodeClient().run_bid_business_format_cleaner_with_trace(
            prompt,
            session_ready_callback=(
                (lambda details: progress_callback("format_cleaner_session_ready", details))
                if progress_callback
                else None
            ),
            stream_callback=(
                (lambda details: progress_callback("format_cleaner_delta", details))
                if progress_callback
                else None
            ),
        )
    except Exception:
        return _run_local_business_format_cleaner(manifest_path)


def _run_local_business_format_cleaner(manifest_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(BUSINESS_FORMAT_CLEANER_RUNNER), str(manifest_path), "--response", "summary"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    parsed = json.loads(completed.stdout or "{}")
    parsed["opencodeOutput"] = {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": BUSINESS_FORMAT_CLEANER_SKILL_NAME,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": completed.stdout or ""}],
    }
    return parsed


def _build_business_assembler_prompt(manifest_path: Path) -> str:
    return f"""
Use the {BUSINESS_ASSEMBLER_SKILL_NAME} skill.

你现在在做 S4 生成标书（商务标响应文件装配）。后端已经准备好 manifest、商务目录 JSON、business_gap_plan、项目事实表、解析产物、商务素材库导出目录和输出路径。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把商务投标文件 docx、business_assembly_report.md、business_needs_review.md、business_assembly_plan.json 写入 manifest 指定路径，并只在 stdout 打印小型摘要 JSON：

{BUSINESS_ASSEMBLER_SKILL_COMMAND} {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def _build_business_format_cleaner_prompt(manifest_path: Path) -> str:
    return f"""
Use the {BUSINESS_FORMAT_CLEANER_SKILL_NAME} skill.

你现在在做 S4 生成标书后的商务标 Word 格式规范化。后端已经准备好 manifest，其中包含 inputFile、outlineFile、outputFile 和 projectName。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把格式规范化后的商务标 docx 和 business_format_clean_report.md 写入 manifest 指定路径，并只在 stdout 打印小型摘要 JSON：

{BUSINESS_FORMAT_CLEANER_SKILL_COMMAND} {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _sections_from_business_assembly_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for item in plan.get("sections") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        if status in {"assembled", "generated_draft"}:
            mode = "generated"
            risks = list(item.get("riskFlags") or [])
        elif status == "placeholder":
            mode = "generated_with_placeholder"
            risks = [*list(item.get("riskFlags") or []), "MATERIAL_UNMATCHED"]
        else:
            mode = "generated_with_placeholder"
            risks = list(item.get("riskFlags") or [])
        sections.append(
            {
                "nodeId": str(item.get("tocNodeId") or item.get("title") or ""),
                "title": str(item.get("title") or "未命名章节"),
                "generationMode": mode,
                "content": f"已装配商务响应章节：{item.get('title') or '未命名章节'}",
                "riskFlags": risks,
            }
        )
    return sections


def _coverage_from_business_assembly_plan(plan: dict[str, Any]) -> dict[str, Any]:
    sections = [item for item in plan.get("sections") or [] if isinstance(item, dict)]
    full = sum(1 for item in sections if str(item.get("status") or "") in {"assembled", "generated_draft"})
    partial = sum(1 for item in sections if str(item.get("status") or "") == "review_required")
    no_cover = max(0, len(sections) - full - partial)
    total = full + partial + no_cover
    percentage = 100 if total == 0 else round(((full * 1.0) + (partial * 0.5)) / total * 100)
    return {
        "percentage": percentage,
        "fullCover": full,
        "partialCover": partial,
        "noCover": no_cover,
        "tree": [],
        "partialItems": [],
        "noCoverItems": [
            {"id": str(item.get("tocNodeId") or ""), "title": str(item.get("title") or ""), "nodeTitle": str(item.get("title") or "")}
            for item in sections
            if str(item.get("status") or "") == "placeholder"
        ],
    }


def _build_fallback_content(report_path: Path, review_path: Path) -> str:
    parts = []
    for title, path in (("装配报告", report_path), ("待复核清单", review_path)):
        if path.exists():
            parts.append(f"# {title}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts) or "# 商务标响应文件装配完成"


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file())


def _safe_filename(value: str, fallback: str) -> str:
    import re

    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback
