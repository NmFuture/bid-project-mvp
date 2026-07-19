from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from app.services.bid_runtime_state import build_directory_opencode_output, build_parse_event, now_iso
from app.services.project_stage_flow import project_stage_label

DEFAULT_PARSE_STALE_AFTER_SECONDS = 300
RUNNING_PARSE_STATUSES = {"running", "processing", "queued"}
TERMINAL_PARSE_STATUSES = {"completed", "failed", "cancelled"}


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
        "phaseKey": "idle",
        "phaseLabel": "等待解析",
        "phasePercent": 0,
        "current": 0,
        "total": 0,
        "fileNames": [],
        "heartbeatAt": "",
        "staleAfterSeconds": DEFAULT_PARSE_STALE_AFTER_SECONDS,
        "startedAt": "",
        "completedAt": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "cancelledAt": "",
        "events": [],
        "opencodeOutput": build_directory_opencode_output(),
    }


def _bounded_int(value: Any, *, minimum: int = 0, maximum: int = 100, default: int = 0) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, min(maximum, resolved))


def _parse_progress_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _ensure_parse_progress_defaults(project: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any]:
    defaults = default_parse_progress()
    for key, value in defaults.items():
        if key not in progress:
            progress[key] = copy.deepcopy(value)
    if not str(progress.get("heartbeatAt") or "").strip():
        progress["heartbeatAt"] = (
            progress.get("startedAt")
            or project.get("updatedAt")
            or progress.get("completedAt")
            or ""
        )
    return progress


def ensure_parse_progress_state(project: dict[str, Any]) -> dict[str, Any]:
    progress = project.get("parse_progress")
    if not isinstance(progress, dict):
        progress = default_parse_progress()
        project["parse_progress"] = progress
    else:
        _ensure_parse_progress_defaults(project, progress)
    return copy.deepcopy(progress)


def start_parse_progress_state(
    project: dict[str, Any],
    message: str = "已开始招标文件解析。",
    file_names: list[str] | None = None,
) -> dict[str, Any]:
    started_at = now_iso()
    progress = {
        "status": "running",
        "percentage": 5,
        "summary": message,
        "phaseKey": "start",
        "phaseLabel": "准备解析",
        "phasePercent": 0,
        "current": 0,
        "total": 0,
        # 目标文件名随进度常驻：进度面板/全局提示/冲突提示都据此提醒用户在解析什么。
        "fileNames": [str(name).strip() for name in (file_names or []) if str(name or "").strip()][:10],
        "heartbeatAt": started_at,
        "staleAfterSeconds": DEFAULT_PARSE_STALE_AFTER_SECONDS,
        "startedAt": started_at,
        "completedAt": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "cancelledAt": "",
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
    phase_key: str | None = None,
    phase_label: str | None = None,
    phase_percent: int | None = None,
    current: int | None = None,
    total: int | None = None,
    stale_after_seconds: int | None = None,
) -> dict[str, Any]:
    progress = project.get("parse_progress") if isinstance(project.get("parse_progress"), dict) else {}
    if not progress:
        start_parse_progress_state(project)
        progress = project["parse_progress"]
    else:
        _ensure_parse_progress_defaults(project, progress)
    updated_at = now_iso()
    existing_status = str(progress.get("status") or "").lower()
    existing_percentage = _bounded_int(progress.get("percentage"))
    existing_phase_key = str(progress.get("phaseKey") or "")
    if status:
        progress["status"] = status
    next_status = str(progress.get("status") or "").lower()
    if percentage is not None:
        requested_percentage = _bounded_int(percentage)
        if next_status in RUNNING_PARSE_STATUSES and existing_status in RUNNING_PARSE_STATUSES | {"idle", ""}:
            progress["percentage"] = max(existing_percentage, requested_percentage)
        else:
            progress["percentage"] = requested_percentage
    if summary is not None:
        progress["summary"] = summary
    if phase_key is not None:
        progress["phaseKey"] = str(phase_key or "").strip() or progress.get("phaseKey") or "general"
    if phase_label is not None:
        progress["phaseLabel"] = str(phase_label or "").strip() or progress.get("phaseLabel") or "解析中"
    if phase_percent is not None:
        requested_phase_percent = _bounded_int(phase_percent)
        next_phase_key = str(progress.get("phaseKey") or "")
        if next_status in RUNNING_PARSE_STATUSES and next_phase_key == existing_phase_key:
            progress["phasePercent"] = max(_bounded_int(progress.get("phasePercent")), requested_phase_percent)
        else:
            progress["phasePercent"] = requested_phase_percent
    if current is not None:
        progress["current"] = max(0, int(current))
    if total is not None:
        progress["total"] = max(0, int(total))
    if stale_after_seconds is not None:
        progress["staleAfterSeconds"] = max(1, int(stale_after_seconds))
    progress["heartbeatAt"] = updated_at
    if opencode_output:
        progress["opencodeOutput"] = {
            **build_directory_opencode_output(),
            **copy.deepcopy(opencode_output),
        }
    if event_message:
        events = progress.setdefault("events", [])
        events.append(build_parse_event(event_message, level=event_level, step=event_step, at=updated_at))
        progress["events"] = events[-80:]
    if status in {"completed", "failed", "cancelled"}:
        progress["completedAt"] = updated_at
        if status == "completed":
            progress["percentage"] = 100
            progress["phaseKey"] = phase_key or "complete"
            progress["phaseLabel"] = phase_label or "解析完成"
            progress["phasePercent"] = 100
    project["parse_progress"] = progress
    project["updatedAt"] = updated_at
    return copy.deepcopy(progress)


