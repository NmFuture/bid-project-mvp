from __future__ import annotations

import base64
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.agent_engine.opencode_engine import OpencodeEngine


class OpencodeEngineAuthHeaderTests(unittest.IsolatedAsyncioTestCase):

    """engine-10：OPENCODE_SERVER_PASSWORD 非空时所有 opencode 请求带 Basic 鉴权头；
    空密码（本地默认）不带头，请求形态与无鉴权现状完全一致。"""



    @staticmethod
    def _basic_token(username: str, password: str) -> str:
        return base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")



    @staticmethod
    def _http_client() -> MagicMock:
        client = MagicMock()
        client.__aenter__.return_value = client
        client.post = AsyncMock()
        client.get = AsyncMock()
        client.delete = AsyncMock()
        return client



    async def test_empty_password_sends_no_auth_header(self) -> None:
        with patch("app.services.agent_engine.opencode_engine.settings.opencode_server_password", ""):
            client = OpencodeEngine(base_url="http://opencode:4096")
        self.assertEqual(client._auth_headers, {})

        response = MagicMock()
        response.json.return_value = {"id": "ses-no-auth"}
        http_client = self._http_client()
        http_client.post.return_value = response
        with patch(
            "app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client
        ) as async_client_cls:
            session = await client.create_session("t")

        self.assertEqual(session, "ses-no-auth")
        self.assertEqual(async_client_cls.call_args.kwargs["headers"], {})



    async def test_password_set_sends_basic_auth_header_on_all_methods(self) -> None:
        expected = {"Authorization": f"Basic {self._basic_token('opencode', 's3cret')}"}
        with patch("app.services.agent_engine.opencode_engine.settings.opencode_server_password", "s3cret"):
            client = OpencodeEngine(base_url="http://opencode:4096")
        self.assertEqual(client._auth_headers, expected)

        http_client = self._http_client()
        create_response = MagicMock()
        create_response.json.return_value = {"id": "ses-auth"}
        http_client.post.return_value = create_response
        http_client.get.return_value = MagicMock(**{"json.return_value": []})
        http_client.delete.return_value = MagicMock(status_code=200)
        with patch(
            "app.services.agent_engine.opencode_engine.httpx.AsyncClient", return_value=http_client
        ) as async_client_cls:
            await client.create_session("t")
            await client.list_session_messages("ses-auth")
            await client.abort_session("ses-auth")
            await client.delete_session("ses-auth")

        # create/post、list/get、abort/post、delete 四次建连全部带同一鉴权头
        self.assertEqual(async_client_cls.call_count, 4)
        for call in async_client_cls.call_args_list:
            self.assertEqual(call.kwargs["headers"], expected)



    async def test_custom_username_is_used_in_basic_token(self) -> None:
        with (
            patch("app.services.agent_engine.opencode_engine.settings.opencode_server_password", "s3cret"),
            patch("app.services.agent_engine.opencode_engine.settings.opencode_server_username", "bidops"),
        ):
            client = OpencodeEngine(base_url="http://opencode:4096")
        self.assertEqual(
            client._auth_headers,
            {"Authorization": f"Basic {self._basic_token('bidops', 's3cret')}"},
        )
