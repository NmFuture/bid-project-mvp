from __future__ import annotations

import copy
from typing import Any

from app.services.bid_runtime_state import build_directory_opencode_output, build_parse_event, now_iso
from app.services.project_stage_flow import project_stage_label


def source_file_type(file_name: str) -> str:
    lowered = str(file_name or "").lower()
    if lowered.endswith(".pdf"):
        return "PDF"
    if lowered.endswith(".md"):
        return "MD"
    if lowered.endswith((".doc", ".docx")):
        return "DOCX"
    return "文件"


def default_parse_progress() -> dict[str, Any]:
    return {
        "status": "idle",
        "percentage": 0,
        "summary": "",
        "startedAt": "",
        "completedAt": "",
        "events": [],
        "opencodeOutput": build_directory_opencode_output(),
    }


def ensure_parse_progress_state(project: dict[str, Any]) -> dict[str, Any]:
    progress = project.get("parse_progress")
    if not isinstance(progress, dict):
        progress = default_parse_progress()
        project["parse_progress"] = progress
    return copy.deepcopy(progress)


def start_parse_progress_state(project: dict[str, Any], message: str = "已开始招标文件解析。") -> dict[str, Any]:
    started_at = now_iso()
    progress = {
        "status": "running",
        "percentage": 5,
        "summary": message,
        "startedAt": started_at,
        "completedAt": "",
        "events": [build_parse_event(message, step="start", at=started_at)],
        "opencodeOutput": build_directory_opencode_output(status="idle"),
    }
    project["parse_progress"] = progress
    project["updatedAt"] = started_at
    return copy.deepcopy(progress)


def update_parse_progress_state(
    project: dict[str, Any],
    *,
    status: str | None = None,
    percentage: int | None = None,
    summary: str | None = None,
    event_message: str = "",
    event_step: str = "general",
    event_level: str = "info",
    opencode_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    progress = project.get("parse_progress") if isinstance(project.get("parse_progress"), dict) else {}
    if not progress:
        start_parse_progress_state(project)
        progress = project["parse_progress"]
    if status:
        progress["status"] = status
    if percentage is not None:
        progress["percentage"] = max(0, min(100, int(percentage)))
    if summary is not None:
        progress["summary"] = summary
    if opencode_output:
        progress["opencodeOutput"] = {
            **build_directory_opencode_output(),
            **copy.deepcopy(opencode_output),
        }
    if event_message:
        events = progress.setdefault("events", [])
        events.append(build_parse_event(event_message, level=event_level, step=event_step))
        progress["events"] = events[-80:]
    if status == "completed":
        progress["completedAt"] = now_iso()
        progress["percentage"] = 100
    project["parse_progress"] = progress
    project["updatedAt"] = now_iso()
    return copy.deepcopy(progress)


def complete_parse_state(
    project: dict[str, Any],
    tender_files: list[dict[str, Any]],
    template_files: list[dict[str, Any]],
    *,
    summary: dict[str, Any] | None = None,
    parse_storage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_at = now_iso()
    project_updates = parse_storage.get("projectUpdates") if isinstance(parse_storage, dict) else {}
    if isinstance(project_updates, dict):
        for field in ["startDate", "endDate", "deadline"]:
            value = str(project_updates.get(field) or "").strip()
            if value and not str(project.get(field) or "").strip():
                project[field] = value
    project["files"] = [item["name"] for item in tender_files]
    project["fileRecords"] = copy.deepcopy(tender_files)
    project["templateFileRecords"] = copy.deepcopy(template_files)
    project["templateFiles"] = [
        {
            "id": item["id"],
            "name": item["name"],
            "sizeLabel": item["size_label"],
        }
        for item in template_files
    ]
    source_files = [
        {
            "id": item["id"].replace("TEN", "SRC"),
            "name": item["name"],
            "type": source_file_type(item["name"]),
            "pageCount": 12,
            "size": item["size_label"],
        }
        for item in tender_files
    ]
    items: list[dict[str, Any]] = []
    structured: dict[str, Any] = {}
    if isinstance(parse_storage, dict):
        raw_items = parse_storage.get("items")
        raw_structured = parse_storage.get("structured")
        if isinstance(raw_items, list):
            items = copy.deepcopy(raw_items)
        if isinstance(raw_structured, dict):
            structured = copy.deepcopy(raw_structured)
    source_file_lookup = {item["name"]: item for item in source_files}
    if summary and parse_storage:
        for document in parse_storage.get("documents", []):
            if source_file_lookup.get(document["name"]):
                source_file_lookup[document["name"]]["pageCount"] = document.get("pageCount", "-")
                source_file_lookup[document["name"]]["textLength"] = document.get("textLength", 0)
    project["parse_result"] = {
        "status": "completed",
        "parsedAt": parsed_at,
        "project": {
            "id": project["id"],
            "files": copy.deepcopy(project["files"]),
            "templateFiles": copy.deepcopy(project["templateFiles"]),
            "startDate": project.get("startDate") or "",
            "endDate": project.get("endDate") or project.get("deadline") or "",
            "deadline": project.get("deadline") or project.get("endDate") or "",
            "currentStage": project["currentStage"],
            "stageLabel": project_stage_label(project),
        },
        "sourceFiles": source_files,
        "items": items,
        "structured": structured,
        "summary": summary or {
            "fileCount": len(source_files),
            "extractedCount": len(items),
            "textLength": 0,
            "textPreview": "",
            "warnings": [],
        },
    }
    project["parse_storage"] = copy.deepcopy(parse_storage or project.get("parse_storage") or {})
    project["updatedAt"] = parsed_at
    return copy.deepcopy(project["parse_result"])


def update_parse_result_state(
    project: dict[str, Any],
    parse_result: dict[str, Any],
    *,
    parse_storage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project["parse_result"] = copy.deepcopy(parse_result)
    if parse_storage is not None:
        project["parse_storage"] = copy.deepcopy(parse_storage)
    project["updatedAt"] = now_iso()
    return copy.deepcopy(project["parse_result"])


def update_template_files_state(
    project: dict[str, Any],
    template_files: list[dict[str, Any]],
) -> dict[str, Any]:
    project["templateFileRecords"] = copy.deepcopy(template_files)
    project["templateFiles"] = [
        {
            "id": item["id"],
            "name": item["name"],
            "sizeLabel": item["size_label"],
        }
        for item in template_files
    ]
    parse_result = project.get("parse_result") or {}
    if isinstance(parse_result, dict):
        parse_project = parse_result.get("project") or {}
        parse_project["id"] = project["id"]
        parse_project["templateFiles"] = copy.deepcopy(project["templateFiles"])
        parse_result["project"] = parse_project
        project["parse_result"] = parse_result
    project["updatedAt"] = now_iso()
    return {
        "project": {
            "id": project["id"],
            "templateFiles": copy.deepcopy(project["templateFiles"]),
            "currentStage": project["currentStage"],
            "stageLabel": project_stage_label(project),
        },
        "templateFiles": copy.deepcopy(project["templateFiles"]),
        "updatedAt": project["updatedAt"],
    }
