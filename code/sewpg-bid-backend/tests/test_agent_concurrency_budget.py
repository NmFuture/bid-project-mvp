"""B4（engine-06）全局并发预算单测。

覆盖：三池同源派生（不再叠加超发）、预算总量不超、派生池 cap 生效、
非阻塞获取失败回滚预算许可、取消不泄漏许可（engine-03 F1 语义保持）、
跨事件循环/跨线程复用、codex/pi 进程池纳入同一预算。
"""
from __future__ import annotations

import asyncio
import json
import threading
import unittest
from collections import deque
from typing import Any
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.agent_engine.codex_engine import _CODEX_PROCESS_SLOTS, CodexEngine
from app.services.agent_engine.concurrency import (
    AGENT_CONCURRENCY_BUDGET,
    BudgetPool,
    ConcurrencyBudget,
)
from app.services.agent_engine.opencode_engine import _OPENCODE_REQUEST_SLOTS, OpencodeEngine
from app.services.agent_engine.pi_engine import _PI_PROCESS_SLOTS, PiEngine
from app.services.outline_generation import _TECH_OUTLINE_REQUEST_SLOTS, TECH_OUTLINE_TOTAL_WORKERS
from app.services.parsing import _S1_SHARD_REQUEST_SLOTS


class BudgetDerivationTests(unittest.TestCase):
    """三个历史信号量池与进程型引擎池全部从同一全局预算派生。"""

    def test_all_pools_derive_from_single_budget(self) -> None:
        for pool in (
            _OPENCODE_REQUEST_SLOTS,
            _S1_SHARD_REQUEST_SLOTS,
            _TECH_OUTLINE_REQUEST_SLOTS,
            _CODEX_PROCESS_SLOTS,
            _PI_PROCESS_SLOTS,
        ):
            self.assertIsInstance(pool, BudgetPool)
            self.assertIs(pool.budget, AGENT_CONCURRENCY_BUDGET)
        self.assertEqual(AGENT_CONCURRENCY_BUDGET.total, settings.agent_concurrency_budget)

    def test_pool_caps(self) -> None:
        budget_total = settings.agent_concurrency_budget
        # 默认请求槽 / 进程型引擎池：不另设 cap，可用满整个预算。
        self.assertEqual(_OPENCODE_REQUEST_SLOTS.cap, budget_total)
        self.assertEqual(_CODEX_PROCESS_SLOTS.cap, budget_total)
        self.assertEqual(_PI_PROCESS_SLOTS.cap, budget_total)
        # 分片/章节池：配置项只是预算内的上限，且被预算钳制。
        self.assertEqual(
            _S1_SHARD_REQUEST_SLOTS.cap,
            min(max(1, settings.s1_parse_shard_concurrency), budget_total),
        )
        self.assertEqual(
            _TECH_OUTLINE_REQUEST_SLOTS.cap,
            min(TECH_OUTLINE_TOTAL_WORKERS, budget_total),
        )

    def test_cap_is_clamped_to_budget(self) -> None:
        pool = ConcurrencyBudget(2).derive(10)
        self.assertEqual(pool.cap, 2)

    def test_over_release_raises(self) -> None:
        pool = ConcurrencyBudget(1).derive()
        with self.assertRaises(ValueError):
            pool.release()


