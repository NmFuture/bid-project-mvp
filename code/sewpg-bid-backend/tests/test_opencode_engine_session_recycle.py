from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from app.services.agent_engine.opencode_engine import OpencodeEngine


class OpencodeEngineSessionRecycleTests(unittest.IsolatedAsyncioTestCase):

    """B3（engine-05）：delete_session 协议实现与终态回收保证。"""



    @staticmethod
    def _http_client_with_delete_response(response: object) -> MagicMock:
        client = MagicMock()
        client.__aenter__.return_value = client
        client.delete = AsyncMock(return_value=response)
        return client



    async def test_delete_session_sends_delete_request(self) -> None:
        client = OpencodeEngine(base_url="http://opencode:4096")
        request = httpx.Request("DELETE", "http://opencode:4096/session/ses-del")
        http_client = self._http_client_with_delete_response(httpx.Response(200, request=request))

        with patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client):
            await client.delete_session("ses-del")

        http_client.delete.assert_awaited_once_with("http://opencode:4096/session/ses-del")



    async def test_delete_session_404_is_idempotent(self) -> None:
        client = OpencodeEngine(base_url="http://opencode:4096")
        request = httpx.Request("DELETE", "http://opencode:4096/session/ses-gone")
        http_client = self._http_client_with_delete_response(httpx.Response(404, request=request))

        with patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client):
            await client.delete_session("ses-gone")  # 不抛：会话已不存在视为回收成功



    async def test_delete_session_5xx_raises_explicitly(self) -> None:
        client = OpencodeEngine(base_url="http://opencode:4096")
        request = httpx.Request("DELETE", "http://opencode:4096/session/ses-err")
        http_client = self._http_client_with_delete_response(httpx.Response(500, request=request))

        with patch("app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client):
            with self.assertRaisesRegex(RuntimeError, "ses-err"):
                await client.delete_session("ses-err")



    async def test_delete_session_quietly_logs_and_never_raises(self) -> None:
        client = OpencodeEngine(base_url="http://opencode:4096")
        with (
            patch.object(client, "delete_session", side_effect=RuntimeError("boom")),
            self.assertLogs("app.services.agent_engine.opencode_engine", level="WARNING") as logs,
        ):
            await client.delete_session_quietly("ses-quiet")

        self.assertTrue(any("ses-quiet" in line for line in logs.output))



    async def test_send_text_prompt_recycles_session_by_default(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-once"),
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": "回复"}]}),
            patch.object(client, "delete_session_quietly") as delete,
        ):
            result = await client.send_text_prompt("一次性任务", "prompt")

        self.assertEqual(result["sessionId"], "ses-once")
        delete.assert_awaited_once_with("ses-once")



    async def test_send_text_prompt_recycles_session_on_error(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-fail"),
            patch.object(client, "send_prompt", side_effect=RuntimeError("生成失败")),
            patch.object(client, "delete_session_quietly") as delete,
        ):
            with self.assertRaisesRegex(RuntimeError, "生成失败"):
                await client.send_text_prompt("一次性任务", "prompt")

        delete.assert_awaited_once_with("ses-fail")



    async def test_send_text_prompt_keep_session_skips_recycle(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-chat"),
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": "回复"}]}),
            patch.object(client, "delete_session_quietly") as delete,
        ):
            result = await client.send_text_prompt("多轮对话", "prompt", keep_session=True)

        self.assertEqual(result["sessionId"], "ses-chat")
        delete.assert_not_called()
