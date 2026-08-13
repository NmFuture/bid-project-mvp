"""CodexEngine：`codex exec` 子进程 + JSON 事件流引擎（改造方案 §4.2，波次 C1）。

借 Harbor `BaseInstalledAgent` 模式：配置集中为类级映射表（`BASE_FLAGS` /
`CLI_FLAGS` / `ENV_VARS`），错误输出经 `ERROR_PATTERNS` 归类成统一异常。

会话模型：**一个 session ≈ 一个 exec 进程**——每次 `run_session` 起一个
`codex exec ... --json` 子进程（续跑用子命令 `codex exec resume <thread_id>`，
engine-09 PoC 按 0.147.0 实测校准：旧快照的 `--resume <id>` 选项已移除；
resume 无 `--sandbox` 选项，用 `-c sandbox_mode=` 等价注入），`abort` = kill
进程；进程在 run 结束 / abort / delete 后必被回收（`wait()` 收尸）。
进程池上限已并入全局并发预算（B4/engine-06，方案 §7）：`run_session` 从
`AGENT_CONCURRENCY_BUDGET` 派生池取许可，持到进程回收后释放；孤儿回收之外
不再有独立的进程池常量。

provider 降级（方案 §3 注 / §6 风险，显式记录）：Codex 的 provider 由
`~/.codex/config.toml` 的 `model_provider` 表与登录态决定，不是按请求可切换的
运行时参数，故 `run_session(provider_id=...)` 降级为**会话级（引擎实例级）固定**
——传入值与实例配置不一致时记 warning 并忽略。`tools` 开关同理：Codex exec 的
工具面由 sandbox 模式决定（实例级固定），不按请求切换。

事件协议（`codex exec --json` JSONL）：`thread.started`（捕获 thread_id）、
`item.completed`（`command_execution` → ToolCompletedEvent；`assistant_message`
→ 回复文本）、`turn.completed` / `turn.failed` / `error`。新版本的 item 类型键
从 `item_type` 改名 `type`，两者都认；0.147.0 起 assistant 文本 item 类型改名
`agent_message`（engine-09 PoC 实测），与 `assistant_message` 都认。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from app.core.config import settings
from app.services.agent_engine import errors as engine_errors
from app.services.agent_engine.base import (
    EngineRunResult,
    ToolCompletedEvent,
)
from app.services.agent_engine.concurrency import AGENT_CONCURRENCY_BUDGET
from app.services.bid_parse_cancel import ParseCancelledError


logger = logging.getLogger(__name__)

CODEX_PROGRESS_HEARTBEAT_SECONDS = 10.0
CODEX_CANCEL_POLL_SECONDS = 0.5
CODEX_KILL_GRACE_SECONDS = 5.0
CODEX_STDERR_TAIL_CHARS = 8192  # stderr 排干只留尾部，供报错详情
# stdout 行缓冲上限：asyncio 子进程流默认 64KiB，而 item.completed 单条 JSONL 携带
# bash 工具完整 aggregated_output——finalize 大 stdout 恰是提前收割载荷，超限会让
# readline 抛 ValueError。对齐 pi_engine 的 8MiB（engine-08 P2-2 同类修复）。
CODEX_STDOUT_STREAM_LIMIT_BYTES = 8 * 1024 * 1024

# 进程池上限 = 全局并发预算（B4）：一个 session 一个 exec 进程，
# 与 opencode 请求槽 / S1 分片 / 目录章节共享同一总量。
_CODEX_PROCESS_SLOTS = AGENT_CONCURRENCY_BUDGET.derive()


@dataclass
class _CodexSessionState:
    """引擎侧会话台账：codex thread_id、当前进程与 opencode 形态的消息日志。"""

    session_id: str
    title: str
    thread_id: str = ""  # 首次 run 从 thread.started 事件捕获，resume 用
    process: asyncio.subprocess.Process | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)


class CodexEngine:
    """`codex exec` 子进程引擎：实现 `base.AgentEngine` async 协议（§3）。"""

    engine_name = "codex"  # AgentEngine 协议属性（§3）

    # Harbor Codex.CLI_FLAGS 模式：配置 → CLI 参数的集中映射表，
    # 拼命令处不散落 if。取值为空（未配置）的项不产参。
    BASE_FLAGS: tuple[str, ...] = ("--json", "--skip-git-repo-check")
    CLI_FLAGS: tuple[tuple[str, Callable[[str], tuple[str, ...]]], ...] = (
        ("model_id", lambda v: ("--model", v)),
        ("sandbox_mode", lambda v: ("--sandbox", v)),
        ("reasoning_effort", lambda v: ("-c", f"model_reasoning_effort={v}")),
    )
    # 引擎配置 → 子进程环境变量映射（Harbor ENV_VARS）：仅配置非空时注入。
    ENV_VARS: tuple[tuple[str, str], ...] = (
        ("codex_home", "CODEX_HOME"),
    )
    # CLI 错误输出归类（ErrorPattern，对齐 errors.py 归一化风格）：
    # 按序匹配，命中即归类；兜底走 _classify_failure 的通用文案。
    ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\b401\b|unauthorized|invalid api key|authentication", re.I),
         "codex CLI 认证失败：请检查登录态或 API Key。"),
        (re.compile(r"\b429\b|rate.?limit|quota|insufficient (quota|funds|credits)", re.I),
         "codex CLI 触发限流或额度不足，请稍后重试。"),
        (re.compile(r"model[_ ]not[_ ]found|does not exist|unknown model", re.I),
         "codex CLI 模型不存在，请检查 CODEX_MODEL_ID 配置。"),
        (re.compile(r"timed?\s*out|deadline exceeded", re.I),
         "codex CLI 调用超时，请缩短输入或稍后重试。"),
        (re.compile(r"stream (error|disconnected)|connection (reset|refused)|network", re.I),
         "codex CLI 连接中断，请检查网络后重试。"),
    )

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        sandbox_mode: str | None = None,
        codex_home: str | None = None,
        timeout_sec: float | None = None,
        request_slots: Any | None = None,
    ) -> None:
        # 配置默认值走环境变量，本地安全：不装 codex CLI 时引擎仍可实例化，
        # 只有真正 run 时才在 create_subprocess_exec 处报「未安装」。
        self.cli_path = str(cli_path or os.getenv("CODEX_CLI_PATH", "codex")).strip() or "codex"
        self.model_id = str(model_id if model_id is not None else os.getenv("CODEX_MODEL_ID", "")).strip()
        self.reasoning_effort = str(
            reasoning_effort if reasoning_effort is not None else os.getenv("CODEX_REASONING_EFFORT", "")
        ).strip()
        self.sandbox_mode = str(
            sandbox_mode or os.getenv("CODEX_SANDBOX_MODE", "workspace-write")
        ).strip() or "workspace-write"
        self.codex_home = str(codex_home if codex_home is not None else os.getenv("BID_CODEX_HOME", "")).strip()
        # idle 监管口径与 opencode 轮询一致（无新输出即判停滞）。
        self.idle_timeout = max(
            120.0,
            min(float(timeout_sec or settings.opencode_timeout_sec), 900.0),
        )
        self._sessions: dict[str, _CodexSessionState] = {}
        self._request_slots = (
            request_slots if request_slots is not None else _CODEX_PROCESS_SLOTS
        )

    # ------------------------------------------------------------------
    # AgentEngine 协议
    # ------------------------------------------------------------------
    async def create_session(self, title: str) -> str:
        """登记引擎侧会话；codex thread_id 在首次 run 的 thread.started 事件后回填。"""
        session_id = f"codex-{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = _CodexSessionState(session_id=session_id, title=str(title or ""))
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
        state = self._require_session(session_id)
        self._warn_fixed_session_config(provider_id, model_id, tools)

        argv = self._build_exec_argv(state, prompt_text)
        env = self._build_subprocess_env()
        logger.info(
            "codex exec session %s 启动：%s <prompt %d chars>",
            session_id,
            shlex.join(argv[:-1]),
            len(prompt_text),
        )
        # 进程池上限 = 全局并发预算（B4）：许可从 spawn 前持到进程回收后。
        # 非阻塞轮询，取消落在等待窗口时不持有许可（语义同 OpencodeEngine._request_slot）。
        while not self._request_slots.acquire(blocking=False):
            await asyncio.sleep(0.1)
        try:
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    limit=CODEX_STDOUT_STREAM_LIMIT_BYTES,  # 工具完整 stdout 单行可能超 64KiB 默认值
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"codex CLI 未安装或不在 PATH（{self.cli_path}）。"
                ) from exc
            except OSError as exc:
                raise RuntimeError(f"codex CLI 启动失败：{exc}") from exc
            state.process = process

            try:
                return await self._pump_events(
                    state,
                    process,
                    stream_callback=stream_callback,
                    on_tool_completed=on_tool_completed,
                    cancel_check=cancel_check,
                )
            finally:
                # 终态必回收：无论正常/收割/取消/异常，进程引用出表并确保已收尸。
                state.process = None
                await self._reap_process(process)
        finally:
            self._request_slots.release()

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        state = self._sessions.get(str(session_id or ""))
        if state is None:
            return []
        return [dict(message) for message in state.messages]

    async def abort_session(self, session_id: str) -> bool:
        state = self._sessions.get(str(session_id or "").strip())
        if state is None:
            return False
        process = state.process
        if process is None:
            return True  # 会话在表且进程已终态回收，视为已停止
        state.process = None
        await self._terminate_process(process)
        return True

    async def delete_session(self, session_id: str) -> None:
        state = self._sessions.pop(str(session_id or "").strip(), None)
        if state is None:
            return
        process = state.process
        state.process = None
        if process is not None:
            await self._terminate_process(process)

    # ------------------------------------------------------------------
    # 命令与环境拼装（CLI_FLAGS / ENV_VARS 映射的消费点）
    # ------------------------------------------------------------------
    def _build_exec_argv(self, state: _CodexSessionState, prompt_text: str) -> list[str]:
        argv = [self.cli_path, "exec"]
        if state.thread_id:
            # 命令拼法校准（engine-09 PoC，codex 0.147.0 实测）：resume 是 exec 的
            # 子命令（`codex exec resume <id> [prompt]`），旧快照的 `--resume <id>`
            # 选项已移除（报 unexpected argument）。
            argv += ["resume", state.thread_id]
        argv.extend(self.BASE_FLAGS)
        for attr, render in self.CLI_FLAGS:
            value = str(getattr(self, attr) or "").strip()
            if not value:
                continue
            if state.thread_id and attr == "sandbox_mode":
                # resume 子命令无 --sandbox 选项（0.147.0），用 -c 等价注入。
                argv.extend(["-c", f'sandbox_mode="{value}"'])
                continue
            argv.extend(render(value))
        argv.append(prompt_text)
        return argv

    def _build_subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        for attr, env_name in self.ENV_VARS:
            value = str(getattr(self, attr) or "").strip()
            if value:
                env[env_name] = value
        return env

    def _warn_fixed_session_config(
        self,
        provider_id: str | None,
        model_id: str | None,
        tools: dict[str, bool] | None,
    ) -> None:
        # provider 降级（§3 注）：codex provider 由 config.toml + 登录态决定，
        # 不按请求切换；tools 开关由 sandbox 模式决定，同为实例级固定。
        if provider_id:
            logger.warning(
                "codex 引擎 provider 为会话级固定（config.toml model_provider），"
                "run_session(provider_id=%s) 已忽略。",
                provider_id,
            )
        if model_id and model_id != self.model_id:
            # 实例未配模型时固定为 CLI 默认模型，按请求传入同样记 warning（review F4）。
            logger.warning(
                "codex 引擎 model 为会话级固定（%s），run_session(model_id=%s) 已忽略。",
                self.model_id or "CLI 默认",
                model_id,
            )
        if tools:
            logger.warning("codex 引擎不支持按请求 tools 开关（sandbox=%s 固定），已忽略。", self.sandbox_mode)

    # ------------------------------------------------------------------
    # 事件泵：流式读 stdout JSONL → 消息日志 / ToolCompletedEvent / 进度增量
    # ------------------------------------------------------------------
    async def _pump_events(
        self,
        state: _CodexSessionState,
        process: asyncio.subprocess.Process,
        *,
        stream_callback: Callable[[dict[str, Any]], None] | None,
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None,
        cancel_check: Callable[[], bool] | None,
    ) -> EngineRunResult:
        reply_parts: list[str] = []
        tool_outputs: list[ToolCompletedEvent] = []
        stream_error: dict[str, Any] | None = None  # turn.failed = 终态失败
        last_error_event: dict[str, Any] | None = None  # error 事件可能只是可重试的流式错误
        started_at = time.monotonic()
        last_activity = started_at
        last_heartbeat = started_at
        # stderr 伴随排干（review F2）：运行期间无人读 stderr，子进程写满管道缓冲
        # （POSIX 通常 64KB）会阻塞在 write 上，stdout 断流被误判 idle。攒尾部供报错详情。
        stderr_sink: list[str] = []
        drain_task = asyncio.create_task(
            self._drain_stderr(process.stderr, stderr_sink),
            name=f"codex-stderr-{state.session_id}",
        )

        try:
            while True:
                if cancel_check is not None and cancel_check():
                    await self._terminate_process(process)
                    state.process = None
                    raise ParseCancelledError("解析已取消。")
                try:
                    raw_line = await asyncio.wait_for(
                        process.stdout.readline(),  # type: ignore[union-attr]
                        timeout=CODEX_CANCEL_POLL_SECONDS,
                    )
                except TimeoutError:
                    if process.returncode is not None and process.stdout.at_eof():  # type: ignore[union-attr]
                        break
                    now = time.monotonic()
                    if now - last_activity > self.idle_timeout:
                        await self._terminate_process(process)
                        state.process = None
                        raise RuntimeError(
                            f"codex idle timeout after {int(self.idle_timeout)} seconds without new output; "
                            f"check session {state.session_id} tool calls."
                        )
                    if stream_callback is not None and now - last_heartbeat >= CODEX_PROGRESS_HEARTBEAT_SECONDS:
                        self._emit_progress(
                            stream_callback,
                            state,
                            heartbeat=True,
                            elapsed_seconds=now - started_at,
                        )
                        last_heartbeat = now
                    continue
                if not raw_line:  # EOF：进程退出且 stdout 读尽
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    logger.debug("codex stdout 非 JSON 行（忽略）：%s", line[:200])
                    continue
                if not isinstance(event, dict):
                    continue
                last_activity = time.monotonic()
                result = self._handle_event(
                    state,
                    event,
                    reply_parts=reply_parts,
                    tool_outputs=tool_outputs,
                    stream_callback=stream_callback,
                    on_tool_completed=on_tool_completed,
                    started_at=started_at,
                )
                if isinstance(result, EngineRunResult):  # 提前收割：立即停进程，不等宽限
                    await self._terminate_process(process)
                    state.process = None
                    return result
                if isinstance(result, dict):  # turn.failed / error 事件
                    if result.get("event_type") == "turn.failed":
                        stream_error = result
                    else:
                        last_error_event = result
        finally:
            await self._join_stderr_drain(drain_task)

        # EOF 后先收尸再读退出码（review F1）：returncode 由 child watcher 异步回填，
        # 直接读可能拿到 None，把成功运行误判为「codex exec 失败（exit None）」。
        await self._reap_process(process)
        state.process = None
        stderr_text = self._stderr_tail(stderr_sink)
        returncode = process.returncode
        if stream_error is not None:
            raise self._classify_failure(stream_error, stderr_text, returncode)
        if returncode is not None and returncode < 0:
            raise RuntimeError(
                f"codex exec 进程被终止（signal {-returncode}），会话可能已被 abort。"
            )
        if returncode != 0:
            raise self._classify_failure(last_error_event, stderr_text, returncode)
        return EngineRunResult(
            session_id=state.session_id,
            reply_text="\n".join(part for part in reply_parts if part).strip(),
            tool_outputs=tool_outputs,
            trace=self._build_trace(state),
        )

    def _handle_event(
        self,
        state: _CodexSessionState,
        event: dict[str, Any],
        *,
        reply_parts: list[str],
        tool_outputs: list[ToolCompletedEvent],
        stream_callback: Callable[[dict[str, Any]], None] | None,
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None,
        started_at: float,
    ) -> EngineRunResult | dict[str, Any] | None:
        event_type = str(event.get("type") or "")
        if event_type == "thread.started":
            thread_id = str(event.get("thread_id") or "").strip()
            if thread_id:
                state.thread_id = thread_id
            return None
        if event_type == "item.completed":
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            return self._handle_item_completed(
                state,
                item,
                reply_parts=reply_parts,
                tool_outputs=tool_outputs,
                stream_callback=stream_callback,
                on_tool_completed=on_tool_completed,
                started_at=started_at,
            )
        if event_type in ("turn.failed", "error"):
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            return {
                "message": str(error.get("message") or event.get("message") or "").strip(),
                "event_type": event_type,
            }
        return None  # turn.started / item.started / turn.completed 等不需要动作

    def _handle_item_completed(
        self,
        state: _CodexSessionState,
        item: dict[str, Any],
        *,
        reply_parts: list[str],
        tool_outputs: list[ToolCompletedEvent],
        stream_callback: Callable[[dict[str, Any]], None] | None,
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None,
        started_at: float,
    ) -> EngineRunResult | None:
        # item 类型键：旧版 item_type，新版 type。
        item_type = str(item.get("item_type") or item.get("type") or "")
        item_id = str(item.get("id") or f"item-{len(state.messages)}")
        if item_type in ("assistant_message", "agent_message"):
            # 事件 schema 校准（engine-09 PoC，codex 0.147.0 实测）：assistant 文本
            # item 类型已改名 agent_message，两键都认。
            text = str(item.get("text") or "").strip()
            if not text:
                return None
            reply_parts.append(text)
            state.messages.append(self._assistant_text_message(state, item_id, text))
            if stream_callback is not None:
                self._emit_progress(
                    stream_callback,
                    state,
                    heartbeat=False,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            return None
        if item_type == "command_execution":
            raw_command = str(item.get("command") or "").strip()
            command = self._extract_shell_command(raw_command)
            stdout = str(item.get("aggregated_output") or item.get("output") or "").strip()
            exit_code = item.get("exit_code")
            state.messages.append(
                self._bash_tool_message(state, item_id, command, stdout, exit_code)
            )
            if exit_code not in (None, 0):
                return None  # 失败命令不上报（对齐 iter_completed_bash_tool_events 口径）
            event = ToolCompletedEvent(
                command=command,
                stdout=stdout,
                event_id=f"{state.session_id}:{item_id}:{command}",
            )
            tool_outputs.append(event)
            if on_tool_completed is not None and on_tool_completed(event):
                # 提前收割（语义与 opencode_engine 一致：回调 True = 收割，
                # 回调可改写 event.stdout 作为产物）。
                if stream_callback is not None:
                    payload = self._build_trace(state)
                    payload["earlyCompletion"] = True
                    payload["elapsedSeconds"] = max(0, int(time.monotonic() - started_at))
                    stream_callback(payload)
                return EngineRunResult(
                    session_id=state.session_id,
                    reply_text=event.stdout,
                    tool_outputs=tool_outputs,
                    trace=self._build_trace(state),
                )
            return None
        if item_type == "reasoning":
            text = str(item.get("text") or "").strip()
            if text:
                state.messages.append(self._reasoning_message(state, item_id, text))
            return None
        return None

    # ------------------------------------------------------------------
    # 进程回收
    # ------------------------------------------------------------------
    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        """kill 并收尸；幂等，已退出的进程直接 wait 收割。"""
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await self._wait_reaped(process)

    async def _reap_process(self, process: asyncio.subprocess.Process) -> None:
        """run 结束后的兜底回收：进程未退出则先等一个宽限再 kill。"""
        if process.returncode is None:
            try:
                await asyncio.wait_for(asyncio.shield(process.wait()), CODEX_KILL_GRACE_SECONDS)
                return
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
        await self._wait_reaped(process)

    @staticmethod
    async def _wait_reaped(process: asyncio.subprocess.Process) -> None:
        with suppress(Exception):
            await process.wait()

    @staticmethod
    async def _drain_stderr(stderr: Any, sink: list[str]) -> None:
        """持续排干子进程 stderr 到 sink（review F2），防止写满管道缓冲假停滞。"""
        if stderr is None:
            return
        with suppress(Exception):
            while True:
                chunk = await stderr.read(4096)
                if not chunk:
                    return
                sink.append(chunk.decode("utf-8", errors="replace"))
                # 有界截断：只保留尾部，报错详情看末尾就够
                if sum(len(part) for part in sink) > CODEX_STDERR_TAIL_CHARS * 4:
                    sink[:] = ["".join(sink)[-CODEX_STDERR_TAIL_CHARS:]]

    @staticmethod
    async def _join_stderr_drain(drain_task: asyncio.Task[None]) -> None:
        """泵结束后 join 排干 task：进程终态 stderr 即 EOF 自然收尾；异常路径兜底取消。"""
        if not drain_task.done():
            with suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(drain_task), CODEX_KILL_GRACE_SECONDS)
        if not drain_task.done():
            drain_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await drain_task

    @staticmethod
    def _stderr_tail(sink: list[str]) -> str:
        return "".join(sink)[-CODEX_STDERR_TAIL_CHARS:].strip()

    # ------------------------------------------------------------------
    # 错误归类（ErrorPattern 消费点，对齐 errors.py 归一化风格）
    # ------------------------------------------------------------------
    def _classify_failure(
        self,
        stream_error: dict[str, Any] | None,
        stderr_text: str,
        returncode: int | None,
    ) -> RuntimeError:
        message = str((stream_error or {}).get("message") or "").strip()
        combined = "\n".join(part for part in (message, stderr_text) if part)
        if engine_errors.is_model_not_found_error(combined):
            return RuntimeError("codex CLI 模型不存在，请检查 CODEX_MODEL_ID 配置。")
        for pattern, normalized in self.ERROR_PATTERNS:
            if pattern.search(combined):
                return RuntimeError(normalized)
        detail = message or engine_errors._short_http_error(
            RuntimeError(stderr_text or f"exit code {returncode}")
        )
        return RuntimeError(f"codex exec 失败（exit {returncode}）：{detail}")

    # ------------------------------------------------------------------
    # opencode 形态的消息日志 / trace（复用 iter_completed_bash_tool_events 与前端留痕）
    # ------------------------------------------------------------------
    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _assistant_text_message(
        self, state: _CodexSessionState, item_id: str, text: str
    ) -> dict[str, Any]:
        return {
            "info": {
                "role": "assistant",
                "id": f"{state.session_id}:{item_id}",
                "time": {"completed": self._now_iso()},
            },
            "parts": [{"type": "text", "text": text}],
        }

    def _reasoning_message(
        self, state: _CodexSessionState, item_id: str, text: str
    ) -> dict[str, Any]:
        return {
            "info": {
                "role": "assistant",
                "id": f"{state.session_id}:{item_id}",
                "time": {"completed": self._now_iso()},
            },
            "parts": [{"type": "reasoning", "reasoning": text}],
        }

    def _bash_tool_message(
        self,
        state: _CodexSessionState,
        item_id: str,
        command: str,
        stdout: str,
        exit_code: Any,
    ) -> dict[str, Any]:
        return {
            "info": {
                "role": "assistant",
                "id": f"{state.session_id}:{item_id}",
                "time": {"completed": self._now_iso()},
            },
            "parts": [
                {
                    "type": "tool",
                    "tool": "bash",
                    "id": item_id,
                    "state": {
                        "status": "completed",
                        "input": {"command": command},
                        "exit": exit_code,
                        "output": stdout,
                    },
                }
            ],
        }

    def _build_trace(self, state: _CodexSessionState) -> dict[str, Any]:
        """opencodeOutput 等价物（前端留痕）：sessionId/parts 形态对齐 SSE 进度载荷。"""
        parts: list[dict[str, Any]] = []
        for message in state.messages[-20:]:
            for part in message.get("parts") or []:
                part_type = str(part.get("type") or "")
                if part_type == "text":
                    parts.append({"type": "text", "text": str(part.get("text") or "")})
                elif part_type == "reasoning":
                    parts.append({"type": "reasoning", "text": str(part.get("reasoning") or "")})
                elif part_type == "tool":
                    state_part = part.get("state") if isinstance(part.get("state"), dict) else {}
                    raw_input = state_part.get("input") if isinstance(state_part.get("input"), dict) else {}
                    parts.append(
                        {
                            "type": "tool",
                            "text": f"codex 执行命令：{raw_input.get('command') or ''}".strip(),
                        }
                    )
        return {
            "status": "received",
            "sessionId": state.session_id,
            "providerId": "codex",
            "modelId": self.model_id,
            "receivedAt": self._now_iso(),
            "parts": parts[-20:],
        }

    def _emit_progress(
        self,
        stream_callback: Callable[[dict[str, Any]], None],
        state: _CodexSessionState,
        *,
        heartbeat: bool,
        elapsed_seconds: float,
    ) -> None:
        payload = self._build_trace(state)
        payload["status"] = "streaming"
        payload["elapsedSeconds"] = max(0, int(elapsed_seconds))
        if heartbeat:
            payload["heartbeat"] = True
        stream_callback(payload)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_shell_command(command: str) -> str:
        """剥掉 codex command_execution 的 shell 包装（`/bin/bash -lc '...'`），

        使 ToolCompletedEvent.command 与 opencode bash 工具口径一致
        （业务回调按首个词匹配受控命令，见 orchestrator._matches_completed_command）。
        """
        try:
            words = shlex.split(command)
        except ValueError:
            return command
        shell = words[0].rsplit("/", 1)[-1] if words else ""
        if len(words) >= 3 and shell in ("bash", "sh") and words[1].startswith("-"):
            inner = " ".join(words[2:]).strip()
            return inner or command
        return command

    def _require_session(self, session_id: str) -> _CodexSessionState:
        state = self._sessions.get(str(session_id or "").strip())
        if state is None:
            raise RuntimeError(f"codex 会话不存在：{session_id}（先 create_session）。")
        return state
