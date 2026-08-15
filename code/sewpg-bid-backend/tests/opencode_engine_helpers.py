"""test_opencode_engine* 共享夹具：LLM 配置工厂、加速时钟、消息序列、静态 plan helper。

由 test_opencode_engine.py 拆分而来，只搬不改。
"""
from __future__ import annotations

import itertools
import unittest
from unittest.mock import AsyncMock, MagicMock
from app.services.agent_engine.opencode_engine import OpencodeEngine


def _db_llm_config(**overrides: object) -> dict:
    config = {
        "enabled": True,
        "providerId": "custom-provider",
        "modelId": "custom-model",
        "model": "custom-model",
        "baseUrl": "https://llm.example.com/v1",
        "opencodeBaseUrl": "http://db-opencode:4096",
        "timeoutMs": 30000,
    }
    config.update(overrides)
    return config


def _accelerated_monotonic(step: float = 60.0):
    """异步化后 time.monotonic 被事件循环共享（loop.time() 同源），固定取值表会被
    循环自身的定时器消耗尽；改为每次调用稳定前进 step 秒的假时钟——对引擎逻辑
    等价于「时间飞速流逝」，对循环定时器则是「立即到期」，两侧都有限可终止。"""
    ticks = itertools.count()
    return lambda: next(ticks) * step


def _sequence_message_fetch(fetches):
    """把「异常对象或消息列表」序列折成 list_session_messages 的 side_effect 函数。

    side_effect 函数的返回值会被当作正常返回，异常必须显式 raise。
    """

    def fetch(_session_id: str) -> list[dict]:
        item = next(fetches)
        if isinstance(item, BaseException):
            raise item
        return item

    return fetch


class OpencodeEngineTestBase(unittest.IsolatedAsyncioTestCase):

    @staticmethod
    def _plan(client: OpencodeEngine, command: str, terminal_validator: object = None):
        return client._orchestrator._build_early_completion_plan(
            command,
            terminal_validator=terminal_validator,
        )



    @staticmethod
    def _http_client_with_post_side_effect(side_effect: object) -> MagicMock:
        client = MagicMock()
        client.__aenter__.return_value = client
        client.post = AsyncMock(side_effect=side_effect)
        return client
