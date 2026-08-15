from __future__ import annotations

import copy
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any


TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
# 只有这些状态代表任务真的还在跑，停止请求才有意义
ACTIVE_TASK_STATUSES = {"queued", "running", "processing", "cancel_requested"}


class BackgroundTaskCancelled(BaseException):
    """后台任务到达安全停止点时抛出。

    刻意不继承 Exception：业务链路里到处是「失败不阻断出稿」的 except Exception，
    继承 Exception 会让用户点的停止被当成一次失败吞掉，任务照跑、界面卡在「停止中」。
    停止是控制流不是错误，语义上与 asyncio.CancelledError 一致。
    各任务入口显式 except BackgroundTaskCancelled 收口成「已停止」。
    """


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def task_cancel_requested(state: dict[str, Any] | None) -> bool:
    current = state if isinstance(state, dict) else {}
    return bool(current.get("cancelRequested")) or str(current.get("status") or "").lower() == "cancel_requested"


def raise_if_task_cancel_requested(state: dict[str, Any] | None) -> None:
    if task_cancel_requested(state):
        raise BackgroundTaskCancelled("任务已请求停止。")


# 当前后台任务的取消探针。任务入口用 task_cancel_scope 挂上，深层调用（尤其是
# opencode 会话轮询）不必层层传参就能拿到，从而在耗时会话中途也能中止而不是
# 干等到下一个阶段边界——那正是「点了停止一直显示停止中」的成因。
_current_task_cancel_check: ContextVar[Callable[[], bool] | None] = ContextVar(
    "current_task_cancel_check",
    default=None,
)


@contextmanager
def task_cancel_scope(cancel_check: Callable[[], bool] | None) -> Iterator[None]:
    token = _current_task_cancel_check.set(cancel_check)
    try:
        yield
    finally:
        _current_task_cancel_check.reset(token)


def throttled_cancel_probe(
    probe: Callable[[], bool],
    min_interval_sec: float = 2.0,
) -> Callable[[], bool]:
    """给探针加节流：轮询每 0.5 秒问一次，而每次探测都要读一次库。

    停止是一锤子买卖，确认过就不用再查；未确认时最多每 min_interval_sec 查一次，
    停止延迟仍在两三秒内，但长会话期间的库读压力降到原来的四分之一。
    """
    last_checked = 0.0
    cancelled = False

    def check() -> bool:
        nonlocal last_checked, cancelled
        if cancelled:
            return True
        now = time.monotonic()
        if last_checked and now - last_checked < min_interval_sec:
            return False
        last_checked = now
        cancelled = bool(probe())
        return cancelled

    return check


def current_task_cancel_check() -> Callable[[], bool] | None:
    return _current_task_cancel_check.get()


def raise_if_current_task_cancelled() -> None:
    check = current_task_cancel_check()
    if check is not None and check():
        raise BackgroundTaskCancelled("任务已请求停止。")


def request_task_cancel(state: dict[str, Any] | None, summary: str) -> dict[str, Any]:
    current = copy.deepcopy(state) if isinstance(state, dict) else {}
    # 任务没在跑就原样返回当前状态：既满足「已结束时返回当前终态」，
    # 也避免把 idle 标成 cancel_requested——那会让前端一直显示一个并不存在的任务、
    # 停止按钮永远卡在「停止中」，而且没有任何心跳能把它recover回来。
    if str(current.get("status") or "").lower() not in ACTIVE_TASK_STATUSES:
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
