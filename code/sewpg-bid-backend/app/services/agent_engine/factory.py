"""AgentEngine 工厂：按 `AGENT_ENGINE` 环境变量实例化引擎（改造方案 §2）。

配置分层遵守根 AGENTS.md：代码默认值本地安全，恒为 `opencode`；
5090 若要切引擎只写 `docker-compose.5090.yml`，不回流改默认值。
codex 由 engine-07（C1）落地；pi 由 engine-08（C2）落地。
engine-09（C3）：S1 分片链路经本工厂取引擎，`AGENT_ENGINE=codex|pi` 可切换。
"""
from __future__ import annotations

import os
from typing import Any

from app.services.agent_engine.base import AgentEngine
from app.services.agent_engine.codex_engine import CodexEngine
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.agent_engine.pi_engine import PiEngine

AGENT_ENGINE_ENV_VAR = "AGENT_ENGINE"
DEFAULT_AGENT_ENGINE = "opencode"


class AgentEngineFactory:
    """按 `AGENT_ENGINE=opencode|codex|pi` 创建引擎实例（对照 Harbor AgentFactory）。"""

    @staticmethod
    def create(
        *,
        model_config: dict[str, Any] | None = None,
        request_slots: Any | None = None,
    ) -> AgentEngine:
        """创建引擎实例。

        - `model_config`：opencode 专属（系统设置的 LLM 配置）；codex/pi 的
          provider/model 由各自 CLI 配置与环境变量决定（engine-07/08 已记录的
          降级），传入即忽略。
        - `request_slots`：并发预算派生池，三引擎构造均支持（B4）。
        """
        name = (
            os.getenv(AGENT_ENGINE_ENV_VAR, DEFAULT_AGENT_ENGINE).strip().lower()
            or DEFAULT_AGENT_ENGINE
        )
        slots_kwargs = {} if request_slots is None else {"request_slots": request_slots}
        if name == DEFAULT_AGENT_ENGINE:
            config_kwargs = {} if model_config is None else {"model_config": model_config}
            return OpencodeEngine(**config_kwargs, **slots_kwargs)
        if name == "codex":
            return CodexEngine(**slots_kwargs)
        if name == "pi":
            return PiEngine(**slots_kwargs)
        raise ValueError(f"未知 AGENT_ENGINE 取值：{name}（可选：opencode/codex/pi）。")
