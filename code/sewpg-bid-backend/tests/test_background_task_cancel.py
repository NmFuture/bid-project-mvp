from __future__ import annotations

import pytest

from app.services.background_task_cancel import (
    BackgroundTaskCancelled,
    cancel_task_state,
    current_task_cancel_check,
    raise_if_current_task_cancelled,
    raise_if_task_cancel_requested,
    request_task_cancel,
    task_cancel_scope,
    throttled_cancel_probe,
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


def test_task_cancel_scope_exposes_probe_to_nested_calls() -> None:
    """深层调用不必层层传参就能拿到取消探针。

    opencode 会话轮询正是靠它在会话中途中止，而不是干等到下一个阶段边界，
    否则用户点了停止只能一直看着「停止中」。
    """
    assert current_task_cancel_check() is None

    cancelled = False
    with task_cancel_scope(lambda: cancelled):
        probe = current_task_cancel_check()
        assert probe is not None
        assert probe() is False
        raise_if_current_task_cancelled()

        cancelled = True
        with pytest.raises(BackgroundTaskCancelled):
            raise_if_current_task_cancelled()

    assert current_task_cancel_check() is None


def test_task_cancel_scope_restores_previous_probe_on_exit() -> None:
    outer = lambda: False  # noqa: E731 - 测试里只要个可辨认的哨兵
    with task_cancel_scope(outer):
        with task_cancel_scope(lambda: True):
            assert current_task_cancel_check() is not outer
        assert current_task_cancel_check() is outer
    assert current_task_cancel_check() is None


def test_task_cancel_scope_clears_probe_even_when_body_raises() -> None:
    with pytest.raises(ValueError):
        with task_cancel_scope(lambda: False):
            raise ValueError("boom")
    assert current_task_cancel_check() is None


def test_raise_if_current_task_cancelled_is_noop_without_scope() -> None:
    raise_if_current_task_cancelled()


def test_throttled_probe_limits_how_often_the_state_is_read() -> None:
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        return False

    check = throttled_cancel_probe(probe, min_interval_sec=60.0)

    assert check() is False
    assert calls["n"] == 1, "第一次必须真读一次，别让停止延迟一整个节流窗口"
    for _ in range(10):
        assert check() is False
    assert calls["n"] == 1, "窗口内不再重复读库"


def test_throttled_probe_latches_once_cancel_is_confirmed() -> None:
    calls = {"n": 0}
    cancelled = {"value": False}

    def probe() -> bool:
        calls["n"] += 1
        return cancelled["value"]

    check = throttled_cancel_probe(probe, min_interval_sec=0.0)

    assert check() is False
    cancelled["value"] = True
    assert check() is True
    seen = calls["n"]

    # 确认停止后就不必再问了：停止是一锤子买卖
    assert check() is True
    assert calls["n"] == seen


def test_cancelled_is_not_an_exception_so_broad_handlers_cannot_swallow_it() -> None:
    """业务链路里到处是「失败不阻断出稿」的 except Exception。

    取消若继承 Exception，用户点的停止会被当成一次失败吞掉：任务照跑到底，
    界面永远卡在「停止中」。这正是实测里看到的现象。
    """
    assert issubclass(BackgroundTaskCancelled, BaseException)
    assert not issubclass(BackgroundTaskCancelled, Exception)

    swallowed = False
    try:
        try:
            raise BackgroundTaskCancelled("stop")
        except Exception:  # noqa: BLE001 - 复现业务里的宽泛兜底
            swallowed = True
    except BackgroundTaskCancelled:
        pass
    assert swallowed is False, "宽泛兜底不得吞掉取消"


def test_cancelled_still_runs_finally_blocks_for_cleanup() -> None:
    cleaned = False
    with pytest.raises(BackgroundTaskCancelled):
        try:
            raise BackgroundTaskCancelled("stop")
        finally:
            cleaned = True
    assert cleaned is True, "取消要能中断，但清理必须照常执行"
