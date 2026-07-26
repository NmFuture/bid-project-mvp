from __future__ import annotations

import copy
from typing import Any

from app.services.bid_fill_state import default_fill_state, fill_document_label, fill_task_label
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.bid_runtime_state import build_directory_event, build_directory_opencode_output, now_iso


def start_fill_generation_state(project: dict[str, Any]) -> dict[str, Any]:
    document_label = fill_document_label(project)
    technical = project.get("bidType") == TECHNICAL_BID_TYPE
    input_label = "准备目录与已选素材" if technical else "准备 S2 目录、Wiki 与素材库"
    preparing_summary = f"已开始拼装{document_label}，正在准备目录与已选素材。" if technical else f"已开始拼装{document_label}，正在准备 S2 目录、Wiki 与素材库。"
    payload = {
        "status": "running",
        "percentage": 5,
        "filledAt": "",
        "runDurationSec": 0,
        "runDuration": "",
        "summary": preparing_summary,
        "output": None,
        "sections": [],
        "opencodeOutput": build_directory_opencode_output(),
        "events": [
            build_directory_event(
                preparing_summary,
                step="bootstrap",
            ),
        ],
        "tasks": [
            {"id": "task-1", "label": input_label, "status": "running"},
            {"id": "task-2", "label": fill_task_label(project), "status": "pending"},
            {"id": "task-3", "label": "写入并规范化 Word 正文", "status": "pending"},
        ],
    }
    project["fill_state"] = payload
    project["updatedAt"] = now_iso()
    return copy.deepcopy(payload)


