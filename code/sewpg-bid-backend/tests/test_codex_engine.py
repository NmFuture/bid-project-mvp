"""CodexEngine 单测（engine-07，C1）：mock `codex exec` 子进程事件流，不依赖真实 CLI。

覆盖：CLI_FLAGS/ENV_VARS 参数拼装、command_execution → ToolCompletedEvent 事件映射、
on_tool_completed 提前收割（含回调改写 stdout）、--resume 续跑、ErrorPattern 错误归类、
cancel/abort/delete 的进程回收、idle 超时、provider/tools 会话级固定降级、
factory 的 codex 分支注册。
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from collections import deque
from typing import Any
from unittest.mock import AsyncMock, patch

from app.services.agent_engine import codex_engine as codex_module
from app.services.agent_engine.base import ToolCompletedEvent, iter_completed_bash_tool_events
from app.services.agent_engine.codex_engine import CodexEngine
from app.services.agent_engine.factory import AgentEngineFactory
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.bid_parse_cancel import ParseCancelledError


class _FakeStdout:
    """按行回吐 JSONL 事件；行尽即 EOF（进程退出）。hang=True 时行尽后挂起，
    直到进程被 kill（模拟长任务/假死会话）。"""

    def __init__(self, process: "_FakeProcess", events: list[dict[str, Any]], hang: bool) -> None:
        self._process = process
        self._lines: deque[bytes] = deque(json.dumps(event).encode() + b"\n" for event in events)
        self._hang = hang

    def at_eof(self) -> bool:
        return not self._lines and not self._hang

    async def readline(self) -> bytes:
        if self._lines:
            await asyncio.sleep(0)
            return self._lines.popleft()
        if self._hang:
            await asyncio.sleep(3600)
            return b""
        self._process.returncode = self._process.exit_code
        return b""


class _FakeStderr:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _FakeProcess:
    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        *,
        exit_code: int = 0,
        stderr: bytes = b"",
        hang: bool = False,
    ) -> None:
        self.returncode: int | None = None
        self.exit_code = exit_code
        self.killed = False
        self.waited = False
        self.stdout = _FakeStdout(self, events or [], hang)
        self.stderr = _FakeStderr(stderr)

    def kill(self) -> None:
        self.killed = True
        self.stdout._hang = False  # 真实进程被 kill 后 stdout 关闭 → EOF
        if self.returncode is None:
            self.returncode = -9

    async def wait(self) -> int:
        self.waited = True
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode


def _thread_started(thread_id: str = "thread-1") -> dict[str, Any]:
    return {"type": "thread.started", "thread_id": thread_id}


def _command_completed(
    command: str,
    *,
    output: str = "",
    exit_code: int = 0,
    item_id: str = "item-1",
) -> dict[str, Any]:
    return {
        "type": "item.completed",
        "item": {
            "id": item_id,
            "item_type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": "completed",
        },
    }


def _assistant_message(text: str, item_id: str = "item-9") -> dict[str, Any]:
    return {
        "type": "item.completed",
        "item": {"id": item_id, "item_type": "assistant_message", "text": text},
    }


def _turn_completed() -> dict[str, Any]:
    return {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}


class _ExecHarness:
    """patch create_subprocess_exec，按序回吐 fake 进程并记录 argv/env。"""

    def __init__(self, *processes: _FakeProcess) -> None:
        self.processes = list(processes)
        self.calls: list[dict[str, Any]] = []
        self._patch = patch(
            "app.services.agent_engine.codex_engine.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=self._spawn),
        )

    async def _spawn(self, *argv: str, **kwargs: Any) -> _FakeProcess:
        self.calls.append({"argv": list(argv), "env": kwargs.get("env")})
        return self.processes[len(self.calls) - 1]

    def __enter__(self) -> "_ExecHarness":
        self._patch.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._patch.stop()


class CodexEngineTests(unittest.IsolatedAsyncioTestCase):
    # ------------------------------------------------------------------
    # 会话生命周期与协议形状
    # ------------------------------------------------------------------
    async def test_create_session_registers_and_lists_empty(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        self.assertTrue(session_id.startswith("codex-"))
        self.assertEqual(await engine.list_messages(session_id), [])
        await engine.delete_session(session_id)
        self.assertEqual(await engine.list_messages(session_id), [])
        self.assertFalse(await engine.abort_session(session_id))

    async def test_run_session_requires_known_session(self) -> None:
        engine = CodexEngine()
        with self.assertRaisesRegex(RuntimeError, "会话不存在"):
            await engine.run_session("codex-missing", "prompt")

    # ------------------------------------------------------------------
    # CLI_FLAGS / ENV_VARS 拼装
    # ------------------------------------------------------------------
    async def test_exec_argv_maps_cli_flags_and_env_vars(self) -> None:
        engine = CodexEngine(
            cli_path="/usr/local/bin/codex",
            model_id="gpt-5-codex",
            reasoning_effort="high",
            sandbox_mode="workspace-write",
            codex_home="/tmp/codex-home",
        )
        session_id = await engine.create_session("t")
        process = _FakeProcess([_thread_started(), _turn_completed()])
        with _ExecHarness(process) as harness:
            await engine.run_session(session_id, "做点什么")

        argv = harness.calls[0]["argv"]
        self.assertEqual(argv[:2], ["/usr/local/bin/codex", "exec"])
        self.assertIn("--json", argv)
        self.assertIn("--skip-git-repo-check", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-5-codex")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(argv[argv.index("-c") + 1], "model_reasoning_effort=high")
        self.assertNotIn("--resume", argv)  # 首跑无 thread_id
        self.assertEqual(argv[-1], "做点什么")
        self.assertEqual(harness.calls[0]["env"]["CODEX_HOME"], "/tmp/codex-home")

    async def test_unset_optional_config_emits_no_extra_flags(self) -> None:
        engine = CodexEngine(model_id="", reasoning_effort="", codex_home="")
        session_id = await engine.create_session("t")
        with _ExecHarness(_FakeProcess([_turn_completed()])) as harness:
            await engine.run_session(session_id, "p")
        argv = harness.calls[0]["argv"]
        self.assertNotIn("--model", argv)
        self.assertNotIn("-c", argv)
        self.assertIn("--sandbox", argv)  # 默认 workspace-write

    # ------------------------------------------------------------------
    # 事件映射与 resume
    # ------------------------------------------------------------------
    async def test_command_execution_maps_to_tool_completed_and_resume(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        seen: list[ToolCompletedEvent] = []
        first = _FakeProcess(
            [
                _thread_started("thread-42"),
                _command_completed(
                    "/bin/bash -lc 's1parse finalize /data/parsed/PRJ/manifest.json'",
                    output='{"outputFile":"/data/parsed/PRJ/out.json"}',
                ),
                _assistant_message("解析完成"),
                _turn_completed(),
            ]
        )
        second = _FakeProcess([_thread_started("thread-42"), _assistant_message("继续"), _turn_completed()])
        with _ExecHarness(first, second) as harness:
            result = await engine.run_session(
                session_id,
                "prompt",
                on_tool_completed=lambda event: bool(seen.append(event)),
            )
            await engine.run_session(session_id, "prompt-2")

        self.assertEqual(len(seen), 1)
        event = seen[0]
        # shell 包装被剥掉，command 与 opencode bash 工具口径一致（首词即受控命令）
        self.assertEqual(event.command, "s1parse finalize /data/parsed/PRJ/manifest.json")
        self.assertEqual(event.stdout, '{"outputFile":"/data/parsed/PRJ/out.json"}')
        self.assertTrue(event.event_id)
        self.assertEqual(result.reply_text, "解析完成")
        self.assertEqual(len(result.tool_outputs), 1)
        self.assertEqual(result.trace["sessionId"], session_id)
        # thread_id 从 thread.started 捕获，第二次 run 走 --resume
        resume_argv = harness.calls[1]["argv"]
        self.assertEqual(resume_argv[resume_argv.index("--resume") + 1], "thread-42")

    async def test_failed_command_is_not_reported(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        seen: list[ToolCompletedEvent] = []
        process = _FakeProcess(
            [
                _thread_started(),
                _command_completed("ls /missing", output="No such file", exit_code=2),
                _turn_completed(),
            ]
        )
        with _ExecHarness(process):
            result = await engine.run_session(
                session_id, "p", on_tool_completed=lambda event: bool(seen.append(event))
            )
        self.assertEqual(seen, [])
        self.assertEqual(result.tool_outputs, [])

    async def test_list_messages_stay_opencode_schema_compatible(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess(
            [
                _thread_started(),
                _command_completed("s1parse finalize /x.json", output='{"ok":true}'),
                _turn_completed(),
            ]
        )
        with _ExecHarness(process):
            await engine.run_session(session_id, "p")
        messages = await engine.list_messages(session_id)
        events = list(iter_completed_bash_tool_events(messages))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].command, "s1parse finalize /x.json")
        self.assertEqual(events[0].stdout, '{"ok":true}')

    # ------------------------------------------------------------------
    # on_tool_completed 提前收割（语义与 opencode_engine 一致）
    # ------------------------------------------------------------------
    async def test_on_tool_completed_true_harvests_early_and_kills_process(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        stream_events: list[dict[str, Any]] = []
        process = _FakeProcess(
            [
                _thread_started(),
                _command_completed("s1parse finalize /x.json", output='{"raw":true}'),
                _assistant_message("这句不该被等到"),
                _turn_completed(),
            ],
            hang=True,  # 收割后进程仍「在跑」，验证被立即 kill
        )

        def on_tool_completed(event: ToolCompletedEvent) -> bool:
            event.stdout = f"harvested:{event.stdout}"  # 回调改写产物
            return True

        with _ExecHarness(process):
            result = await engine.run_session(
                session_id,
                "p",
                stream_callback=stream_events.append,
                on_tool_completed=on_tool_completed,
            )

        self.assertEqual(result.reply_text, "harvested:{\"raw\":true}")
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)  # 显式收尸
        self.assertIsNone(engine._sessions[session_id].process)
        early = [event for event in stream_events if event.get("earlyCompletion")]
        self.assertTrue(early)
        self.assertEqual(early[-1]["sessionId"], session_id)

    async def test_stream_callback_receives_progress_deltas(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        stream_events: list[dict[str, Any]] = []
        process = _FakeProcess(
            [_thread_started(), _assistant_message("第一段"), _assistant_message("第二段"), _turn_completed()]
        )
        with _ExecHarness(process):
            result = await engine.run_session(session_id, "p", stream_callback=stream_events.append)
        self.assertEqual(result.reply_text, "第一段\n第二段")
        streaming = [event for event in stream_events if event.get("status") == "streaming"]
        self.assertEqual(len(streaming), 2)
        self.assertEqual(streaming[0]["sessionId"], session_id)

    # ------------------------------------------------------------------
    # ErrorPattern 错误归类
    # ------------------------------------------------------------------
    async def test_stream_error_event_is_classified(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess(
            [
                _thread_started(),
                {"type": "turn.failed", "error": {"message": "429 rate limit exceeded"}},
            ],
            exit_code=1,
        )
        with _ExecHarness(process):
            with self.assertRaisesRegex(RuntimeError, "限流"):
                await engine.run_session(session_id, "p")

    async def test_nonzero_exit_stderr_auth_is_classified(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess([], exit_code=1, stderr=b"401 Unauthorized: invalid api key")
        with _ExecHarness(process):
            with self.assertRaisesRegex(RuntimeError, "认证失败"):
                await engine.run_session(session_id, "p")

    async def test_model_not_found_uses_shared_normalizer(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess([], exit_code=1, stderr=b"ProviderModelNotFound: nope")
        with _ExecHarness(process):
            with self.assertRaisesRegex(RuntimeError, "模型不存在"):
                await engine.run_session(session_id, "p")

    async def test_unknown_failure_falls_back_to_generic_message(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess([], exit_code=1, stderr=b"some weird failure")
        with _ExecHarness(process):
            with self.assertRaisesRegex(RuntimeError, r"codex exec 失败（exit 1）：some weird failure"):
                await engine.run_session(session_id, "p")

    async def test_missing_cli_binary_raises_install_hint(self) -> None:
        engine = CodexEngine(cli_path="/nonexistent/codex")
        session_id = await engine.create_session("t")
        with patch(
            "app.services.agent_engine.codex_engine.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError("no such file")),
        ):
            with self.assertRaisesRegex(RuntimeError, "codex CLI 未安装"):
                await engine.run_session(session_id, "p")

    # ------------------------------------------------------------------
    # cancel / abort / delete / idle 的进程回收
    # ------------------------------------------------------------------
    async def test_cancel_check_kills_process_and_raises(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess([_thread_started()], hang=True)
        with _ExecHarness(process):
            with self.assertRaises(ParseCancelledError):
                await engine.run_session(session_id, "p", cancel_check=lambda: True)
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertIsNone(engine._sessions[session_id].process)

    async def test_abort_session_kills_running_process_and_run_raises(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess([_thread_started()], hang=True)
        with (
            _ExecHarness(process),
            patch.object(codex_module, "CODEX_CANCEL_POLL_SECONDS", 0.01),
        ):
            run_task = asyncio.create_task(engine.run_session(session_id, "p"))
            await asyncio.sleep(0.05)  # 让事件泵进入挂起读取
            self.assertTrue(await engine.abort_session(session_id))
            with self.assertRaisesRegex(RuntimeError, "进程被终止"):
                await run_task
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)

    async def test_abort_without_running_process_is_idempotent(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        with _ExecHarness(_FakeProcess([_turn_completed()])):
            await engine.run_session(session_id, "p")
        self.assertTrue(await engine.abort_session(session_id))  # 已终态回收 → 视为已停止

    async def test_delete_session_kills_running_process_and_drops_state(self) -> None:
        engine = CodexEngine()
        session_id = await engine.create_session("t")
        process = _FakeProcess([_thread_started()], hang=True)
        with (
            _ExecHarness(process),
            patch.object(codex_module, "CODEX_CANCEL_POLL_SECONDS", 0.01),
        ):
            run_task = asyncio.create_task(engine.run_session(session_id, "p"))
            await asyncio.sleep(0.05)
            await engine.delete_session(session_id)
            with self.assertRaisesRegex(RuntimeError, "进程被终止"):
                await run_task
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertNotIn(session_id, engine._sessions)
        self.assertFalse(await engine.abort_session(session_id))

    async def test_idle_timeout_kills_stalled_process(self) -> None:
        engine = CodexEngine()
        engine.idle_timeout = 0.02
        session_id = await engine.create_session("t")
        process = _FakeProcess([_thread_started()], hang=True)
        with (
            _ExecHarness(process),
            patch.object(codex_module, "CODEX_CANCEL_POLL_SECONDS", 0.01),
        ):
            with self.assertRaisesRegex(RuntimeError, "idle timeout"):
                await engine.run_session(session_id, "p")
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)

    # ------------------------------------------------------------------
    # provider/tools 会话级固定降级（§3 注，显式记录）
    # ------------------------------------------------------------------
    async def test_provider_model_tools_params_are_ignored_with_warning(self) -> None:
        engine = CodexEngine(model_id="fixed-model")
        session_id = await engine.create_session("t")
        with _ExecHarness(_FakeProcess([_turn_completed()])) as harness:
            with self.assertLogs("app.services.agent_engine.codex_engine", level="WARNING") as logs:
                await engine.run_session(
                    session_id,
                    "p",
                    provider_id="other-provider",
                    model_id="other-model",
                    tools={"bash": True},
                )
        argv = harness.calls[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "fixed-model")  # 仍用实例配置
        warning_text = "\n".join(logs.output)
        self.assertIn("provider", warning_text)
        self.assertIn("tools", warning_text)


class CodexFactoryTests(unittest.TestCase):
    def test_factory_creates_codex_engine(self) -> None:
        with patch.dict(os.environ, {"AGENT_ENGINE": "codex"}):
            engine = AgentEngineFactory.create()
        self.assertIsInstance(engine, CodexEngine)
        self.assertEqual(engine.engine_name, "codex")

    def test_factory_default_stays_opencode(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_ENGINE", None)
            engine = AgentEngineFactory.create()
        self.assertIsInstance(engine, OpencodeEngine)

    def test_factory_pi_still_not_implemented(self) -> None:
        with patch.dict(os.environ, {"AGENT_ENGINE": "pi"}):
            with self.assertRaises(NotImplementedError):
                AgentEngineFactory.create()


if __name__ == "__main__":
    unittest.main()
