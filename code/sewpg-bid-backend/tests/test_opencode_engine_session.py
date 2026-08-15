from __future__ import annotations

import asyncio
import itertools
import threading
from unittest.mock import MagicMock, patch
import httpx
from app.services.agent_engine import errors as engine_errors
from app.services.agent_engine.opencode_engine import OpencodeEngine

from opencode_engine_helpers import (
    OpencodeEngineTestBase,
    _sequence_message_fetch,
)


class OpencodeEngineTests(OpencodeEngineTestBase):

    async def test_create_session_retries_connection_refused_until_service_recovers(self) -> None:
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session")
        response = MagicMock()
        response.json.return_value = {"id": "ses-recovered"}
        http_client = self._http_client_with_post_side_effect(
            [
                httpx.ConnectError("[Errno 111] Connection refused", request=request),
                httpx.ConnectError("[Errno 111] Connection refused", request=request),
                response,
            ]
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            session = await client.create_session("技术标素材预览")

        self.assertEqual(session, "ses-recovered")
        self.assertEqual(http_client.post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])



    async def test_create_session_retries_transient_service_unavailable(self) -> None:
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session")
        unavailable = httpx.Response(503, request=request)
        recovered = MagicMock()
        recovered.json.return_value = {"id": "ses-after-503"}
        http_client = self._http_client_with_post_side_effect([unavailable, recovered])

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            session = await client.create_session("技术标素材预览")

        self.assertEqual(session, "ses-after-503")
        self.assertEqual(http_client.post.call_count, 2)
        sleep.assert_called_once_with(0.5)



    async def test_create_session_reports_error_after_transient_retry_budget_exhausted(self) -> None:
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session")
        http_client = self._http_client_with_post_side_effect(
            httpx.ConnectError("[Errno 111] Connection refused", request=request)
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "Connection refused"):
                await client.create_session("技术标素材预览")

        self.assertEqual(http_client.post.call_count, 7)
        self.assertEqual(sleep.call_count, 6)



    async def test_create_session_does_not_retry_non_transient_http_error(self) -> None:
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session")
        response = httpx.Response(400, request=request)
        http_client = self._http_client_with_post_side_effect([response])

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "400 Bad Request"):
                await client.create_session("技术标素材预览")

        self.assertEqual(http_client.post.call_count, 1)
        sleep.assert_not_called()



    async def test_send_prompt_includes_explicit_tool_overrides(self) -> None:
        client = OpencodeEngine(
            base_url="http://opencode:4096",
            provider_id="provider-test",
            model_id="model-test",
        )
        response = MagicMock()
        response.text = '{"parts": []}'
        response.json.return_value = {"parts": []}
        http_client = self._http_client_with_post_side_effect(response)
        tool_overrides = {"bash": False, "read": False, "write": False}

        with patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client):
            await client.send_prompt("session-safe", "只返回文字", tools=tool_overrides)

        payload = http_client.post.call_args.kwargs["json"]
        self.assertEqual(payload["tools"], tool_overrides)



    async def test_send_text_prompt_omits_tool_overrides_by_default(self) -> None:
        client = OpencodeEngine()

        with patch.object(
            client,
            "create_session",
            return_value="session-default-tools",
        ), patch.object(
            client,
            "send_prompt",
            return_value={"parts": [{"type": "text", "text": "普通回复"}]},
        ) as send_prompt:
            await client.send_text_prompt("普通任务", "继续执行")

        send_prompt.assert_called_once_with("session-default-tools", "继续执行")



    async def test_send_prompt_retries_connect_error_until_delivered(self) -> None:
        """连接未建立（prompt 确认未送达）→ 按预算重发，幂等安全。"""
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session/ses-1/message")
        recovered = MagicMock()
        recovered.text = '{"ok": true}'
        recovered.json.return_value = {"parts": [{"type": "text", "text": "done"}]}
        http_client = self._http_client_with_post_side_effect(
            [
                httpx.ConnectError("[Errno 111] Connection refused", request=request),
                httpx.ConnectTimeout("connect timed out", request=request),
                recovered,
            ]
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            response = await client.send_prompt("ses-1", "prompt")

        self.assertEqual(response["parts"][0]["text"], "done")
        self.assertEqual(http_client.post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])



    async def test_send_prompt_connect_error_budget_exhausted_raises(self) -> None:
        """重发预算耗尽后显式报错（保留连接失败上下文）。"""
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session/ses-1/message")
        http_client = self._http_client_with_post_side_effect(
            httpx.ConnectError("[Errno 111] Connection refused", request=request)
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "连接未建立.*ses-1.*已重发 2 次"):
                await client.send_prompt("ses-1", "prompt")

        self.assertEqual(http_client.post.call_count, 3)  # 首次 + 2 次重发
        self.assertEqual(sleep.call_count, 2)



    async def test_send_prompt_does_not_retry_read_timeout(self) -> None:
        """读超时 = prompt 可能已送达并在执行中，重发会重复执行 → 禁止自动重试。"""
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session/ses-1/message")
        http_client = self._http_client_with_post_side_effect(
            httpx.ReadTimeout("read timed out", request=request)
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            with self.assertRaises(engine_errors.PromptDeliveryUncertainError) as context:
                await client.send_prompt("ses-1", "prompt")

        self.assertIsInstance(context.exception, RuntimeError)  # 调用方语义不变
        self.assertIn("ses-1", str(context.exception))
        self.assertIn("未自动重发", str(context.exception))
        self.assertEqual(http_client.post.call_count, 1)
        sleep.assert_not_called()



    async def test_send_prompt_does_not_retry_502_after_delivery(self) -> None:
        """收到 502 响应说明请求已送达网关/服务端，送达状态不确定 → 不自动重发。"""
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session/ses-1/message")
        http_client = self._http_client_with_post_side_effect(
            [httpx.Response(502, request=request)]
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            with self.assertRaises(engine_errors.PromptDeliveryUncertainError) as context:
                await client.send_prompt("ses-1", "prompt")

        self.assertIn("502", str(context.exception))
        self.assertIn("ses-1", str(context.exception))
        self.assertEqual(http_client.post.call_count, 1)
        sleep.assert_not_called()



    async def test_send_prompt_4xx_is_definitive_rejection_not_delivery_uncertain(self) -> None:
        """4xx（除 408/429）= 服务端确定性拒绝：直接失败，文案不得误称「送达状态不确定」。"""
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session/ses-1/message")
        http_client = self._http_client_with_post_side_effect(
            [httpx.Response(400, request=request)]
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            with self.assertRaises(RuntimeError) as context:
                await client.send_prompt("ses-1", "prompt")

        self.assertNotIsInstance(context.exception, engine_errors.PromptDeliveryUncertainError)
        self.assertIn("服务端拒绝", str(context.exception))
        self.assertIn("400", str(context.exception))
        self.assertNotIn("送达状态不确定", str(context.exception))
        self.assertEqual(http_client.post.call_count, 1)
        sleep.assert_not_called()



    async def test_send_prompt_429_stays_delivery_uncertain(self) -> None:
        """429 限流是瞬态 4xx：请求可能已进入服务端，保持投递不确定语义。"""
        client = OpencodeEngine()
        request = httpx.Request("POST", "http://opencode:4096/session/ses-1/message")
        http_client = self._http_client_with_post_side_effect(
            [httpx.Response(429, request=request)]
        )

        with (
            patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep") as sleep,
        ):
            with self.assertRaises(engine_errors.PromptDeliveryUncertainError) as context:
                await client.send_prompt("ses-1", "prompt")

        self.assertIn("429", str(context.exception))
        self.assertEqual(http_client.post.call_count, 1)
        sleep.assert_not_called()



    async def test_poll_recovers_from_transient_disconnect(self) -> None:
        """轮询 GET 中途断连（服务重启抖动）→ 按退避重连续轮询，不立即判死。"""
        client = OpencodeEngine()

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        completed_messages = [
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
        request = httpx.Request("GET", "http://opencode:4096/session/ses-gap/message")
        fetches = itertools.chain(
            [
                httpx.ConnectError("[Errno 111] Connection refused", request=request),
                httpx.RemoteProtocolError("Server disconnected", request=request),
            ],
            itertools.repeat(completed_messages),
        )

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", side_effect=_sequence_message_fetch(fetches)) as list_messages,
            # 退避归零（不 patch asyncio.sleep：那是全局模块属性，会把 worker 的慢发送也变快）
            patch("app.services.agent_engine.opencode_engine.settings.opencode_poll_reconnect_backoff_sec", (0, 0, 0, 0, 0, 0)),
        ):
            response = await client._send_prompt_with_session_polling(
                "ses-gap",
                "prompt",
                early_completion=self._plan(client, "s4gap"),
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s4gap")
        self.assertGreaterEqual(list_messages.call_count, 3)



    async def test_poll_reconnect_budget_exhausted_raises_explicit_disconnect_error(self) -> None:
        """重连预算耗尽 → 显式报「断线」（非 idle 超时/模型 stall 文案）。"""
        client = OpencodeEngine()
        release_worker = threading.Event()

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            await asyncio.to_thread(release_worker.wait, 2.0)
            return {"parts": []}

        request = httpx.Request("GET", "http://opencode:4096/session/ses-down/message")

        def always_down(_session_id: str) -> list[dict]:
            raise httpx.ConnectError("[Errno 111] Connection refused", request=request)

        try:
            with (
                patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
                patch.object(client, "list_session_messages", side_effect=always_down),
                patch("app.services.agent_engine.opencode_engine.settings.opencode_poll_reconnect_backoff_sec", (0, 0, 0, 0, 0, 0)),
            ):
                with self.assertRaises(engine_errors.PollReconnectExhaustedError) as context:
                    await client._send_prompt_with_session_polling(
                        "ses-down",
                        "prompt",
                        early_completion=self._plan(client, "s4gap"),
                    )
        finally:
            release_worker.set()
        await asyncio.sleep(0.05)  # 让发送 task 收尾，不留孤儿 task

        message = str(context.exception)
        self.assertIn("断线", message)
        self.assertIn("ses-down", message)
        self.assertIn("非模型停滞", message)
        self.assertNotIn("idle timeout", message)



    async def test_poll_disconnect_time_does_not_count_toward_idle(self) -> None:
        """断线时间不计入 idle：重连耗时超过 idle 时限也不得误判模型 stall。

        真实时钟验证：idle 1.2s，断线重连约 2s（两次 1s 退避）；无折扣时
        第二轮即触发 idle timeout，有折扣时会话正常跑到 worker 返回。
        """
        client = OpencodeEngine()

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(3.4)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        steady_messages = [
            {
                "info": {"role": "assistant", "id": "msg-working"},
                "parts": [{"type": "text", "text": "working"}],
            }
        ]
        request = httpx.Request("GET", "http://opencode:4096/session/ses-flap/message")
        fetches = itertools.chain(
            [
                steady_messages,  # 第一轮：建立 signature 基线
                httpx.ConnectError("Connection refused", request=request),  # 第二轮：断线
                httpx.ConnectError("Connection refused", request=request),
            ],
            itertools.repeat(steady_messages),  # 重连成功后恢复
        )

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", side_effect=_sequence_message_fetch(fetches)),
            patch.object(client, "abort_session", return_value=True) as abort_session,
            patch.object(client, "_session_polling_idle_timeout", return_value=1.2),
            patch("app.services.agent_engine.opencode_engine.settings.opencode_poll_reconnect_max_attempts", 2),
            patch("app.services.agent_engine.opencode_engine.settings.opencode_poll_reconnect_backoff_sec", (1, 1)),
        ):
            response = await client._send_prompt_with_session_polling(
                "ses-flap",
                "prompt",
                early_completion=self._plan(client, "factcurate"),
            )

        # 未被误判 stall：无 abort、无提前收割，走 worker 正常返回路径。
        abort_session.assert_not_called()
        self.assertNotIn("_earlyCompletion", response)
        self.assertIn('{"late":true}', response["parts"][0]["text"])



    async def test_poll_reconnect_then_stall_still_detected(self) -> None:
        """断线恢复后仍无新输出（假死）→ idle 超时照常判 stall，断线不掩盖真停滞。"""
        client = OpencodeEngine()
        release_worker = threading.Event()

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            await asyncio.to_thread(release_worker.wait, 5.0)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        steady_messages = [
            {
                "info": {"role": "assistant", "id": "msg-working"},
                "parts": [{"type": "text", "text": "working"}],
            }
        ]
        request = httpx.Request("GET", "http://opencode:4096/session/ses-stall/message")
        fetches = itertools.chain(
            [
                steady_messages,
                httpx.ConnectError("Connection refused", request=request),  # 抖一次
            ],
            itertools.repeat(steady_messages),  # 恢复后再无新输出（假死）
        )

        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "list_session_messages", side_effect=_sequence_message_fetch(fetches)),
            patch.object(client, "abort_session", side_effect=abort_session) as abort,
            patch.object(client, "_session_polling_idle_timeout", return_value=0.8),
            patch("app.services.agent_engine.opencode_engine.settings.opencode_poll_reconnect_max_attempts", 1),
            patch("app.services.agent_engine.opencode_engine.settings.opencode_poll_reconnect_backoff_sec", (0,)),
        ):
            with self.assertRaisesRegex(RuntimeError, "idle timeout"):
                await client._send_prompt_with_session_polling(
                    "ses-stall",
                    "prompt",
                    early_completion=self._plan(client, "factcurate"),
                )

        abort.assert_called_once_with("ses-stall")



    async def test_recoverable_error_classification(self) -> None:
        """可恢复错误分类表：与 create_session 白名单（429/502/503/504）语义对齐。"""
        request = httpx.Request("GET", "http://opencode:4096/session/ses-1/message")
        # 连接未建立 = prompt 确认未送达，可安全重发
        self.assertTrue(engine_errors.is_pre_delivery_error(httpx.ConnectError("refused", request=request)))
        self.assertTrue(engine_errors.is_pre_delivery_error(httpx.ConnectTimeout("timeout", request=request)))
        self.assertFalse(engine_errors.is_pre_delivery_error(httpx.ReadTimeout("timeout", request=request)))
        self.assertFalse(engine_errors.is_pre_delivery_error(httpx.RemoteProtocolError("drop", request=request)))
        # 轮询 GET 幂等：断连/读超时/429/502/503/504/非 JSON 均可重连
        for status in (429, 502, 503, 504):
            exc = httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request))
            self.assertTrue(engine_errors.is_recoverable_poll_error(exc), status)
        self.assertTrue(engine_errors.is_recoverable_poll_error(httpx.ReadTimeout("t", request=request)))
        self.assertTrue(engine_errors.is_recoverable_poll_error(httpx.RemoteProtocolError("d", request=request)))
        self.assertTrue(engine_errors.is_recoverable_poll_error(ValueError("not json")))
        # 确定性错误（4xx/500）不可恢复
        for status in (400, 404, 500):
            exc = httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request))
            self.assertFalse(engine_errors.is_recoverable_poll_error(exc), status)
