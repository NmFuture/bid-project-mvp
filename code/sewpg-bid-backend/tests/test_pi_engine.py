"""PiEngine 单测：fake 子进程模拟 pi --mode rpc 的 JSONL 交互（本机无 Pi 二进制）。

覆盖：RPC 收发（id 关联/握手/拒绝）、事件映射（text/tool/agent 终态）、
on_tool_completed 提前收割、abort/delete 进程回收、idle 超时、heartbeat、
进度增量、cancel_check、进程中途退出。
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.services.agent_engine.factory import AgentEngineFactory
from app.services.agent_engine.pi_engine import (
    PI_RPC_PROTOCOL,
    PI_RPC_STREAM_LIMIT_BYTES,
    PI_SESSION_EVENT_BUFFER_MAX,
    PiEngine,
)
from app.services.bid_parse_cancel import ParseCancelledError


class _FakeStdout:
    """队列驱动的 stdout：feed() 注入 JSONL，feed_eof() 模拟进程关闭。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    def feed(self, record: dict) -> None:
        self._queue.put_nowait(json.dumps(record).encode("utf-8") + b"\n")

    def feed_eof(self) -> None:
        self._queue.put_nowait(b"")

    async def readline(self) -> bytes:
        return await self._queue.get()


class _FakeStdin:
    def __init__(self, process: "FakePiProcess") -> None:
        self._process = process
        self.lines: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.lines.append(data)
        for raw in data.decode("utf-8").splitlines():
            if raw.strip():
                self._process.receive(json.loads(raw))

    async def drain(self) -> None:
        pass


class FakePiProcess:
    """同形 asyncio.subprocess.Process 的 fake。

    handlers: {command_type: fn(proc, payload) -> bool}；返回 True 表示 handler
    已自行响应（不再自动 ack），返回 False 则对带 id 的命令自动 ack success。
    """

    def __init__(self, handlers: dict | None = None) -> None:
        self.pid = 4321
        self.returncode: int | None = None
        self.killed = False
        self.argv: list[str] | None = None
        self.stdout = _FakeStdout()
        self.stdin = _FakeStdin(self)
        self._handlers = handlers or {}

    def receive(self, payload: dict) -> None:
        handler = self._handlers.get(payload.get("type"))
        if handler is not None and handler(self, payload):
            return
        if "id" in payload:
            self.stdout.feed(
                {
                    "type": "response",
                    "id": payload["id"],
                    "command": payload.get("type"),
                    "success": True,
                    "data": {},
                }
            )

    def commands(self, command_type: str) -> list[dict]:
        return [
            json.loads(raw)
            for line in self.stdin.lines
            for raw in line.decode("utf-8").splitlines()
            if raw.strip() and json.loads(raw).get("type") == command_type
        ]

    def kill(self) -> None:
        self.killed = True
        if self.returncode is None:
            self.returncode = -9
            self.stdout.feed_eof()

    def terminate(self) -> None:
        self.kill()

    async def wait(self) -> int:
        while self.returncode is None:
            await asyncio.sleep(0.005)
        return self.returncode


def _text_run_events(text: str) -> list[dict]:
    return [
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": text}},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "stopReason": "stop",
            },
        },
        {"type": "agent_end", "messages": [], "willRetry": False},
        {"type": "agent_settled"},
    ]


def _prompt_handler(events: list[dict], *, delay: float = 0.0):
    def handler(proc: FakePiProcess, payload: dict) -> bool:
        async def emit() -> None:
            if delay:
                await asyncio.sleep(delay)
            for event in events:
                proc.stdout.feed(event)

        asyncio.get_running_loop().create_task(emit())
        return False  # 仍走自动 ack

    return handler


