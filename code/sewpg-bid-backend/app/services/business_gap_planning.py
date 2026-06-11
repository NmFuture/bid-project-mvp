from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

from docx import Document
from sqlalchemy import select

from app.core.config import BASE_DIR, settings
from app.models import async_session
from app.models.materials import WikiDoc, WikiNode
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.business_material_store import business_material_store
from app.services.business_s1_handoff import business_s1_consumption_context
from app.services.bid_runtime_state import now_iso
from app.services.identity import build_project_material_scope
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.minio_client import minio_client
from app.services.opencode_client import OpencodeClient
from app.services.parse_profiles import BUSINESS_PARSE_PROFILE
from app.services.business_bidder_profile import load_business_bidder_facts
from app.services.business_gap_fact_table import PROJECT_FACT_TABLE_SCHEMA_VERSION, build_project_fact_table
from app.services.performance_library_service import performance_library_service
from app.services.performance_package_service import performance_package_service
from app.services.template_store import resolve_fallback_bid_template_file_sync
from app.services.turbine_models import project_turbine_model
from app.services.workspace_artifacts import business_workspace_dir, legacy_workspace_roots
from app.services.workspace_project_access import ensure_workspace_project_type


BUSINESS_GAP_PLAN_SCHEMA_VERSION = "bid-business-gap-plan-v1"
BUSINESS_GAP_PLANNER_SKILL_NAME = "bid-business-gap-planner"
BUSINESS_TABLE_FILL_SCHEMA_VERSION = "bid-business-table-fill-v1"
BUSINESS_TABLE_FILL_SKILL_NAME = "bid-business-table-fill"


def _business_skill_runner(skill_name: str) -> Path:
    preferred = BASE_DIR / "opencode" / "skills" / skill_name / "scripts" / "run_from_manifest.py"
    legacy = BASE_DIR / "opencode" / "skill" / skill_name / "scripts" / "run_from_manifest.py"
    return preferred if preferred.exists() or not legacy.exists() else legacy


BUSINESS_GAP_PLANNER_RUNNER = _business_skill_runner(BUSINESS_GAP_PLANNER_SKILL_NAME)
BUSINESS_TABLE_FILL_RUNNER = _business_skill_runner(BUSINESS_TABLE_FILL_SKILL_NAME)


