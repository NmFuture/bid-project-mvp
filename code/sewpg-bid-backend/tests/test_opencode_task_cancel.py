from __future__ import annotations

import contextvars
import threading
import time

import httpx
import pytest

from app.services.background_task_cancel import BackgroundTaskCancelled, task_cancel_scope
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.opencode_client import OpencodeClient


class _StubClient:
    """只实现轮询路径用到的那几个方法，避免起真实会话。"""

    def __init__(self, *, block_forever: bool = True) -> None:
        self.aborted: list[str] = []
        self.prompt_calls = 0
        self.blocking_calls = 0
        self.timeout = httpx.Timeout(30.0, connect=10.0)
        self._released = threading.Event()
        self._block_forever = block_forever

    def send_prompt(self, session_id: str, prompt_text: str, timeout=None):  # noqa: ANN001, ARG002
        self.prompt_calls += 1
        if timeout is None:
            # 没有 timeout 参数说明走的是「整段阻塞」的快捷路径
            self.blocking_calls += 1
            return {"parts": []}
        if self._block_forever:
            self._released.wait(10)
        return {"parts": []}

    def abort_session(self, session_id: str) -> bool:
        self.aborted.append(session_id)
        self._released.set()
        return True

    def _session_polling_idle_timeout(self, early_tool_command: str) -> float:  # noqa: ARG002
        return 600.0

    def release(self) -> None:
        self._released.set()


def _poll(stub: _StubClient, **kwargs):
    return OpencodeClient._send_prompt_with_session_polling(stub, "ses-1", "prompt", **kwargs)


def _poll_in_thread(stub: _StubClient, **kwargs) -> tuple[threading.Thread, dict, dict]:
    """在后台线程里跑轮询，并显式把当前上下文带过去。

    取消探针放在 ContextVar 里，threading.Thread 不会继承调用方的上下文；
    真实链路是同一个线程进作用域再发起会话，这里用 copy_context 复现那个前提，
    否则线程里读不到探针，测试会静默走回「整段阻塞」的快捷路径而变得没有意义。
    """
    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}
    ctx = contextvars.copy_context()

    def run() -> None:
        try:
            result["value"] = ctx.run(_poll, stub, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - 测试要看清具体异常
            error["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, result, error


def test_no_cancel_probe_keeps_the_plain_blocking_path() -> None:
    stub = _StubClient(block_forever=False)

    result = _poll(stub)

    assert result == {"parts": []}
    assert stub.blocking_calls == 1, "没有探针也没有流式回调时不必起轮询线程"
    assert stub.aborted == []


def test_task_cancel_scope_aborts_the_running_session_mid_flight() -> None:
    """这就是「点了停止一直显示停止中」的修复点。

    技术标四类长任务不传 cancel_check，靠任务作用域拿到探针；
    没有它时请求整段阻塞在 send_prompt 里，会话跑完之前谁也拦不住。
    """
    stub = _StubClient()
    cancelled = False

    with task_cancel_scope(lambda: cancelled):
        started = time.monotonic()
        cancelled = True
        with pytest.raises(BackgroundTaskCancelled):
            _poll(stub)
        elapsed = time.monotonic() - started

    assert stub.aborted == ["ses-1"], "必须同时请求中止外部会话，而不是只抛异常"
    assert stub.blocking_calls == 0, "有探针就必须走轮询路径"
    assert elapsed < 5, "应在一个轮询间隔内响应，不是等会话自然结束"


def test_scope_probe_that_stays_false_does_not_abort() -> None:
    stub = _StubClient()

    with task_cancel_scope(lambda: False):
        worker, result, error = _poll_in_thread(stub)
        time.sleep(1.2)
        assert stub.blocking_calls == 0, "探针必须在线程里可见，否则这条用例是空转的"
        assert not stub.aborted, "没请求停止就不该中止会话"
        stub.release()
        worker.join(5)

    assert "error" not in error, f"不该抛异常：{error.get('error')}"
    assert result["value"] == {"parts": []}


def test_explicit_cancel_check_still_raises_the_parse_error() -> None:
    """解析链路显式传探针，异常类型保持不变，收口逻辑不受影响。"""
    stub = _StubClient()

    with pytest.raises(ParseCancelledError):
        _poll(stub, cancel_check=lambda: True)

    assert stub.aborted == ["ses-1"]


def test_explicit_cancel_check_wins_over_the_scope_probe() -> None:
    stub = _StubClient()

    with task_cancel_scope(lambda: False):
        with pytest.raises(ParseCancelledError):
            _poll(stub, cancel_check=lambda: True)

    assert stub.aborted == ["ses-1"]


def test_cancel_only_polling_does_not_kill_a_long_but_healthy_session() -> None:
    """只为观察取消探针而轮询时不能做卡死监管。

    这条路径没有任何活动信号（无流式回调、无 early tool 快照），last_activity
    永远不动；若照常判定 idle，正常跑着的长会话会被误杀成 idle timeout。
    """
    stub = _StubClient()
    stub._session_polling_idle_timeout = lambda early_tool_command: 0.2  # noqa: SLF001

    with task_cancel_scope(lambda: False):
        worker, result, error = _poll_in_thread(stub)
        time.sleep(1.5)
        assert stub.blocking_calls == 0, "探针必须在线程里可见，否则这条用例是空转的"
        assert not stub.aborted, "没有活动信号不等于卡死，不该中止会话"
        assert "error" not in error, f"不该抛 idle timeout：{error.get('error')}"
        stub.release()
        worker.join(5)

    assert result["value"] == {"parts": []}


def test_outline_chapter_pool_carries_the_cancel_probe_into_worker_threads() -> None:
    """目录生成按章节并行，线程池必须带上取消探针。

    ContextVar 不会被 ThreadPoolExecutor 自动继承；不显式复制上下文的话，
    章节级会话读不到探针，点了停止只能干等它自己跑完。
    """
    import inspect

    from app.services import outline_generation

    source = inspect.getsource(outline_generation)
    assert "contextvars.copy_context().run" in source
    assert "submit_with_context(run_chapter, chapter)" in source
    assert "executor.submit(run_chapter, chapter)" not in source
