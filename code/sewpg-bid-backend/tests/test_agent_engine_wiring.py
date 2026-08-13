"""engine-09（C3）接线单测：工厂取引擎、plan→协议回调适配、分片协议路径、repair 解耦。

全部使用 fake/内存替身，不依赖真实 CLI（codex/pi）与 opencode 服务。
"""
from __future__ import annotations

import os
import types
import unittest
from unittest.mock import patch

from app.services.agent_engine import json_utils
from app.services.agent_engine.base import (
    EarlyCompletionPlan,
    EngineRunResult,
    ToolCompletedEvent,
    tool_completed_callback_from_plan,
)
from app.services.agent_engine.factory import (
    AGENT_ENGINE_ENV_VAR,
    AgentEngineFactory,
)
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.agent_engine.orchestrator import AgentOrchestrator
from app.services.bid_parse_cancel import ParseCancelledError


class AgentEngineFactoryWiringTests(unittest.TestCase):
    def test_default_engine_is_opencode(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(AGENT_ENGINE_ENV_VAR, None)
            engine = AgentEngineFactory.create()
        self.assertIsInstance(engine, OpencodeEngine)
        self.assertEqual(engine.engine_name, "opencode")

    def test_create_selects_engine_by_env(self) -> None:
        with (
            patch.dict(os.environ, {AGENT_ENGINE_ENV_VAR: "codex"}),
            patch("app.services.agent_engine.factory.CodexEngine") as codex_cls,
        ):
            AgentEngineFactory.create()
        codex_cls.assert_called_once_with()

        with (
            patch.dict(os.environ, {AGENT_ENGINE_ENV_VAR: "pi"}),
            patch("app.services.agent_engine.factory.PiEngine") as pi_cls,
        ):
            AgentEngineFactory.create()
        pi_cls.assert_called_once_with()

    def test_create_rejects_unknown_engine(self) -> None:
        with patch.dict(os.environ, {AGENT_ENGINE_ENV_VAR: "bogus"}):
            with self.assertRaisesRegex(ValueError, "未知 AGENT_ENGINE"):
                AgentEngineFactory.create()

    def test_model_config_only_forwarded_to_opencode(self) -> None:
        model_config = {"enabled": True, "modelId": "m"}
        slots = object()
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("app.services.agent_engine.factory.OpencodeEngine") as opencode_cls,
        ):
            os.environ.pop(AGENT_ENGINE_ENV_VAR, None)
            AgentEngineFactory.create(model_config=model_config, request_slots=slots)
        opencode_cls.assert_called_once_with(model_config=model_config, request_slots=slots)

        # codex/pi 的 provider/model 由各自 CLI 配置决定（engine-07/08 已记录降级），
        # opencode 系统设置不入参；并发预算池三引擎都接。
        with (
            patch.dict(os.environ, {AGENT_ENGINE_ENV_VAR: "codex"}),
            patch("app.services.agent_engine.factory.CodexEngine") as codex_cls,
        ):
            AgentEngineFactory.create(model_config=model_config, request_slots=slots)
        codex_cls.assert_called_once_with(request_slots=slots)

        with (
            patch.dict(os.environ, {AGENT_ENGINE_ENV_VAR: "pi"}),
            patch("app.services.agent_engine.factory.PiEngine") as pi_cls,
        ):
            AgentEngineFactory.create(model_config=model_config, request_slots=slots)
        pi_cls.assert_called_once_with(request_slots=slots)


class PlanToCallbackAdapterTests(unittest.TestCase):
    """EarlyCompletionPlan → 协议级 on_tool_completed 适配（engine-07 遗留）。"""

    def test_none_plan_or_no_factory_yields_none(self) -> None:
        self.assertIsNone(tool_completed_callback_from_plan(None))
        self.assertIsNone(tool_completed_callback_from_plan(EarlyCompletionPlan()))

    def test_callback_false_passes_through(self) -> None:
        plan = EarlyCompletionPlan(tool_completed_factory=lambda: (lambda _event: False))
        callback = tool_completed_callback_from_plan(plan)
        assert callback is not None
        event = ToolCompletedEvent(command="s1parse finalize /m.json", stdout="raw")
        self.assertFalse(callback(event))
        self.assertEqual(event.stdout, "raw", "未命中的事件不得改写 stdout")

    def test_callback_true_rewrites_stdout_via_harvest_payload(self) -> None:
        # produce_payload 覆盖（s2 终态校验形态）：收割产物以计划产物为准。
        plan = EarlyCompletionPlan(
            tool_completed_factory=lambda: (lambda _event: True),
            produce_payload=lambda _event: "validated-payload",
        )
        callback = tool_completed_callback_from_plan(plan)
        assert callback is not None
        event = ToolCompletedEvent(command="s2outline finalize /w", stdout="raw")
        self.assertTrue(callback(event))
        self.assertEqual(event.stdout, "validated-payload")

    def test_callback_true_defaults_to_event_stdout(self) -> None:
        plan = EarlyCompletionPlan(tool_completed_factory=lambda: (lambda _event: True))
        callback = tool_completed_callback_from_plan(plan)
        assert callback is not None
        event = ToolCompletedEvent(command="s4gap", stdout="raw-output")
        self.assertTrue(callback(event))
        self.assertEqual(event.stdout, "raw-output")

    def test_factory_called_once_for_single_protocol_phase(self) -> None:
        calls: list[str] = []

        def factory():  # 协议引擎只有事件流内一个相位，工厂只取一次
            calls.append("taken")
            return lambda _event: True

        plan = EarlyCompletionPlan(tool_completed_factory=factory)
        callback = tool_completed_callback_from_plan(plan)
        assert callback is not None
        callback(ToolCompletedEvent(command="c", stdout="o"))
        callback(ToolCompletedEvent(command="c", stdout="o"))
        self.assertEqual(calls, ["taken"])