class BudgetPoolTests(unittest.TestCase):
    def test_nonblocking_acquire_rolls_back_budget_permit_when_cap_full(self) -> None:
        """cap 满时非阻塞获取失败必须立即归还预算许可，不占坑。"""
        budget = ConcurrencyBudget(2)
        capped = budget.derive(1)
        full = budget.derive()

        self.assertTrue(capped.acquire(blocking=False))  # 占 1 预算 + 1 cap
        self.assertFalse(capped.acquire(blocking=False))  # cap 满 → 失败且归还预算
        self.assertTrue(full.acquire(blocking=False))  # 预算还剩 1，别的池仍可取
        self.assertFalse(full.acquire(blocking=False))  # 预算真的只有 2：叠加超发被消除

        capped.release()
        full.release()
        self.assertTrue(full.acquire(blocking=False))
        self.assertTrue(full.acquire(blocking=False))
        full.release()
        full.release()

    def test_pool_reusable_across_event_loops_and_threads(self) -> None:
        """引擎实例跨事件循环复用（asyncio.run 桥接线程 / FastAPI 循环）预算不炸。"""
        pool = ConcurrencyBudget(1).derive()
        errors: list[BaseException] = []

        async def roundtrip() -> None:
            while not pool.acquire(blocking=False):  # 引擎同款非阻塞轮询（预算=1，会真排队）
                await asyncio.sleep(0.01)
            try:
                await asyncio.sleep(0)
            finally:
                pool.release()

        asyncio.run(roundtrip())
        asyncio.run(roundtrip())  # 第二个事件循环复用同一池

        def thread_roundtrip() -> None:
            try:
                asyncio.run(roundtrip())
            except BaseException as exc:  # noqa: BLE001 - 汇聚线程内所有失败
                errors.append(exc)

        threads = [threading.Thread(target=thread_roundtrip) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        # 全部归还后预算恢复
        self.assertTrue(pool.acquire(blocking=False))
        pool.release()


class BudgetConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_total_concurrency_never_exceeds_budget(self) -> None:
        """多池混合并发：总在飞数恒 ≤ 预算，各派生池恒 ≤ 自身 cap。"""
        budget = ConcurrencyBudget(3)
        pools = [budget.derive(), budget.derive(2), budget.derive(2)]
        inflight = 0
        max_inflight = 0
        pool_inflight = [0, 0, 0]
        pool_max = [0, 0, 0]

        async def worker(index: int) -> None:
            nonlocal inflight, max_inflight
            pool_index = index % len(pools)
            pool = pools[pool_index]
            while not pool.acquire(blocking=False):
                await asyncio.sleep(0.005)
            try:
                inflight += 1
                pool_inflight[pool_index] += 1
                max_inflight = max(max_inflight, inflight)
                pool_max[pool_index] = max(pool_max[pool_index], pool_inflight[pool_index])
                await asyncio.sleep(0.01)
            finally:
                inflight -= 1
                pool_inflight[pool_index] -= 1
                pool.release()

        await asyncio.gather(*(worker(i) for i in range(18)))

        self.assertEqual(max_inflight, 3)  # 预算被打满过（防测试空转）但从未超过
        self.assertLessEqual(pool_max[1], 2)
        self.assertLessEqual(pool_max[2], 2)
        for _ in range(3):  # 结束后许可全部归还
            self.assertTrue(pools[0].acquire(blocking=False))
        for _ in range(3):
            pools[0].release()

    async def test_opencode_request_slot_cancelled_while_waiting_does_not_leak(self) -> None:
        """engine-03 F1 语义在 BudgetPool 上保持：取消落在等待窗口不泄漏许可。"""
        pool = ConcurrencyBudget(1).derive()
        client = OpencodeEngine(request_slots=pool)
        self.assertTrue(pool.acquire(blocking=False))  # 占满预算，迫使引擎调用排队

        task = asyncio.create_task(client.create_session("预算排队取消"))
        await asyncio.sleep(0.3)  # 让协程进入预算轮询等待窗口（轮询间隔 0.1s）
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        pool.release()
        self.assertTrue(pool.acquire(blocking=False), "取消排队中的预算获取不得泄漏许可")
        pool.release()


class _FakeCodexStdout:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._lines: deque[bytes] = deque(json.dumps(event).encode() + b"\n" for event in events)

    def at_eof(self) -> bool:
        return not self._lines

    async def readline(self) -> bytes:
        if self._lines:
            await asyncio.sleep(0)
            return self._lines.popleft()
        return b""


class _FakeCodexStderr:
    async def read(self, n: int = -1) -> bytes:
        return b""


class _FakeCodexProcess:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.returncode: int | None = None
        self.stdout = _FakeCodexStdout(events)
        self.stderr = _FakeCodexStderr()

    def kill(self) -> None:
        if self.returncode is None:
            self.returncode = -9

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def _codex_done_events() -> list[dict[str, Any]]:
    return [
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.completed",
            "item": {"id": "item-9", "item_type": "assistant_message", "text": "完成。"},
        },
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    ]


