"""三条 finalize 链路 + factcurate 特判的表征测试（engine-02）。

全部通过 OpencodeEngine 的公开业务方法驱动，只 mock 最底层 HTTP 原语
（create_session / send_prompt / list_session_messages / abort_session），
锁定以下现有行为，供 A1 重构（on_tool_completed 回调 + finalize 收敛 +
业务编排层上移）前后比对：

- s1parse-finalize / btplnav-finalize / s2outline-finalize 的提前完成收割
  （in-loop 与 prompt 返回后等待两种相位）、idle 超时后的 stalled 异常与 trace。
- factcurate「不提前返回」：bash 工具完成不代表终稿，必须等会话自然完成。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import unittest
from unittest.mock import patch

from app.services.agent_engine.opencode_engine import OpencodeEngine


def _bash_tool_message(
    command: str,
    *,
    output: str,
    status: str = "completed",
    message_id: str = "msg-tool",
    finish: str | None = None,
) -> dict:
    info: dict = {"role": "assistant", "id": message_id}
    if finish is not None:
        info["finish"] = finish
    return {
        "info": info,
        "parts": [
            {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": status,
                    "input": {"command": command},
                    "exit": 0,
                    "output": output,
                },
            }
        ],
    }


_S1_FINALIZE_OUTPUT = (
    '{"schemaVersion":"bid-business-tender-structured-v1",'
    '"outputFile":"/data/parsed/PRJ/s1_structured_result.json",'
    '"summary":{"workflowStage":"finalized"}}'
)
_BTPLNAV_FINALIZE_OUTPUT = (
    '{"schemaVersion":"bid-business-template-extractor-v1",'
    '"outputFile":"/data/parsed/PRJ/business_template_extraction/business_template_extraction.json",'
    '"summary":{"templateCount":11,"warningCount":0}}'
)
_S2_FINALIZE_OUTPUT = (
    '{"schema_version":"technical-outline.v1",'
    '"outputFile":"/data/documents/PRJ/toc.json",'
    '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
)


class FinalizeChainCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    """公开方法级别的表征测试：重构只许改内部结构，不许改这些可观察行为。"""

    # ------------------------------------------------------------------
    # s1parse-finalize
    # ------------------------------------------------------------------
    async def test_s1_finalize_early_completes_through_public_method(self) -> None:
        client = OpencodeEngine()
        stream_events: list[dict] = []

        async def slow_send_prompt(_session_id: str, _prompt: str, **_kwargs: object) -> dict:
            await asyncio.sleep(1.2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            _bash_tool_message(
                "s1parse finalize /data/parsed/PRJ/s1_parse_manifest.json",
                output=_S1_FINALIZE_OUTPUT,
            )
        ]

        with (
            patch.object(client, "create_session", return_value={"id": "ses-s1-early"}),
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
        ):
            started_at = time.monotonic()
            result = await client.generate_tender_parse_with_trace(
                "prompt",
                stream_callback=stream_events.append,
            )

        self.assertLess(time.monotonic() - started_at, 1.2)
        self.assertEqual(result["outputFile"], "/data/parsed/PRJ/s1_structured_result.json")
        self.assertEqual(result["opencodeOutput"]["completionSource"], "s1parse-finalize")
        early_events = [event for event in stream_events if event.get("earlyCompletion")]
        self.assertTrue(early_events)
        self.assertEqual(early_events[-1]["completionSource"], "s1parse-finalize")

    async def test_s1_finalize_waits_after_prompt_return_through_public_method(self) -> None:
        client = OpencodeEngine()
        intermediate = [
            _bash_tool_message(
                "s1parse validate /data/parsed/PRJ/s1_parse_manifest.json",
                output='{"status":"passed"}',
                message_id="msg-validate",
            )
        ]
        finalized = [
            *intermediate,
            _bash_tool_message(
                "s1parse finalize /data/parsed/PRJ/s1_parse_manifest.json",
                output=_S1_FINALIZE_OUTPUT,
                message_id="msg-finalize",
            ),
        ]
        snapshots = iter([intermediate, finalized])

        def list_messages(_session_id: str) -> list[dict]:
            try:
                return next(snapshots)
            except StopIteration:
                return finalized

        with (
            patch.object(client, "create_session", return_value={"id": "ses-s1-wait"}),
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": ""}]}),
            patch.object(client, "list_session_messages", side_effect=list_messages),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            result = await client.generate_tender_parse_with_trace("prompt")

        self.assertEqual(result["outputFile"], "/data/parsed/PRJ/s1_structured_result.json")
        self.assertEqual(result["opencodeOutput"]["completionSource"], "s1parse-finalize")

    async def test_s1_finalize_stall_raises_with_trace_through_public_method(self) -> None:
        client = OpencodeEngine()
        running_messages = [
            {
                "info": {"role": "assistant", "id": "msg-read"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "read",
                        "state": {
                            "status": "running",
                            "input": {"filePath": "/data/parsed/PRJ/document_map.json"},
                        },
                    }
                ],
            }
        ]

        with (
            patch.object(client, "create_session", return_value={"id": "ses-s1-stall"}),
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": ""}]}),
            patch.object(client, "list_session_messages", return_value=running_messages),
            patch.object(client, "_session_polling_idle_timeout", return_value=0.2),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            with self.assertRaises(RuntimeError) as context:
                await client.generate_tender_parse_with_trace("prompt")

        exc = context.exception
        self.assertIn("opencode incomplete/stalled", str(exc))
        trace = getattr(exc, "opencode_trace")
        self.assertEqual(trace["status"], "stalled")
        self.assertEqual(trace["sessionId"], "ses-s1-stall")
        self.assertIn("s1parse finalize", trace["failureReason"])
        self.assertEqual(trace["lastTool"], "read")
        self.assertEqual(trace["lastToolStatus"], "running")

    # ------------------------------------------------------------------
    # btplnav-finalize
    # ------------------------------------------------------------------
    async def test_btplnav_finalize_early_completes_through_public_method(self) -> None:
        client = OpencodeEngine()

        async def slow_send_prompt(_session_id: str, _prompt: str, **_kwargs: object) -> dict:
            await asyncio.sleep(1.2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            _bash_tool_message(
                "btplnav finalize /data/parsed/PRJ/business_template_extraction_manifest.json",
                output=_BTPLNAV_FINALIZE_OUTPUT,
            )
        ]

        with (
            patch.object(client, "create_session", return_value={"id": "ses-btplnav-early"}),
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
        ):
            started_at = time.monotonic()
            result = await client.extract_business_templates_with_trace("prompt")

        self.assertLess(time.monotonic() - started_at, 1.2)
        self.assertEqual(result["summary"]["templateCount"], 11)
        self.assertEqual(result["opencodeOutput"]["completionSource"], "btplnav-finalize")

    async def test_btplnav_finalize_stall_raises_with_trace_through_public_method(self) -> None:
        client = OpencodeEngine()
        running_messages = [
            _bash_tool_message(
                "btplnav read /tmp/manifest.json DOC-1 100 180 --max-chars 4000",
                output="",
                status="running",
                message_id="msg-btplnav-running",
            )
        ]

        with (
            patch.object(client, "create_session", return_value={"id": "ses-btplnav-stall"}),
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": ""}]}),
            patch.object(client, "list_session_messages", return_value=running_messages),
            patch.object(client, "_session_polling_idle_timeout", return_value=0.2),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            with self.assertRaises(RuntimeError) as context:
                await client.extract_business_templates_with_trace("prompt")

        exc = context.exception
        self.assertIn("opencode incomplete/stalled", str(exc))
        trace = getattr(exc, "opencode_trace")
        self.assertEqual(trace["status"], "stalled")
        self.assertIn("btplnav finalize", trace["failureReason"])
        self.assertEqual(trace["lastToolStatus"], "running")

    # ------------------------------------------------------------------
    # s2outline-finalize
    # ------------------------------------------------------------------
    async def test_s2_outline_finalize_early_completes_and_stops_session_through_public_method(self) -> None:
        client = OpencodeEngine()
        release_worker = threading.Event()

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs: object) -> dict:
            await asyncio.to_thread(release_worker.wait, 5)
            return {"parts": [{"type": "text", "text": _S2_FINALIZE_OUTPUT}]}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        messages = [
            _bash_tool_message(
                "s2outline finalize /data/documents/PRJ/s2_input.json",
                output=_S2_FINALIZE_OUTPUT,
                finish="tool-calls",
            )
        ]

        try:
            with (
                patch.object(client, "create_session", return_value={"id": "ses-s2-early"}),
                patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
                patch.object(client, "list_session_messages", return_value=messages),
                patch.object(client, "abort_session", side_effect=abort_session) as abort_mock,
            ):
                started_at = time.monotonic()
                result = await client.generate_outline_with_trace(
                    "prompt",
                    early_tool_command="s2outline-finalize",
                )
        finally:
            release_worker.set()

        self.assertLess(time.monotonic() - started_at, 2.0)
        self.assertEqual(result["outputFile"], "/data/documents/PRJ/toc.json")
        self.assertEqual(result["opencodeOutput"]["completionSource"], "s2outline-finalize")
        abort_mock.assert_called_once_with("ses-s2-early")

    async def test_s2_outline_terminal_validator_harvest_through_public_method(self) -> None:
        client = OpencodeEngine()
        release_worker = threading.Event()
        finalized_payload = {
            "schema_version": "technical-outline.v1",
            "outputFile": "/data/documents/PRJ/toc.json",
            "summary": {"total_nodes": 64, "workflowStage": "finalized"},
        }

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs: object) -> dict:
            await asyncio.to_thread(release_worker.wait, 5)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        messages = [
            _bash_tool_message(
                "s2outline finalize /data/documents/PRJ/s2_input.json",
                output=json.dumps(finalized_payload),
                finish="stop",
            )
        ]

        try:
            with (
                patch.object(client, "create_session", return_value={"id": "ses-s2-validator"}),
                patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
                patch.object(client, "list_session_messages", return_value=messages),
                patch.object(client, "abort_session", side_effect=abort_session) as abort_mock,
            ):
                result = await client.generate_outline_with_trace(
                    "prompt",
                    early_tool_command="s2outline-finalize",
                    terminal_validator=lambda: finalized_payload,
                )
        finally:
            release_worker.set()

        self.assertEqual(result["outputFile"], "/data/documents/PRJ/toc.json")
        self.assertEqual(
            result["opencodeOutput"]["completionSource"],
            "s2outline-terminal-validator",
        )
        abort_mock.assert_called_once_with("ses-s2-validator")

    async def test_s2_outline_finalize_stall_raises_with_trace_through_public_method(self) -> None:
        client = OpencodeEngine()
        running_messages = [
            _bash_tool_message(
                "s2outline section /data/documents/PRJ/s2_input.json TEN-2:S0279",
                output="",
                status="running",
                message_id="msg-s2-running",
            )
        ]

        with (
            patch.object(client, "create_session", return_value={"id": "ses-s2-stall"}),
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": ""}]}),
            patch.object(client, "list_session_messages", return_value=running_messages),
            patch.object(client, "_session_polling_idle_timeout", return_value=0.2),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            with self.assertRaises(RuntimeError) as context:
                await client.generate_outline_with_trace(
                    "prompt",
                    early_tool_command="s2outline-finalize",
                )

        exc = context.exception
        self.assertIn("opencode incomplete/stalled", str(exc))
        trace = getattr(exc, "opencode_trace")
        self.assertEqual(trace["status"], "stalled")
        self.assertIn("s2outline finalize", trace["failureReason"])

    # ------------------------------------------------------------------
    # factcurate 不提前返回
    # ------------------------------------------------------------------
    async def test_factcurate_never_returns_early_through_public_method(self) -> None:
        """factcurate 的建议文件由 LLM 多轮迭代写出（先草稿后填值），脚本完成
        不代表终稿；提前返回会回收草稿并孤儿化会话，必须等会话自然完成。"""
        client = OpencodeEngine()

        async def slow_send_prompt(_session_id: str, _prompt: str, **_kwargs: object) -> dict:
            await asyncio.sleep(1.2)
            return {"parts": [{"type": "text", "text": '{"suggestionsPath":"/tmp/suggestions.json"}'}]}

        messages = [
            _bash_tool_message(
                "factcurate /tmp/fact_curate_input.json",
                output='{"schema":"bid-tech-fact-curate-v1","counts":{"fill":0}}',
            )
        ]

        with (
            patch.object(client, "create_session", return_value={"id": "ses-factcurate"}),
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
        ):
            started_at = time.monotonic()
            result = await client.run_bid_tech_fact_curator_with_trace(
                "prompt",
                early_tool_command="factcurate",
            )

        self.assertGreaterEqual(time.monotonic() - started_at, 1.0)
        self.assertEqual(result["suggestionsPath"], "/tmp/suggestions.json")
        self.assertNotIn("earlyCompletion", result["opencodeOutput"])


if __name__ == "__main__":
    unittest.main()