class _FakeProtocolEngine:
    """只实现 AgentEngine 协议的 fake（无 opencode 门面/轮询私有方法）。"""

    engine_name = "fake"
    model_id = "fake-model"

    def __init__(self) -> None:
        self.created_titles: list[str] = []
        self.run_calls: list[dict] = []
        self.aborted: list[str] = []
        self.deleted: list[str] = []
        self.run_result = EngineRunResult(
            session_id="",
            reply_text="分片完成",
            trace={"sessionId": "", "status": "received"},
        )
        self.run_error: Exception | None = None

    async def create_session(self, title: str) -> str:
        self.created_titles.append(title)
        return "fake-ses-1"

    async def run_session(self, session_id, prompt_text, **kwargs):
        self.run_calls.append({"session_id": session_id, "prompt": prompt_text, **kwargs})
        if self.run_error is not None:
            raise self.run_error
        self.run_result.session_id = session_id
        self.run_result.trace["sessionId"] = session_id
        return self.run_result

    async def list_messages(self, session_id: str) -> list[dict]:
        return []

    async def abort_session(self, session_id: str) -> bool:
        self.aborted.append(session_id)
        return True

    async def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)


class OrchestratorShardProtocolPathTests(unittest.IsolatedAsyncioTestCase):
    """S1 分片链路（run_tender_parse_shard_with_trace）只经协议方法驱动引擎。"""

    async def test_shard_runs_via_protocol_and_recycles_session(self) -> None:
        engine = _FakeProtocolEngine()
        orchestrator = AgentOrchestrator(engine)
        ready: list[dict] = []

        result = await orchestrator.run_tender_parse_shard_with_trace(
            "分片 prompt",
            title="S1 技术标解析 · 分片A",
            session_ready_callback=ready.append,
        )

        self.assertEqual(engine.created_titles, ["S1 技术标解析 · 分片A"])
        self.assertEqual(len(engine.run_calls), 1)
        call = engine.run_calls[0]
        self.assertEqual(call["session_id"], "fake-ses-1")
        self.assertEqual(call["prompt"], "分片 prompt")
        self.assertIsNone(call["on_tool_completed"], "分片链路不挂提前完成计划")
        self.assertIsNotNone(call["stream_callback"])
        self.assertEqual(engine.deleted, ["fake-ses-1"], "终态必须回收会话")
        self.assertEqual(result, {"opencodeOutput": {"sessionId": "fake-ses-1", "status": "received"}})
        # 无 provider_id 属性的协议引擎回退引擎名
        self.assertEqual(
            ready,
            [{"sessionId": "fake-ses-1", "providerId": "fake", "modelId": "fake-model"}],
        )

    async def test_shard_cancel_aborts_and_recycles(self) -> None:
        engine = _FakeProtocolEngine()
        orchestrator = AgentOrchestrator(engine)

        with self.assertRaises(ParseCancelledError):
            await orchestrator.run_tender_parse_shard_with_trace(
                "prompt",
                cancel_check=lambda: True,
            )

        self.assertEqual(engine.aborted, ["fake-ses-1"])
        self.assertEqual(engine.deleted, ["fake-ses-1"])
        self.assertEqual(engine.run_calls, [], "取消在 run 前发生，不得发起会话运行")

    async def test_shard_failure_still_recycles_session(self) -> None:
        engine = _FakeProtocolEngine()
        engine.run_error = RuntimeError("引擎失败")
        orchestrator = AgentOrchestrator(engine)

        with self.assertRaisesRegex(RuntimeError, "引擎失败"):
            await orchestrator.run_tender_parse_shard_with_trace("prompt")

        self.assertEqual(engine.deleted, ["fake-ses-1"])