def update_fill_generation_state(
    project: dict[str, Any],
    *,
    percentage: int | None = None,
    summary: str | None = None,
    tasks: list[dict[str, Any]] | None = None,
    status: str | None = None,
    event_message: str | None = None,
    event_level: str = "info",
    event_step: str = "general",
    opencode_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = copy.deepcopy(project.get("fill_state") or default_fill_state(project))
    if percentage is not None:
        current["percentage"] = max(0, min(100, int(percentage)))
    if summary is not None:
        current["summary"] = summary
    if tasks is not None:
        current["tasks"] = copy.deepcopy(tasks)
    if status is not None:
        current["status"] = status
    if opencode_output is not None:
        merged_output = build_directory_opencode_output()
        merged_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
        merged_output.update(copy.deepcopy(opencode_output))
        merged_output["parts"] = copy.deepcopy(merged_output.get("parts") or [])[-20:]
        current["opencodeOutput"] = merged_output
    if event_message:
        events = list(current.get("events") or [])
        events.append(
            build_directory_event(
                event_message,
                level=event_level,
                step=event_step,
            )
        )
        current["events"] = events[-20:]
    project["fill_state"] = current
    project["updatedAt"] = now_iso()
    return copy.deepcopy(current)


def fail_fill_generation_state(
    project: dict[str, Any],
    *,
    message: str,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = copy.deepcopy(project.get("fill_state") or default_fill_state(project))
    current["status"] = "failed"
    current["summary"] = message
    current_output = build_directory_opencode_output()
    current_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
    if (
        current_output.get("status") != "idle"
        or current_output.get("sessionId")
        or current_output.get("providerId")
        or current_output.get("modelId")
        or current_output.get("parts")
    ):
        current_output["status"] = "failed"
    current["opencodeOutput"] = current_output
    if tasks is not None:
        current["tasks"] = copy.deepcopy(tasks)
    events = list(current.get("events") or [])
    events.append(build_directory_event(message, level="error", step="failed"))
    current["events"] = events[-20:]
    project["fill_state"] = current
    project["updatedAt"] = now_iso()
    return copy.deepcopy(current)


def complete_fill_generation_state(project: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    filled_at = now_iso()
    sections = [
        {
            "nodeId": "OL-1",
            "title": "项目概况",
            "generationMode": "generated",
            "evidenceRefs": [],
            "riskFlags": [],
        },
        {
            "nodeId": "OL-2",
            "title": "企业业绩",
            "generationMode": "placeholder",
            "evidenceRefs": [],
            "riskFlags": ["FACT_REQUIRED"],
        },
    ]
    document_label = fill_document_label(project)
    input_label = "准备目录与已选素材" if project.get("bidType") == TECHNICAL_BID_TYPE else "准备 S2 目录、Wiki 与素材库"
    project["fill_state"] = {
        "status": "completed",
        "percentage": 100,
        "filledAt": filled_at,
        "runDurationSec": 79,
        "runDuration": "1分19秒",
        "summary": f"{document_label}拼装完成。",
        "output": {
            "fileName": f"{project['name']}_正文.docx",
            "fileType": "docx",
            "size": "2.8 MB",
            "fileUrl": "",
        },
        "sections": sections,
        "opencodeOutput": build_directory_opencode_output(),
        "events": [
            build_directory_event(f"{document_label}拼装完成。", level="success", step="done", at=filled_at),
        ],
        "tasks": [
            {"id": "task-1", "label": input_label, "status": "done"},
            {"id": "task-2", "label": fill_task_label(project), "status": "done"},
            {"id": "task-3", "label": "写入并规范化 Word 正文", "status": "done"},
        ],
    }
    project["document_state"]["sourceFileName"] = f"{project['name']}_正文.docx"
    project["document_state"]["fileName"] = f"{project['name']}_正文.docx"
    project["document_state"]["fallback"]["content"] = (
        f"# {project['name']}\n\n## 项目概况\n本稿为 MVP 占位正文。\n\n## 企业业绩\n【此处待补充真实业绩信息】"
    )
    project["updatedAt"] = filled_at
    return copy.deepcopy(project["fill_state"])


def save_fill_generation_result_state(
    project: dict[str, Any],
    *,
    project_id: str,
    summary: str,
    sections: list[dict[str, Any]],
    content: str,
    filled_at: str,
    run_duration_sec: int,
    file_size_bytes: int,
    opencode_output: dict[str, Any] | None = None,
    file_name: str | None = None,
    coverage: dict[str, Any] | None = None,
    assembly: dict[str, Any] | None = None,
) -> dict[str, Any]:
    file_name = file_name or f"{project['name']}_正文.docx"
    current_state = copy.deepcopy(project.get("fill_state") or {})
    current_events = list(copy.deepcopy(current_state.get("events") or []))
    current_output = build_directory_opencode_output()
    current_output.update(copy.deepcopy(current_state.get("opencodeOutput") or {}))
    if opencode_output is not None:
        current_output.update(copy.deepcopy(opencode_output))
    current_output["parts"] = copy.deepcopy(current_output.get("parts") or [])[-20:]
    document_label = fill_document_label(project)
    input_label = "准备目录与已选素材" if project.get("bidType") == TECHNICAL_BID_TYPE else "准备 S2 目录、Wiki 与素材库"
    current_events.append(
        build_directory_event(
            f"{document_label}拼装完成，已输出 {len(sections)} 个目录章节。",
            level="success",
            step="done",
            at=filled_at,
        )
    )
    project["fill_state"] = {
        "status": "completed",
        "percentage": 100,
        "filledAt": filled_at,
        "runDurationSec": int(run_duration_sec),
        "runDuration": format_duration(run_duration_sec),
        "summary": summary,
        "output": {
            "fileName": file_name,
            "fileType": "docx",
            "size": format_file_size(file_size_bytes),
            "fileUrl": "",
        },
        "sections": copy.deepcopy(sections),
        "coverage": copy.deepcopy(coverage or {}),
        "assembly": copy.deepcopy(assembly or {}),
        "opencodeOutput": current_output,
        "events": current_events[-20:],
        "tasks": [
            {"id": "task-1", "label": input_label, "status": "done"},
            {"id": "task-2", "label": fill_task_label(project), "status": "done"},
            {"id": "task-3", "label": "写入并规范化 Word 正文", "status": "done"},
        ],
    }

    document_state = project["document_state"]
    next_version = int(document_state.get("version") or 1)
    if document_state.get("lastSavedAt"):
        next_version += 1
    document_state["status"] = "ready"
    document_state["sourceFileName"] = file_name
    document_state["fileName"] = file_name
    document_state["fileType"] = "docx"
    document_state["version"] = next_version
    document_state["lastSavedAt"] = filled_at
    document_state["fallback"]["content"] = content
    document_state["onlyoffice"]["title"] = file_name
    document_state["onlyoffice"]["documentKey"] = f"{project_id}-v{next_version}"

    project["updatedAt"] = filled_at
    return copy.deepcopy(project["fill_state"])


def format_duration(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    minutes = total // 60
    remain_seconds = total % 60
    if minutes <= 0:
        return f"{remain_seconds}秒"
    return f"{minutes}分{remain_seconds}秒"


def format_file_size(size_bytes: int) -> str:
    safe_size = max(0, int(size_bytes or 0))
    if safe_size < 1024:
        return f"{safe_size} B"
    if safe_size < 1024 * 1024:
        return f"{safe_size / 1024:.1f} KB"
    return f"{safe_size / (1024 * 1024):.1f} MB"
