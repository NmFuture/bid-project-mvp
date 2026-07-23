from __future__ import annotations

import asyncio
import copy
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from app.core.config import BASE_DIR, settings
from app.services.bid_fill_generation_state import save_fill_generation_result_state
from app.services.bid_project_state import project_parse_input_records
from app.services.bid_type import TECHNICAL_BID_TYPE, require_bid_type
from app.services.minio_client import minio_client
from app.services.onlyoffice_documents import document_path
from app.services.bid_runtime_state import now_iso
from app.services.technical_gap_repository import get_technical_gap_project_runtime_state
from app.services.technical_gap_domain import (
    technical_gap_artifact_is_s7_ready,
    technical_outline_number_and_title,
)
from app.services.technical_gap_state import ensure_technical_gap_state
from app.services.technical_material_store import technical_material_store
from app.services.turbine_models import project_turbine_model
from app.services.workspace_project_access import (
    get_workspace_project_runtime_state,
    persist_workspace_project_state,
    require_workspace_project_for_update,
)
from app.services.workspace_artifacts import legacy_workspace_roots, technical_workspace_stage_dir
from app.services.wiki_export import export_wiki


ASSEMBLER_SKILL_NAME = "bid-tech-assembler"
ASSEMBLER_SKILL_COMMAND = "s7assemble"
ASSEMBLER_SKILL_DIR = BASE_DIR / "opencode" / "skills" / "bid-tech-assembler"
ASSEMBLER_RUNNER = ASSEMBLER_SKILL_DIR / "scripts" / "run_from_manifest.py"
TECH_FORMAT_CLEANER_SKILL_NAME = "bid-tech-format-cleaner"
TECH_FORMAT_CLEANER_SKILL_DIR = BASE_DIR / "opencode" / "skills" / TECH_FORMAT_CLEANER_SKILL_NAME
TECH_FORMAT_CLEANER_RUNNER = TECH_FORMAT_CLEANER_SKILL_DIR / "scripts" / "run_from_manifest.py"
WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def assemble_tech_bid_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    project = get_workspace_project_runtime_state(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: ValueError("技术标生成标书仅支持技术标项目。"),
    )
    outline_state = copy.deepcopy(project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {})
    parse_storage = copy.deepcopy(project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {})
    _, template_file_records = project_parse_input_records(project_id, project)

    if outline_state.get("reviewStatus") != "confirmed":
        raise ValueError("请先完成目录确认后再生成标书。")

    started_at = time.monotonic()
    work_dir = _prepare_work_dir(project_id, parse_storage)
    toc_json_path = _prepare_toc_json(project_id, project, outline_state, parse_storage, work_dir)
    gap_plan_path = _prepare_gap_plan(project_id, work_dir)
    if not gap_plan_path:
        raise ValueError("请先完成素材匹配，再组装技术标正文。")
    wiki_dir = work_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    material_library_dir = work_dir / "selected_materials"
    assembly_gap_plan_path, material_cards = _stage_selected_gap_plan_materials(
        gap_plan_path,
        material_library_dir,
    )
    assembler_owns_material_cleanup = False
    try:
        gap_plan_card_count = 0
        synthesized_card_count = 0
        template_file = _select_template_file(template_file_records)
        project_params = _build_project_params(project, toc_json_path)
        turbine_model = project_turbine_model(project)

        if progress_callback:
            progress_callback(
                "inputs_ready",
                {
                    "tocJsonPath": str(toc_json_path),
                    "wikiCardCount": len(material_cards),
                    "exportedMaterialCount": len([item for item in material_cards if item.get("available")]),
                    "synthesizedMaterialCardCount": synthesized_card_count,
                    "gapPlanMaterialCardCount": gap_plan_card_count,
                },
            )

        output_file = work_dir / f"{_safe_filename(str(project.get('name') or project_id), project_id)}_正文.docx"
        manifest_path = work_dir / "s7_assembly_input.json"
        bid_type = require_bid_type(
            project.get("bidType"),
            error_message="技术标正文拼装必须显式传入技术标项目。",
        )
        manifest = {
            "projectId": project_id,
            "projectName": str(project.get("name") or project_id),
            "bidType": bid_type,
            "workDir": str(work_dir),
            "tocJsonPath": str(toc_json_path),
            "gapPlanPath": str(assembly_gap_plan_path),
            "wikiDir": str(wiki_dir),
            "materialLibraryDir": str(material_library_dir),
            "templateFile": str(template_file) if template_file else "",
            "projectParamsPath": str(work_dir / "project_params.json"),
            "projectParams": project_params,
            "projectTurbineModel": turbine_model,
            "outputFile": str(output_file),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        if progress_callback:
            progress_callback(
                "calling_assembler",
                {
                    "manifestPath": str(manifest_path),
                    "workDir": str(work_dir),
                },
            )
        assembler_owns_material_cleanup = True
        result = _run_assembler_with_selected_material_cleanup(
            manifest_path,
            material_library_dir,
            progress_callback=progress_callback,
        )
    except Exception as assembly_error:
        try:
            assembly_gap_plan_path.unlink(missing_ok=True)
        except Exception as cleanup_error:
            raise ExceptionGroup(
                f"技术标组装失败，且未能清理运行态缺口计划：{assembly_gap_plan_path}",
                [assembly_error, cleanup_error],
            ) from assembly_error
        raise
    finally:
        if not assembler_owns_material_cleanup:
            _clear_selected_materials(material_library_dir)
    assembled_path = Path(str(result.get("outputFile") or output_file))
    if not assembled_path.exists():
        raise RuntimeError(f"S4 生成标书未生成输出文件：{assembled_path}")

    plan_path = Path(str(result.get("planFile") or work_dir / "assembly_plan.json"))
    plan = _load_json_list(plan_path)
    assembly_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    assembly_warnings = _normalize_warnings(result.get("warnings"))
    coverage = _build_material_coverage(plan, material_cards)
    sections = _sections_from_plan(plan)
    content = _build_fallback_content(plan, assembly_summary, assembly_warnings)

    if progress_callback:
        progress_callback(
            "assembling_result",
            {
                "sectionCount": len(sections),
                "usedMaterialCount": coverage["fullCover"],
                "unassembledMaterialCount": coverage["noCover"],
            },
        )

    format_clean = _run_tech_format_cleaner_step(
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
    file_name = final_output_path.name
    run_duration_sec = max(1, int(round(time.monotonic() - started_at)))
    filled_at = now_iso()

    opencode_output = result.get("opencodeOutput") if isinstance(result.get("opencodeOutput"), dict) else {}
    opencode_output.update(
        {
            "skill": ASSEMBLER_SKILL_NAME,
            "workDir": str(work_dir),
            "manifestPath": str(manifest_path),
            "outputFile": str(final_output_path),
            "rawOutputFile": str(assembled_path),
            "assemblyReport": "",
            "needsReview": "",
            "summary": assembly_summary,
            "warnings": assembly_warnings,
            "coverage": {
                "usedMaterialCount": coverage["fullCover"],
                "unassembledMaterialCount": coverage["noCover"],
            },
            "formatClean": format_clean,
        }
    )
    if not opencode_output.get("parts"):
        opencode_output["status"] = "received"
        opencode_output["sessionId"] = ""
        opencode_output["providerId"] = "futurecode"
        opencode_output["modelId"] = ASSEMBLER_SKILL_NAME
        opencode_output["receivedAt"] = filled_at
        opencode_output["parts"] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "skill": ASSEMBLER_SKILL_NAME,
                        "manifestPath": str(manifest_path),
                        "outputFile": str(final_output_path),
                        "rawOutputFile": str(assembled_path),
                        "assemblyReport": "",
                        "needsReview": "",
                        "summary": assembly_summary,
                        "warnings": assembly_warnings,
                        "formatClean": format_clean,
                    },
                    ensure_ascii=False,
                ),
            }
        ]

    project_for_update = require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: ValueError("技术标生成标书仅支持技术标项目。"),
    )
    payload = save_fill_generation_result_state(
        project_for_update,
        project_id=project_id,
        summary="技术标正文拼装完成。",
        sections=sections,
        content=content,
        filled_at=filled_at,
        run_duration_sec=run_duration_sec,
        file_size_bytes=file_size_bytes,
        opencode_output=opencode_output,
        file_name=file_name,
        coverage=coverage,
        assembly={
            "skill": "bid-tech-assembler",
            "workDir": str(work_dir),
            "manifestPath": str(manifest_path),
            "tocJsonPath": str(toc_json_path),
            "gapPlanPath": str(assembly_gap_plan_path),
            "wikiDir": str(wiki_dir),
            "materialLibraryDir": str(material_library_dir),
            "outputFile": str(final_output_path),
            "rawOutputFile": str(assembled_path),
            "documentPath": str(target_path),
            "assemblyReport": "",
            "needsReview": "",
            "planFile": str(plan_path),
            "summary": assembly_summary,
            "warnings": assembly_warnings,
            "formatClean": format_clean,
        },
    )
    persist_workspace_project_state(project_for_update)
    return payload


