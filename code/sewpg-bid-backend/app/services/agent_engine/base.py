"""AgentEngine 协议与公共类型（改造方案 §3）。

B1（engine-03）起协议为 §3 的 async 目标形态；`OpencodeEngine` 内部为
`httpx.AsyncClient` + asyncio task 轮询（每会话 daemon 线程已消除）。
同步调用方经项目既有桥接 `app.services.file_utils.run_awaitable_sync` 进入。

A1（engine-02）落地 on_tool_completed 语义：引擎只检测「一个 bash 工具完成」并上报
ToolCompletedEvent；是否提前收割由业务回调判定。该回调经
EarlyCompletionPlan 注入 `_send_prompt_with_session_polling(early_completion=...)`。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol


@dataclass
class ToolCompletedEvent:
    """引擎检测到「一个 bash 工具完成」时上报的事件。

    引擎只负责上报，不判断业务语义；`is_terminal` 由业务判定后回填。
    业务回调可以改写 `stdout`（如换成终态校验产物或 manifest 合成结果），
    引擎收割时以事件当前的 `stdout` 为准。
    """

    command: str  # 受控命令名，如 "s1parse-finalize"
    stdout: str  # 命令完整 stdout
    is_terminal: bool = False
    event_id: str = ""  # 引擎分配的稳定性标识（message:part:command），供业务按次去重


@dataclass
class EngineRunResult:
    """一次会话运行的引擎侧结果。"""

    session_id: str
    reply_text: str
    tool_outputs: list[ToolCompletedEvent] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)  # opencodeOutput 等价物，供前端留痕


@dataclass
class EarlyCompletionPlan:
    """一次轮询会话的提前完成计划（A1）：业务差异点全部以回调/参数注入。

    引擎轮询循环不识任何业务命令；它只做通用监管（idle 超时、心跳、取消、
    「bash 工具完成」事件上报），以下字段决定提前收割与停滞报错的全部差异：

    - `tool_completed_factory`：每个相位（prompt 在飞 / prompt 返回后等待）各取一个
      `on_tool_completed(event) -> bool` 回调；返回 True = 提前收割。
    - `produce_payload`：收割产物，默认取 `event.stdout`（s2 终态校验路径会先停会话
      再跑 validator 产出，保持原「停 → 校验」顺序）。
    - `on_assistant_stopped`：assistant 自然停止时的产物回调（s2 终态校验）。
    - `on_idle_stalled`：idle 超时的业务 stall 报错；None = 引擎抛通用超时。
    """

    display_label: str = ""  # heartbeat earlyToolCommand 标签 / 兜底 completionSource
    tool_completed_factory: Callable[[], Callable[[ToolCompletedEvent], bool]] | None = None
    produce_payload: Callable[[ToolCompletedEvent], str] | None = None
    stop_on_early_complete: bool = False
    stop_label: str = ""  # 收割后停会话失败时的报错前缀
    completion_source: str = ""
    completion_trace_text: str = ""  # in-loop 收割 trace 文案
    include_elapsed_in_loop: bool = False  # in-loop 收割的流式回执是否带 elapsedSeconds
    on_assistant_stopped: Callable[[], str] | None = None
    assistant_stop_trace_text: str = ""
    assistant_stop_completion_source: str = ""
    on_idle_stalled: Callable[[str, list[dict[str, Any]], float], None] | None = None
    wait_after_prompt_return: bool = False  # prompt 返回后继续等命令完成（三条 finalize 链路）
    grace_wait_running_tool: bool = False  # s1：prompt 返回时工具仍在跑的宽限等待
    immediate_trace_text: str = ""  # prompt 返回后即时/宽限收割的 trace 文案
    post_return_trace_text: str = ""  # 收敛等待收割的 trace 文案

    def harvest_payload(self, event: ToolCompletedEvent) -> str:
        if self.produce_payload is not None:
            return self.produce_payload(event)
        return event.stdout


def iter_completed_bash_tool_events(
    messages: list[dict[str, Any]],
) -> Iterable[ToolCompletedEvent]:
    """把会话消息折成「已完成 bash 工具」事件流（新的在前）。

    这是引擎的通用检测能力：只认消息结构（opencode 会话消息 schema），
    不过滤任何业务命令；命令匹配与终态判定由业务回调完成。
    未来 Codex/Pi 引擎把各自事件流映射成同一类型即可复用上层回调。
    """
    for message in reversed(messages):
        info = message.get("info") if isinstance(message.get("info"), dict) else {}
        for part in reversed(message.get("parts") or []):
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            if str(part.get("tool") or "") != "bash":
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            if state.get("status") != "completed":
                continue
            metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
            exit_code = state.get("exit")
            if exit_code is None:
                exit_code = metadata.get("exit")
            if exit_code not in (None, 0):
                continue
            raw_input = state.get("input") if isinstance(state.get("input"), dict) else {}
            command = str(raw_input.get("command") or "").strip()
            stdout = str(state.get("output") or metadata.get("output") or "").strip()
            event_id = f"{info.get('id') or ''}:{part.get('id') or ''}:{command}"
            yield ToolCompletedEvent(command=command, stdout=stdout, event_id=event_id)


class AgentEngine(Protocol):
    """引擎无关的「会话 + 可监管」原语（B1 起为 §3 的 async 目标形态）。"""

    engine_name: str  # "opencode" | "codex" | "pi"

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
        # A1（engine-02）落地：返回 True = 提前收割；经 EarlyCompletionPlan
        # 注入 OpencodeEngine._send_prompt_with_session_polling。
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> EngineRunResult: ...

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    async def abort_session(self, session_id: str) -> bool: ...

    async def delete_session(self, session_id: str) -> None: ...