class OpencodeEngineRunSessionTests(unittest.IsolatedAsyncioTestCase):
    """OpencodeEngine.run_session：协议语义（EngineRunResult）与失败显式抛出。"""

    async def test_run_session_returns_engine_run_result(self) -> None:
        client = OpencodeEngine()
        bash_message = {
            "info": {"role": "assistant", "id": "m1"},
            "parts": [
                {
                    "type": "tool",
                    "tool": "bash",
                    "id": "p1",
                    "state": {
                        "status": "completed",
                        "input": {"command": "s1parse submit /m.json"},
                        "exit": 0,
                        "output": '{"ok":true}',
                    },
                }
            ],
        }
        with (
            patch.object(client, "create_session", return_value="ses-run"),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={"parts": [{"type": "text", "text": "回复文本"}]},
            ) as polling,
            patch.object(client, "_best_effort_messages", return_value=[bash_message]),
        ):
            session_id = await client.create_session("t")
            result = await client.run_session(session_id, "prompt")

        polling.assert_awaited_once()
        kwargs = polling.await_args.kwargs
        self.assertIsNone(kwargs["early_completion"], "无回调时不构造提前完成计划")
        self.assertIsInstance(result, EngineRunResult)
        self.assertEqual(result.session_id, "ses-run")
        self.assertEqual(result.reply_text, "回复文本")
        self.assertEqual([event.command for event in result.tool_outputs], ["s1parse submit /m.json"])
        self.assertEqual(result.trace["sessionId"], "ses-run")
        self.assertEqual(result.trace["status"], "received")

    async def test_run_session_builds_minimal_plan_from_callback(self) -> None:
        client = OpencodeEngine()
        captured: dict = {}

        async def fake_polling(_session_id, _prompt, **kwargs):
            captured.update(kwargs)
            return {"parts": [{"type": "text", "text": "ok"}]}

        with (
            patch.object(client, "_send_prompt_with_session_polling", side_effect=fake_polling),
            patch.object(client, "_best_effort_messages", return_value=[]),
        ):
            await client.run_session("ses-x", "prompt", on_tool_completed=lambda _e: False)

        plan = captured.get("early_completion")
        self.assertIsInstance(plan, EarlyCompletionPlan)
        self.assertTrue(plan.stop_on_early_complete, "协议收割语义 = 收割即停会话")
        callback = plan.tool_completed_factory()
        event = ToolCompletedEvent(command="c", stdout="o")
        self.assertFalse(callback(event))

    async def test_run_session_raises_on_session_error(self) -> None:
        client = OpencodeEngine()
        error_response = {
            "info": {"error": {"name": "ProviderError", "data": {"message": "模型报错"}}},
            "parts": [],
        }
        with patch.object(
            client,
            "_send_prompt_with_session_polling",
            return_value=error_response,
        ):
            with self.assertRaisesRegex(RuntimeError, "模型报错"):
                await client.run_session("ses-err", "prompt")


class JsonRepairProtocolTests(unittest.IsolatedAsyncioTestCase):
    """json_utils._repair_json_payload：只依赖协议方法，回收 duck-typing 兜底（P3-2）。"""

    async def test_repair_uses_protocol_methods_and_delete_fallback(self) -> None:
        deleted: list[str] = []

        async def fake_create_session(title: str) -> str:
            return "repair-ses"

        async def fake_run_session(session_id: str, prompt: str, **_kwargs) -> EngineRunResult:
            return EngineRunResult(session_id=session_id, reply_text='{"fixed": true}')

        async def fake_delete_session(session_id: str) -> None:
            deleted.append(session_id)

        # 只有协议方法的 fake（无 send_prompt / delete_session_quietly 门面旧名）
        fake_engine = types.SimpleNamespace(
            create_session=fake_create_session,
            run_session=fake_run_session,
            delete_session=fake_delete_session,
        )

        repaired = await json_utils._repair_json_payload(fake_engine, "broken", "assembly")

        self.assertEqual(repaired, '{"fixed": true}')
        self.assertEqual(deleted, ["repair-ses"])

    async def test_repair_delete_failure_does_not_mask_result(self) -> None:
        async def fake_create_session(title: str) -> str:
            return "repair-ses"

        async def fake_run_session(session_id: str, prompt: str, **_kwargs) -> EngineRunResult:
            return EngineRunResult(session_id=session_id, reply_text="{}")

        async def failing_delete(session_id: str) -> None:
            raise RuntimeError("回收失败")

        fake_engine = types.SimpleNamespace(
            create_session=fake_create_session,
            run_session=fake_run_session,
            delete_session=failing_delete,
        )

        with self.assertLogs("app.services.agent_engine.json_utils", level="WARNING"):
            repaired = await json_utils._repair_json_payload(fake_engine, "broken", "wiki")
        self.assertEqual(repaired, "{}")

    async def test_repair_empty_reply_raises(self) -> None:
        fake_engine = types.SimpleNamespace(
            create_session=lambda title: _async_return("repair-ses"),
            run_session=lambda session_id, prompt, **kw: _async_return(
                EngineRunResult(session_id=session_id, reply_text="")
            ),
            delete_session=lambda session_id: _async_return(None),
        )

        with self.assertRaisesRegex(RuntimeError, "无法解析"):
            await json_utils._repair_json_payload(fake_engine, "broken", "outline")


async def _async_return(value):
    return value


if __name__ == "__main__":
    unittest.main()