def _prepare_work_dir(project_id: str, parse_storage: dict[str, Any]) -> Path:
    work_dir = technical_workspace_stage_dir(project_id, "s7_assembly_workdir")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _runtime_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if path.exists():
        return path
    if path_text.startswith("/data/parsed/"):
        mapped = settings.parsed_dir / path_text.removeprefix("/data/parsed/")
        if mapped.exists():
            return mapped
        project_id, _, suffix = path_text.removeprefix("/data/parsed/").partition("/")
        remapped = settings.documents_dir / project_id / "technical-workspace" / suffix
        if remapped.exists():
            return remapped
    if path_text.startswith("/data/documents/"):
        mapped = settings.documents_dir / path_text.removeprefix("/data/documents/")
        if mapped.exists():
            return mapped
    if path_text.startswith("/data/uploads/"):
        mapped = settings.uploads_dir / path_text.removeprefix("/data/uploads/")
        if mapped.exists():
            return mapped
    return path


def _prepare_toc_json(
    project_id: str,
    project: dict[str, Any],
    outline_state: dict[str, Any],
    parse_storage: dict[str, Any],
    work_dir: Path,
) -> Path:
    nodes = list(outline_state.get("nodes") or [])
    if nodes:
        output = {
            "schema_version": "bid-toc-json-v1",
            "document_title": f"{project.get('name') or project_id}投标文件总目录",
            "project": {
                "owner": project.get("customerName") or "",
                "name": project.get("name") or project_id,
                "code": project.get("projectCode") or project_id,
            },
            "items": _outline_nodes_to_toc_items(nodes),
        }
        target = work_dir / settings.s2_toc_output_file_name
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    directory_state = project.get("directory_state") if isinstance(project.get("directory_state"), dict) else {}
    opencode_output = directory_state.get("opencodeOutput") or {}
    candidates = [
        str(opencode_output.get("tocJsonPath") or ""),
        str(opencode_output.get("outputFile") or ""),
    ]
    for root in legacy_workspace_roots(project_id, parse_storage):
        s2_work_dir = root / "s2_toc_workdir"
        candidates.extend(str(path) for path in sorted(s2_work_dir.glob("*.json")) if "evidence" not in path.name.lower())

    for candidate in candidates:
        if not candidate:
            continue
        path = _runtime_path(candidate)
        if path.exists() and path.suffix.lower() == ".json":
            target = work_dir / settings.s2_toc_output_file_name
            shutil.copy2(path, target)
            return target

    raise ValueError("S2 目录 JSON 不存在，且 S3 当前目录为空，暂时无法拼装正文。")


