"""harness-07：超时配置统一的回归覆盖。

事实源与推导公式见 app/core/config.py「harness-07」注释：
- read 超时：系统设置页 timeoutMs（用户可改），未配置时回退 OPENCODE_TIMEOUT_SEC；
- idle 超时：clamp(OPENCODE_TIMEOUT_SEC, 120, 900)；
- 总超时（长轮询 message 读超时）：max(read, idle + 60s 收尾宽限)。

覆盖：三个超时的推导公式、引擎接线（改 timeoutMs 后实际请求超时随之变化）、
健康检查展示「当前生效超时」。OpenCode/DB 全部 mock 或走显式入参，不依赖外部服务。
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.core.config import (
    OPENCODE_RUN_READ_GRACE_SEC,
    resolve_opencode_idle_timeout_sec,
    resolve_opencode_read_timeout_sec,
    resolve_opencode_timeouts,
    settings,
)
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.system_settings import system_settings_service


class ReadTimeoutDerivationTests(unittest.TestCase):
    def test_read_timeout_from_timeout_ms(self) -> None:
        self.assertEqual(resolve_opencode_read_timeout_sec(30000), 30.0)
        self.assertEqual(resolve_opencode_read_timeout_sec(120000), 120.0)

    def test_read_timeout_floor_is_one_second(self) -> None:
        self.assertEqual(resolve_opencode_read_timeout_sec(500), 1.0)

    def test_read_timeout_falls_back_to_env_when_unset(self) -> None:
        with patch.object(settings, "opencode_timeout_sec", 42.0):
            for unset in (None, 0, "", "abc"):
                self.assertEqual(resolve_opencode_read_timeout_sec(unset), 42.0)


class IdleTimeoutDerivationTests(unittest.TestCase):
    def test_idle_timeout_clamps_env_value(self) -> None:
        with patch.object(settings, "opencode_timeout_sec", 1800.0):
            self.assertEqual(resolve_opencode_idle_timeout_sec(), 900.0)
        with patch.object(settings, "opencode_timeout_sec", 60.0):
            self.assertEqual(resolve_opencode_idle_timeout_sec(), 120.0)
        with patch.object(settings, "opencode_timeout_sec", 300.0):
            self.assertEqual(resolve_opencode_idle_timeout_sec(), 300.0)

    def test_idle_timeout_explicit_override(self) -> None:
        self.assertEqual(resolve_opencode_idle_timeout_sec(2000.0), 900.0)
        self.assertEqual(resolve_opencode_idle_timeout_sec(10.0), 120.0)
        self.assertEqual(resolve_opencode_idle_timeout_sec(240.0), 240.0)


class RunReadTimeoutDerivationTests(unittest.TestCase):
    def test_run_read_is_idle_plus_grace_when_read_is_short(self) -> None:
        with patch.object(settings, "opencode_timeout_sec", 1800.0):
            profile = resolve_opencode_timeouts(30000)
        self.assertEqual(profile.read_timeout_sec, 30.0)
        self.assertEqual(profile.idle_timeout_sec, 900.0)
        self.assertEqual(
            profile.run_read_timeout_sec,
            profile.idle_timeout_sec + OPENCODE_RUN_READ_GRACE_SEC,
        )

    def test_run_read_follows_read_when_read_exceeds_idle_plus_grace(self) -> None:
        with patch.object(settings, "opencode_timeout_sec", 1800.0):
            profile = resolve_opencode_timeouts(2_000_000)
        self.assertEqual(profile.read_timeout_sec, 2000.0)
        self.assertEqual(profile.run_read_timeout_sec, 2000.0)


class EngineTimeoutWiringTests(unittest.TestCase):
    """引擎接线：设置页 timeoutMs 改变后，实际请求的读超时随之变化。"""

    def test_engine_read_timeout_follows_timeout_ms(self) -> None:
        engine_30s = OpencodeEngine(timeout_ms=30000, model_config={})
        engine_120s = OpencodeEngine(timeout_ms=120000, model_config={})
        self.assertEqual(engine_30s.timeout.read, 30.0)
        self.assertEqual(engine_120s.timeout.read, 120.0)
        self.assertGreater(engine_120s.timeout.read, engine_30s.timeout.read)

    def test_engine_read_timeout_falls_back_to_env_when_timeout_ms_missing(self) -> None:
        with patch.object(settings, "opencode_timeout_sec", 77.0):
            engine = OpencodeEngine(model_config={})
        self.assertEqual(engine.timeout.read, 77.0)

    def test_engine_idle_timeout_uses_shared_derivation(self) -> None:
        engine = OpencodeEngine(timeout_ms=30000, model_config={})
        with patch.object(settings, "opencode_timeout_sec", 1800.0):
            self.assertEqual(engine._session_polling_idle_timeout(), 900.0)
        with patch.object(settings, "opencode_timeout_sec", 60.0):
            self.assertEqual(engine._session_polling_idle_timeout(), 120.0)


class HealthTimeoutDisplayTests(unittest.TestCase):
    """harness-07 改造方案 §3：健康检查展示「当前生效超时」。"""

    def test_check_opencode_reports_effective_timeouts(self) -> None:
        base_item = {
            "id": "svc-opencode",
            "name": "OpenCode 服务",
            "status": "online",
            "latency": "1ms",
            "uptime": "-",
            "detail": "HTTP 200",
        }
        llm_config = {
            "enabled": True,
            "baseUrl": "https://llm.example.com/v1",
            "modelId": "demo-model",
            "timeoutMs": 45000,
        }
        with (
            patch.object(
                system_settings_service, "get_model_secret_config", new=AsyncMock(return_value=llm_config)
            ),
            patch.object(
                system_settings_service, "_check_http", new=AsyncMock(return_value=dict(base_item))
            ),
            patch.object(
                system_settings_service, "_opencode_config_warning", new=AsyncMock(return_value="")
            ),
            patch.object(settings, "opencode_timeout_sec", 1800.0),
        ):
            item = asyncio.run(system_settings_service._check_opencode())

        self.assertEqual(item["effectiveTimeouts"]["readSec"], 45.0)
        self.assertEqual(item["effectiveTimeouts"]["idleSec"], 900.0)
        self.assertEqual(item["effectiveTimeouts"]["runReadSec"], 960.0)
        self.assertIn("当前生效超时", item["detail"])
        self.assertIn("read 45s", item["detail"])

    def test_check_opencode_effective_timeouts_fall_back_to_env(self) -> None:
        base_item = {
            "id": "svc-opencode",
            "name": "OpenCode 服务",
            "status": "online",
            "latency": "1ms",
            "uptime": "-",
            "detail": "HTTP 200",
        }
        with (
            patch.object(
                system_settings_service, "get_model_secret_config", new=AsyncMock(return_value={})
            ),
            patch.object(
                system_settings_service, "_check_http", new=AsyncMock(return_value=dict(base_item))
            ),
            patch.object(
                system_settings_service, "_opencode_config_warning", new=AsyncMock(return_value="")
            ),
            patch.object(settings, "opencode_timeout_sec", 240.0),
        ):
            item = asyncio.run(system_settings_service._check_opencode())

        self.assertEqual(item["effectiveTimeouts"]["readSec"], 240.0)
        self.assertEqual(item["effectiveTimeouts"]["idleSec"], 240.0)
        self.assertEqual(item["effectiveTimeouts"]["runReadSec"], 300.0)


if __name__ == "__main__":
    unittest.main()
