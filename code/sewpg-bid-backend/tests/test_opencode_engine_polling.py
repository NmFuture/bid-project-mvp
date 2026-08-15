from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch
import httpx
from app.services.agent_engine.opencode_engine import OpencodeEngine

from opencode_engine_helpers import (
    OpencodeEngineTestBase,
)


class OpencodeEngineTests(OpencodeEngineTestBase):

    async def test_polling_can_early_complete_without_stream_callback(self) -> None:
        client = OpencodeEngine()

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s4gap /tmp/s4_gap_input.json"},
                            "exit": 0,
                            "output": (
                                '{"schema_version":"bid-tech-gap-plan-v1",'
                                '"outputFile":"/tmp/gap_plan.json","summary":{},"itemCount":0}'
                            ),
                        },
                    }
                ]
            }
        ]

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
        ):
            started_at = time.monotonic()
            response = await client._send_prompt_with_session_polling(
                "ses-gap",
                "prompt",
                early_completion=self._plan(client, "s4gap"),
            )

        self.assertLess(time.monotonic() - started_at, 1.5)
        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s4gap")
        self.assertIn("bid-tech-gap-plan-v1", response["parts"][0]["text"])



    async def test_polling_run_timeout_not_shorter_than_idle_supervision(self) -> None:
        """系统设置 timeoutMs 较短（如默认 30s）时，轮询监管的长任务 HTTP 读超时
        必须抬到 idle 监管时限以上，否则脚本/生成阶段请求先被 30s 读超时杀掉，
        后端 400 而 futurecode 会话仍在后台运行（产物无人回收）。"""
        client = OpencodeEngine()
        client.timeout = httpx.Timeout(30.0, connect=10.0)
        captured: dict = {}

        def capturing_send_prompt(session_id: str, prompt_text: str, **kwargs) -> dict:
            captured.update(kwargs)
            return {"parts": [{"type": "text", "text": '{"ok":true}'}]}

        with (
            patch.object(client, "send_prompt", side_effect=capturing_send_prompt),
            patch.object(client, "list_session_messages", return_value=[]),
        ):
            await client._send_prompt_with_session_polling(
                "ses-timeout-floor",
                "prompt",
                early_completion=self._plan(client, "factcurate"),
            )

        run_timeout = captured.get("timeout")
        self.assertIsInstance(run_timeout, httpx.Timeout)
        idle_timeout = client._session_polling_idle_timeout("factcurate")
        self.assertGreaterEqual(run_timeout.read, idle_timeout)



    async def test_idle_timeout_aborts_session_and_joins_worker(self) -> None:
        client = OpencodeEngine()
        release_worker = threading.Event()
        worker_finished = threading.Event()

        async def blocked_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.to_thread(release_worker.wait, 2.0)
            worker_finished.set()
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "abort_session", side_effect=abort_session) as abort,
            patch.object(client, "list_session_messages", return_value=[]),
            patch.object(client, "_session_polling_idle_timeout", return_value=0.01),
        ):
            with self.assertRaisesRegex(RuntimeError, "idle timeout"):
                await client._send_prompt_with_session_polling(
                    "ses-idle-abort",
                    "prompt",
                    early_completion=self._plan(client, "factcurate"),
                )

        abort.assert_called_once_with("ses-idle-abort")
        # idle 超时报错前必须等到 worker task 收尾（对齐原 thread.join 语义）：
        # abort 放行后 worker 才完成，能返回说明发送 task 已被收割。
        self.assertTrue(worker_finished.is_set())



    async def test_polling_emits_heartbeat_when_snapshot_does_not_change(self) -> None:
        client = OpencodeEngine()
        events: list[dict] = []

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(1.2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            {
                "info": {"role": "assistant", "id": "msg-working"},
                "parts": [{"type": "text", "text": "working"}],
            }
        ]

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
            patch("app.services.agent_engine.opencode_engine.OPENCODE_PROGRESS_HEARTBEAT_SECONDS", 0.1),
        ):
            await client._send_prompt_with_session_polling(
                "ses-heartbeat",
                "prompt",
                stream_callback=events.append,
            )

        heartbeat_events = [event for event in events if event.get("heartbeat")]
        self.assertTrue(heartbeat_events)
        self.assertGreaterEqual(heartbeat_events[-1]["idleSeconds"], 1)
        self.assertGreaterEqual(heartbeat_events[-1]["elapsedSeconds"], heartbeat_events[-1]["idleSeconds"])
        self.assertEqual(heartbeat_events[-1]["sessionId"], "ses-heartbeat")



    async def test_polling_aborts_session_when_cancel_requested(self) -> None:
        client = OpencodeEngine()

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "abort_session", return_value=True) as abort_session,
        ):
            with self.assertRaisesRegex(RuntimeError, "解析已取消"):
                await client._send_prompt_with_session_polling(
                    "ses_cancel_polling_probe",
                    "prompt",
                    early_completion=self._plan(client, "s1parse-finalize"),
                    cancel_check=lambda: True,
                )

        abort_session.assert_called_once_with("ses_cancel_polling_probe")



    async def test_request_slot_cancelled_while_waiting_does_not_leak_permit(self) -> None:
        """取消落在并发预算等待窗口时不得泄漏许可（to_thread(acquire) 无法被取消，
        executor 线程随后 acquire 成功却无人 release；预算默认 1 时一次泄漏即
        进程级挂死）。"""
        slots = threading.BoundedSemaphore(1)
        client = OpencodeEngine(request_slots=slots)
        slots.acquire()  # 占满预算，迫使引擎调用在 _request_slot 里排队

        task = asyncio.create_task(client.create_session("预算排队取消"))
        await asyncio.sleep(0.3)  # 让协程进入预算轮询等待窗口（轮询间隔 0.1s）
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        slots.release()
        self.assertTrue(
            slots.acquire(blocking=False),
            "取消排队中的预算获取不得泄漏许可",
        )
        slots.release()



    async def test_polling_propagates_worker_error_to_caller(self) -> None:
        """发送 prompt 的 worker task 异常必须如实抛给主协程（不静默死亡）。"""
        client = OpencodeEngine()

        async def failing_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            await asyncio.sleep(0.6)  # 让主循环先进入轮询再失败
            raise RuntimeError("futurecode 生成失败：boom")

        with (
            patch.object(client, "send_prompt", side_effect=failing_send_prompt),
            patch.object(client, "list_session_messages", return_value=[]),
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await client._send_prompt_with_session_polling(
                    "ses-worker-error",
                    "prompt",
                    stream_callback=MagicMock(),
                )