def parse_progress_snapshot_state(project: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    progress = ensure_parse_progress_state(project)
    status = str(progress.get("status") or "").lower()
    if status not in RUNNING_PARSE_STATUSES:
        progress["stale"] = False
        return progress

    stale_after = max(1, int(progress.get("staleAfterSeconds") or DEFAULT_PARSE_STALE_AFTER_SECONDS))
    heartbeat_at = (
        progress.get("heartbeatAt")
        or progress.get("startedAt")
        or project.get("updatedAt")
        or ""
    )
    heartbeat = _parse_progress_timestamp(heartbeat_at)
    now_dt = _parse_progress_timestamp(now or now_iso())
    if heartbeat is None or now_dt is None:
        progress["stale"] = False
        return progress

    stale_seconds = int((now_dt - heartbeat).total_seconds())
    if stale_seconds <= stale_after:
        progress["stale"] = False
        return progress

    phase_label = str(progress.get("phaseLabel") or "当前阶段").strip()
    progress["status"] = "stale"
    progress["stale"] = True
    progress["staleSeconds"] = stale_seconds
    progress["statusBeforeStale"] = status
    progress["summary"] = f"解析长时间没有进度更新，可能中断。上次阶段：{phase_label}。"
    return progress


def cancel_parse_progress_state(
    project: dict[str, Any],
    message: str = "已请求停止后端解析和 Opencode 任务。",
    *,
    opencode_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    progress = project.get("parse_progress") if isinstance(project.get("parse_progress"), dict) else {}
    if not progress:
        start_parse_progress_state(project)
        progress = project["parse_progress"]

    cancelled_at = now_iso()
    progress["status"] = "cancelled"
    progress["summary"] = message
    progress["phaseKey"] = "cancel"
    progress["phaseLabel"] = "已停止"
    progress["phasePercent"] = 100
    progress["heartbeatAt"] = cancelled_at
    progress["cancelRequested"] = True
    progress["cancelRequestedAt"] = progress.get("cancelRequestedAt") or cancelled_at
    progress["cancelledAt"] = cancelled_at
    progress["completedAt"] = cancelled_at

    trace = opencode_output
    if trace is None:
        existing_trace = progress.get("opencodeOutput")
        trace = copy.deepcopy(existing_trace) if isinstance(existing_trace, dict) else {}
    if trace:
        trace = {
            **build_directory_opencode_output(),
            **copy.deepcopy(trace),
            "status": "cancelled",
        }
        parts = trace.get("parts") if isinstance(trace.get("parts"), list) else []
        if not parts:
            trace["parts"] = [{"type": "text", "text": message}]
        progress["opencodeOutput"] = trace

    events = progress.setdefault("events", [])
    events.append(build_parse_event(message, level="warning", step="cancel", at=cancelled_at))
    progress["events"] = events[-80:]
    project["parse_progress"] = progress
    project["updatedAt"] = cancelled_at
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
