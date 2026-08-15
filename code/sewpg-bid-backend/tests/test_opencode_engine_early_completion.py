from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.agent_engine import orchestrator
from app.services.agent_engine.opencode_engine import OpencodeEngine

from opencode_engine_helpers import (
    OpencodeEngineTestBase,
    _accelerated_monotonic,
)


class OpencodeEngineTests(OpencodeEngineTestBase):

    async def test_assistant_stop_validator_releases_a_completed_handoff_request(self) -> None:
        client = OpencodeEngine()
        release_worker = threading.Event()
        stopped_messages = [
            {
                "info": {"role": "assistant", "id": "msg-checkpoint", "finish": "stop"},
                "parts": [
                    {
                        "type": "text",
                        "text": '{"workflowStage":"decision_checkpoint"}',
                    }
                ],
            }
        ]

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            await asyncio.to_thread(release_worker.wait, 5)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        validator = MagicMock(return_value={"complete": False, "decidedCount": 57})
        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "list_session_messages", return_value=stopped_messages),
            patch.object(client, "abort_session", side_effect=abort_session) as abort,
        ):
            response = await client._send_prompt_with_session_polling(
                "ses-checkpoint",
                "prompt",
                stream_callback=MagicMock(),
                assistant_stop_validator=validator,
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "assistant-stop-validator")
        self.assertEqual(response["_assistantStopValidation"]["decidedCount"], 57)
        validator.assert_called_once_with()
        abort.assert_called_once_with("ses-checkpoint")



    async def test_handoff_stops_after_first_completed_decision_batch(self) -> None:
        client = OpencodeEngine()
        release_worker = threading.Event()
        decision_messages = [
            {
                "info": {"role": "assistant", "id": "msg-decision"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": (
                                    "s2outline decision-batch /data/documents/PRJ/s2_input.json "
                                    "'{\"batch_token\":\"batch-1\",\"items\":[]}'"
                                )
                            },
                            "exit": 0,
                            "output": '{"complete":false,"decided_count":29}',
                        },
                    }
                ],
            }
        ]

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            await asyncio.to_thread(release_worker.wait, 5)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "list_session_messages", return_value=decision_messages),
            patch.object(client, "abort_session", side_effect=abort_session) as abort,
        ):
            response = await client._send_prompt_with_session_polling(
                "ses-checkpoint",
                "prompt",
                stream_callback=MagicMock(),
                early_completion=self._plan(client, "s2outline-decision-batch"),
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-decision-batch")
        abort.assert_called_once_with("ses-checkpoint")



    async def test_business_outline_tool_output_never_triggers_early_completion(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            manifest_path = tmpdir / "s2_input.json"
            work_dir = tmpdir / "work"
            work_dir.mkdir()
            (work_dir / "outline.json").write_text(
                json.dumps({"schema_version": "business_bid_outline.v1", "sections": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps({"workDir": str(work_dir), "outputFile": str(work_dir / "toc.json")}, ensure_ascii=False),
                encoding="utf-8",
            )
            messages = [
                {
                    "parts": [
                        {
                            "type": "tool",
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "input": {"command": f"business-outline {manifest_path}"},
                                "exit": 0,
                                "output": '{"schema_version":"business-outline-inputs-v1"}',
                            },
                        }
                    ]
                }
            ]

            output = orchestrator.find_completed_bash_tool_output(messages, "business-outline")
            synthesized = orchestrator._synthesize_tool_response_from_manifest(
                f"business-outline {manifest_path}",
                "business-outline",
            )

        self.assertEqual(output, "")
        self.assertEqual(synthesized, "")



    async def test_build_output_trace_marks_early_wikibuild_completion(self) -> None:
        client = OpencodeEngine()
        response = client._tool_output_response(
            session_id="ses-wiki",
            output='{"summary":"Wiki 已生成","nodes":[]}',
            trace_parts=[{"type": "text", "text": "wikibuild 已完成"}],
        )
        response["_completionSource"] = "wikibuild"

        trace = client._build_output_trace("ses-wiki", response)

        self.assertTrue(trace["earlyCompletion"])
        self.assertEqual(trace["completionSource"], "wikibuild")



    async def test_generate_wiki_blueprint_uses_wikibuild_early_completion(self) -> None:
        client = OpencodeEngine()

        with (
            patch.object(client, "create_session", return_value="ses-wiki"),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={"parts": [{"type": "text", "text": '{"summary":"Wiki 已生成","nodes":[]}'}]},
            ) as send_prompt,
            patch.object(
                client._orchestrator,
                "_extract_wiki_blueprint_json",
                return_value={"summary": "Wiki 已生成", "nodes": []},
            ),
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            await client.generate_wiki_blueprint_with_trace("prompt", stream_callback=lambda _: None)

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_completion"].display_label, "wikibuild")



    async def test_gap_planner_uses_s4gap_early_completion(self) -> None:
        client = OpencodeEngine()

        with (
            patch.object(client, "create_session", return_value="ses-gap"),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                '{"schema_version":"bid-tech-gap-plan-v1",'
                                '"outputFile":"/tmp/gap_plan.json","summary":{},"itemCount":0}'
                            ),
                        }
                    ]
                },
            ) as send_prompt,
            patch.object(
                client._orchestrator,
                "_extract_gap_plan_json",
                return_value={
                    "schema_version": "bid-tech-gap-plan-v1",
                    "outputFile": "/tmp/gap_plan.json",
                },
            ),
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            await client.run_bid_tech_gap_planner_with_trace("prompt")

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_completion"].display_label, "s4gap")



    async def test_generate_tender_parse_uses_s1_finalize_completion(self) -> None:
        client = OpencodeEngine()

        with (
            patch.object(client, "create_session", return_value="ses-s1"),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                '{"schemaVersion":"bid-business-tender-structured-v1",'
                                '"outputFile":"/tmp/s1_structured_result.json",'
                                '"summary":{"workflowStage":"finalized"}}'
                            ),
                        }
                    ]
                },
            ) as send_prompt,
            patch.object(
                client._orchestrator,
                "_extract_tender_parse_json",
                return_value={"outputFile": "/tmp/s1_structured_result.json"},
            ),
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            await client.generate_tender_parse_with_trace("prompt", stream_callback=lambda _: None)

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_completion"].display_label, "s1parse-finalize")



    async def test_s1_parse_raises_session_api_error_before_waiting_for_finalize(self) -> None:
        client = OpencodeEngine()
        messages = [
            {
                "info": {
                    "role": "assistant",
                    "id": "msg-error",
                    "sessionID": "ses-s1-api-error",
                    "providerID": "deepseek",
                    "modelID": "deepseek-v4-pro",
                    "error": {
                        "name": "APIError",
                        "data": {
                            "message": "The `reasoning_content` in the thinking mode must be passed back to the API.",
                            "statusCode": 400,
                        },
                    },
                },
                "parts": [],
            }
        ]

        with (
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": ""}]}),
            patch.object(client, "list_session_messages", return_value=messages),
            patch.object(
                client,
                "_wait_for_early_completion_after_prompt_return",
                side_effect=AssertionError("should fail on session error before waiting for finalize"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "reasoning_content") as context:
                await client._send_prompt_with_session_polling(
                    "ses-s1-api-error",
                    "prompt",
                    early_completion=self._plan(client, "s1parse-finalize"),
                )

        trace = getattr(context.exception, "opencode_trace")
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["agentStatus"], "error")
        self.assertEqual(trace["sessionId"], "ses-s1-api-error")
        self.assertEqual(trace["providerId"], "deepseek")
        self.assertEqual(trace["modelId"], "deepseek-v4-pro")
        self.assertIn("reasoning_content", trace["failureReason"])



    async def test_extract_business_templates_uses_btplnav_finalize_early_completion(self) -> None:
        client = OpencodeEngine()

        with (
            patch.object(client, "create_session", return_value="ses-template-agentic"),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                '{"schemaVersion":"bid-business-template-extractor-v1",'
                                '"outputFile":"/tmp/business_template_extraction.json",'
                                '"summary":{"templateCount":2,"warningCount":0}}'
                            ),
                        }
                    ]
                },
            ) as send_prompt,
            patch.object(client, "_build_output_trace", return_value={"completionSource": "btplnav-finalize"}),
        ):
            result = await client.extract_business_templates_with_trace("prompt")

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_completion"].display_label, "btplnav-finalize")
        self.assertEqual(result["summary"]["templateCount"], 2)
        self.assertEqual(result["opencodeOutput"]["completionSource"], "btplnav-finalize")



    async def test_extract_business_templates_aborts_session_when_cancelled_after_session_ready(self) -> None:
        client = OpencodeEngine()
        ready_events: list[dict[str, str]] = []

        def session_ready(details: dict[str, str]) -> None:
            ready_events.append(details)
            raise ParseCancelledError("解析已取消。")

        with (
            patch.object(client, "create_session", return_value="ses-template-cancel"),
            patch.object(client, "send_prompt") as send_prompt,
            patch.object(client, "abort_session", return_value=True) as abort_session,
        ):
            with self.assertRaisesRegex(ParseCancelledError, "解析已取消"):
                await client.extract_business_templates_with_trace(
                    "prompt",
                    session_ready_callback=session_ready,
                    cancel_check=lambda: True,
                )

        self.assertEqual(ready_events[0]["sessionId"], "ses-template-cancel")
        abort_session.assert_called_once_with("ses-template-cancel")
        send_prompt.assert_not_called()



    async def test_btplnav_finalize_tool_output_is_terminal(self) -> None:
        final_output = (
            '{"schemaVersion":"bid-business-template-extractor-v1",'
            '"outputFile":"/data/parsed/PRJ/business_template_extraction/business_template_extraction.json",'
            '"summary":{"templateCount":2,"warningCount":0}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "btplnav finalize /data/parsed/PRJ/business_template_extraction_manifest.json"},
                            "exit": 0,
                            "output": final_output,
                        },
                    }
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "btplnav-finalize")

        self.assertIn('"templateCount":2', output)



    async def test_btplnav_non_finalize_commands_do_not_trigger_early_completion(self) -> None:
        final_output = (
            '{"schemaVersion":"bid-business-template-extractor-v1",'
            '"outputFile":"/data/parsed/PRJ/business_template_extraction/business_template_extraction.json",'
            '"summary":{"templateCount":2,"warningCount":0}}'
        )
        for command in [
            "btplnav prepare /data/parsed/PRJ/business_template_extraction_manifest.json",
            "btplnav overview /data/parsed/PRJ/business_template_extraction_manifest.json --page 1",
            "btplnav submit /data/parsed/PRJ/business_template_extraction_manifest.json templates /tmp/templates.json",
            "btplnav validate /data/parsed/PRJ/business_template_extraction_manifest.json",
            "btplnav status /data/parsed/PRJ/business_template_extraction_manifest.json",
        ]:
            with self.subTest(command=command):
                messages = [
                    {
                        "parts": [
                            {
                                "type": "tool",
                                "tool": "bash",
                                "state": {
                                    "status": "completed",
                                    "input": {"command": command},
                                    "output": final_output,
                                    "exit": 0,
                                },
                            }
                        ]
                    }
                ]

                output = orchestrator.find_completed_bash_tool_output(messages, "btplnav-finalize")

                self.assertEqual(output, "")



    async def test_btplnav_finalize_requires_terminal_json_output(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "btplnav finalize /data/parsed/PRJ/manifest.json"},
                            "output": '{"status":"waiting","summary":{"templateCount":0}}',
                            "exit": 0,
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "btplnav finalize /data/parsed/PRJ/manifest.json"},
                            "output": (
                                '{"schemaVersion":"bid-business-template-extractor-v1",'
                                '"outputFile":"/data/parsed/PRJ/business_template_extraction/business_template_extraction.json",'
                                '"summary":{"templateCount":2,"warningCount":0}}'
                            ),
                            "exit": 0,
                        },
                    },
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "btplnav-finalize")

        self.assertIn('"outputFile"', output)
        self.assertIn('"templateCount":2', output)



    async def test_s1_finalize_output_is_terminal_only_for_finalized_stage(self) -> None:
        self.assertTrue(
            orchestrator._s1_finalize_output_is_terminal(
                '{"schemaVersion":"bid-business-tender-structured-v1","summary":{"workflowStage":"finalized"}}'
            )
        )
        self.assertFalse(
            orchestrator._s1_finalize_output_is_terminal(
                '{"schemaVersion":"bid-business-tender-structured-v1","summary":{"workflowStage":"failed"}}'
            )
        )
        self.assertFalse(
            orchestrator._s1_finalize_output_is_terminal(
                '{"schemaVersion":"bid-business-tender-structured-v1","summary":{"workflowStage":"prepared"}}'
            )
        )



    async def test_factcurate_never_returns_early(self) -> None:
        """factcurate 不提前返回：建议文件由 LLM 多轮迭代写出（先草稿后填值），
        「脚本完成 / 文件已落地」都不代表终稿——提前返回会回收草稿并孤儿化会话
        （实测三轮三种竞态）。必须等会话自然完成，走正常返回路径。"""
        client = OpencodeEngine()

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(1.2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "factcurate /tmp/fact_curate_input.json"},
                            "exit": 0,
                            "output": '{"schema":"bid-tech-fact-curate-v1","counts":{"fill":0}}',
                        },
                    }
                ]
            }
        ]

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
        ):
            started_at = time.monotonic()
            response = await client._send_prompt_with_session_polling(
                "ses-factcurate",
                "prompt",
                early_completion=self._plan(client, "factcurate"),
            )
            self.assertGreaterEqual(time.monotonic() - started_at, 1.0)
            self.assertNotIn("_earlyCompletion", response)
            self.assertIn('{"late":true}', response["parts"][0]["text"])



    async def test_generate_tender_parse_aborts_session_when_cancelled_after_session_ready(self) -> None:
        client = OpencodeEngine()

        with (
            patch.object(client, "create_session", return_value="ses_cancel_ready_probe"),
            patch.object(client, "send_prompt") as send_prompt,
            patch.object(client, "abort_session", return_value=True) as abort_session,
        ):
            with self.assertRaisesRegex(ParseCancelledError, "解析已取消"):
                await client.generate_tender_parse_with_trace(
                    "prompt",
                    session_ready_callback=lambda _details: (_ for _ in ()).throw(
                        ParseCancelledError("解析已取消。")
                    ),
                    cancel_check=lambda: True,
                )

        abort_session.assert_called_once_with("ses_cancel_ready_probe")
        send_prompt.assert_not_called()



    async def test_s1_parse_does_not_complete_on_prepare_stdout(self) -> None:
        client = OpencodeEngine()

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(1.0)
            return {
                "parts": [
                    {
                        "type": "text",
                        "text": (
                            '{"schemaVersion":"bid-business-tender-structured-v1",'
                            '"outputFile":"/data/parsed/PRJ/s1_structured_result.json",'
                            '"summary":{"workflowStage":"prepared"}}'
                        ),
                    }
                ]
            }

        messages = [
            {
                "info": {"role": "assistant", "id": "msg-prepare"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s1parse /data/parsed/PRJ/s1_parse_manifest.json"},
                            "exit": 0,
                            "output": (
                                '{"schemaVersion":"bid-business-tender-structured-v1",'
                                '"outputFile":"/data/parsed/PRJ/s1_structured_result.json",'
                                '"summary":{"workflowStage":"prepared"}}'
                            ),
                        },
                    }
                ],
            }
        ]

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
            patch("app.services.agent_engine.opencode_engine.settings.opencode_timeout_sec", 1),
            patch("app.services.agent_engine.opencode_engine.time.monotonic", side_effect=_accelerated_monotonic()),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "opencode incomplete/stalled"):
                await client._send_prompt_with_session_polling(
                    "ses-s1",
                    "prompt",
                    early_completion=self._plan(client, "s1parse-finalize"),
                )



    async def test_s1_parse_waits_for_finalize_after_prompt_returns_between_tool_calls(self) -> None:
        client = OpencodeEngine()
        finalize_output = (
            '{"schemaVersion":"bid-business-tender-structured-v1",'
            '"outputFile":"/data/parsed/PRJ/s1_structured_result.json",'
            '"summary":{"workflowStage":"finalized"}}'
        )
        intermediate_messages = [
            {
                "info": {"role": "assistant", "id": "msg-between-tools"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s1parse validate /data/parsed/PRJ/s1_parse_manifest.json"
                            },
                            "exit": 0,
                            "output": '{"status":"passed"}',
                        },
                    }
                ],
            }
        ]
        finalized_messages = [
            *intermediate_messages,
            {
                "info": {"role": "assistant", "id": "msg-finalize"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s1parse finalize /data/parsed/PRJ/s1_parse_manifest.json"},
                            "exit": 0,
                            "output": finalize_output,
                        },
                    }
                ],
            },
        ]
        snapshots = iter([intermediate_messages, finalized_messages])

        def list_messages(session_id: str) -> list[dict]:
            try:
                return next(snapshots)
            except StopIteration:
                return finalized_messages

        with (
            patch.object(client, "send_prompt", return_value={"parts": [{"type": "text", "text": ""}]}),
            patch.object(client, "list_session_messages", side_effect=list_messages) as list_session_messages,
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            response = await client._send_prompt_with_session_polling(
                "ses-s1",
                "prompt",
                early_completion=self._plan(client, "s1parse-finalize"),
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s1parse-finalize")
        self.assertIn('"workflowStage":"finalized"', response["parts"][0]["text"])
        self.assertGreaterEqual(list_session_messages.call_count, 2)



    async def test_btplnav_waits_for_finalize_after_prompt_timeout(self) -> None:
        client = OpencodeEngine()
        finalize_output = (
            '{"schemaVersion":"bid-business-template-extractor-v1",'
            '"outputFile":"/data/parsed/PRJ/business_template_extraction/business_template_extraction.json",'
            '"summary":{"templateCount":11,"warningCount":0}}'
        )
        validation_messages = [
            {
                "info": {"role": "assistant", "id": "msg-validate"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "btplnav validate /data/parsed/PRJ/business_template_extraction_manifest.json"
                            },
                            "exit": 0,
                            "output": '{"status":"passed"}',
                        },
                    }
                ],
            }
        ]
        finalized_messages = [
            *validation_messages,
            {
                "info": {"role": "assistant", "id": "msg-finalize"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "btplnav finalize /data/parsed/PRJ/business_template_extraction_manifest.json"
                            },
                            "exit": 0,
                            "output": finalize_output,
                        },
                    }
                ],
            },
        ]
        snapshots = iter([validation_messages, finalized_messages])

        def list_messages(session_id: str) -> list[dict]:
            try:
                return next(snapshots)
            except StopIteration:
                return finalized_messages

        with (
            patch.object(client, "send_prompt", side_effect=RuntimeError("futurecode 生成超时，请缩短输入或稍后重试。")),
            patch.object(client, "list_session_messages", side_effect=list_messages) as list_session_messages,
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            response = await client._send_prompt_with_session_polling(
                "ses-template-extraction",
                "prompt",
                early_completion=self._plan(client, "btplnav-finalize"),
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "btplnav-finalize")
        self.assertIn('"templateCount":11', response["parts"][0]["text"])
        self.assertGreaterEqual(list_session_messages.call_count, 2)



    async def test_btplnav_stalled_running_tool_reports_trace(self) -> None:
        client = OpencodeEngine()
        messages = [
            {
                "info": {"role": "assistant", "id": "msg-btplnav-running"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "running",
                            "input": {
                                "command": "btplnav read /tmp/manifest.json DOC-1 100 180 --max-chars 4000"
                            },
                        },
                    }
                ],
            }
        ]

        with self.assertRaises(RuntimeError) as context:
            orchestrator._raise_command_stalled(client, "btplnav finalize", "ses-btplnav", messages, 30)

        exc = context.exception
        self.assertIn("opencode incomplete/stalled", str(exc))
        trace = getattr(exc, "opencode_trace")
        self.assertEqual(trace["status"], "stalled")
        self.assertEqual(trace["sessionId"], "ses-btplnav")
        self.assertEqual(trace["lastTool"], "bash")
        self.assertEqual(trace["lastToolStatus"], "running")
        self.assertIn("btplnav read", json.dumps(trace["lastToolInput"], ensure_ascii=False))



    async def test_s1_parse_stalled_running_read_reports_trace(self) -> None:
        client = OpencodeEngine()

        async def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            await asyncio.sleep(2.0)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            {
                "info": {"role": "assistant", "id": "msg-read"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "read",
                        "state": {
                            "status": "running",
                            "input": {"filePath": "/data/parsed/PRJ-0017/document_map.json"},
                        },
                    }
                ],
            }
        ]

        # 异步化后 time.monotonic 被事件循环共享，固定取值表会被循环自身消耗尽；
        # 假时钟每次调用稳定前进 60 秒，引擎的 idle 判定与循环定时器都有限可终止。
        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
            patch("app.services.agent_engine.opencode_engine.settings.opencode_timeout_sec", 1),
            patch("app.services.agent_engine.opencode_engine.time.monotonic", side_effect=_accelerated_monotonic()),
        ):
            with self.assertRaises(RuntimeError) as context:
                await client._send_prompt_with_session_polling(
                    "ses-stalled",
                    "prompt",
                    early_completion=self._plan(client, "s1parse-finalize"),
                )

        exc = context.exception
        self.assertIn("opencode incomplete/stalled", str(exc))
        trace = getattr(exc, "opencode_trace")
        self.assertEqual(trace["status"], "stalled")
        self.assertEqual(trace["sessionId"], "ses-stalled")
        self.assertEqual(trace["lastTool"], "read")
        self.assertEqual(trace["lastToolStatus"], "running")
        self.assertEqual(trace["lastMessageId"], "msg-read")
        self.assertIn("document_map.json", json.dumps(trace["lastToolInput"], ensure_ascii=False))



    async def test_early_tool_output_does_not_repair_traceback_into_outline(self) -> None:
        client = OpencodeEngine()
        response = client._tool_output_response(
            session_id="ses-test",
            output='Traceback (most recent call last):\nzipfile.BadZipFile: File is not a zip file',
            trace_parts=[{"type": "text", "text": "tool failed"}],
        )

        with patch.object(client, "_repair_json_payload") as repair:
            with self.assertRaisesRegex(RuntimeError, "工具输出不是有效 JSON"):
                await client._orchestrator._extract_outline_json(response)

        repair.assert_not_called()



    async def test_completed_early_tool_output_must_be_json(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "wikibuild /tmp/wiki_input.json"},
                            "exit": None,
                            "output": "Traceback (most recent call last):\nzipfile.BadZipFile: File is not a zip file",
                        },
                    }
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "wikibuild")

        self.assertEqual(output, "")
