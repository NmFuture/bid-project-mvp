"""AgentEngine 工厂：按 `AGENT_ENGINE` 环境变量实例化引擎（改造方案 §2）。

配置分层遵守根 AGENTS.md：代码默认值本地安全，恒为 `opencode`；
5090 若要切引擎只写 `docker-compose.5090.yml`，不回流改默认值。
codex 由 engine-07（C1）落地；pi 由 engine-08（C2）落地。
"""
from __future__ import annotations

import os

from app.services.agent_engine.base import AgentEngine
from app.services.agent_engine.codex_engine import CodexEngine
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.agent_engine.pi_engine import PiEngine

AGENT_ENGINE_ENV_VAR = "AGENT_ENGINE"
DEFAULT_AGENT_ENGINE = "opencode"


class AgentEngineFactory:
    """按 `AGENT_ENGINE=opencode|codex|pi` 创建引擎实例（对照 Harbor AgentFactory）。"""

    @staticmethod
    def create() -> AgentEngine:
        name = (
            os.getenv(AGENT_ENGINE_ENV_VAR, DEFAULT_AGENT_ENGINE).strip().lower()
            or DEFAULT_AGENT_ENGINE
        )
        if name == DEFAULT_AGENT_ENGINE:
            return OpencodeEngine()
        if name == "codex":
            return CodexEngine()
        if name == "pi":
            return PiEngine()
        raise ValueError(f"未知 AGENT_ENGINE 取值：{name}（可选：opencode/codex/pi）。")