class PiEngineTests(unittest.IsolatedAsyncioTestCase):
    def _engine(self, **overrides) -> PiEngine:
        params = {
            "pi_command": "pi-fake",
            "provider_id": "p0",
            "model_id": "m0",
            "idle_timeout_sec": 5.0,
            "heartbeat_interval_sec": 0.1,
            "rpc_timeout_sec": 2.0,
        }
        params.update(overrides)
        return PiEngine(**params)

    async def _create(self, engine: PiEngine, process: FakePiProcess) -> str:
        with patch.object(engine, "_spawn_process", new=AsyncMock(return_value=process)) as spawn:
            session_id = await engine.create_session("测试会话")
        process.argv = spawn.call_args.args[0]
        return session_id

    # ------------------------------------------------------------------
    # RPC 收发
    # ------------------------------------------------------------------
    async def test_create_session_spawns_rpc_process_and_handshakes(self) -> None:
        engine = self._engine()
        process = FakePiProcess()

        session_id = await self._create(engine, process)

        self.assertTrue(session_id.startswith("pi-"))
        self.assertIn(session_id, engine._sessions)
        # argv 全量形态锁定（engine-09 review P2-1，pi 0.73.1 实测校准）：
        # `-n title` 是非法选项不得出现；headless 默认 --no-extensions。
        self.assertEqual(
            process.argv,
            ["pi-fake", "--mode", "rpc", "--no-session", "--no-extensions", "--provider", "p0", "--model", "m0"],
        )
        self.assertNotIn("-n", process.argv)
        self.assertEqual(len(process.commands("get_state")), 1)  # 握手
        await engine.delete_session(session_id)

    async def test_create_session_extensions_opt_in_via_env(self) -> None:
        """PI_NO_EXTENSIONS=0（或构造参数）关闭 --no-extensions（engine-09 review P2-1）。"""
        with patch.dict(os.environ, {"PI_NO_EXTENSIONS": "0"}):
            engine = self._engine()
        process = FakePiProcess()

        session_id = await self._create(engine, process)

        self.assertNotIn("--no-extensions", process.argv)
        self.assertNotIn("-n", process.argv)
        await engine.delete_session(session_id)

    async def test_create_session_handshake_timeout_kills_process(self) -> None:
        engine = self._engine(rpc_timeout_sec=0.2)
        process = FakePiProcess({"get_state": lambda proc, payload: True})  # 不应答

        with patch.object(engine, "_spawn_process", new=AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RuntimeError, "握手失败"):
                await engine.create_session("t")

        self.assertTrue(process.killed)
        self.assertEqual(engine._sessions, {})

    async def test_create_session_spawn_oserror_raises_runtime_error(self) -> None:
        engine = self._engine()
        with patch.object(engine, "_spawn_process", new=AsyncMock(side_effect=FileNotFoundError("no pi"))):
            with self.assertRaisesRegex(RuntimeError, "启动失败"):
                await engine.create_session("t")

    async def test_run_session_prompt_response_correlation(self) -> None:
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(_text_run_events("完成。"))})
        session_id = await self._create(engine, process)

        result = await engine.run_session(session_id, "写一段标书")

        prompts = process.commands("prompt")
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["message"], "写一段标书")
        self.assertIn("id", prompts[0])
        self.assertEqual(result.session_id, session_id)
        self.assertEqual(result.reply_text, "完成。")
        self.assertEqual(result.trace["protocol"], PI_RPC_PROTOCOL)
        self.assertFalse(result.trace["earlyCompletion"])
        await engine.delete_session(session_id)

    async def test_run_session_rejected_prompt_raises(self) -> None:
        def reject(proc: FakePiProcess, payload: dict) -> bool:
            proc.stdout.feed(
                {"type": "response", "id": payload["id"], "command": "prompt", "success": False, "error": "no model"}
            )
            return True

        engine = self._engine()
        process = FakePiProcess({"prompt": reject})
        session_id = await self._create(engine, process)

        with self.assertRaisesRegex(RuntimeError, "no model"):
            await engine.run_session(session_id, "hi")
        await engine.delete_session(session_id)

    async def test_run_session_set_model_before_prompt_when_model_changes(self) -> None:
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(_text_run_events("ok"))})
        session_id = await self._create(engine, process)

        await engine.run_session(session_id, "hi", provider_id="p1", model_id="m1")

        set_models = process.commands("set_model")
        self.assertEqual(len(set_models), 1)
        self.assertEqual(set_models[0]["provider"], "p1")
        self.assertEqual(set_models[0]["modelId"], "m1")
        await engine.delete_session(session_id)

    async def test_run_session_rejects_tools_override(self) -> None:
        engine = self._engine()
        process = FakePiProcess()
        session_id = await self._create(engine, process)

        with self.assertRaises(ValueError):
            await engine.run_session(session_id, "hi", tools={"websearch": False})
        await engine.delete_session(session_id)

    async def test_run_session_unknown_session_raises(self) -> None:
        engine = self._engine()
        with self.assertRaises(KeyError):
            await engine.run_session("pi-missing", "hi")

    # ------------------------------------------------------------------
    # 事件映射 / 提前收割
    # ------------------------------------------------------------------
    async def test_bash_tool_completion_maps_to_event_and_early_harvest(self) -> None:
        events = [
            {
                "type": "tool_execution_start",
                "toolCallId": "call-1",
                "toolName": "bash",
                "args": {"command": "s1parse-finalize --out x.json"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "call-1",
                "toolName": "bash",
                "result": {"content": [{"type": "text", "text": "FINAL-OUTPUT"}]},
                "isError": False,
            },
            # 收割后进程即被回收，这些事件不应再被需要
            {"type": "agent_settled"},
        ]
        seen = []

        def on_tool_completed(event) -> bool:
            seen.append(event)
            return True

        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(events)})
        session_id = await self._create(engine, process)

        result = await engine.run_session(session_id, "run", on_tool_completed=on_tool_completed)

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].command, "s1parse-finalize --out x.json")
        self.assertEqual(seen[0].stdout, "FINAL-OUTPUT")
        self.assertEqual(seen[0].event_id, f"{session_id}:call-1:s1parse-finalize --out x.json")
        self.assertEqual(result.reply_text, "FINAL-OUTPUT")
        self.assertEqual(len(result.tool_outputs), 1)
        self.assertTrue(result.trace["earlyCompletion"])
        # 收割后进程必被回收（abort RPC + kill + 出进程表）
        self.assertTrue(process.killed)
        self.assertNotIn(session_id, engine._sessions)
        self.assertEqual(len(process.commands("abort")), 1)

    async def test_non_terminal_callback_continues_until_settled(self) -> None:
        events = [
            {
                "type": "tool_execution_start",
                "toolCallId": "call-1",
                "toolName": "bash",
                "args": {"command": "ls"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "call-1",
                "toolName": "bash",
                "result": {"content": [{"type": "text", "text": "file.txt"}]},
                "isError": False,
            },
            *_text_run_events("最终回复"),
        ]
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(events)})
        session_id = await self._create(engine, process)

        result = await engine.run_session(
            session_id, "run", on_tool_completed=lambda event: False
        )

        self.assertEqual(result.reply_text, "最终回复")
        self.assertEqual(len(result.tool_outputs), 1)
        self.assertFalse(result.trace["earlyCompletion"])
        self.assertFalse(process.killed)  # 正常结束不杀进程
        await engine.delete_session(session_id)

    async def test_error_tool_completion_is_not_reported(self) -> None:
        events = [
            {
                "type": "tool_execution_start",
                "toolCallId": "call-1",
                "toolName": "bash",
                "args": {"command": "s1parse-finalize"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "call-1",
                "toolName": "bash",
                "result": {"content": [{"type": "text", "text": "boom"}]},
                "isError": True,
            },
            *_text_run_events("done"),
        ]
        seen = []
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(events)})
        session_id = await self._create(engine, process)

        result = await engine.run_session(
            session_id, "run", on_tool_completed=lambda event: seen.append(event) or True
        )

        self.assertEqual(seen, [])
        self.assertEqual(result.tool_outputs, [])
        await engine.delete_session(session_id)

    async def test_assistant_error_stop_reason_raises(self) -> None:
        events = [
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": "provider overloaded",
                },
            },
        ]
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(events)})
        session_id = await self._create(engine, process)

        with self.assertRaisesRegex(RuntimeError, "provider overloaded"):
            await engine.run_session(session_id, "run")
        self.assertTrue(process.killed)
        self.assertNotIn(session_id, engine._sessions)

    async def test_process_exit_mid_run_raises(self) -> None:
        def crash(proc: FakePiProcess, payload: dict) -> bool:
            proc.stdout.feed(
                {"type": "response", "id": payload["id"], "command": "prompt", "success": True}
            )
            proc.returncode = 1
            proc.stdout.feed_eof()
            return True

        engine = self._engine()
        process = FakePiProcess({"prompt": crash})
        session_id = await self._create(engine, process)

        with self.assertRaisesRegex(RuntimeError, "意外退出"):
            await engine.run_session(session_id, "run")
        self.assertNotIn(session_id, engine._sessions)

    # ------------------------------------------------------------------
    # 监管：进度增量 / heartbeat / idle 超时 / 取消
    # ------------------------------------------------------------------
    async def test_stream_callback_receives_progress_deltas(self) -> None:
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(_text_run_events("你好世界"))})
        session_id = await self._create(engine, process)
        streamed: list[dict] = []

        await engine.run_session(session_id, "run", stream_callback=streamed.append)

        text_payloads = [
            payload
            for payload in streamed
            for part in payload.get("parts", [])
            if part.get("type") == "text" and "你好" in (part.get("text") or "")
        ]
        self.assertTrue(text_payloads)
        self.assertTrue(all(payload["sessionId"] == session_id for payload in streamed))
        self.assertTrue(all(payload["providerId"] == "p0" for payload in streamed))
        await engine.delete_session(session_id)

    async def test_heartbeat_emitted_while_waiting(self) -> None:
        engine = self._engine(heartbeat_interval_sec=0.1, idle_timeout_sec=5.0)
        process = FakePiProcess({"prompt": _prompt_handler(_text_run_events("迟到的回复"), delay=0.45)})
        session_id = await self._create(engine, process)
        streamed: list[dict] = []

        result = await engine.run_session(session_id, "run", stream_callback=streamed.append)

        self.assertEqual(result.reply_text, "迟到的回复")
        heartbeats = [payload for payload in streamed if payload.get("heartbeat")]
        self.assertGreaterEqual(len(heartbeats), 1)
        self.assertIn("idleSeconds", heartbeats[0])
        await engine.delete_session(session_id)

    async def test_idle_timeout_kills_process_and_raises(self) -> None:
        engine = self._engine(idle_timeout_sec=0.3)
        process = FakePiProcess()  # prompt 仅自动 ack，无后续事件
        session_id = await self._create(engine, process)

        with self.assertRaisesRegex(RuntimeError, "idle timeout"):
            await engine.run_session(session_id, "run")

        self.assertTrue(process.killed)
        self.assertNotIn(session_id, engine._sessions)

    async def test_cancel_check_aborts_and_reaps_process(self) -> None:
        engine = self._engine(idle_timeout_sec=30.0)
        process = FakePiProcess()  # 无事件，等 cancel
        session_id = await self._create(engine, process)

        with self.assertRaises(ParseCancelledError):
            await engine.run_session(session_id, "run", cancel_check=lambda: True)

        self.assertTrue(process.killed)
        self.assertNotIn(session_id, engine._sessions)
        self.assertEqual(len(process.commands("abort")), 1)

    async def test_external_abort_interrupts_run_without_waiting_idle(self) -> None:
        """run 中外部 abort 必须主动打断等待（engine-08 P3-1），不干等 idle 超时。"""
        engine = self._engine(idle_timeout_sec=30.0)  # 足够大：若等 idle 本用例会超时
        process = FakePiProcess()  # prompt 仅自动 ack，无后续事件
        session_id = await self._create(engine, process)

        run_task = asyncio.create_task(engine.run_session(session_id, "run"))
        await asyncio.sleep(0.1)  # 让 run 进入事件等待
        await engine.abort_session(session_id)

        with self.assertRaises(ParseCancelledError):
            await asyncio.wait_for(run_task, timeout=5.0)
        self.assertTrue(process.killed)
        self.assertNotIn(session_id, engine._sessions)

    # ------------------------------------------------------------------
    # 事件缓冲有界（engine-08 P3-2）
    # ------------------------------------------------------------------
    async def test_event_buffer_is_bounded_and_keeps_tail(self) -> None:
        engine = self._engine()
        process = FakePiProcess()
        session_id = await self._create(engine, process)
        session = engine._sessions[session_id]

        total = PI_SESSION_EVENT_BUFFER_MAX * 2 + 100
        for index in range(total):
            engine._dispatch_record(session, {"type": "message_update", "seq": index})

        self.assertLessEqual(len(session.events), PI_SESSION_EVENT_BUFFER_MAX * 2)
        self.assertGreater(session.events_trimmed, 0)
        # 尾部保留：最新事件还在缓冲里
        self.assertEqual(session.events[-1]["seq"], total - 1)
        await engine.delete_session(session_id)

    async def test_run_session_unaffected_by_prior_buffer_trim(self) -> None:
        """修剪后绝对游标不乱：长跑会话缓冲被截过，后续 run 仍能正确收事件。"""
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(_text_run_events("修剪后正常"))})
        session_id = await self._create(engine, process)
        session = engine._sessions[session_id]
        for index in range(PI_SESSION_EVENT_BUFFER_MAX * 2 + 10):
            engine._dispatch_record(session, {"type": "message_update", "seq": index})
        self.assertGreater(session.events_trimmed, 0)

        result = await engine.run_session(session_id, "run")

        self.assertEqual(result.reply_text, "修剪后正常")
        await engine.delete_session(session_id)

    # ------------------------------------------------------------------
    # 进程回收 / 消息查询
    # ------------------------------------------------------------------
    async def test_abort_session_reaps_process(self) -> None:
        engine = self._engine()
        process = FakePiProcess()
        session_id = await self._create(engine, process)

        self.assertTrue(await engine.abort_session(session_id))
        self.assertTrue(process.killed)
        self.assertNotIn(session_id, engine._sessions)
        # 幂等
        self.assertFalse(await engine.abort_session(session_id))

    async def test_delete_session_reaps_process_idempotently(self) -> None:
        engine = self._engine()
        process = FakePiProcess()
        session_id = await self._create(engine, process)

        await engine.delete_session(session_id)
        self.assertTrue(process.killed)
        self.assertNotIn(session_id, engine._sessions)
        await engine.delete_session(session_id)  # 不抛

    async def test_reader_task_is_stopped_after_delete(self) -> None:
        engine = self._engine()
        process = FakePiProcess()
        session_id = await self._create(engine, process)
        reader = engine._sessions[session_id].reader_task

        await engine.delete_session(session_id)
        self.assertTrue(reader.done())

    async def test_list_messages_returns_messages(self) -> None:
        def get_messages(proc: FakePiProcess, payload: dict) -> bool:
            proc.stdout.feed(
                {
                    "type": "response",
                    "id": payload["id"],
                    "command": "get_messages",
                    "success": True,
                    "data": {"messages": [{"role": "user", "content": "hi"}, "oops"]},
                }
            )
            return True

        engine = self._engine()
        process = FakePiProcess({"get_messages": get_messages})
        session_id = await self._create(engine, process)

        messages = await engine.list_messages(session_id)
        self.assertEqual(messages, [{"role": "user", "content": "hi"}])
        # 回收后进程不可用 → 空列表
        await engine.delete_session(session_id)
        self.assertEqual(await engine.list_messages(session_id), [])

    async def test_extension_ui_dialog_auto_cancelled(self) -> None:
        def prompt_with_ui(proc: FakePiProcess, payload: dict) -> bool:
            async def emit() -> None:
                proc.stdout.feed({"type": "extension_ui_request", "id": "ui-1", "method": "confirm", "title": "?"})
                for event in _text_run_events("ok"):
                    proc.stdout.feed(event)

            asyncio.get_running_loop().create_task(emit())
            return False

        engine = self._engine()
        process = FakePiProcess({"prompt": prompt_with_ui})
        session_id = await self._create(engine, process)

        await engine.run_session(session_id, "run")

        responses = process.commands("extension_ui_response")
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], "ui-1")
        self.assertTrue(responses[0]["cancelled"])
        await engine.delete_session(session_id)

    # ------------------------------------------------------------------
    # stdout 行缓冲上限（review P2-2）
    # ------------------------------------------------------------------
    async def test_spawn_process_raises_stream_limit(self) -> None:
        engine = self._engine()
        with patch(
            "app.services.agent_engine.pi_engine.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=FakePiProcess()),
        ) as spawn:
            await engine._spawn_process(["pi-fake", "--mode", "rpc"])
        self.assertEqual(spawn.call_args.kwargs.get("limit"), PI_RPC_STREAM_LIMIT_BYTES)
        self.assertGreaterEqual(PI_RPC_STREAM_LIMIT_BYTES, 8 * 1024 * 1024)

    async def test_oversized_single_line_tool_output_is_harvested(self) -> None:
        # 超 64KiB（asyncio 默认行缓冲）的单条 JSONL：finalize 完整 stdout 即收割载荷。
        big_output = "X" * (256 * 1024)
        events = [
            {
                "type": "tool_execution_start",
                "toolCallId": "call-big",
                "toolName": "bash",
                "args": {"command": "s1parse-finalize"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "call-big",
                "toolName": "bash",
                "result": {"content": [{"type": "text", "text": big_output}]},
                "isError": False,
            },
        ]
        engine = self._engine()
        process = FakePiProcess({"prompt": _prompt_handler(events)})
        session_id = await self._create(engine, process)

        result = await engine.run_session(
            session_id, "run", on_tool_completed=lambda event: True
        )

        self.assertEqual(result.reply_text, big_output)
        self.assertEqual(len(result.tool_outputs[0].stdout), 256 * 1024)


class PiEngineFactoryTests(unittest.TestCase):
    def test_factory_creates_pi_engine(self) -> None:
        with patch.dict(os.environ, {"AGENT_ENGINE": "pi"}):
            engine = AgentEngineFactory.create()
        self.assertIsInstance(engine, PiEngine)
        self.assertEqual(engine.engine_name, "pi")


if __name__ == "__main__":
    unittest.main()