def build_business_gap_plan_for_project(project: dict[str, Any]) -> dict[str, Any]:
    ensure_workspace_project_type(
        project,
        bid_type=BUSINESS_BID_TYPE,
        wrong_type_error=lambda _project_id: ValueError("商务标缺口处理仅支持商务标项目。"),
    )

    project_id = str(project.get("id") or "")
    project_dir = business_workspace_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir = project_dir / "gaps"
    work_dir.mkdir(parents=True, exist_ok=True)

    toc_json_path = _resolve_business_toc_json(project, work_dir)
    s1_context = business_s1_consumption_context(project)
    parse_result_path = work_dir / "parse_result.json"
    parse_result_path.write_text(
        json.dumps(s1_context.get("parseResult") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_path = work_dir / "business_gap_state.json"
    _write_state_snapshot(project.get("business_gap_state"), state_path)

    material_scope = build_project_material_scope(project)
    selected_model = project_turbine_model(project)
    material_index = _business_material_index(material_scope, selected_model)
    template_index = _business_template_index(project, work_dir)
    evidence_segments = _business_evidence_segments_from_materials(material_index)
    output_file = work_dir / "business_gap_plan.json"
    manifest_path = work_dir / "business_gap_input.json"
    business_wiki_dir = _resolve_business_wiki_dir(project, work_dir)
    business_wiki_index = _build_business_wiki_index(business_wiki_dir)
    business_wiki_index = _merge_material_evidence_segments(business_wiki_index, evidence_segments)
    business_gap_state = project.get("business_gap_state") if isinstance(project.get("business_gap_state"), dict) else {}
    material_feedback = _business_material_feedback_index(business_gap_state)
    project_fact_table = (
        business_gap_state.get("projectFactTable")
        if isinstance(business_gap_state.get("projectFactTable"), dict)
        else {}
    )
    if str(project_fact_table.get("schemaVersion") or "") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
        try:
            bidder_profile = _run_async(load_business_bidder_facts())
        except Exception:
            bidder_profile = {}
        project_fact_table = build_project_fact_table(project, business_gap_state, bidder_profile=bidder_profile)
    manifest = {
        "projectId": project_id,
        "projectName": str(project.get("name") or project_id),
        "bidType": BUSINESS_BID_TYPE,
        "workDir": str(work_dir),
        "tocJsonPath": str(toc_json_path),
        "parseResultPath": str(parse_result_path),
        "s1Handoff": s1_context.get("handoff") or {},
        "s1Consumption": {
            "source": str(s1_context.get("source") or "legacy_parse_result"),
            "structuredResultPath": str(s1_context.get("structuredResultPath") or ""),
            "paths": copy_jsonable_dict(s1_context.get("paths")),
        },
        "businessWikiDir": str(business_wiki_dir or ""),
        "businessWikiIndex": business_wiki_index,
        "projectIdentity": project.get("identity") or {},
        "materialScope": material_scope,
        "materialIndex": material_index,
        "templateIndex": template_index,
        "evidenceSegments": evidence_segments,
        "materialFeedback": material_feedback,
        "projectFactTable": project_fact_table,
        "selectedBusinessTurbineModel": selected_model,
        "statePath": str(state_path),
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_business_gap_planner_skill(manifest_path)
    plan_path = Path(str(result.get("outputFile") or output_file)).expanduser()
    if not plan_path.exists():
        raise RuntimeError(f"商务标缺口计划未生成：{plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _validate_business_gap_plan_toc_coverage(plan, toc_json_path)
    plan["planFile"] = str(plan_path)
    plan["manifestPath"] = str(manifest_path)
    plan["phase"] = "business_gap_detection"
    plan["s1Consumption"] = {
        "source": str(s1_context.get("source") or "legacy_parse_result"),
        "structuredResultPath": str(s1_context.get("structuredResultPath") or ""),
        "handoff": copy_jsonable_dict(s1_context.get("handoff")),
    }
    plan["opencodeOutput"] = result.get("opencodeOutput") or _local_opencode_output(manifest_path, result)
    return plan


def build_business_gap_material_picker_index(project: dict[str, Any]) -> dict[str, Any]:
    """Build the same business material/evidence index used by S3 planner for manual selection."""
    ensure_workspace_project_type(
        project,
        bid_type=BUSINESS_BID_TYPE,
        wrong_type_error=lambda _project_id: ValueError("商务标素材选择仅支持商务标项目。"),
    )
    project_id = str(project.get("id") or "")
    work_dir = business_workspace_dir(project_id) / "gaps"
    material_scope = build_project_material_scope(project)
    selected_model = project_turbine_model(project)
    material_index = _business_material_index(material_scope, selected_model)
    template_index = _business_template_index(project, work_dir)
    material_segments = _business_evidence_segments_from_materials(material_index)
    business_wiki_dir = _resolve_business_wiki_dir(project, work_dir)
    business_wiki_index = _build_business_wiki_index(business_wiki_dir)
    business_wiki_index = _merge_material_evidence_segments(business_wiki_index, material_segments)
    business_gap_state = project.get("business_gap_state") if isinstance(project.get("business_gap_state"), dict) else {}
    return {
        "schemaVersion": "bid-business-material-picker-index-v1",
        "projectId": project_id,
        "bidType": BUSINESS_BID_TYPE,
        "materialScope": material_scope,
        "materialIndex": material_index,
        "templateIndex": template_index,
        "evidenceSegments": business_wiki_index.get("evidenceSegments") or material_segments,
        "materialFeedback": _business_material_feedback_index(business_gap_state),
        "businessWikiIndexSummary": business_wiki_index.get("summary") if isinstance(business_wiki_index.get("summary"), dict) else {},
        "selectedBusinessTurbineModel": selected_model,
    }


def copy_jsonable_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return json.loads(json.dumps(value, ensure_ascii=False))


def _business_material_feedback_index(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {"schemaVersion": "bid-business-material-feedback-v1", "items": []}
    raw_items = state.get("materialFeedback")
    if not isinstance(raw_items, list):
        return {"schemaVersion": "bid-business-material-feedback-v1", "items": []}
    items = [item for item in raw_items if isinstance(item, dict)]
    return {
        "schemaVersion": "bid-business-material-feedback-v1",
        "items": items[-300:],
        "summary": {"count": len(items)},
    }


def run_business_gap_planner_skill(manifest_path: Path) -> dict[str, Any]:
    prompt = _build_business_gap_planner_prompt(manifest_path)
    try:
        return OpencodeClient().run_bid_business_gap_planner_with_trace(prompt)
    except Exception:
        return _run_local_skill_runner(BUSINESS_GAP_PLANNER_RUNNER, manifest_path, BUSINESS_GAP_PLAN_SCHEMA_VERSION)


def run_business_table_fill_skill(manifest_path: Path) -> dict[str, Any]:
    prompt = _build_business_table_fill_prompt(manifest_path)
    try:
        return OpencodeClient().run_bid_business_table_fill_with_trace(prompt)
    except Exception:
        return _run_local_skill_runner(BUSINESS_TABLE_FILL_RUNNER, manifest_path, BUSINESS_TABLE_FILL_SCHEMA_VERSION)


def _build_business_table_fill_prompt(manifest_path: Path) -> str:
    return f"""
Use the {BUSINESS_TABLE_FILL_SKILL_NAME} skill.

你现在在做 S3 商务标 AI 填写。后端已经准备好 manifest，其中包含待填写文件、来源素材、项目事实表和输出文件路径。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把填写后的文件写入 manifest 指定的输出路径，并只在 stdout 打印小型摘要 JSON：

businesstablefill {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def summarize_business_gap_plan(plan: dict[str, Any]) -> dict[str, Any]:
    tasks = [item for item in plan.get("tasks") or [] if isinstance(item, dict)]
    toc_refs = [item for item in plan.get("tocRefs") or [] if isinstance(item, dict)]
    statuses: dict[str, int] = {}
    decisions: dict[str, int] = {}
    modules: dict[str, int] = {}
    handling_modes: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "")
        decision = str(task.get("decision") or "")
        module_key = str(task.get("moduleKey") or "")
        handling_mode = str(task.get("handlingMode") or "")
        if handling_mode == "manual_select":
            handling_mode = "manual_upload"
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        if decision:
            decisions[decision] = decisions.get(decision, 0) + 1
        if module_key:
            modules[module_key] = modules.get(module_key, 0) + 1
        if handling_mode:
            handling_modes[handling_mode] = handling_modes.get(handling_mode, 0) + 1
    blocking = sum(1 for task in tasks if str(task.get("status") or "") in {"needs_input", "filling", "review_required"})
    return {
        "tocRefCount": len(toc_refs),
        "taskCount": len(tasks),
        "coverageStatus": "complete",
        "readyCount": statuses.get("ready", 0) + statuses.get("resolved", 0),
        "needsInputCount": statuses.get("needs_input", 0),
        "reviewRequiredCount": statuses.get("review_required", 0),
        "blockingCount": blocking,
        "decisionCounts": decisions,
        "statusCounts": statuses,
        "moduleCounts": modules,
        "handlingModeCounts": handling_modes,
    }


def refresh_business_gap_artifact_urls(
    project_id: str,
    plan: dict[str, Any],
    *,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> None:
    for task in plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for artifact in task.get("resolvedArtifacts") or []:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifactId") or "")
            file_name = str(artifact.get("fileName") or Path(str(artifact.get("filePath") or "")).name or "artifact")
            if not artifact_id:
                continue
            rel = f"/api/business/projects/{project_id}/business-gaps/artifacts/{artifact_id}/content/{quote(file_name)}"
            browser_url = f"{browser_base_url.rstrip('/')}{rel}" if browser_base_url else rel
            server_url = f"{onlyoffice_base_url.rstrip('/')}{rel}" if onlyoffice_base_url else browser_url
            artifact["fileUrl"] = browser_url
            artifact["browserFileUrl"] = browser_url
            if file_name.lower().endswith(".docx"):
                artifact["onlyoffice"] = {
                    "status": "ready",
                    "mode": "view",
                    "fileUrl": server_url,
                    "browserFileUrl": browser_url,
                    "documentServerFileUrl": server_url,
                    "documentKey": f"{project_id}-{artifact_id}",
                    "title": file_name,
                }


def _write_state_snapshot(state: Any, state_path: Path) -> None:
    tasks_by_id: dict[str, Any] = {}
    plan = state.get("plan") if isinstance(state, dict) and isinstance(state.get("plan"), dict) else {}
    for task in plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        state_item = {
            key: task.get(key)
            for key in (
                "status",
                "decision",
                "selectedMaterialRefs",
                "notes",
                "confirmed",
                "resolvedArtifacts",
                "assemblyMode",
                "materialUsage",
                "fillPlan",
                "selectedEvidenceSegments",
            )
            if key in task
        }
        for key in (str(task.get("id") or ""), str(task.get("taskKey") or "")):
            if key:
                tasks_by_id[key] = state_item
    state_path.write_text(json.dumps({"schemaVersion": "bid-business-gap-state-v1", "tasks": tasks_by_id}, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_business_toc_json(project: dict[str, Any], work_dir: Path) -> Path:
    project_id = str(project.get("id") or "")
    parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
    outline_nodes = list((project.get("outline_state") or {}).get("nodes") or [])
    if outline_nodes:
        output = {
            "schema_version": "bid-toc-json-v1",
            "document_title": f"{project.get('name') or project_id}商务投标文件目录",
            "project": {
                "owner": project.get("customerName") or project.get("owner") or "",
                "name": project.get("name") or project_id,
                "code": project.get("projectCode") or project_id,
            },
            "items": _outline_nodes_to_toc_items(outline_nodes),
        }
        target = work_dir / settings.s2_toc_output_file_name
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    candidates: list[Path] = []
    directory_output = ((project.get("directory_state") or {}).get("opencodeOutput") or {})
    for value in (directory_output.get("tocJsonPath"), directory_output.get("outputFile")):
        if value:
            candidates.append(Path(str(value)).expanduser())
    for root in legacy_workspace_roots(project_id, parse_storage):
        if "business-workspace" not in str(root) and root != business_workspace_dir(project_id):
            continue
        s2_work_dir = root / "s2_toc_workdir"
        candidates.extend(path for path in sorted(s2_work_dir.glob("*.json")) if "evidence" not in path.name.lower())
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".json":
            target = work_dir / settings.s2_toc_output_file_name
            if candidate.resolve() != target.resolve():
                shutil.copy2(candidate, target)
            return target

    output = {
        "schema_version": "bid-toc-json-v1",
        "document_title": f"{project.get('name') or project_id}商务投标文件目录",
        "project": {
            "owner": project.get("customerName") or project.get("owner") or "",
            "name": project.get("name") or project_id,
            "code": project.get("projectCode") or project_id,
        },
        "items": _outline_nodes_to_toc_items(outline_nodes),
    }
    target = work_dir / settings.s2_toc_output_file_name
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _outline_nodes_to_toc_items(nodes: list[dict[str, Any]], prefix: str = "", level: int = 1) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            continue
        number = str(node.get("tocNumber") or (f"{prefix}.{index}" if prefix else str(index)))
        items.append(
            {
                "order": len(items) + 1,
                "number": number,
                "title": str(node.get("title") or "").strip(),
                "level": level,
                "annotation": str(node.get("annotation") or "保留"),
                "source": str(node.get("source") or "outline_state"),
                "reason": str(node.get("reason") or ""),
                "requiredStatus": str(node.get("requiredStatus") or node.get("required_status") or ""),
                "sourceText": str(node.get("sourceText") or node.get("source_text") or ""),
                "source_refs": node.get("sourceRefs") or node.get("source_refs") or [],
                "material_refs": list(node.get("material_refs") or node.get("materialRefs") or []),
            }
        )
        children = node.get("children") if isinstance(node.get("children"), list) else []
        child_items = _outline_nodes_to_toc_items(children, number, level + 1)
        for child in child_items:
            child["order"] = len(items) + 1
            items.append(child)
    return items


def _resolve_business_wiki_dir(project: dict[str, Any], work_dir: Path) -> Path | None:
    project_id = str(project.get("id") or "")
    candidates = [business_workspace_dir(project_id) / "wiki", work_dir / "wiki"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _build_business_wiki_index(wiki_dir: Path | None) -> dict[str, Any]:
    nodes = _run_async(_business_wiki_docs_from_db())
    if not nodes and wiki_dir:
        nodes = _business_wiki_docs_from_files(wiki_dir)
    mapping_rows: list[dict[str, Any]] = []
    evidence_cards: list[dict[str, Any]] = []
    todo_items: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    for node in nodes:
        title = str(node.get("title") or "")
        content = str(node.get("markdownContent") or "")
        if not content:
            continue
        if (
            title.startswith(("02-模板模块映射表", "02-章节映射表"))
            or "/02-模板模块映射表/" in str(node.get("path") or "")
            or "/02-章节映射表/" in str(node.get("path") or "")
        ):
            mapping_rows.extend(_parse_business_wiki_table(content))
            detail = _parse_business_wiki_field_list(content)
            if detail.get("module_code"):
                mapping_rows.append(detail)
        elif (
            title.startswith(("03-证据卡片", "03-素材卡片"))
            or "/03-证据卡片/" in str(node.get("path") or "")
            or "/03-素材卡片/" in str(node.get("path") or "")
        ):
            card = _parse_business_wiki_evidence_card(title, content)
            if card:
                evidence_cards.append(card)
        elif title.startswith("04-待填写") or "/04-待填写" in str(node.get("path") or ""):
            todo_items.extend(_parse_business_wiki_table(content))
        elif title.startswith("05-使用规则") or "/05-使用规则/" in str(node.get("path") or ""):
            rules.extend(_parse_business_wiki_table(content))

    mapping_rows = _dedupe_wiki_rows(mapping_rows, ("module_code", "module_name", "source_path_prefix"))
    evidence_cards = _dedupe_wiki_rows(evidence_cards, ("card_id", "material_id", "path", "title"))
    evidence_segments = _business_evidence_segments_from_cards(evidence_cards)
    return {
        "schemaVersion": "bid-business-wiki-index-v1",
        "source": "db" if nodes else "none",
        "mappingRows": mapping_rows[:120],
        "evidenceCards": evidence_cards[:600],
        "evidenceSegments": evidence_segments[:1600],
        "todoItems": todo_items[:200],
        "rules": rules[:200],
        "summary": {
            "mappingRowCount": len(mapping_rows),
            "evidenceCardCount": len(evidence_cards),
            "evidenceSegmentCount": len(evidence_segments),
            "todoItemCount": len(todo_items),
            "ruleCount": len(rules),
        },
    }


async def _business_wiki_docs_from_db() -> list[dict[str, Any]]:
    async with async_session() as session:
        try:
            await ensure_material_runtime_tables(session)
            rows = (
                await session.execute(
                    select(WikiNode, WikiDoc)
                    .join(WikiDoc, WikiDoc.node_id == WikiNode.id)
                    .order_by(WikiNode.path, WikiNode.sort_order, WikiNode.id)
                )
            ).all()
        except Exception:
            return []
    docs: list[dict[str, Any]] = []
    for node, doc in rows:
        title = str(node.title or "")
        path = str(node.path or title)
        bid_types = {str(item) for item in (node.bid_types or [])}
        if "商务标" not in bid_types and "商务标Wiki" not in path and "商务标Wiki" not in title:
            continue
        docs.append(
            {
                "id": f"WIKI-{int(node.id):04d}",
                "title": title,
                "path": path,
                "markdownContent": str(doc.markdown_content or ""),
            }
        )
    return docs


def _business_wiki_docs_from_files(wiki_dir: Path) -> list[dict[str, Any]]:
    if not wiki_dir.exists():
        return []
    docs: list[dict[str, Any]] = []
    for path in sorted(wiki_dir.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        docs.append({"title": path.stem, "path": str(path.relative_to(wiki_dir)), "markdownContent": content})
    return docs


def _parse_business_wiki_table(markdown: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = [line.strip() for line in markdown.splitlines()]
    index = 0
    while index + 1 < len(lines):
        header = lines[index]
        separator = lines[index + 1]
        if not (header.startswith("|") and separator.startswith("|") and "---" in separator):
            index += 1
            continue
        headers = [_clean_wiki_cell(cell) for cell in header.strip("|").split("|")]
        index += 2
        while index < len(lines) and lines[index].startswith("|"):
            cells = [_clean_wiki_cell(cell) for cell in lines[index].strip("|").split("|")]
            if len(cells) >= len(headers):
                row = {headers[pos]: cells[pos] for pos in range(len(headers)) if headers[pos]}
                if any(value and value != "-" for value in row.values()):
                    rows.append(row)
            index += 1
    return rows


def _parse_business_wiki_field_list(markdown: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.count("|") < 3:
            continue
        cells = [_clean_wiki_cell(cell) for cell in stripped.strip("|").split("|")]
        if len(cells) == 2 and cells[0] not in {"field", "---"}:
            fields[cells[0]] = cells[1]
    return fields


def _parse_business_wiki_evidence_card(title: str, markdown: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    for line in markdown.splitlines():
        match = re.match(r"^\s*-\s*([A-Za-z0-9_]+)\s*:\s*(.*)\s*$", line)
        if match:
            fields[match.group(1)] = _clean_wiki_cell(match.group(2))
    card_id = fields.get("card_id") or ""
    material_id = fields.get("material_id") or ""
    path = fields.get("path") or ""
    if not any((card_id, material_id, path)):
        return {}
    segment_rows = [
        {
            "segment_id": row.get("segment_id") or "",
            "segment_title": row.get("segment_title") or "",
            "segment_type": row.get("segment_type") or "",
            "segment_scope": row.get("segment_scope") or "",
            "segment_source_pages": row.get("segment_source_pages") or "",
            "segment_summary": row.get("segment_summary") or "",
            "segment_keywords": row.get("segment_keywords") or "",
        }
        for row in _parse_business_wiki_table(markdown)
        if row.get("segment_id") or row.get("segment_title")
    ]
    return {
        "card_id": card_id,
        "material_id": material_id,
        "title": fields.get("title") or title,
        "path": path,
        "cleaned_file_name": fields.get("cleaned_file_name") or "",
        "material_tier": fields.get("material_tier") or "",
        "business_category": fields.get("business_category") or "",
        "evidence_topic": fields.get("evidence_topic") or "",
        "evidence_type": fields.get("evidence_type") or "",
        "identity_scope": fields.get("identity_scope") or "",
        "customer_id": fields.get("customer_id") or "",
        "customer_name": fields.get("customer_name") or "",
        "project_id": fields.get("project_id") or "",
        "project_code": fields.get("project_code") or "",
        "applicable_modules": _split_wiki_multi_value(fields.get("applicable_modules") or ""),
        "applicable_chapters": _split_wiki_multi_value(fields.get("applicable_chapters") or ""),
        "chapter_keywords": _split_wiki_multi_value(fields.get("chapter_keywords") or ""),
        "usage_mode": fields.get("usage_mode") or "",
        "priority_score": fields.get("priority_score") or "",
        "needs_human_confirm": fields.get("needs_human_confirm") or "",
        "key_fields": _split_wiki_multi_value(fields.get("key_fields") or ""),
        "keywords": _split_wiki_multi_value(fields.get("keywords") or ""),
        "document_type": fields.get("document_type") or "",
        "summary": fields.get("summary") or "",
        "issuer": fields.get("issuer") or "",
        "document_number": fields.get("document_number") or "",
        "issue_date": fields.get("issue_date") or "",
        "expiry_date": fields.get("expiry_date") or "",
        "validity_status": fields.get("validity_status") or "",
        "last_verified_at": fields.get("last_verified_at") or "",
        "turbine_models": _split_wiki_multi_value(fields.get("turbine_models") or ""),
        "components": _split_wiki_multi_value(fields.get("components") or ""),
        "applicable_conditions": fields.get("applicable_conditions") or "",
        "risk_notes": fields.get("risk_notes") or "",
        "ocr_status": fields.get("ocr_status") or "",
        "ocr_source_type": fields.get("ocr_source_type") or "",
        "ocr_confidence": fields.get("ocr_confidence") or "",
        "is_final_version": fields.get("is_final_version") or "",
        "source_pages": fields.get("source_pages") or "",
        "cleaning_strategy": fields.get("cleaning_strategy") or "",
        "segment_id": fields.get("segment_id") or "",
        "segment_title": fields.get("segment_title") or "",
        "segment_type": fields.get("segment_type") or "",
        "segment_scope": fields.get("segment_scope") or "",
        "segment_source_pages": fields.get("segment_source_pages") or "",
        "segment_summary": fields.get("segment_summary") or "",
        "segment_keywords": _split_wiki_multi_value(fields.get("segment_keywords") or ""),
        "segments": segment_rows,
    }


def _business_evidence_segments_from_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            continue
        rows = card.get("segments") if isinstance(card.get("segments"), list) else []
        if rows:
            for row_index, row in enumerate(rows, start=1):
                segment = _business_evidence_segment_from_card(card, row, index=index, row_index=row_index, seen=seen)
                if segment:
                    segments.append(segment)
            continue
        segment = _business_evidence_segment_from_card(card, {}, index=index, row_index=1, seen=seen)
        if segment:
            segments.append(segment)
    return segments


def _business_evidence_segment_from_card(
    card: dict[str, Any],
    row: dict[str, Any],
    *,
    index: int,
    row_index: int,
    seen: set[str],
) -> dict[str, Any]:
    card_id = str(card.get("card_id") or "").strip()
    material_id = str(card.get("material_id") or "").strip()
    path = str(card.get("path") or "").strip()
    title = str(row.get("segment_title") or card.get("segment_title") or card.get("title") or Path(path).stem or f"证据片段{index}-{row_index}").strip()
    segment_id = str(row.get("segment_id") or card.get("segment_id") or "").strip()
    if not segment_id:
        base = f"{card_id or material_id or path}:{title}:{row_index}"
        segment_id = f"biz-seg-{_stable_short_id(base)}"
    if segment_id in seen:
        suffix = _stable_short_id(f"{segment_id}:{index}:{row_index}")
        segment_id = f"{segment_id}-{suffix}"
    seen.add(segment_id)
    summary = str(row.get("segment_summary") or card.get("segment_summary") or card.get("summary") or "").strip()
    keywords = _dedupe_strings([
        *[str(item) for item in _split_wiki_multi_value(str(row.get("segment_keywords") or ""))],
        *[str(item) for item in (card.get("segment_keywords") or [])],
        *[str(item) for item in (card.get("keywords") or [])],
        *[str(item) for item in (card.get("key_fields") or [])],
        str(card.get("business_category") or ""),
        str(card.get("evidence_topic") or ""),
        str(card.get("document_type") or ""),
        title,
        *[str(item) for item in (card.get("applicable_chapters") or [])],
        *[str(item) for item in (card.get("chapter_keywords") or [])],
    ])
    return {
        "segment_id": segment_id,
        "card_id": card_id,
        "material_id": material_id,
        "title": title,
        "segment_type": str(row.get("segment_type") or card.get("segment_type") or card.get("evidence_type") or "").strip(),
        "segment_scope": str(row.get("segment_scope") or card.get("segment_scope") or "card_primary").strip(),
        "material_tier": str(card.get("material_tier") or "").strip(),
        "business_category": str(card.get("business_category") or "").strip(),
        "evidence_topic": str(card.get("evidence_topic") or "").strip(),
        "document_type": str(card.get("document_type") or "").strip(),
        "usage_mode": str(card.get("usage_mode") or "").strip(),
        "path": path,
        "source_pages": str(row.get("segment_source_pages") or card.get("segment_source_pages") or card.get("source_pages") or "").strip(),
        "summary": summary,
        "applicable_chapters": [str(item) for item in (card.get("applicable_chapters") or []) if str(item).strip()],
        "chapter_keywords": [str(item) for item in (card.get("chapter_keywords") or []) if str(item).strip()],
        "key_fields": [str(item) for item in (card.get("key_fields") or []) if str(item).strip()],
        "keywords": keywords[:24],
        "validity_status": str(card.get("validity_status") or "").strip(),
        "expiry_date": str(card.get("expiry_date") or "").strip(),
        "risk_notes": str(card.get("risk_notes") or "").strip(),
        "ocr_status": str(card.get("ocr_status") or "").strip(),
        "ocr_confidence": str(card.get("ocr_confidence") or "").strip(),
        "needs_human_confirm": str(card.get("needs_human_confirm") or "").strip(),
        "priority_score": str(card.get("priority_score") or "").strip(),
        "turbine_models": [str(item) for item in (card.get("turbine_models") or []) if str(item).strip()],
        "components": [str(item) for item in (card.get("components") or []) if str(item).strip()],
    }


def _business_evidence_segments_from_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        extracted = _business_evidence_segments_from_cleaned_word(material)
        if extracted:
            segments.extend(extracted)
            continue
        material_id = str(material.get("id") or material.get("materialId") or "").strip()
        title = str(material.get("name") or material.get("fileName") or material.get("cleanedFileName") or material_id).strip()
        folder_path = str(material.get("folderPath") or "").strip()
        if not material_id and not title:
            continue
        ext = Path(title).suffix.lower().strip(".")
        path = "/".join(part for part in (folder_path, title) if part)
        segment_type = _infer_material_segment_type(path, ext)
        usage_mode = _infer_material_segment_usage(path, ext)
        segment = {
            "segment_id": f"mat-seg-{_stable_short_id(material_id or path or title)}",
            "card_id": "",
            "material_id": material_id,
            "title": Path(title).stem or title,
            "segment_type": segment_type,
            "segment_scope": "file_fallback",
            "material_tier": str(material.get("materialTier") or material.get("libraryScope") or "").strip(),
            "business_category": _infer_material_segment_category(path),
            "document_type": _infer_material_segment_document_type(path, ext),
            "usage_mode": usage_mode,
            "path": path,
            "source_pages": "整件/待定位",
            "summary": "素材文件级兜底片段，当前主要依据文件名和路径匹配；如文件内包含多个模块，建议后续通过商务 Wiki/OCR 生成更细证据片段。",
            "key_fields": [],
            "keywords": _dedupe_strings([*_material_segment_keywords(path), *_material_tag_keywords(material)])[:24],
            "validity_status": "",
            "expiry_date": "",
            "risk_notes": "文件级兜底片段，需人工确认文件内具体位置。",
            "ocr_status": "",
            "ocr_confidence": "",
            "needs_human_confirm": "yes",
            "priority_score": "50",
            "turbine_models": [str(material.get("turbineModelLabel") or "").strip()] if str(material.get("turbineModelLabel") or "").strip() else [],
            "components": [],
        }
        segments.append(segment)
    return segments


def _business_evidence_segments_from_cleaned_word(material: dict[str, Any]) -> list[dict[str, Any]]:
    if str(material.get("cleanStatus") or "") != "cleaned" or not material.get("hasCleanedWord"):
        return []
    material_id = str(material.get("id") or material.get("materialId") or "").strip()
    if not material_id:
        return []
    try:
        payload = _run_async(business_material_store.raw_download_cleaned_content(material_id))
    except Exception:
        return []
    suffix = Path(str(payload.get("fileName") or "")).suffix.lower()
    if suffix != ".docx":
        return []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / safe_segment(str(payload.get("fileName") or f"{material_id}.docx"), f"{material_id}.docx")
            minio_client.download_file(str(payload["bucket"]), str(payload["key"]), path)
            doc = Document(str(path))
            return _segments_from_docx_paragraphs(material, [paragraph.text for paragraph in doc.paragraphs])
    except Exception:
        return []


def _segments_from_docx_paragraphs(material: dict[str, Any], paragraphs: list[str]) -> list[dict[str, Any]]:
    material_id = str(material.get("id") or material.get("materialId") or "").strip()
    material_name = str(material.get("name") or material.get("cleanedFileName") or material_id).strip()
    folder_path = str(material.get("folderPath") or "").strip()
    path = "/".join(part for part in (folder_path, material_name) if part)
    sections: list[dict[str, Any]] = []
    current_title = Path(material_name).stem or material_name
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines, current_title
        text = "\n".join(line for line in current_lines if line).strip()
        if not text:
            current_lines = []
            return
        sections.append(_segment_from_text_block(material, current_title, text, path, len(sections) + 1))
        current_lines = []

    for raw in paragraphs:
        line = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not line:
            continue
        if _looks_like_business_segment_heading(line):
            flush()
            current_title = line[:80]
            continue
        current_lines.append(line)
        if len("".join(current_lines)) > 1600:
            flush()
    flush()
    if not sections:
        compact = "\n".join(line.strip() for line in paragraphs if str(line).strip())[:1800]
        if compact:
            sections.append(_segment_from_text_block(material, Path(material_name).stem or material_name, compact, path, 1))
    return sections[:24]


def _looks_like_business_segment_heading(line: str) -> bool:
    text = str(line or "").strip()
    if len(text) > 80:
        return False
    return bool(
        re.match(r"^([一二三四五六七八九十]+[、.．]|第[一二三四五六七八九十0-9]+[章节条]|[0-9]+([.．][0-9]+)*[、.．]?)", text)
        or any(keyword in text for keyword in ("投标函", "授权", "廉洁", "承诺", "价格表", "开标", "规格", "偏差", "保证金", "保函", "证书", "业绩", "审计报告", "资信证明"))
    )


def _segment_from_text_block(material: dict[str, Any], title: str, text: str, path: str, index: int) -> dict[str, Any]:
    material_id = str(material.get("id") or material.get("materialId") or "").strip()
    summary = re.sub(r"\s+", " ", text).strip()[:240]
    keywords = _dedupe_strings(
        [*_material_segment_keywords(f"{path}/{title}"), *_keywords_from_text(summary), *_material_tag_keywords(material)]
    )
    return {
        "segment_id": f"mat-docx-seg-{_stable_short_id(f'{material_id}:{title}:{index}:{summary[:60]}')}",
        "card_id": "",
        "material_id": material_id,
        "title": title,
        "segment_type": "cleaned_word_section",
        "segment_scope": "cleaned_docx_section",
        "material_tier": str(material.get("materialTier") or material.get("libraryScope") or "").strip(),
        "business_category": _infer_material_segment_category(f"{path}/{title}"),
        "document_type": _infer_material_segment_document_type(f"{path}/{title}", "docx"),
        "usage_mode": _infer_material_segment_usage(f"{path}/{title}", "docx"),
        "path": path,
        "source_pages": f"清洗稿段落{index}",
        "summary": summary,
        "key_fields": [],
        "keywords": keywords[:24],
        "validity_status": "",
        "expiry_date": "",
        "risk_notes": "由清洗 Word 自动切片，需人工确认落位片段是否完整。",
        "ocr_status": "cleaned_word_text",
        "ocr_confidence": "",
        "needs_human_confirm": "yes",
        "priority_score": "80",
        "turbine_models": [str(material.get("turbineModelLabel") or "").strip()] if str(material.get("turbineModelLabel") or "").strip() else [],
        "components": [],
    }


def _keywords_from_text(text: str) -> list[str]:
    result: list[str] = []
    for marker in ("投标函", "授权", "廉洁", "保证金", "保函", "履约", "报价", "价格", "开标", "规格", "偏差", "供货范围", "营业执照", "资质", "认证", "证书", "业绩", "合同", "中标", "承诺", "声明", "说明", "审计报告", "资信证明", "纳税"):
        if marker in text:
            result.append(marker)
    result.extend(item for item in re.split(r"[/_\-\s　.。；;，,、（）()【】\\]+", text) if len(item) >= 2 and len(item) <= 16)
    return result[:30]


def safe_segment(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = text.strip(" .")
    return text or fallback


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem or "file"
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法为文件生成唯一路径：{path}")


def _merge_material_evidence_segments(wiki_index: dict[str, Any], material_segments: list[dict[str, Any]]) -> dict[str, Any]:
    result = dict(wiki_index or {})
    existing = [segment for segment in result.get("evidenceSegments") or [] if isinstance(segment, dict)]
    seen = {str(segment.get("segment_id") or "") for segment in existing if str(segment.get("segment_id") or "")}
    merged = list(existing)
    for segment in material_segments:
        segment_id = str(segment.get("segment_id") or "")
        if not segment_id or segment_id in seen:
            continue
        seen.add(segment_id)
        merged.append(segment)
    result["evidenceSegments"] = merged[:2000]
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    result["summary"] = {**summary, "evidenceSegmentCount": len(merged)}
    return result


def _infer_material_segment_type(path: str, ext: str) -> str:
    text = str(path or "")
    if ext in {"png", "jpg", "jpeg", "bmp", "gif", "webp", "tif", "tiff"}:
        return "scan_image"
    if ext == "pdf":
        return "pdf_attachment"
    if any(keyword in text for keyword in ("报价", "价格", "规格", "偏差", "供货范围", "开标")):
        return "table_source"
    if any(keyword in text for keyword in ("证书", "认证", "营业执照", "资质")):
        return "certificate_proof"
    return "document_proof"


def _infer_material_segment_usage(path: str, ext: str) -> str:
    text = str(path or "")
    if ext in {"png", "jpg", "jpeg", "bmp", "gif", "webp", "tif", "tiff"}:
        return "extract_image"
    if any(keyword in text for keyword in ("报价", "价格", "规格", "偏差", "供货范围", "开标")):
        return "fill_table"
    if any(keyword in text for keyword in ("投标函", "授权", "委托", "法定代表人", "否决", "符合性")):
        return "extract_fields"
    return "attach_whole"


def _infer_material_segment_category(path: str) -> str:
    text = str(path or "")
    if any(keyword in text for keyword in ("资质", "营业执照", "信用", "资信", "纳税", "开户")):
        return "资格资质"
    if any(keyword in text for keyword in ("机型认证", "大部件", "型式认证", "证书")):
        return "专题证书"
    if any(keyword in text for keyword in ("业绩", "合同", "中标", "240h", "验收")):
        return "业绩证明"
    if any(keyword in text for keyword in ("报价", "价格", "规格", "偏差")):
        return "报价与分项表"
    if any(keyword in text for keyword in ("承诺", "声明", "说明")):
        return "承诺函件"
    return "商务素材"


def _infer_material_segment_document_type(path: str, ext: str) -> str:
    text = str(path or "")
    if "投标函" in text:
        return "投标函"
    if "授权" in text or "委托" in text:
        return "授权文件"
    if "报价" in text or "价格" in text:
        return "报价表"
    if "规格" in text:
        return "规格表"
    if "偏差" in text:
        return "偏差表"
    if "保证金" in text or "回单" in text:
        return "保证金凭证"
    if any(keyword in text for keyword in ("证书", "认证", "营业执照", "资质")):
        return "证书/资质文件"
    if ext:
        return ext.upper()
    return "商务文件"


def _material_tag_keywords(material: dict[str, Any]) -> list[str]:
    return [str(tag).strip() for tag in material.get("tags") or [] if str(tag).strip()]


def _material_segment_keywords(path: str) -> list[str]:
    text = str(path or "")
    candidates = re.split(r"[/_\-\s　.。；;，,、（）()【】\\]+", text)
    keywords = [item for item in candidates if len(item) >= 2]
    for marker in ("投标函", "授权", "廉洁", "保证金", "保函", "报价", "价格", "开标", "规格", "偏差", "供货范围", "营业执照", "资质", "认证", "证书", "业绩", "合同", "中标", "承诺", "声明", "说明"):
        if marker in text:
            keywords.append(marker)
    return _dedupe_strings(keywords)[:24]


def _stable_short_id(value: str) -> str:
    import hashlib

    text = str(value or "").strip() or "segment"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in {"-", "[]", "待识别", "待抽取", "待回退检索"}:
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _split_wiki_multi_value(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text or text in {"-", "[]", "待识别", "待抽取", "待回退检索"}:
        return []
    return [
        item.strip(" `")
        for item in re.split(r"[、,，;；]+", text)
        if item.strip(" `") and item.strip(" `") not in {"-", "[]"}
    ]


def _clean_wiki_cell(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("\\|", "|")
    text = re.sub(r"<br\s*/?>", "；", text, flags=re.IGNORECASE)
    return text.strip(" `")


def _dedupe_wiki_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = next((str(row.get(field) or "").strip() for field in keys if str(row.get(field) or "").strip()), "")
        if not key:
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _business_material_index(material_scope: dict[str, Any], selected_model: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    _ = selected_model
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
        for raw in payload.get("items") or []:
            if not isinstance(raw, dict):
                continue
            material_id = str(raw.get("id") or "")
            if not material_id or material_id in seen:
                continue
            seen.add(material_id)
            folder = str(raw.get("folderPath") or "")
            name = str(raw.get("name") or "")
            items.append(
                {
                    "id": material_id,
                    "materialId": material_id,
                    "name": name,
                    "fileName": str(raw.get("fileName") or name),
                    "folderPath": folder,
                    "path": str(raw.get("path") or "/".join(part for part in (folder, name) if part)),
                    "materialTier": str(raw.get("materialTier") or scope.get("materialTier") or ""),
                    "libraryScope": str(raw.get("materialTier") or scope.get("materialTier") or ""),
                    "businessMaterialKind": str(raw.get("businessMaterialKind") or ""),
                    "businessMaterialKindLabel": str(raw.get("businessMaterialKindLabel") or ""),
                    "sourceType": str(raw.get("sourceType") or "material_library"),
                    "candidateType": str(raw.get("candidateType") or "raw_material"),
                    "hasCleanedWord": bool(raw.get("hasCleanedWord")),
                    "cleanedFileName": str(raw.get("cleanedFileName") or ""),
                    "cleanStatus": str(raw.get("cleanStatus") or ""),
                    "size": int(raw.get("size") or raw.get("sizeBytes") or 0),
                    "turbineModelLabel": str(raw.get("turbineModelLabel") or ""),
                    "tags": [str(tag) for tag in raw.get("tags") or [] if str(tag).strip()],
                    "keywords": [str(keyword) for keyword in raw.get("keywords") or [] if str(keyword).strip()],
                    "summary": str(raw.get("summary") or ""),
                    "businessCategory": str(raw.get("businessCategory") or raw.get("business_category") or ""),
                    "documentType": str(raw.get("documentType") or raw.get("document_type") or ""),
                    "reviewStatus": str(raw.get("reviewStatus") or ""),
                    "updatedAt": str(raw.get("updatedAt") or ""),
                }
            )
    try:
        performance_candidates = _run_async(performance_library_service.list_match_candidates(material_scope, limit=300))
    except Exception:
        performance_candidates = []
    for candidate in performance_candidates:
        if not isinstance(candidate, dict):
            continue
        material_id = str(candidate.get("id") or candidate.get("materialId") or "")
        if not material_id or material_id in seen:
            continue
        seen.add(material_id)
        items.append(candidate)
    for candidate in _performance_package_candidates(limit=300):
        material_id = str(candidate.get("id") or "")
        if not material_id or material_id in seen:
            continue
        seen.add(material_id)
        items.append(candidate)
    return items


def _performance_package_candidates(limit: int = 300) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if str(settings.project_store_backend or "").lower() != "postgres":
        return candidates
    try:
        listing = _run_async(performance_package_service.list_categories(page=1, page_size=50))
    except Exception:
        return candidates
    for summary in listing.get("items") or []:
        if not isinstance(summary, dict) or not str(summary.get("id") or ""):
            continue
        try:
            detail = _run_async(performance_package_service.get_category(str(summary["id"])))
        except Exception:
            continue
        category = detail.get("item") if isinstance(detail.get("item"), dict) else summary
        candidates.append(_performance_package_candidate_from_category(category))
        for row in detail.get("rows") or []:
            if isinstance(row, dict):
                candidates.append(_performance_package_candidate_from_item(category, row))
        if len(candidates) >= limit:
            break
    return candidates[:limit]


def _performance_package_candidate_from_category(category: dict[str, Any]) -> dict[str, Any]:
    name = str(category.get("name") or "") or str(category.get("id") or "业绩包")
    scope = str(category.get("scope") or "standard")
    models = [str(model) for model in category.get("turbineModels") or [] if str(model).strip()]
    keywords = [
        keyword
        for keyword in [name, str(category.get("scene") or ""), str(category.get("powerRating") or ""), *models]
        if str(keyword).strip()
    ]
    return {
        "id": str(category.get("id") or ""),
        "materialId": str(category.get("id") or ""),
        "categoryId": str(category.get("id") or ""),
        "name": name,
        "fileName": str(category.get("summaryFileName") or name),
        "folderPath": "商务标/共用业绩库",
        "path": "/".join(["商务标", "共用业绩库", name]),
        "materialTier": scope,
        "libraryScope": scope,
        "businessMaterialKind": "performance",
        "businessMaterialKindLabel": "共用业绩",
        "sourceType": "performance_package",
        "candidateType": "performance_category",
        "hasCleanedWord": False,
        "cleanedFileName": "",
        "cleanStatus": "original_only" if category.get("summaryFileName") else "metadata_only",
        "size": 0,
        "turbineModelLabel": "/".join(models[:5]),
        "tags": [str(tag) for tag in category.get("tags") or [] if str(tag).strip()],
        "keywords": keywords[:24],
        "summary": str(category.get("summary") or ""),
        "businessCategory": "业绩证明",
        "documentType": "业绩汇总表",
        "reviewStatus": str(category.get("reviewStatus") or "draft"),
        "updatedAt": str(category.get("updatedAt") or ""),
        "itemCount": int(category.get("itemCount") or 0),
    }


def _performance_package_candidate_from_item(category: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    category_name = str(category.get("name") or "")
    scope = str(category.get("scope") or "standard")
    project_name = str(item.get("projectName") or "")
    customer = str(item.get("customerName") or "")
    title = project_name or f"{category_name}-行{item.get('rowIndex')}"
    models = [str(model) for model in item.get("turbineModels") or [] if str(model).strip()]
    contract_items = [
        attachment
        for attachment in item.get("attachments") or []
        if isinstance(attachment, dict) and str(attachment.get("attachmentType") or "") == "contract_item"
    ]
    years = [
        str(year)
        for year in (item.get("contractYear"), item.get("deliveryYear"), item.get("operationYear"))
        if year
    ]
    keywords = [
        keyword
        for keyword in [
            category_name,
            str(category.get("scene") or ""),
            str(category.get("powerRating") or ""),
            project_name,
            customer,
            *models,
            *years,
        ]
        if str(keyword).strip()
    ]
    values = item.get("values") if isinstance(item.get("values"), dict) else {}
    for raw_value in values.values():
        text_value = str(raw_value or "").strip()
        if text_value and text_value not in keywords:
            keywords.append(text_value)
    summary_parts = [
        customer,
        "/".join(models),
        str(item.get("contractQuantity") or ""),
        str(item.get("commissionedCapacityMw") or ""),
        str(item.get("deliveryOrOperationTime") or ""),
    ]
    return {
        "id": str(item.get("id") or ""),
        "materialId": str(item.get("id") or ""),
        "categoryId": str(item.get("categoryId") or category.get("id") or ""),
        "name": title,
        "fileName": str(contract_items[0].get("fileName") or "") if contract_items else str(category.get("summaryFileName") or title),
        "folderPath": "/".join(["商务标", "共用业绩库", category_name or "业绩包"]),
        "path": "/".join(["商务标", "共用业绩库", category_name or "业绩包", title]),
        "materialTier": scope,
        "libraryScope": scope,
        "businessMaterialKind": "performance",
        "businessMaterialKindLabel": "共用业绩",
        "sourceType": "performance_package",
        "candidateType": "performance_item",
        "hasCleanedWord": False,
        "cleanedFileName": "",
        "cleanStatus": "original_only" if contract_items else "metadata_only",
        "size": int(contract_items[0].get("sizeBytes") or 0) if contract_items else 0,
        "turbineModelLabel": "/".join(models[:5]),
        "tags": [str(tag) for tag in category.get("tags") or [] if str(tag).strip()],
        "keywords": keywords[:24],
        "summary": "；".join(part for part in (str(value).strip() for value in summary_parts) if part),
        "businessCategory": "业绩证明",
        "documentType": "业绩明细",
        "reviewStatus": str(category.get("reviewStatus") or "draft"),
        "updatedAt": str(category.get("updatedAt") or ""),
        "contractYear": item.get("contractYear"),
        "deliveryYear": item.get("deliveryYear"),
        "operationYear": item.get("operationYear"),
        "attachments": [
            {
                "id": str(attachment.get("id") or ""),
                "categoryId": str(attachment.get("categoryId") or ""),
                "itemId": str(attachment.get("itemId") or item.get("id") or ""),
                "fileName": str(attachment.get("fileName") or ""),
                "matchConfidence": attachment.get("matchConfidence"),
                "matchMethod": str(attachment.get("matchMethod") or ""),
            }
            for attachment in contract_items
        ],
    }


def _business_template_index(project: dict[str, Any], work_dir: Path) -> list[dict[str, Any]]:
    """Return project/default bid templates as first-class S3 template candidates."""
    project_id = str(project.get("id") or "")
    candidates: list[dict[str, Any]] = []
    source_records = [record for record in project.get("templateFileRecords") or [] if isinstance(record, dict)]
    source_kind = "project_upload"
    if not source_records and _template_fallback_enabled(project):
        try:
            fallback_record = resolve_fallback_bid_template_file_sync(project_id, BUSINESS_BID_TYPE)
        except Exception:
            fallback_record = None
        if isinstance(fallback_record, dict):
            source_records = [fallback_record]
            source_kind = "system_default"

    for index, record in enumerate(source_records, start=1):
        source_path = Path(str(record.get("path") or "")).expanduser()
        suffix = source_path.suffix.lower()
        if not source_path.exists() or suffix != ".docx":
            continue
        name = str(record.get("name") or source_path.name or f"商务模板-{index}.docx")
        template_id = str(record.get("id") or f"BTPL-{source_kind}-{index}")
        destination_dir = work_dir / "templates"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{index:02d}-{safe_segment(name, f'business-template-{index}.docx')}"
        try:
            shutil.copy2(source_path, destination)
        except Exception:
            continue
        candidates.append(
            {
                "templateId": template_id,
                "templateName": name,
                "fileName": destination.name,
                "filePath": str(destination),
                "originalPath": str(source_path),
                "sourceMode": "project_uploaded_bid_template" if source_kind == "project_upload" else "system_default_bid_template",
                "sourceLabel": "项目上传模板" if source_kind == "project_upload" else "系统默认商务模板",
                "templateScope": "project" if source_kind == "project_upload" else "default",
                "assemblyMode": "template_fill_docx",
                "materialUsage": "fill_template",
                "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "score": 0.92 if source_kind == "project_upload" else 0.78,
                "reason": "S1/S2 项目上传投标模板" if source_kind == "project_upload" else "未上传项目模板，使用系统默认商务模板",
                "previewable": True,
                "confirmed": False,
                "reviewStatus": "candidate",
                "size": int(record.get("size_bytes") or source_path.stat().st_size if source_path.exists() else 0),
            }
        )
    return candidates


def _template_fallback_enabled(project: dict[str, Any]) -> bool:
    fallback = project.get("templateFallback") if isinstance(project.get("templateFallback"), dict) else {}
    enabled = fallback.get("enabled")
    return True if enabled is None else bool(enabled)


def _run_async(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


def _validate_business_gap_plan_toc_coverage(plan: dict[str, Any], toc_json_path: Path) -> None:
    toc = json.loads(toc_json_path.read_text(encoding="utf-8"))
    expected = len([item for item in toc.get("items") or [] if isinstance(item, dict)])
    actual = len([item for item in plan.get("tocRefs") or [] if isinstance(item, dict)])
    if plan.get("schemaVersion") != BUSINESS_GAP_PLAN_SCHEMA_VERSION:
        raise RuntimeError("商务标缺口计划 schemaVersion 不正确。")
    if expected != actual:
        raise RuntimeError(f"商务标缺口计划目录覆盖不完整：目录 {expected} 项，计划 {actual} 项。")


def _run_local_skill_runner(runner: Path, manifest_path: Path, schema_version: str) -> dict[str, Any]:
    if not runner.exists():
        raise RuntimeError(f"商务标缺口 Skill runner 不存在：{runner}")
    result = subprocess.run(
        [sys.executable, str(runner), "--manifest", str(manifest_path), "--response", "summary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
        raise RuntimeError(f"商务标缺口 Skill runner 执行失败（{result.returncode}）：{detail}")
    payload = json.loads(result.stdout or "{}")
    payload.setdefault("schemaVersion", schema_version)
    payload.setdefault("opencodeOutput", _local_opencode_output(manifest_path, payload, stdout=result.stdout.strip()))
    return payload


def _local_opencode_output(manifest_path: Path, payload: dict[str, Any], stdout: str = "") -> dict[str, Any]:
    return {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": BUSINESS_GAP_PLANNER_SKILL_NAME,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": stdout or json.dumps(payload, ensure_ascii=False)}],
    }


def _build_business_gap_planner_prompt(manifest_path: Path) -> str:
    return f"""
Use the {BUSINESS_GAP_PLANNER_SKILL_NAME} skill.

你现在在做 S3 商务标缺口处理。后端已经准备好 manifest，其中包含人工确认后的商务目录 JSON、商务标解析结果、商务标素材边界、商务素材索引、商务 Wiki 路径和项目所用机型。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整 business_gap_plan.json 写入 manifest 指定路径，并只在 stdout 打印小型摘要 JSON：

businessgap {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()
