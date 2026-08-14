"""PiEngine：Pi（pi-mono / pi-coding-agent）stdio RPC 引擎（改造方案 §4.3，波次 C2）。

会话模型：**一个 session = 一个 `pi --mode rpc` 常驻进程**（Pi RPC 单进程只承载
一个会话，多会话 = 多进程）。引擎持有显式进程表，`abort_session` /
`delete_session` / `run_session` 终态路径（提前收割、取消、idle 超时、运行出错）
都会把进程回收（先 RPC `abort` 再 kill + reap），不留孤儿。进程池上限已并入
全局并发预算（B4/engine-06，方案 §7）：`create_session` spawn 前从
`AGENT_CONCURRENCY_BUDGET` 派生池取许可，`_terminate_session` 回收时释放。

协议依据（事件协议版本显式记录，升级 Pi 前必须核对）：
`PI_RPC_PROTOCOL` 指向 pi-mono 仓库 `packages/coding-agent/docs/rpc.md` 的
2026-08-13 快照。要点：

- 启动：`pi --mode rpc [--no-extensions] [--provider P] [--model M] [--no-session]`
  （engine-09 PoC 按 pi 0.73.1 实测校准：快照里的 `-n title` 是非法选项，已移除；
  headless 默认 `--no-extensions`，坏扩展会在 RPC 启动时杀掉进程）。
- 传输：stdin/stdout 严格 JSONL（LF 分隔，容忍行尾 ``\\r``）；命令可带 `id`，
  响应 `{"type":"response","command":...,"success":bool,"data":...,"error":...}`
  回带同一 `id`。
- 命令：`prompt` / `abort` / `get_state` / `get_messages` / `set_model`。
- 事件：`message_update`（text/thinking delta）、`message_end`、
  `tool_execution_start|update|end`（bash 工具完成事件映射来源）、
  `agent_end`（运行终态，载荷只有 `messages`，无 `willRetry` 字段；
  官方 AgentEvent 联合类型无 `agent_settled`）、`auto_retry_end`（最终失败）。
- 扩展 UI 对话请求（`extension_ui_request`）在 headless 下自动回 `cancelled`，
  避免 agent 侧无限等待。

周边监管（idle 超时 / heartbeat / 进度增量 / cancel_check）复用
`agent_engine/monitor.py` 的 `SessionMonitor`（方案 §5 公共监管器，与
opencode/codex 同源）；本类只保留 RPC 收发、事件折叠与进程生命周期。

已知降级（显式记录，PoC 时复核）：
- `tools` 按请求开关：Pi RPC 无对应命令，`run_session` 收到非 None 直接 ValueError。
- 按请求切 provider/model：降级为 run 前发 `set_model`（会话级生效）。
- 会话绑定创建它的事件循环（asyncio 子进程流的循环亲和性），不支持跨循环复用。
- `--no-session` 默认不落盘，`delete_session` 无需清理会话文件。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from app.services.agent_engine.base import EngineRunResult, ToolCompletedEvent
from app.services.agent_engine.concurrency import AGENT_CONCURRENCY_BUDGET
from app.services.agent_engine.monitor import SessionMonitor
from app.services.bid_parse_cancel import ParseCancelledError

logger = logging.getLogger(__name__)

# 进程池上限 = 全局并发预算（B4）：常驻 RPC 进程与 opencode 请求槽 / S1 分片 /
# 目录章节共享同一总量，一个许可 = 一个并发会话进程。
_PI_PROCESS_SLOTS = AGENT_CONCURRENCY_BUDGET.derive()

# 事件协议版本（显式记录）：pi-mono packages/coding-agent/docs/rpc.md，2026-08-13 快照。
# 升级 Pi 二进制前核对该文档的事件/命令 schema 是否漂移。
PI_RPC_PROTOCOL = "pi-mono rpc.md @ 2026-08-13"

PI_PROGRESS_HEARTBEAT_SECONDS = 10.0
PI_RPC_COMMAND_TIMEOUT_SECONDS = 10.0
PI_ABORT_TIMEOUT_SECONDS = 5.0
PI_PROCESS_STOP_TIMEOUT_SECONDS = 10.0
PI_DEFAULT_IDLE_TIMEOUT_SECONDS = 300.0
_RUN_POLL_MAX_SECONDS = 0.5

# 会话事件缓冲上限（engine-08 P3-2）：`session.events` 此前只增不减，长寿命多轮
# 会话会无限涨内存。保留尾部 N 条（与 codex_engine stderr 有界尾部同思路），
# run 游标按绝对序号计数，抗前部修剪；list_messages 走 RPC get_messages，不受影响。
PI_SESSION_EVENT_BUFFER_MAX = 2000

# stdout 行缓冲上限：asyncio 子进程流默认 64KiB，而 `tool_execution_end`/`message_end`
# 单条 JSONL 携带 bash 工具完整 stdout——finalize 命令的完整 stdout 恰是提前收割载荷，
# 超限会让 readline 抛 ValueError。显式放大到 8MiB（PoC 用大输出用例复核）。
PI_RPC_STREAM_LIMIT_BYTES = 8 * 1024 * 1024

# headless 下会阻塞 agent 的扩展 UI 对话方法（自动回 cancelled）。
_DIALOG_UI_METHODS = frozenset({"select", "confirm", "input", "editor"})

PI_COMMAND_ENV_VAR = "PI_COMMAND"
PI_PROVIDER_ENV_VAR = "PI_PROVIDER_ID"
PI_MODEL_ENV_VAR = "PI_MODEL_ID"
PI_IDLE_TIMEOUT_ENV_VAR = "PI_IDLE_TIMEOUT_SEC"
PI_NO_EXTENSIONS_ENV_VAR = "PI_NO_EXTENSIONS"


@dataclass
class _PiSession:
    """进程表条目：一个 session 的全部运行态。"""

    session_id: str
    process: Any  # asyncio.Process（测试为同形 fake）
    provider_id: str
    model_id: str
    reader_task: asyncio.Task[None] | None = None
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    events_trimmed: int = 0  # 前部累计修剪条数；事件绝对序号 = events_trimmed + 下标
    new_event: asyncio.Event = field(default_factory=asyncio.Event)
    terminating: bool = False
    exit_status: int | None = None


class _RunState:
    """一次 run_session 的事件折叠状态（进度增量 / 提前收割共用）。"""

    def __init__(self) -> None:
        self.parts: list[dict[str, Any]] = []
        self.tool_outputs: list[ToolCompletedEvent] = []
        self.reply_text: str = ""
        self.settled = False
        self.harvested: ToolCompletedEvent | None = None
        self.error: RuntimeError | None = None
        self._text_part: dict[str, Any] | None = None
        self._reasoning_part: dict[str, Any] | None = None
        self._tool_parts: dict[str, dict[str, Any]] = {}
        self._tool_args: dict[str, dict[str, Any]] = {}

    def signature(self) -> tuple[tuple[str, str], ...]:
        items = []
        for part in self.parts:
            if part.get("type") == "tool":
                state = part.get("state") or {}
                items.append(("tool", f"{state.get('status')}:{state.get('output') or ''}"))
            else:
                items.append((str(part.get("type") or ""), str(part.get("text") or part.get("reasoning") or "")))
        return tuple(items)


class PiEngine:
    """Pi stdio RPC 引擎：进程表 + JSONL RPC + 事件流折叠（实现 `AgentEngine` 协议）。"""

    engine_name = "pi"  # AgentEngine 协议属性（§3）

    def __init__(
        self,
        *,
        pi_command: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        idle_timeout_sec: float | None = None,
        heartbeat_interval_sec: float = PI_PROGRESS_HEARTBEAT_SECONDS,
        rpc_timeout_sec: float = PI_RPC_COMMAND_TIMEOUT_SECONDS,
        request_slots: Any | None = None,
        disable_extensions: bool | None = None,
    ) -> None:
        self.pi_command = (
            pi_command or os.getenv(PI_COMMAND_ENV_VAR, "").strip() or "pi"
        )
        if disable_extensions is None:
            disable_extensions = os.getenv(PI_NO_EXTENSIONS_ENV_VAR, "1").strip() not in {"0", "false", "no"}
        self.disable_extensions = disable_extensions
        self.provider_id = (
            provider_id if provider_id is not None else os.getenv(PI_PROVIDER_ENV_VAR, "").strip()
        )
        self.model_id = model_id if model_id is not None else os.getenv(PI_MODEL_ENV_VAR, "").strip()
        if idle_timeout_sec is None:
            idle_timeout_sec = float(os.getenv(PI_IDLE_TIMEOUT_ENV_VAR, "") or PI_DEFAULT_IDLE_TIMEOUT_SECONDS)
        self.idle_timeout = max(1.0, float(idle_timeout_sec))
        self.heartbeat_interval = max(0.05, float(heartbeat_interval_sec))
        self.rpc_timeout = max(0.1, float(rpc_timeout_sec))
        self._sessions: dict[str, _PiSession] = {}
        self._request_seq = itertools.count(1)
        self._request_slots = (
            request_slots if request_slots is not None else _PI_PROCESS_SLOTS
        )

    # ------------------------------------------------------------------
    # AgentEngine 协议
    # ------------------------------------------------------------------
    async def create_session(self, title: str) -> str:
        # 命令拼法校准（engine-09 PoC，pi 0.73.1 实测）：rpc.md 快照里的 `-n title`
        # 在真实 CLI 是非法选项（进程直接退出、握手失败）；`--no-session` 不落盘，
        # title 本无持久化意义，仅留引擎日志。用户环境坏扩展会在 RPC 启动时炸掉
        # 进程，headless 场景默认 `--no-extensions`（PI_NO_EXTENSIONS=0 可关）。
        argv = [self.pi_command, "--mode", "rpc", "--no-session"]
        if self.disable_extensions:
            argv.append("--no-extensions")
        if self.provider_id:
            argv += ["--provider", self.provider_id]
        if self.model_id:
            argv += ["--model", self.model_id]
        logger.info("pi rpc session 启动（title=%s）：%s", str(title or ""), argv)
        # 进程池上限 = 全局并发预算（B4）：许可从 spawn 前持到 _terminate_session
        # 回收；非阻塞轮询，取消落在等待窗口时不持有许可（同 OpencodeEngine._request_slot）。
        while not self._request_slots.acquire(blocking=False):
            await asyncio.sleep(0.1)
        try:
            process = await self._spawn_process(argv)
        except OSError as exc:
            self._request_slots.release()
            raise RuntimeError(f"Pi RPC 进程启动失败（{self.pi_command}）：{exc}") from exc
        except BaseException:
            # 含 CancelledError：spawn 窗口被取消同样要归还许可（review P2-1 同类路径）。
            self._request_slots.release()
            raise
        session_id = f"pi-{uuid.uuid4().hex[:12]}"
        session = _PiSession(
            session_id=session_id,
            process=process,
            provider_id=self.provider_id,
            model_id=self.model_id,
        )
        self._sessions[session_id] = session
        session.reader_task = asyncio.create_task(
            self._reader_pump(session), name=f"pi-rpc-reader-{session_id}"
        )
        try:
            # 握手：确认对端确实讲 RPC 协议（二进制缺失/模式错误在此 fail-fast）。
            await self._rpc(session, {"type": "get_state"}, timeout=self.rpc_timeout)
        except BaseException as exc:
            # 含 CancelledError（BaseException，review P2-1）：握手窗口被取消时
            # session_id 尚未返回调用方、无人兜底，不回收 = 进程 + 预算许可双泄漏。
            await self._terminate_session(session_id)
            if isinstance(exc, RuntimeError):
                raise RuntimeError(f"Pi RPC 握手失败：{exc}") from exc
            raise
        return session_id

    async def run_session(
        self,
        session_id: str,
        prompt_text: str,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        tools: dict[str, bool] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> EngineRunResult:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"未知 Pi session：{session_id}")
        if tools is not None:
            # Pi RPC 无按请求工具开关（rpc.md 无对应命令）；显式失败而非静默忽略。
            raise ValueError("Pi RPC 不支持按请求工具开关（tools 参数）。")
        try:
            if (provider_id or model_id) and (
                (provider_id or session.provider_id) != session.provider_id
                or (model_id or session.model_id) != session.model_id
            ):
                await self._rpc(
                    session,
                    {
                        "type": "set_model",
                        "provider": provider_id or session.provider_id,
                        "modelId": model_id or session.model_id,
                    },
                )
                session.provider_id = provider_id or session.provider_id
                session.model_id = model_id or session.model_id

            state = _RunState()
            # 绝对序号游标：事件缓冲有界（前部修剪会推移下标），按
            # events_trimmed + 下标 计数才不被修剪打乱。
            cursor = session.events_trimmed + len(session.events)
            # 监管时钟（idle/心跳/进度活动）复用 SessionMonitor（方案 §5）。
            monitor = SessionMonitor(
                idle_timeout=self.idle_timeout,
                heartbeat_interval=self.heartbeat_interval,
            )
            last_signature: tuple[tuple[str, str], ...] | None = None

            # prompt 被接受后事件流异步推进；success=false = 拒绝（未接受）。
            await self._rpc(session, {"type": "prompt", "message": prompt_text})

            while True:
                if cursor < session.events_trimmed:
                    # 极端溢出：未消费事件已被修剪丢弃，跳到现存最旧一条继续。
                    logger.warning(
                        "pi session %s 事件缓冲溢出，丢弃 %d 条未消费事件。",
                        session_id,
                        session.events_trimmed - cursor,
                    )
                    cursor = session.events_trimmed
                index = cursor - session.events_trimmed
                while index < len(session.events):
                    event = session.events[index]
                    cursor += 1
                    index += 1
                    monitor.note_event()
                    self._handle_event(session, event, state, on_tool_completed)
                if state.error is not None:
                    await self._terminate_session(session_id)
                    raise state.error
                if state.harvested is not None:
                    reply = state.harvested.stdout
                    await self._terminate_session(session_id)
                    if stream_callback is not None:
                        stream_callback(
                            self._stream_payload(
                                session,
                                state,
                                status="received",
                                elapsed_seconds=monitor.elapsed_seconds(),
                                extra={"earlyCompletion": True},
                            )
                        )
                    return EngineRunResult(
                        session_id=session_id,
                        reply_text=reply,
                        tool_outputs=state.tool_outputs,
                        trace=self._build_trace(session, state, monitor.started_at, early_completion=True),
                    )
                if state.settled:
                    if stream_callback is not None:
                        signature = state.signature()
                        if signature != last_signature:
                            stream_callback(
                                self._stream_payload(
                                    session, state, elapsed_seconds=monitor.elapsed_seconds()
                                )
                            )
                    return EngineRunResult(
                        session_id=session_id,
                        reply_text=state.reply_text,
                        tool_outputs=state.tool_outputs,
                        trace=self._build_trace(session, state, monitor.started_at, early_completion=False),
                    )
                if SessionMonitor.should_cancel(cancel_check):
                    await self._terminate_session(session_id)
                    raise ParseCancelledError("解析已取消。")

                if stream_callback is not None:
                    signature = state.signature()
                    if signature != last_signature:
                        last_signature = signature
                        monitor.note_progress()
                        stream_callback(
                            self._stream_payload(session, state, elapsed_seconds=monitor.elapsed_seconds())
                        )
                    elif monitor.heartbeat_due():
                        heartbeat_index = monitor.take_heartbeat()
                        stream_callback(
                            self._stream_payload(
                                session,
                                state,
                                elapsed_seconds=monitor.elapsed_seconds(),
                                extra={
                                    "heartbeat": True,
                                    "heartbeatIndex": heartbeat_index,
                                    "idleSeconds": max(1, int(monitor.idle_seconds())),
                                },
                            )
                        )
                if monitor.is_idle_timeout():
                    await self._terminate_session(session_id)
                    raise RuntimeError(
                        f"pi idle timeout after {int(self.idle_timeout)} seconds without new events; "
                        f"check session {session_id} tool calls."
                    )

                # 等待粒度跟随最近的监管 deadline（心跳/idle），保证超时精度。
                wait_seconds = min(
                    _RUN_POLL_MAX_SECONDS,
                    max(0.05, monitor.idle_remaining()),
                    max(0.05, monitor.heartbeat_remaining())
                    if stream_callback is not None
                    else _RUN_POLL_MAX_SECONDS,
                )
                with suppress(TimeoutError):
                    await asyncio.wait_for(session.new_event.wait(), timeout=wait_seconds)
                session.new_event.clear()
        except asyncio.CancelledError:
            # 外部任务取消（review P2-1 同类路径）：回收进程 + 归还预算许可。
            # _terminate_session 幂等，内部终态路径已回收时此处为 no-op。
            await self._terminate_session(session_id)
            raise

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        session = self._sessions.get(session_id)
        if session is None:
            return []
        try:
            data = await self._rpc(session, {"type": "get_messages"})
        except RuntimeError:
            return []
        messages = (data or {}).get("messages") if isinstance(data, dict) else None
        if isinstance(messages, list):
            return [item for item in messages if isinstance(item, dict)]
        return []

    async def abort_session(self, session_id: str) -> bool:
        """abort = 终态：先发 RPC `abort` 再回收进程（会话模型为一次 run 一个进程）。"""
        return await self._terminate_session(session_id)

    async def delete_session(self, session_id: str) -> None:
        await self._terminate_session(session_id)

    # ------------------------------------------------------------------
    # 进程生命周期（显式进程表 + 终态清理）
    # ------------------------------------------------------------------
    async def _spawn_process(self, argv: list[str]) -> Any:
        """拆出便于测试注入 fake 子进程（本机无 Pi 二进制）。"""
        return await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,  # 不混入 stdout 的 JSONL；退出码经 returncode 观察
            limit=PI_RPC_STREAM_LIMIT_BYTES,  # 默认 64KiB 装不下工具完整 stdout（收割载荷）
        )

    async def _terminate_session(self, session_id: str) -> bool:
        """回收会话进程：RPC abort（尽力）→ kill → reap → 关 reader → 归还预算许可。幂等。"""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.terminating = True
        try:
            process = session.process
            if process.returncode is None and session.exit_status is None:
                try:
                    await self._rpc(session, {"type": "abort"}, timeout=PI_ABORT_TIMEOUT_SECONDS)
                except Exception as exc:  # abort 失败不阻断回收
                    logger.warning("pi session %s RPC abort 失败，直接 kill：%s", session_id, exc)
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:  # pragma: no cover - 进程已退出
                    pass
            with suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(process.wait()), PI_PROCESS_STOP_TIMEOUT_SECONDS)
            if process.returncode is None:  # pragma: no cover - kill 未生效的兜底告警
                logger.warning("pi session %s 进程在 kill 后未退出。", session_id)
            reader = session.reader_task
            if reader is not None and not reader.done():
                reader.cancel()
                with suppress(asyncio.CancelledError):
                    await reader
            return True
        finally:
            self._request_slots.release()  # 进程许可与进程同生死；pop 保证只归还一次

    # ------------------------------------------------------------------
    # RPC 收发（JSONL，id 关联）
    # ------------------------------------------------------------------
    async def _rpc(
        self, session: _PiSession, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        request_id = f"{session.session_id}:{next(self._request_seq)}"
        command = str(payload.get("type") or "")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        session.pending[request_id] = future
        try:
            line = (json.dumps({**payload, "id": request_id}, ensure_ascii=False) + "\n").encode("utf-8")
            session.process.stdin.write(line)
            await session.process.stdin.drain()
        except Exception as exc:
            session.pending.pop(request_id, None)
            raise RuntimeError(f"Pi RPC 命令 {command} 写入失败（进程可能已退出）：{exc}") from exc
        try:
            response = await asyncio.wait_for(future, timeout or self.rpc_timeout)
        except TimeoutError as exc:
            raise RuntimeError(f"Pi RPC 命令 {command} 响应超时。") from exc
        finally:
            session.pending.pop(request_id, None)
        if not response.get("success"):
            raise RuntimeError(f"Pi RPC 命令 {command} 失败：{response.get('error') or 'unknown error'}")
        return response.get("data")

    async def _reader_pump(self, session: _PiSession) -> None:
        """读 stdout JSONL：response 路由给等待方，事件进会话缓冲，UI 对话自动取消。"""
        process = session.process
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace")
                if text.endswith("\n"):
                    text = text[:-1]
                if text.endswith("\r"):
                    text = text[:-1]
                if not text.strip():
                    continue
                try:
                    record = json.loads(text)
                except ValueError:
                    logger.warning("pi rpc 忽略非 JSON 行：%.200s", text)
                    continue
                self._dispatch_record(session, record)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pi session %s reader 异常退出。", session.session_id)
        finally:
            session.exit_status = process.returncode
            for pending in session.pending.values():
                if not pending.done():
                    pending.set_exception(RuntimeError("Pi RPC 进程已退出，命令无响应。"))
            session.pending.clear()
            # 唤醒 run 循环：进程退出对未 settled 的运行是错误，对已 terminating 的是正常收尾。
            self._append_event(
                session,
                {"type": "_process_exit", "returncode": process.returncode, "terminating": session.terminating},
            )

    @staticmethod
    def _append_event(session: _PiSession, record: dict[str, Any]) -> None:
        """事件入会话缓冲（有界：只留尾部，engine-08 P3-2）并唤醒等待方。"""
        session.events.append(record)
        # 滞后修剪：超 2 倍上限才截到上限，摊销切片成本。
        if len(session.events) > PI_SESSION_EVENT_BUFFER_MAX * 2:
            overflow = len(session.events) - PI_SESSION_EVENT_BUFFER_MAX
            del session.events[:overflow]
            session.events_trimmed += overflow
        session.new_event.set()

    def _dispatch_record(self, session: _PiSession, record: dict[str, Any]) -> None:
        record_type = str(record.get("type") or "")
        if record_type == "response" and str(record.get("id") or "") in session.pending:
            future = session.pending[str(record["id"])]
            if not future.done():
                future.set_result(record)
            return
        if record_type == "extension_ui_request" and str(record.get("method") or "") in _DIALOG_UI_METHODS:
            # headless：对话类 UI 请求自动取消，避免 agent 侧无限阻塞。
            try:
                session.process.stdin.write(
                    (json.dumps(
                        {"type": "extension_ui_response", "id": record.get("id"), "cancelled": True}
                    ) + "\n").encode("utf-8")
                )
            except Exception:
                logger.warning("pi session %s 回写 extension_ui_response 失败。", session.session_id)
            return
        self._append_event(session, record)

    # ------------------------------------------------------------------
    # 事件折叠（message/tool 事件 → 进度增量 / ToolCompletedEvent / 终态）
    # ------------------------------------------------------------------
    def _handle_event(
        self,
        session: _PiSession,
        event: dict[str, Any],
        state: _RunState,
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None,
    ) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "_process_exit":
            if state.settled or state.harvested is not None:
                return
            if event.get("terminating"):
                # 本循环的终态路径都在返回/抛错前才回收进程；运行中收到 terminating
                # 退出事件 = 外部 abort/delete。主动打断等待（engine-08 P3-1），
                # 不再干等 idle 超时。与 cancel_check 同为取消语义。
                state.error = ParseCancelledError(
                    f"Pi 会话已被外部中止（session {session.session_id}）。"
                )
                return
            state.error = RuntimeError(
                f"Pi RPC 进程意外退出（session {session.session_id}，"
                f"returncode={event.get('returncode')}）。"
            )
            return
        if event_type == "message_update":
            delta = event.get("assistantMessageEvent") or {}
            delta_type = str(delta.get("type") or "")
            if delta_type == "text_delta":
                if state._text_part is None:
                    state._text_part = {"type": "text", "text": ""}
                    state.parts.append(state._text_part)
                state._text_part["text"] += str(delta.get("delta") or "")
            elif delta_type == "thinking_delta":
                if state._reasoning_part is None:
                    state._reasoning_part = {"type": "reasoning", "reasoning": ""}
                    state.parts.append(state._reasoning_part)
                state._reasoning_part["reasoning"] += str(delta.get("delta") or "")
            return
        if event_type == "message_end":
            message = event.get("message") if isinstance(event.get("message"), dict) else {}
            state._text_part = None
            state._reasoning_part = None
            if str(message.get("role") or "") != "assistant":
                return
            text = self._extract_message_text(message)
            if text:
                state.reply_text = text
            if str(message.get("stopReason") or "") == "error":
                detail = str(message.get("errorMessage") or "").strip() or "stopReason=error"
                state.error = RuntimeError(f"Pi 会话出错（session {session.session_id}）：{detail}")
            return
        if event_type == "tool_execution_start":
            tool_call_id = str(event.get("toolCallId") or "")
            args = event.get("args") if isinstance(event.get("args"), dict) else {}
            state._tool_args[tool_call_id] = args
            part = {
                "type": "tool",
                "tool": str(event.get("toolName") or ""),
                "id": tool_call_id,
                "state": {"status": "running", "input": args, "output": ""},
            }
            state._tool_parts[tool_call_id] = part
            state.parts.append(part)
            return
        if event_type == "tool_execution_update":
            part = state._tool_parts.get(str(event.get("toolCallId") or ""))
            if part is not None:
                part["state"]["output"] = self._extract_result_text(event.get("partialResult"))
            return
        if event_type == "tool_execution_end":
            tool_call_id = str(event.get("toolCallId") or "")
            tool_name = str(event.get("toolName") or "")
            is_error = bool(event.get("isError"))
            output = self._extract_result_text(event.get("result"))
            part = state._tool_parts.get(tool_call_id)
            if part is not None:
                part["state"]["status"] = "error" if is_error else "completed"
                part["state"]["output"] = output
            if tool_name != "bash" or is_error:
                return
            args = state._tool_args.get(tool_call_id) or {}
            command = str(args.get("command") or "").strip()
            completed = ToolCompletedEvent(
                command=command,
                stdout=output.strip(),
                event_id=f"{session.session_id}:{tool_call_id}:{command}",
            )
            state.tool_outputs.append(completed)
            if on_tool_completed is not None and on_tool_completed(completed):
                # 回调可改写 stdout（终态校验产物）；收割以事件当前 stdout 为准。
                state.harvested = completed
            return
        if event_type == "agent_settled":
            # 防御分支：官方 AgentEvent 联合类型无此事件（2026-08-13 快照），
            # 真实协议下不会触发；保留以兼容未来/分叉版本可能的 settled 事件。
            state.settled = True
            return
        if event_type == "agent_end" and not event.get("willRetry"):
            # 运行终态以 agent_end 为准；官方载荷无 willRetry 字段（willRetry 在
            # compaction_end 上），`not event.get("willRetry")` 在真实协议下恒真，
            # 判断保留为防御写法。
            state.settled = True
            return
        if event_type == "auto_retry_end" and not event.get("success"):
            state.error = RuntimeError(
                f"Pi 自动重试耗尽（session {session.session_id}）："
                f"{event.get('finalError') or 'unknown error'}"
            )
            return
        if event_type == "extension_error":
            logger.warning("pi session %s 扩展错误：%s", session.session_id, event.get("error"))

    @staticmethod
    def _extract_message_text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        texts = [
            str(block.get("text") or "").strip()
            for block in content or []
            if isinstance(block, dict) and str(block.get("type") or "") == "text"
        ]
        return "\n".join(text for text in texts if text).strip()

    @staticmethod
    def _extract_result_text(result: Any) -> str:
        if not isinstance(result, dict):
            return ""
        texts = [
            str(block.get("text") or "")
            for block in result.get("content") or []
            if isinstance(block, dict) and str(block.get("type") or "") == "text"
        ]
        return "".join(texts).strip()

    # ------------------------------------------------------------------
    # 留痕 / 流式回执（对齐 opencode_engine 的 payload 形态）
    # ------------------------------------------------------------------
    @staticmethod
    def _received_at() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _stream_payload(
        self,
        session: _PiSession,
        state: _RunState,
        *,
        status: str = "streaming",
        elapsed_seconds: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status if state.parts else "waiting",
            "sessionId": session.session_id,
            "providerId": session.provider_id,
            "modelId": session.model_id,
            "receivedAt": self._received_at(),
            "parts": [dict(part) for part in state.parts],
        }
        if elapsed_seconds is not None:
            payload["elapsedSeconds"] = max(0, int(elapsed_seconds))
        if extra:
            payload.update(extra)
        return payload

    def _build_trace(
        self, session: _PiSession, state: _RunState, started_at: float, *, early_completion: bool
    ) -> dict[str, Any]:
        return {
            "engine": self.engine_name,
            "protocol": PI_RPC_PROTOCOL,
            "sessionId": session.session_id,
            "providerId": session.provider_id,
            "modelId": session.model_id,
            "parts": [dict(part) for part in state.parts],
            "toolCalls": len(state.tool_outputs),
            "elapsedSeconds": max(0, int(time.monotonic() - started_at)),
            "earlyCompletion": early_completion,
        }
