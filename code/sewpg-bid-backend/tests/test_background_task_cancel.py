from __future__ import annotations

import pytest

from app.services.background_task_cancel import (
    BackgroundTaskCancelled,
    cancel_task_state,
    raise_if_task_cancel_requested,
    request_task_cancel,
)


def test_request_task_cancel_is_idempotent() -> None:
    state = {"status": "running", "percentage": 42, "summary": "正在生成。"}

    first = request_task_cancel(state, "已请求停止，正在等待安全停止点。")
    second = request_task_cancel(first, "已请求停止，正在等待安全停止点。")

    assert state["status"] == "running"
    assert first["status"] == second["status"] == "cancel_requested"
    assert first["cancelRequested"] is True
    assert first["cancelRequestedAt"] == second["cancelRequestedAt"]
    assert first["summary"] == "已请求停止，正在等待安全停止点。"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_request_task_cancel_preserves_terminal_state(status: str) -> None:
    state = {"status": status, "summary": "终态"}

    assert request_task_cancel(state, "停止中") == state


def test_raise_if_task_cancel_requested_recognizes_both_state_shapes() -> None:
    with pytest.raises(BackgroundTaskCancelled):
        raise_if_task_cancel_requested({"status": "cancel_requested"})

    with pytest.raises(BackgroundTaskCancelled):
        raise_if_task_cancel_requested({"status": "running", "cancelRequested": True})


def test_cancel_task_state_records_terminal_fields_without_forcing_percentage() -> None:
    state = {
        "status": "cancel_requested",
        "percentage": 61,
        "startedAt": "2026-08-14T10:00:00+00:00",
        "cancelRequestedAt": "2026-08-14T10:01:00+00:00",
    }

    result = cancel_task_state(state, "任务已停止。")

    assert result["status"] == "cancelled"
    assert result["percentage"] == 61
    assert result["cancelRequested"] is True
    assert result["cancelledAt"]
    assert result["completedAt"] == result["cancelledAt"]
    assert result["summary"] == "任务已停止。"


@pytest.mark.parametrize("state", [
    {"status": "idle", "summary": "尚未运行。"},
    {"status": "", "summary": "从未跑过。"},
    {},
    None,
])
def test_request_task_cancel_ignores_tasks_that_are_not_running(state) -> None:
    """没有在跑的任务被停止时必须原样返回。

    把 idle 标成 cancel_requested 会让前端一直显示一个并不存在的任务，
    停止按钮永远停在「停止中」，而且 stale 检测只看 running，救不回来。
    """
    expected = dict(state) if isinstance(state, dict) else {}

    assert request_task_cancel(state, "停止中") == expected


def test_request_task_cancel_still_applies_to_queued_tasks() -> None:
    result = request_task_cancel({"status": "queued", "percentage": 0}, "已请求停止。")

    assert result["status"] == "cancel_requested"
    assert result["cancelRequested"] is True
