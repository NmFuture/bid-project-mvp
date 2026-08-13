"""AgentEngine 协议与公共类型（改造方案 §3）。

A0 起步为同步签名（§7 已拍板：A0 纯改名，不引入并发语义变化），与现状行为一致；
async 化是 engine-03（B1）的事，届时本协议翻成 §3 的 async 目标形态：

    class AgentEngine(Protocol):
        engine_name: str    # "opencode" | "codex" | "pi"

        async def create_session(self, title: str) -> str: ...
        async def run_session(
            self,
            session_id: str,
            prompt_text: str,
            *,
            provider_id: str | None = None,
            model_id: str | None = None,
            tools: dict[str, bool] | None = None,
            stream_callback: Callable[[dict[str, Any]], None] | None = None,
            on_tool_completed: Callable[[ToolCompletedEvent], bool] | None = None,  # 返回 True = 提前收割
            cancel_check: Callable[[], bool] | None = None,
        ) -> EngineRunResult: ...
        async def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...
        async def abort_session(self, session_id: str) -> bool: ...
        async def delete_session(self, session_id: str) -> None: ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ToolCompletedEvent:
    """引擎检测到「一个 bash 工具完成」时上报的事件。

    引擎只负责上报，不判断业务语义；`is_terminal` 由业务判定后回填。
    """

    command: str  # 受控命令名，如 "s1parse-finalize"
    stdout: str  # 命令完整 stdout
    is_terminal: bool = False


@dataclass
class EngineRunResult:
    """一次会话运行的引擎侧结果。"""

    session_id: str
    reply_text: str
    tool_outputs: list[ToolCompletedEvent] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)  # opencodeOutput 等价物，供前端留痕


class AgentEngine(Protocol):
    """引擎无关的「会话 + 可监管」原语（同步起步，async 目标形态见模块 docstring）。"""

    engine_name: str  # "opencode" | "codex" | "pi"

    def create_session(self, title: str) -> str: ...

    def run_session(
        self,
        session_id: str,
        prompt_text: str,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        tools: dict[str, bool] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        # A0 保留现状 early_tool_command 语义（对应 _send_prompt_with_session_polling 的通用形态）；
        # on_tool_completed 事件回调在 engine-02（A1）落地。
        early_tool_command: str = "",
        cancel_check: Callable[[], bool] | None = None,
    ) -> EngineRunResult: ...

    def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    def abort_session(self, session_id: str) -> bool: ...

    def delete_session(self, session_id: str) -> None: ...