def _prepare_gap_plan(project_id: str, work_dir: Path) -> Path | None:
    technical_project = get_technical_gap_project_runtime_state(project_id)
    gap_state = ensure_technical_gap_state(technical_project)
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    if not plan:
        recovered_plan_path = technical_workspace_stage_dir(project_id, "s4_gap_workdir") / "gap_plan.json"
        if recovered_plan_path.exists():
            loaded = json.loads(recovered_plan_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                plan = loaded
    if not plan:
        return None
    plan = json.loads(json.dumps(plan, ensure_ascii=False))
    plan = _with_recovered_ai_fill_artifacts(project_id, plan)
    target = work_dir / "gap_plan.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _with_recovered_ai_fill_artifacts(project_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if not items:
        return plan
    ai_fill_dir = technical_workspace_stage_dir(project_id, "s4_gap_workdir") / "ai_fill"
    if not ai_fill_dir.exists():
        return plan

    by_gap_id = {
        str(item.get("id") or ""): item
        for item in items
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    recovered_count = 0
    for gap_dir in sorted(path for path in ai_fill_dir.glob("GAP-*") if path.is_dir()):
        item = by_gap_id.get(gap_dir.name)
        if not item:
            continue
        output_files = [
            path
            for path in sorted(gap_dir.glob("*.docx"))
            if "_AI填写" in path.stem and not path.name.startswith("~$")
        ]
        if not output_files:
            continue

        existing_paths = {
            str(artifact.get("path") or artifact.get("docx") or "")
            for artifact in item.get("resolvedArtifacts") or []
            if isinstance(artifact, dict)
        }
        artifacts: list[dict[str, Any]] = []
        for index, output_file in enumerate(output_files, start=1):
            output_path = str(output_file)
            if output_path in existing_paths:
                continue
            report = _load_ai_fill_report(output_file)
            title = str(report.get("title") or item.get("title") or output_file.stem)
            quality_report = report.get("qualityReport") if isinstance(report.get("qualityReport"), dict) else {}
            s7_ready = bool(report.get("s7Ready")) or quality_report.get("status") == "passed"
            artifacts.append(
                {
                    "id": f"RECOVERED-{gap_dir.name}-{index:03d}",
                    "source": "ai_fill",
                    "skill": str(report.get("skill") or ""),
                    "gapId": gap_dir.name,
                    "title": title,
                    "fileName": output_file.name,
                    "path": output_path,
                    "qualityReport": quality_report,
                    "s7Ready": s7_ready,
                    "qualityGate": "auto_passed" if s7_ready else "needs_review",
                    "confirmed": s7_ready,
                    "recoveredBy": "s4_assembly",
                }
            )
        if not artifacts:
            continue
        item.setdefault("resolvedArtifacts", []).extend(artifacts)
        item["matchedMaterials"] = []
        item["status"] = "resolved" if all(artifact["s7Ready"] for artifact in artifacts) else "needs_input"
        item["resolvedSource"] = f"{len(item.get('resolvedArtifacts') or [])} 份AI填写产物"
        recovered_count += len(artifacts)

    if recovered_count:
        plan = dict(plan)
        plan["s7RecoveredAiFillArtifactCount"] = recovered_count
    return plan


def _load_ai_fill_report(output_file: Path) -> dict[str, Any]:
    report_path = output_file.with_suffix(".fill_report.json")
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            report = data.get("fillReport") if isinstance(data.get("fillReport"), dict) else {}
            merged = dict(report)
            if isinstance(data.get("qualityReport"), dict):
                merged["qualityReport"] = data["qualityReport"]
            if "s7Ready" in data:
                merged["s7Ready"] = bool(data.get("s7Ready"))
            for key in ("title", "skill", "status"):
                if data.get(key) and key not in merged:
                    merged[key] = data.get(key)
            return merged
    return {}


def _gap_plan_has_resolved_artifacts(plan: dict[str, Any]) -> bool:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        for artifact in item.get("resolvedArtifacts") or []:
            if not isinstance(artifact, dict):
                continue
            if not technical_gap_artifact_is_s7_ready(artifact):
                continue
            path = _runtime_path(str(artifact.get("path") or artifact.get("docx") or ""))
            if path.exists() and path.suffix.lower() == ".docx":
                return True
    return False


def _outline_nodes_to_toc_items(nodes: list[dict[str, Any]], prefix: str = "", level: int = 1) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        fallback_number = f"{prefix}.{index}" if prefix else str(index)
        number, title = technical_outline_number_and_title(node, fallback_number)
        flat_number = (
            ""
            if re.match(r"^(?:技术)?附表|^副表|^附件", number, flags=re.IGNORECASE)
            else fallback_number
        )
        items.append(
            {
                "order": len(items),
                "level": level,
                "number": number,
                "chapter_no_flat": flat_number,
                "title": title,
                "annotation": str(node.get("annotation") or "保留"),
                "source": "outline_state",
                "reason": "",
            }
        )
        children = node.get("children") or []
        if isinstance(children, list):
            items.extend(_outline_nodes_to_toc_items(children, fallback_number, level + 1))
    return items


def _prepare_wiki_dir(project: dict[str, Any], parse_storage: dict[str, Any], work_dir: Path) -> Path:
    target = work_dir / "wiki"
    project_id = str(project.get("id") or "")
    candidates = [_runtime_path(str(root / "s2_toc_workdir" / "wiki")) for root in legacy_workspace_roots(project_id, parse_storage)]
    for candidate in candidates:
        if (candidate / "卡片").exists():
            shutil.copytree(candidate, target, dirs_exist_ok=True)
            return target

    target.mkdir(parents=True, exist_ok=True)
    cards_dir = target / "卡片"
    cards_dir.mkdir(parents=True, exist_ok=True)
    try:
        export_wiki(
            api_base=settings.bid_internal_api_base_url or "http://fastapi:8000",
            bid_type=require_bid_type(
                project.get("bidType"),
                error_message="技术标 Wiki 导出必须显式传入技术标项目。",
            ),
            out_dir=target,
        )
    except Exception:
        # Wiki API is a convenience source. S4 can still synthesize filesystem
        # cards from the material library below, so keep the assembly path alive.
        cards_dir.mkdir(parents=True, exist_ok=True)
    if not cards_dir.exists():
        cards_dir.mkdir(parents=True, exist_ok=True)
    return target


def _select_template_file(template_file_records: list[dict[str, Any]]) -> Path | None:
    for record in template_file_records:
        path = _runtime_path(str(record.get("path") or ""))
        if path.exists() and path.suffix.lower() == ".docx" and "附表" not in str(record.get("name") or path.name):
            return path
    for record in template_file_records:
        path = _runtime_path(str(record.get("path") or ""))
        if path.exists() and path.suffix.lower() == ".docx":
            return path
    return None


def _build_project_params(project: dict[str, Any], toc_json_path: Path) -> dict[str, Any]:
    data = json.loads(toc_json_path.read_text(encoding="utf-8"))
    toc_project = data.get("project") if isinstance(data, dict) else {}
    if not isinstance(toc_project, dict):
        toc_project = {}
    turbine = project_turbine_model(project)
    return {
        "project_name": str(toc_project.get("name") or project.get("name") or project.get("id") or ""),
        "project_short": str(project.get("name") or project.get("id") or "项目")[:24],
        "client_name": str(toc_project.get("owner") or project.get("customerName") or ""),
        "tender_no": str(toc_project.get("code") or project.get("projectCode") or ""),
        "turbine_model": str(turbine.get("model") or ""),
        "turbine_platform": str(turbine.get("platform") or ""),
        "rated_power_kw": turbine.get("ratedPowerKw") or "",
        "rotor_diameter_m": turbine.get("rotorDiameterM") or "",
        "turbine_layout": str(turbine.get("layout") or ""),
    }


def _augment_wiki_with_material_cards(toc_json_path: Path, wiki_dir: Path, project: dict[str, Any]) -> int:
    """S4 bid assembly needs one filesystem card per source material.

    The platform Wiki API currently exports useful root pages plus aggregate
    card pages. The legacy assembler, however, matches `卡片/*.md` by
    frontmatter. This adapter writes project-scoped, per-material cards without
    changing the database Wiki itself.
    """

    cards_dir = wiki_dir / "卡片"
    cards_dir.mkdir(parents=True, exist_ok=True)
    toc_entries = _load_toc_match_entries(toc_json_path)
    if not toc_entries:
        return 0

    raw_payload = _run_async(
        technical_material_store.raw_files(
            page=1,
            page_size=1000,
        )
    )
    raw_items = [item for item in raw_payload.get("items") or [] if isinstance(item, dict)]
    identity = _project_identity_from_toc(toc_json_path, project)

    written = 0
    for item in raw_items:
        if not _material_is_assemblable(item):
            continue
        if not _material_matches_project(item, identity):
            continue
        section, score = _best_toc_section_for_material(item, toc_entries)
        if not section or score < 8:
            continue
        card_path = cards_dir / f"RAW-{str(item.get('id') or '').replace('/', '-')}-{_safe_filename(str(item.get('name') or 'material'), 'material')}.md"
        card_path.write_text(_render_runtime_material_card(item, section), encoding="utf-8")
        written += 1
    return written


def _augment_wiki_with_gap_plan_cards(gap_plan_path: Path | None, wiki_dir: Path) -> int:
    if not gap_plan_path or not gap_plan_path.exists():
        return 0
    plan = json.loads(gap_plan_path.read_text(encoding="utf-8"))
    items = plan.get("items") if isinstance(plan, dict) else []
    if not isinstance(items, list):
        return 0
    cards_dir = wiki_dir / "卡片"
    cards_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        section = str(item.get("number") or item.get("tocItemId") or "").strip()
        title = str(item.get("title") or "缺口补料").strip()
        sources: list[dict[str, Any]] = []
        sources.extend(source for source in item.get("matchedMaterials") or [] if isinstance(source, dict))
        sources.extend(source for source in item.get("resolvedArtifacts") or [] if isinstance(source, dict))
        for index, source in enumerate(sources, start=1):
            material_id = str(source.get("id") or "")
            path = str(source.get("path") or source.get("docx") or "").strip()
            if not material_id and not path:
                continue
            card_name = _safe_filename(str(source.get("title") or source.get("fileName") or title), f"{title}-{index}")
            card_path = cards_dir / f"gap-plan-{_safe_filename(section, 'section')}-{index}-{card_name}.md"
            card_path.write_text(
                _render_gap_plan_material_card(
                    item=item,
                    source=source,
                    section=section,
                    title=card_name,
                ),
                encoding="utf-8",
            )
            written += 1
    return written


def _render_gap_plan_material_card(
    *,
    item: dict[str, Any],
    source: dict[str, Any],
    section: str,
    title: str,
) -> str:
    source_type = str(source.get("source") or "gap_plan")
    scope = "定制" if source_type in {"ai_fill", "manual"} else "通用"
    path = str(source.get("path") or source.get("docx") or "").strip()
    material_id = str(source.get("id") or "")
    file_name = str(source.get("fileName") or Path(path).name or f"{title}.docx")
    lines = [
        "---",
        f"name: {json.dumps(title, ensure_ascii=False)}",
        f"path: {json.dumps(path or file_name, ensure_ascii=False)}",
        f"scope: {json.dumps(scope, ensure_ascii=False)}",
        'category: "缺口处理"',
        f"material_id: {json.dumps(material_id if material_id.startswith('RAW-') else '', ensure_ascii=False)}",
        f"cleaned_file_name: {json.dumps(file_name, ensure_ascii=False)}",
        f"skeleton_section: {json.dumps(section, ensure_ascii=False)}",
        'skeleton_level: "section"',
        'material_level_range: "none"',
        "heading_count: 0",
        "shift: 0",
        'attach_mode: "normal"',
        "deprecated: false",
        "---",
        "",
        f"# {title}",
        "",
        "## Gap Plan 信息",
        f"- toc_title: {item.get('title') or ''}",
        f"- source: {source_type}",
        f"- path: {path}",
        f"- material_id: {material_id}",
        f"- skeleton_section: {section}",
    ]
    return "\n".join(lines).strip() + "\n"


def _load_toc_match_entries(toc_json_path: Path) -> list[dict[str, str]]:
    data = json.loads(toc_json_path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else []
    entries: list[dict[str, str]] = []
    if not isinstance(items, list):
        return entries
    for item in items:
        if not isinstance(item, dict):
            continue
        number = str(item.get("number") or "").strip()
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        flat = _toc_number_to_flat(number)
        if not flat and not number.startswith("第"):
            continue
        entries.append(
            {
                "section": flat,
                "number": number,
                "title": title,
                "text": f"{number} {title}".strip(),
            }
        )
    return entries


def _toc_number_to_flat(number: str) -> str:
    text = str(number or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+){0,6}", text):
        return text
    chapter_match = re.fullmatch(r"第([一二三四五六七八九十百千万0-9]+)章", text)
    if chapter_match:
        return str(_chinese_number_to_int(chapter_match.group(1)))
    return ""


def _chinese_number_to_int(value: str) -> int:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(text, 0)


def _project_identity_from_toc(toc_json_path: Path, project: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(toc_json_path.read_text(encoding="utf-8"))
    toc_project = data.get("project") if isinstance(data, dict) else {}
    identity = toc_project.get("identity") if isinstance(toc_project, dict) else {}
    if not isinstance(identity, dict):
        identity = {}
    aliases = identity.get("customerAliases") if isinstance(identity.get("customerAliases"), list) else []
    return {
        "customerId": str(identity.get("customerId") or ""),
        "customerName": str(
            identity.get("customerCanonicalName")
            or identity.get("customerName")
            or project.get("customerName")
            or ""
        ),
        "customerAliases": {str(item) for item in aliases if str(item).strip()},
        "projectId": str(identity.get("projectId") or project.get("projectId") or ""),
        "projectCode": str(identity.get("projectCode") or project.get("projectCode") or ""),
        "workspaceProjectId": str(identity.get("workspaceProjectId") or project.get("id") or ""),
    }


def _material_is_assemblable(item: dict[str, Any]) -> bool:
    name = str(item.get("name") or "")
    cleaned_name = str(item.get("cleanedFileName") or "")
    ext = Path(name).suffix.lower()
    if bool(item.get("hasCleanedWord")) or cleaned_name.lower().endswith(".docx"):
        return True
    return ext == ".docx"


def _material_matches_project(item: dict[str, Any], identity: dict[str, Any]) -> bool:
    scope = str(item.get("identityScope") or "").strip().lower()
    tier = str(item.get("materialTier") or "").strip().lower()
    if scope in {"", "general"} and tier in {"", "standard", "general"}:
        return True
    if scope == "customer" or tier == "customer":
        material_customer_id = str(item.get("customerId") or "")
        if material_customer_id and material_customer_id == str(identity.get("customerId") or ""):
            return True
        names = {
            str(item.get("customerName") or ""),
            str(item.get("customerCanonicalName") or ""),
            *[str(alias) for alias in item.get("customerAliases") or []],
        }
        project_names = {
            str(identity.get("customerName") or ""),
            *[str(alias) for alias in identity.get("customerAliases") or []],
        }
        return bool({name for name in names if name} & {name for name in project_names if name})
    if scope == "project" or tier == "project":
        project_keys = {
            str(identity.get("projectId") or ""),
            str(identity.get("projectCode") or ""),
            str(identity.get("workspaceProjectId") or ""),
        }
        material_keys = {
            str(item.get("projectId") or ""),
            str(item.get("projectCode") or ""),
        }
        return bool({key for key in project_keys if key} & {key for key in material_keys if key})
    return True


def _best_toc_section_for_material(item: dict[str, Any], toc_entries: list[dict[str, str]]) -> tuple[str, int]:
    material_name_text = " ".join(
        [
            str(item.get("name") or ""),
            str(item.get("cleanedFileName") or ""),
        ]
    )
    material_text = " ".join([material_name_text, str(item.get("folderPath") or "")])
    best_section = ""
    best_score = 0
    best_rank: tuple[int, int, int] = (0, 0, 0)
    for entry in toc_entries:
        title = str(entry.get("title") or "")
        score = _title_match_score(material_text, title)
        direct_score = _title_match_score(material_name_text, title)
        depth = len(str(entry.get("section") or "").split("."))
        rank = (score, direct_score, depth)
        if rank > best_rank:
            best_rank = rank
            best_score = score
            best_section = str(entry.get("section") or "")
    return best_section, best_score


def _title_match_score(material_text: str, toc_title: str) -> int:
    material = _normalize_match_text(material_text)
    title = _normalize_match_text(toc_title)
    if not material or not title:
        return 0
    score = 0
    if title in material or material in title:
        score += 100
    for n in (6, 5, 4, 3, 2):
        seen: set[str] = set()
        for index in range(max(0, len(title) - n + 1)):
            token = title[index : index + n]
            if token in seen or token not in material:
                continue
            seen.add(token)
            score += n
    return score


def _normalize_match_text(value: str) -> str:
    text = re.sub(r"\.(docx|doc|pdf|xlsx|xlsm|xls)$", "", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"技术标|商务标|专题|方案|报告|情况|一览表|相关|项目|投标|文件", "", text)
    return re.sub(r"[\s:：，,。.！!？?\\\-_/'\"“”‘’·（）()【】\[\]/]+", "", text)


def _render_runtime_material_card(item: dict[str, Any], section: str) -> str:
    name = str(item.get("name") or item.get("cleanedFileName") or "未命名素材")
    card_name = Path(str(item.get("cleanedFileName") or name)).stem
    scope = "通用" if str(item.get("materialTier") or "") == "standard" else "定制"
    category = str(item.get("group") or Path(str(item.get("folderPath") or "素材")).name or "素材")
    cleaned_name = str(item.get("cleanedFileName") or "")
    bid_type = require_bid_type(
        item.get("bidType"),
        error_message="技术标运行态素材卡片必须显式传入标类。",
    )
    lines = [
        "---",
        f"name: {json.dumps(card_name, ensure_ascii=False)}",
        f"path: {json.dumps(str(item.get('folderPath') or '') + '/' + name, ensure_ascii=False)}",
        f"scope: {json.dumps(scope, ensure_ascii=False)}",
        f"category: {json.dumps(category, ensure_ascii=False)}",
        f"material_id: {json.dumps(str(item.get('id') or ''), ensure_ascii=False)}",
        f"identity_scope: {json.dumps(str(item.get('identityScope') or 'general'), ensure_ascii=False)}",
        f"material_scope: {json.dumps(str(item.get('materialScope') or item.get('identityScope') or 'general'), ensure_ascii=False)}",
        f"bid_type: {json.dumps(bid_type, ensure_ascii=False)}",
        f"customer_id: {json.dumps(str(item.get('customerId') or ''), ensure_ascii=False)}",
        f"customer_name: {json.dumps(str(item.get('customerCanonicalName') or item.get('customerName') or ''), ensure_ascii=False)}",
        f"customer_aliases: {json.dumps('、'.join(str(alias) for alias in item.get('customerAliases') or []), ensure_ascii=False)}",
        f"project_id: {json.dumps(str(item.get('projectId') or ''), ensure_ascii=False)}",
        f"project_code: {json.dumps(str(item.get('projectCode') or ''), ensure_ascii=False)}",
        f"cleaned_file_name: {json.dumps(cleaned_name, ensure_ascii=False)}",
        f"skeleton_section: {json.dumps(section, ensure_ascii=False)}",
        'skeleton_level: "section"',
        'material_level_range: "none"',
        "heading_count: 0",
        "shift: 0",
        'attach_mode: "normal"',
        "deprecated: false",
        "---",
        "",
        f"# {Path(cleaned_name or name).stem}",
        "",
        "## Merge 信息",
        f"- path: {str(item.get('folderPath') or '').strip('/')}/{name}",
        f"- material_id: {str(item.get('id') or '')}",
        f"- skeleton_section: {section}",
        f"- cleaned_file_name: {cleaned_name}",
    ]
    return "\n".join(lines).strip() + "\n"


def _export_material_library(wiki_dir: Path, library_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    if library_dir.exists():
        shutil.rmtree(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)

    cards: list[dict[str, Any]] = []
    for card_path in sorted((wiki_dir / "卡片").rglob("*.md")):
        text = card_path.read_text(encoding="utf-8")
        fields = _parse_card_fields(text)
        if not fields:
            continue
        material_id = str(fields.get("material_id") or "").strip()
        title = _card_title(text, card_path)
        scope = str(fields.get("scope") or "通用").strip() or "通用"
        category = str(fields.get("category") or "素材").strip() or "素材"
        original_path = str(fields.get("path") or "").strip()
        file_name = _material_file_name(fields, original_path, title)
        relative_path = _material_relative_path(scope, category, file_name)
        target_path = library_dir / relative_path
        card = {
            "id": material_id or original_path or str(card_path),
            "title": title,
            "path": relative_path,
            "originalPath": original_path,
            "scope": scope,
            "category": category,
            "cardFile": str(card_path),
            "available": False,
        }

        try:
            _copy_material_to_library(material_id, original_path, target_path)
            card["available"] = target_path.exists()
        except Exception as exc:
            card["error"] = str(exc)

        updated_fields = {"path": relative_path}
        if not card["available"]:
            updated_fields["deprecated"] = "true"
            updated_fields["condition"] = f"素材文件未导出：{card.get('error') or 'unknown'}"
        card_path.write_text(_replace_frontmatter_fields(text, updated_fields), encoding="utf-8")
        cards.append(card)
    return library_dir, cards


def _payload_is_docx(payload: dict[str, Any]) -> bool:
    mime_type = str(payload.get("mimeType") or "")
    file_name = str(payload.get("fileName") or "")
    return "wordprocessingml" in mime_type or file_name.lower().endswith(".docx")


def _cleanup_partial_download(target_path: Path, download_error: Exception) -> Exception:
    cleanup_errors: list[Exception] = []
    temp_path = target_path.with_suffix(f"{target_path.suffix}.download")
    for partial_path in (target_path, temp_path):
        try:
            partial_path.unlink(missing_ok=True)
        except Exception as cleanup_error:
            cleanup_errors.append(cleanup_error)
    if cleanup_errors:
        return ExceptionGroup(
            f"下载失败且未能清理部分文件：{target_path}",
            [download_error, *cleanup_errors],
        )
    return download_error


def _stage_selected_gap_plan_materials(
    gap_plan_path: Path,
    staging_dir: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    runtime_plan_path = gap_plan_path.with_name("assembly_gap_plan.json")
    _clear_selected_materials(staging_dir)
    if runtime_plan_path.exists():
        runtime_plan_path.unlink()
    staging_dir.mkdir(parents=True, exist_ok=True)

    plan = json.loads(gap_plan_path.read_text(encoding="utf-8"))
    items = plan.get("items") if isinstance(plan, dict) else []
    staged_materials: list[dict[str, Any]] = []
    try:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("coverageRole") or item.get("coverage_role") or "").strip() == "covered_by_parent":
                continue

            resolved_artifacts = item.get("resolvedArtifacts") or []
            source_key = "resolvedArtifacts" if resolved_artifacts else "matchedMaterials"
            sources = item.get(source_key) or []
            for index, source in enumerate(sources if isinstance(sources, list) else [], start=1):
                if not isinstance(source, dict):
                    continue
                if source_key == "resolvedArtifacts" and not technical_gap_artifact_is_s7_ready(source):
                    continue

                original_path = str(source.get("path") or source.get("docx") or "").strip()
                source_name = str(
                    source.get("fileName")
                    or source.get("name")
                    or Path(original_path).name
                    or f"material-{index}.docx"
                )
                gap_id = _safe_filename(str(item.get("id") or item.get("number") or "gap"), "gap")
                file_name = _safe_filename(source_name, f"material-{index}.docx")
                relative_path = Path(gap_id) / f"{index:02d}-{file_name}"
                target_path = staging_dir / relative_path
                try:
                    _copy_material_to_library(
                        str(source.get("materialId") or source.get("id") or ""),
                        original_path,
                        target_path,
                    )
                except Exception as exc:
                    number = str(item.get("number") or item.get("id") or "未编号目录")
                    raise RuntimeError(f"{number} 已选素材 {source_name} 准备失败：{exc}") from exc

                source["path"] = relative_path.as_posix()
                staged_materials.append(
                    {
                        "id": str(source.get("id") or ""),
                        "title": source_name,
                        "path": relative_path.as_posix(),
                        "originalPath": original_path,
                        "gapId": str(item.get("id") or ""),
                        "available": True,
                    }
                )

        runtime_plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return runtime_plan_path, staged_materials
    except Exception:
        _clear_selected_materials(staging_dir)
        if runtime_plan_path.exists():
            runtime_plan_path.unlink()
        raise


def _clear_selected_materials(staging_dir: Path) -> None:
    if staging_dir.exists():
        shutil.rmtree(staging_dir)


def _run_assembler_with_selected_material_cleanup(
    manifest_path: Path,
    staging_dir: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    try:
        return _run_assembler_manifest(manifest_path, progress_callback=progress_callback)
    finally:
        _clear_selected_materials(staging_dir)


def _copy_material_to_library(material_id: str, original_path: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    path = _runtime_path(original_path)
    if path.exists() and path.suffix.lower() == ".docx":
        shutil.copy2(path, target_path)
        return

    if material_id:
        # 优先使用原始 Word：素材清洗版可能误改标题层级（把正文短句升为
        # Heading），S7 只认原始 docx 真实的 Heading/outlineLvl/TOC，不猜层级。
        raw_error: Exception | None = None
        try:
            candidate = _run_async(technical_material_store.raw_download_content(material_id))
        except Exception as exc:
            raw_error = exc
        else:
            if _payload_is_docx(candidate):
                try:
                    minio_client.download_file(
                        str(candidate["bucket"]),
                        str(candidate["key"]),
                        target_path,
                    )
                except Exception as exc:
                    raw_error = _cleanup_partial_download(target_path, exc)
                else:
                    return

        # 原始文件缺失、实际下载失败或不是 docx（如 .doc）时回退清洗稿。
        cleaned_error: Exception | None = None
        try:
            payload = _run_async(technical_material_store.raw_download_cleaned_content(material_id))
        except Exception as exc:
            cleaned_error = exc
        else:
            if not _payload_is_docx(payload):
                cleaned_error = RuntimeError(f"素材 {material_id} 不是可拼装 docx。")
            else:
                try:
                    minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
                except Exception as exc:
                    cleaned_error = _cleanup_partial_download(target_path, exc)
                else:
                    return

        if cleaned_error is not None:
            if raw_error is None:
                raise cleaned_error
            raise ExceptionGroup(
                f"素材 {material_id} 原始 Word 与清洗稿均无法下载。",
                [raw_error, cleaned_error],
            )
    raise RuntimeError("卡片缺少 material_id，且 path 不是可读 docx。")


def _run_async(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("素材导出不能在已运行的 asyncio event loop 中同步执行。")


def _parse_card_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            for raw_line in text[3:end].strip().splitlines():
                if ":" not in raw_line:
                    continue
                key, _, value = raw_line.partition(":")
                fields[key.strip()] = _clean_field_value(value)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- ") or ":" not in line:
            continue
        key, _, value = line[2:].partition(":")
        key = key.strip()
        if key in {
            "path",
            "material_id",
            "scope",
            "category",
            "skeleton_section",
            "cleaned_file_name",
            "cleanedFileName",
            "deprecated",
            "condition",
        }:
            fields.setdefault(key, _clean_field_value(value))
    return fields


def _replace_frontmatter_fields(text: str, updates: dict[str, str]) -> str:
    if not text.startswith("---"):
        lines = ["---", *[f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in updates.items()], "---", "", text]
        return "\n".join(lines)
    end = text.find("\n---", 3)
    if end < 0:
        return text
    body = text[end + len("\n---") :]
    lines = text[3:end].strip().splitlines()
    seen: set[str] = set()
    out_lines: list[str] = ["---"]
    for raw_line in lines:
        if ":" not in raw_line:
            out_lines.append(raw_line)
            continue
        key, _, _ = raw_line.partition(":")
        clean_key = key.strip()
        if clean_key in updates:
            out_lines.append(f"{clean_key}: {json.dumps(str(updates[clean_key]), ensure_ascii=False)}")
            seen.add(clean_key)
        else:
            out_lines.append(raw_line)
    for key, value in updates.items():
        if key not in seen:
            out_lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    out_lines.append("---")
    return "\n".join(out_lines) + body


def _clean_field_value(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def _card_title(text: str, card_path: Path) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            return line[2:].strip() or card_path.stem
    return card_path.stem


def _material_file_name(fields: dict[str, str], original_path: str, title: str) -> str:
    name = str(fields.get("cleaned_file_name") or fields.get("cleanedFileName") or "").strip()
    if not name:
        name = Path(original_path).name if original_path else f"{title}.docx"
    if not name.lower().endswith(".docx"):
        name = f"{Path(name).stem}.docx"
    return _safe_filename(name, "material.docx")


def _material_relative_path(scope: str, category: str, file_name: str) -> str:
    root = "投标资料库-通用" if scope == "通用" else "投标资料库-定制"
    return str(Path(root) / _safe_filename(category, "素材") / _safe_filename(file_name, "material.docx"))


def _run_assembler_manifest(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    if progress_callback:
        progress_callback(
            "assembler_session_ready",
            {
                "sessionId": str(manifest_path),
                "providerId": "local-skill",
                "modelId": ASSEMBLER_SKILL_NAME,
            },
        )
    return _run_local_assembler(manifest_path)


def _run_local_assembler(manifest_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(ASSEMBLER_RUNNER), "--manifest", str(manifest_path), "--response", "summary"],
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
        "modelId": ASSEMBLER_SKILL_NAME,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": completed.stdout or ""}],
    }
    return parsed


def _run_tech_format_cleaner_step(
    *,
    project: dict[str, Any],
    toc_json_path: Path,
    assembled_path: Path,
    work_dir: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    manifest_path = work_dir / "tech_format_clean_input.json"
    outline_path = _prepare_tech_format_outline(toc_json_path, work_dir)
    output_path = assembled_path.with_name(f"{assembled_path.stem}.formatted.docx")
    manifest = {
        "schemaVersion": "bid-tech-format-clean-manifest-v1",
        "inputFile": str(assembled_path),
        "outlineFile": str(outline_path),
        "outputFile": str(output_path),
        "projectName": str(project.get("name") or project.get("id") or "技术标项目"),
        "styleSpecPath": str(ASSEMBLER_SKILL_DIR / "references" / "heading_style.json"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if progress_callback:
        progress_callback(
            "calling_format_cleaner",
            {
                "manifestPath": str(manifest_path),
                "inputFile": str(assembled_path),
                "skill": TECH_FORMAT_CLEANER_SKILL_NAME,
            },
        )

    try:
        result = _run_local_tech_format_cleaner(manifest_path)
        formatted_path = Path(str(result.get("outputFile") or output_path)).expanduser()
        if not formatted_path.exists():
            raise RuntimeError(f"技术标格式清洗未生成输出文件：{formatted_path}")
        clean_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        clean_warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else clean_summary.get("warnings")
        clean = {
            "status": "completed",
            "skill": TECH_FORMAT_CLEANER_SKILL_NAME,
            "manifestPath": str(manifest_path),
            "inputFile": str(assembled_path),
            "outlineFile": str(outline_path),
            "outputFile": str(formatted_path),
            "reportFile": "",
            "summary": clean_summary,
            "warnings": _normalize_warnings(clean_warnings),
            "opencodeOutput": result.get("opencodeOutput") if isinstance(result.get("opencodeOutput"), dict) else {},
        }
        if progress_callback:
            progress_callback(
                "format_cleaner_completed",
                {"summary": clean["summary"], "outputFile": clean["outputFile"], "skill": TECH_FORMAT_CLEANER_SKILL_NAME},
            )
        return clean
    except Exception as exc:
        clean = {
            "status": "failed",
            "skill": TECH_FORMAT_CLEANER_SKILL_NAME,
            "manifestPath": str(manifest_path),
            "inputFile": str(assembled_path),
            "outlineFile": str(outline_path),
            "outputFile": str(assembled_path),
            "reportFile": "",
            "summary": {},
            "warnings": [],
            "opencodeOutput": {},
            "error": str(exc),
        }
        if progress_callback:
            progress_callback(
                "format_cleaner_failed",
                {"error": str(exc), "manifestPath": str(manifest_path), "skill": TECH_FORMAT_CLEANER_SKILL_NAME},
            )
        return clean


def _run_local_tech_format_cleaner(manifest_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(TECH_FORMAT_CLEANER_RUNNER), str(manifest_path), "--response", "summary"],
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
        "modelId": TECH_FORMAT_CLEANER_SKILL_NAME,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": completed.stdout or ""}],
    }
    return parsed


def _prepare_tech_format_outline(toc_json_path: Path, work_dir: Path) -> Path:
    target = work_dir / "tech_format_outline.json"
    toc = json.loads(toc_json_path.read_text(encoding="utf-8"))
    items = toc.get("items") if isinstance(toc, dict) and isinstance(toc.get("items"), list) else []
    outline = {
        "schema_version": "tech_bid_outline.v1",
        "document_name": str(toc.get("document_title") or "技术标投标文件") if isinstance(toc, dict) else "技术标投标文件",
        "sections": _tech_format_sections_from_toc_items(items),
    }
    if not outline["sections"]:
        outline["sections"] = [{"id": "TECH-FORMAT-0001", "title": "技术标投标文件", "number": "", "level": 1, "children": []}]
    target.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _tech_format_sections_from_toc_items(items: list[Any]) -> list[dict[str, Any]]:
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
        level = _infer_tech_format_level(raw, default=level)
        section = {
            "id": str(raw.get("itemId") or raw.get("nodeId") or raw.get("id") or f"TECH-FORMAT-{index:04d}"),
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


def _infer_tech_format_level(item: dict[str, Any], *, default: int = 1) -> int:
    level = max(1, min(int(default or 1), 9))
    candidates = [
        str(item.get("number") or item.get("tocNumber") or "").strip(),
        str(item.get("chapter_no_flat") or item.get("chapterNoFlat") or "").strip(),
        str(item.get("chapter_no") or item.get("chapterNo") or "").strip(),
    ]
    title = str(item.get("title") or item.get("name") or "").strip()
    if title:
        candidates.append(title)
    inferred = max((_infer_tech_format_level_from_number(value) or 0 for value in candidates), default=0)
    if inferred:
        level = max(level, inferred)
    return max(1, min(level, 9))


def _infer_tech_format_level_from_number(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    first_token = re.split(r"\s+", text, maxsplit=1)[0]
    candidate = first_token.strip("：:、")
    if re.fullmatch(r"第[一二三四五六七八九十百\d]+章", candidate):
        return 1
    if re.fullmatch(r"\d+(?:\.\d+)*", candidate):
        return candidate.count(".") + 1

    appendix = re.fullmatch(r"(?:技术)?附表\s*([A-Za-z])((?:[.-]\d+)*)", candidate)
    if appendix:
        suffix = appendix.group(2) or ""
        parts = [part for part in re.split(r"[.-]", suffix) if part]
        return 1 + len(parts)

    if re.fullmatch(r"附表\d+", candidate) or re.fullmatch(r"技术附表[A-Za-z]", candidate):
        return 1
    return None


def _build_assembler_prompt(manifest_path: Path) -> str:
    return f"""
Use the {ASSEMBLER_SKILL_NAME} skill.

你现在在做 S4 生成标书（技术标正文拼装）。后端已经准备好 manifest、S1 目录 JSON、Wiki 文件系统副本、素材库导出目录和输出路径。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整正文 docx 和 assembly_plan.json 写入 manifest 指定路径，并只在 stdout 打印小型摘要 JSON：

{ASSEMBLER_SKILL_COMMAND} {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schema_version": "bid-tech-assembly-v1",
  "outputFile": "/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/投标文件-正文.docx",
  "assemblyReport": "",
  "needsReview": "",
  "planFile": "/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/assembly_plan.json",
  "summary": {{"total": 0, "byStatus": {{}}, "usedPathCount": 0, "warningCount": 0}},
  "warnings": []
}}
""".strip()


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return _iter_dicts(data)


def _iter_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _sections_from_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for item in _iter_dicts(plan):
        if _safe_int(item.get("level")) != 1 or str(item.get("status") or "") == "OUT_OF_SCOPE":
            continue
        status = str(item.get("status") or "")
        if status in {"MATCHED", "ADAPTED", "COVER", "STRUCTURAL"}:
            generation_mode = "generated"
            risk_flags: list[str] = []
        elif status == "NEEDS_REVIEW":
            generation_mode = "generated_with_placeholder"
            risk_flags = ["FACT_REQUIRED"]
        else:
            generation_mode = "placeholder"
            risk_flags = ["MATERIAL_UNMATCHED"]
        title = str(item.get("title") or "未命名章节")
        sections.append(
            {
                "nodeId": f"TOC-{item.get('toc_idx')}",
                "title": title,
                "generationMode": generation_mode,
                "content": f"已按目录拼装：{title}",
                "riskFlags": risk_flags,
            }
        )
    return sections


def _build_material_coverage(plan: list[dict[str, Any]], cards: list[dict[str, Any]]) -> dict[str, Any]:
    used_paths: set[str] = set()
    used_path_keys: set[str] = set()
    partial_items: list[dict[str, Any]] = []
    for item in _iter_dicts(plan):
        status = str(item.get("status") or "")
        if status in {"MATCHED", "ADAPTED", "COVER"}:
            for path in item.get("paths") or []:
                path_text = str(path).strip()
                if not path_text:
                    continue
                used_paths.add(path_text)
                used_path_keys.update(_coverage_path_keys(path_text))
        elif status in {"UNMATCHED", "NEEDS_REVIEW"}:
            partial_items.append(
                {
                    "id": f"TOC-{item.get('toc_idx')}",
                    "title": str(item.get("title") or "未命名目录项"),
                    "nodeTitle": f"目录项未匹配素材：{item.get('chapter_no') or ''}".strip(),
                }
            )

    material_cards = [card for card in _iter_dicts(cards) if card.get("available")]
    no_cover_items = [
        {
            "id": str(card.get("id") or card.get("path") or ""),
            "title": str(card.get("title") or card.get("path") or "未命名素材"),
            "nodeTitle": f"素材未出现在 S2 目录 JSON 或拼装计划中：{card.get('scope') or ''}/{card.get('category') or ''}",
        }
        for card in material_cards
        if not _coverage_card_used(card, used_path_keys)
    ]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in material_cards:
        scope = str(card.get("scope") or "通用")
        category = str(card.get("category") or "素材")
        grouped[f"{scope}/{category}"].append(card)

    tree: list[dict[str, Any]] = []
    for group_name, group_cards in sorted(grouped.items()):
        children = []
        for card in sorted(group_cards, key=lambda item: str(item.get("title") or "")):
            used = _coverage_card_used(card, used_path_keys)
            children.append(
                {
                    "id": str(card.get("id") or card.get("path") or ""),
                    "title": str(card.get("title") or card.get("path") or "未命名素材"),
                    "coverage": 100 if used else 0,
                    "status": "full" if used else "none",
                    "children": [],
                }
            )
        used_count = sum(1 for child in children if child["status"] == "full")
        coverage = 100 if not children else round(used_count / len(children) * 100)
        tree.append(
            {
                "id": group_name,
                "title": group_name,
                "coverage": coverage,
                "status": "full" if coverage == 100 else "partial" if coverage else "none",
                "children": children,
            }
        )

    full_cover = sum(1 for card in material_cards if _coverage_card_used(card, used_path_keys))
    no_cover = len(no_cover_items)
    partial_cover = len(partial_items)
    total_materials = len(material_cards)
    percentage = 100 if total_materials == 0 else round((total_materials - no_cover) / total_materials * 100)
    return {
        "percentage": percentage,
        "fullCover": full_cover,
        "partialCover": partial_cover,
        "noCover": no_cover,
        "tree": tree,
        "partialItems": partial_items,
        "noCoverItems": no_cover_items,
        "basis": "assembly_materials_vs_s2_toc_json",
    }


def _coverage_card_used(card: dict[str, Any], used_path_keys: set[str]) -> bool:
    return bool(_coverage_path_keys(str(card.get("path") or "")) & used_path_keys) or bool(
        _coverage_path_keys(str(card.get("originalPath") or "")) & used_path_keys
    )


def _coverage_path_keys(path_text: str) -> set[str]:
    path_text = str(path_text or "").strip()
    if not path_text:
        return set()
    keys = {path_text}
    try:
        keys.add(str(_runtime_path(path_text)))
    except Exception:
        pass
    return {key for key in keys if key}


def _normalize_warnings(value: Any) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return warnings
    for item in value:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        message = str(item.get("message") or "").strip()
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if code and message and count > 0:
            warnings.append({"code": code, "message": message, "count": count})
    return warnings


def _build_fallback_content(
    plan: list[dict[str, Any]],
    summary: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> str:
    clean_plan = _iter_dicts(plan)
    clean_warnings = _iter_dicts(warnings)
    lines = ["# 技术标正文拼装摘要", ""]
    lines.append(
        f"共处理 {_safe_int(summary.get('total'), len(clean_plan))} 个目录项，"
        f"结构化告警 {_safe_int(summary.get('warningCount'), sum(_safe_int(item.get('count')) for item in clean_warnings))} 项。"
    )
    lines.extend(["", "## 章节结果"])
    if clean_plan:
        for item in clean_plan[:200]:
            number = str(item.get("chapter_no") or "").strip()
            title = str(item.get("title") or "未命名章节").strip()
            status = str(item.get("status") or "UNKNOWN").strip()
            lines.append(f"- {number} {title}：{status}".strip())
    else:
        lines.append("- 无可用拼装计划。")
    lines.extend(["", "## 告警"])
    if clean_warnings:
        for item in clean_warnings:
            lines.append(
                f"- [{str(item.get('code') or 'UNKNOWN')}] "
                f"{str(item.get('message') or '未提供告警说明')}（{_safe_int(item.get('count'))}）"
            )
    else:
        lines.append("- 无结构化告警。")
    return "\n".join(lines).strip()


def _safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback
