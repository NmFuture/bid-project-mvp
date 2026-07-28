from __future__ import annotations

import copy
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE


def fill_task_label(project: dict[str, Any]) -> str:
    bid_type = _project_bid_type(project)
    if bid_type == TECHNICAL_BID_TYPE:
        return "组装技术标正文"
    return f"调用{bid_type}正文拼装 skill"


def fill_document_label(project: dict[str, Any]) -> str:
    bid_type = _project_bid_type(project)
    return f"{bid_type}正文"


def default_fill_tasks(project: dict[str, Any]) -> list[dict[str, Any]]:
    input_label = "准备目录与已选素材" if _project_bid_type(project) == TECHNICAL_BID_TYPE else "准备 S2 目录、Wiki 与素材库"
    return [
        {"id": "task-1", "label": input_label, "status": "pending"},
        {"id": "task-2", "label": fill_task_label(project), "status": "pending"},
        {"id": "task-3", "label": "写入 Word 正文", "status": "pending"},
    ]


def default_fill_state(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "idle",
        "percentage": 0,
        "filledAt": "",
        "runDurationSec": 0,
        "runDuration": "",
        "summary": "尚未生成标书，请点击“生成标书”后继续。",
        "output": None,
        "sections": [],
        "opencodeOutput": default_fill_opencode_output(),
        "events": [],
        "tasks": default_fill_tasks(project),
    }


def default_fill_opencode_output(
    *,
    status: str = "idle",
    session_id: str = "",
    provider_id: str = "",
    model_id: str = "",
    received_at: str = "",
    parts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "sessionId": session_id,
        "providerId": provider_id,
        "modelId": model_id,
        "receivedAt": received_at,
        "parts": copy.deepcopy(parts or []),
    }


def _project_bid_type(project: dict[str, Any]) -> str:
    bid_type = str((project or {}).get("bidType") or "").strip()
    if bid_type not in {TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE}:
        raise ValueError("正文生成状态必须显式传入技术标或商务标项目。")
    return bid_type
