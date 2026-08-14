from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any


TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}


class BackgroundTaskCancelled(RuntimeError):
    """后台任务到达安全停止点时抛出。"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def task_cancel_requested(state: dict[str, Any] | None) -> bool:
    current = state if isinstance(state, dict) else {}
    return bool(current.get("cancelRequested")) or str(current.get("status") or "").lower() == "cancel_requested"


def raise_if_task_cancel_requested(state: dict[str, Any] | None) -> None:
    if task_cancel_requested(state):
        raise BackgroundTaskCancelled("任务已请求停止。")


def request_task_cancel(state: dict[str, Any] | None, summary: str) -> dict[str, Any]:
    current = copy.deepcopy(state) if isinstance(state, dict) else {}
    if str(current.get("status") or "").lower() in TERMINAL_TASK_STATUSES:
        return current
    requested_at = str(current.get("cancelRequestedAt") or "") or _now_iso()
    current.update(
        {
            "status": "cancel_requested",
            "cancelRequested": True,
            "cancelRequestedAt": requested_at,
            "summary": summary,
        }
    )
    return current


def cancel_task_state(state: dict[str, Any] | None, summary: str) -> dict[str, Any]:
    current = copy.deepcopy(state) if isinstance(state, dict) else {}
    cancelled_at = str(current.get("cancelledAt") or "") or _now_iso()
    current.update(
        {
            "status": "cancelled",
            "cancelRequested": True,
            "cancelRequestedAt": str(current.get("cancelRequestedAt") or "") or cancelled_at,
            "cancelledAt": cancelled_at,
            "completedAt": cancelled_at,
            "summary": summary,
        }
    )
    return current