class CodexBudgetTests(unittest.IsolatedAsyncioTestCase):
    """进程型引擎（codex）：一个 session 一个进程，进程池纳入全局预算。"""

    async def test_run_session_releases_budget_permit_on_completion(self) -> None:
        budget = ConcurrencyBudget(1)
        pool = budget.derive()
        engine = CodexEngine(request_slots=pool)
        process = _FakeCodexProcess(_codex_done_events())

        with patch(
            "app.services.agent_engine.codex_engine.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            session_id = await engine.create_session("预算回收")
            result = await engine.run_session(session_id, "写一段标书")

        self.assertEqual(result.reply_text, "完成。")
        self.assertTrue(pool.acquire(blocking=False), "run 结束后预算许可必须归还")
        pool.release()

    async def test_run_session_waits_for_budget_and_cancel_does_not_leak(self) -> None:
        pool = ConcurrencyBudget(1).derive()
        engine = CodexEngine(request_slots=pool)
        session_id = await engine.create_session("预算排队")
        self.assertTrue(pool.acquire(blocking=False))  # 占满预算

        with patch(
            "app.services.agent_engine.codex_engine.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeCodexProcess(_codex_done_events())),
        ) as spawn:
            task = asyncio.create_task(engine.run_session(session_id, "排队中的 prompt"))
            await asyncio.sleep(0.3)  # 进入预算轮询等待窗口
            spawn.assert_not_called()  # 预算未满前不得起进程
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        pool.release()
        self.assertTrue(pool.acquire(blocking=False), "取消等待中的 run 不得泄漏许可")
        pool.release()


class _FakePiStdout:
    """队列驱动的 stdout：feed() 注入 JSONL，feed_eof() 模拟进程关闭。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    def feed(self, record: dict[str, Any]) -> None:
        self._queue.put_nowait(json.dumps(record).encode("utf-8") + b"\n")

    def feed_eof(self) -> None:
        self._queue.put_nowait(b"")

    async def readline(self) -> bytes:
        return await self._queue.get()


class _FakePiStdin:
    def __init__(self, process: "_FakePiProcess") -> None:
        self._process = process
        self.lines: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.lines.append(data)
        for raw in data.decode("utf-8").splitlines():
            if raw.strip() and "id" in (payload := json.loads(raw)):
                self._process.stdout.feed(
                    {
                        "type": "response",
                        "id": payload["id"],
                        "command": payload.get("type"),
                        "success": True,
                        "data": {},
                    }
                )

    async def drain(self) -> None:
        pass


class _FakePiProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdout = _FakePiStdout()
        self.stdin = _FakePiStdin(self)

    def kill(self) -> None:
        if self.returncode is None:
            self.returncode = -9
            self.stdout.feed_eof()

    async def wait(self) -> int:
        while self.returncode is None:
            await asyncio.sleep(0.005)
        return self.returncode


class PiBudgetTests(unittest.IsolatedAsyncioTestCase):
    """进程型引擎（pi）：常驻 RPC 进程从 create 持许可到 terminate 归还。"""

    def _engine(self, pool: BudgetPool) -> PiEngine:
        return PiEngine(
            pi_command="pi-fake",
            provider_id="p0",
            model_id="m0",
            rpc_timeout_sec=2.0,
            request_slots=pool,
        )

    async def test_session_holds_permit_until_terminated(self) -> None:
        pool = ConcurrencyBudget(1).derive()
        engine = self._engine(pool)
        process = _FakePiProcess()

        with patch.object(engine, "_spawn_process", new=AsyncMock(return_value=process)):
            session_id = await engine.create_session("预算占用")

        self.assertFalse(pool.acquire(blocking=False), "会话进程存活期间预算许可必须被占用")

        await engine.delete_session(session_id)
        self.assertTrue(pool.acquire(blocking=False), "会话回收后预算许可必须归还")
        pool.release()

    async def test_spawn_failure_releases_permit(self) -> None:
        pool = ConcurrencyBudget(1).derive()
        engine = self._engine(pool)

        with patch.object(
            engine, "_spawn_process", new=AsyncMock(side_effect=FileNotFoundError("no pi"))
        ):
            with self.assertRaisesRegex(RuntimeError, "启动失败"):
                await engine.create_session("t")

        self.assertTrue(pool.acquire(blocking=False), "spawn 失败不得泄漏预算许可")
        pool.release()

    async def test_create_session_cancelled_while_waiting_does_not_leak(self) -> None:
        pool = ConcurrencyBudget(1).derive()
        engine = self._engine(pool)
        self.assertTrue(pool.acquire(blocking=False))  # 占满预算

        with patch.object(
            engine, "_spawn_process", new=AsyncMock(return_value=_FakePiProcess())
        ) as spawn:
            task = asyncio.create_task(engine.create_session("预算排队取消"))
            await asyncio.sleep(0.3)  # 进入预算轮询等待窗口
            spawn.assert_not_called()  # 预算未满前不得起进程
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        pool.release()
        self.assertTrue(pool.acquire(blocking=False), "取消排队中的 create 不得泄漏许可")
        pool.release()
