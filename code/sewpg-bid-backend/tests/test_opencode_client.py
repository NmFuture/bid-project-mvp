from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.bid_parse_cancel import ParseCancelledError
from app.services.opencode_client import OpencodeClient


class OpencodeClientTests(unittest.TestCase):
    def test_extract_outline_json_repairs_invalid_json_once(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": '{"summary":"目录生成完成","nodes":[{"id":"OL-1","title":"项目概况","children":[],}]}',
                }
            ]
        }

        with patch.object(
            client,
            "_repair_json_payload",
            return_value='{"summary":"目录生成完成","nodes":[{"id":"OL-1","title":"项目概况","children":[]}]}',
        ) as repair:
            parsed = client._extract_outline_json(response)

        repair.assert_called_once()
        self.assertEqual(parsed["summary"], "目录生成完成")
        self.assertEqual(parsed["nodes"][0]["title"], "项目概况")

    def test_extract_outline_json_promotes_repair_failure(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": "{invalid json}",
                }
            ]
        }

        with patch.object(
            client,
            "_repair_json_payload",
            side_effect=RuntimeError("修复失败"),
        ) as repair:
            with self.assertRaises(RuntimeError) as context:
                client._extract_outline_json(response)

        repair.assert_called_once()
        self.assertIn("futurecode JSON 解析失败", str(context.exception))

    def test_parse_json_payload_extracts_first_balanced_object_with_required_array(self) -> None:
        content = """
我先说明判断依据：
{not json}
```json
{
  "decisions": [
    {"candidateId": "CAND-0001", "confidence": 0.9}
  ]
}
```
后续说明不应影响解析。
"""

        parsed = OpencodeClient._parse_json_payload(content)

        self.assertEqual(parsed["decisions"][0]["candidateId"], "CAND-0001")

    def test_extract_business_template_extraction_json_repairs_damaged_summary(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"schemaVersion":"bid-business-template-extractor-v1",'
                        '"outputFile":"/tmp/business_template_extraction.json",'
                        '"summary":{"templateCount":"2" broken}}'
                    ),
                }
            ]
        }
        repaired = (
            '{"schemaVersion":"bid-business-template-extractor-v1",'
            '"outputFile":"/tmp/business_template_extraction.json",'
            '"summary":{"templateCount":2,"warningCount":0}}'
        )

        with patch.object(client, "_repair_json_payload", return_value=repaired) as repair:
            parsed = client._extract_business_template_extraction_json(response)

        repair.assert_called_once()
        self.assertEqual(parsed["summary"]["templateCount"], 2)

    def test_extract_business_template_extraction_json_rejects_missing_output_and_summary(self) -> None:
        client = OpencodeClient()
        response = {"parts": [{"type": "text", "text": '{"schemaVersion":"bid-business-template-extractor-v1"}'}]}

        with self.assertRaisesRegex(RuntimeError, "商务模板提取 JSON 结构不正确"):
            client._extract_business_template_extraction_json(response)

    def test_extract_business_template_extraction_json_accepts_summary_only(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '```json\n'
                        '{"schemaVersion":"bid-business-template-extractor-v1",'
                        '"summary":{"templateCount":1,"warningCount":0}}\n'
                        '```'
                    ),
                }
            ]
        }

        parsed = client._extract_business_template_extraction_json(response)

        self.assertEqual(parsed["summary"]["templateCount"], 1)

    def test_extract_outline_json_accepts_v2_toc_items(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"schema_version":"bid-toc-json-v1","summary":{"total_items":1},'
                        '"items":[{"order":1,"number":"第一章","title":"技术方案",'
                        '"level":1,"annotation":"保留","source":"template","reason":""}]}'
                    ),
                }
            ]
        }

        parsed = client._extract_outline_json(response)

        self.assertEqual(parsed["schema_version"], "bid-toc-json-v1")
        self.assertEqual(parsed["items"][0]["title"], "技术方案")

    def test_extract_outline_json_accepts_v2_output_file_summary(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"schema_version":"bid-toc-json-v1","outputFile":'
                        '"/data/documents/PRJ-0001/technical-workspace/s2_toc_workdir/投标文件-总目录.json",'
                        '"summary":{"total_items":659},"itemCount":659}'
                    ),
                }
            ]
        }

        parsed = client._extract_outline_json(response)

        self.assertEqual(parsed["itemCount"], 659)
        self.assertIn("投标文件-总目录.json", parsed["outputFile"])

    def test_find_completed_s2toc_tool_output_ignores_later_running_reads(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2toc /data/documents/PRJ/s2_input.json"},
                            "output": '{"schema_version":"bid-toc-json-v1","outputFile":"/tmp/toc.json"}',
                            "exit": 0,
                        },
                    },
                ],
            },
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "read",
                        "state": {
                            "status": "running",
                            "input": {"filePath": "/tmp/toc.json"},
                        },
                    },
                ],
            },
        ]

        output = OpencodeClient._find_completed_bash_tool_output(messages, "s2toc")

        self.assertIn('"outputFile":"/tmp/toc.json"', output)

    def test_build_output_trace_marks_early_s2_completion(self) -> None:
        client = OpencodeClient()
        response = client._tool_output_response(
            session_id="ses-test",
            output='{"schema_version":"bid-toc-json-v1","outputFile":"/tmp/toc.json"}',
            trace_parts=[{"type": "text", "text": "s2toc 已完成"}],
        )
        response["_completionSource"] = "s2toc"

        trace = client._build_output_trace("ses-test", response)

        self.assertTrue(trace["earlyCompletion"])
        self.assertEqual(trace["completionSource"], "s2toc")
        self.assertEqual(trace["parts"][0]["text"], "s2toc 已完成")

    def test_build_output_trace_marks_early_wikibuild_completion(self) -> None:
        client = OpencodeClient()
        response = client._tool_output_response(
            session_id="ses-wiki",
            output='{"summary":"Wiki 已生成","nodes":[]}',
            trace_parts=[{"type": "text", "text": "wikibuild 已完成"}],
        )
        response["_completionSource"] = "wikibuild"

        trace = client._build_output_trace("ses-wiki", response)

        self.assertTrue(trace["earlyCompletion"])
        self.assertEqual(trace["completionSource"], "wikibuild")

    def test_generate_wiki_blueprint_uses_wikibuild_early_completion(self) -> None:
        client = OpencodeClient()

        with (
            patch.object(client, "create_session", return_value={"id": "ses-wiki"}),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={"parts": [{"type": "text", "text": '{"summary":"Wiki 已生成","nodes":[]}'}]},
            ) as send_prompt,
            patch.object(
                client,
                "_extract_wiki_blueprint_json",
                return_value={"summary": "Wiki 已生成", "nodes": []},
            ),
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            client.generate_wiki_blueprint_with_trace("prompt", stream_callback=lambda _: None)

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_tool_command"], "wikibuild")

    def test_gap_planner_uses_s4gap_early_completion(self) -> None:
        client = OpencodeClient()

        with (
            patch.object(client, "create_session", return_value={"id": "ses-gap"}),
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
                client,
                "_extract_gap_plan_json",
                return_value={
                    "schema_version": "bid-tech-gap-plan-v1",
                    "outputFile": "/tmp/gap_plan.json",
                },
            ),
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            client.run_bid_tech_gap_planner_with_trace("prompt")

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_tool_command"], "s4gap")

    def test_generate_tender_parse_uses_s1_finalize_completion(self) -> None:
        client = OpencodeClient()

        with (
            patch.object(client, "create_session", return_value={"id": "ses-s1"}),
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
                client,
                "_extract_tender_parse_json",
                return_value={"outputFile": "/tmp/s1_structured_result.json"},
            ),
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            client.generate_tender_parse_with_trace("prompt", stream_callback=lambda _: None)

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_tool_command"], "s1parse-finalize")

    def test_s1_parse_raises_session_api_error_before_waiting_for_finalize(self) -> None:
        client = OpencodeClient()
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
                "_wait_for_s1_finalize_after_prompt_return",
                side_effect=AssertionError("should fail on session error before waiting for finalize"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "reasoning_content") as context:
                client._send_prompt_with_session_polling(
                    "ses-s1-api-error",
                    "prompt",
                    early_tool_command="s1parse-finalize",
                )

        trace = getattr(context.exception, "opencode_trace")
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["agentStatus"], "error")
        self.assertEqual(trace["sessionId"], "ses-s1-api-error")
        self.assertEqual(trace["providerId"], "deepseek")
        self.assertEqual(trace["modelId"], "deepseek-v4-pro")
        self.assertIn("reasoning_content", trace["failureReason"])

    def test_extract_business_templates_uses_btplnav_finalize_early_completion(self) -> None:
        client = OpencodeClient()

        with (
            patch.object(client, "create_session", return_value={"id": "ses-template-agentic"}),
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
            result = client.extract_business_templates_with_trace("prompt")

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_tool_command"], "btplnav-finalize")
        self.assertEqual(result["summary"]["templateCount"], 2)
        self.assertEqual(result["opencodeOutput"]["completionSource"], "btplnav-finalize")

    def test_extract_business_templates_aborts_session_when_cancelled_after_session_ready(self) -> None:
        client = OpencodeClient()
        ready_events: list[dict[str, str]] = []

        def session_ready(details: dict[str, str]) -> None:
            ready_events.append(details)
            raise ParseCancelledError("解析已取消。")

        with (
            patch.object(client, "create_session", return_value={"id": "ses-template-cancel"}),
            patch.object(client, "send_prompt") as send_prompt,
            patch.object(client, "abort_session", return_value=True) as abort_session,
        ):
            with self.assertRaisesRegex(ParseCancelledError, "解析已取消"):
                client.extract_business_templates_with_trace(
                    "prompt",
                    session_ready_callback=session_ready,
                    cancel_check=lambda: True,
                )

        self.assertEqual(ready_events[0]["sessionId"], "ses-template-cancel")
        abort_session.assert_called_once_with("ses-template-cancel")
        send_prompt.assert_not_called()

    def test_btplnav_finalize_tool_output_is_terminal(self) -> None:
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

        output = OpencodeClient._find_completed_bash_tool_output(messages, "btplnav-finalize")

        self.assertIn('"templateCount":2', output)

    def test_btplnav_non_finalize_commands_do_not_trigger_early_completion(self) -> None:
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

                output = OpencodeClient._find_completed_bash_tool_output(messages, "btplnav-finalize")

                self.assertEqual(output, "")

    def test_btplnav_finalize_requires_terminal_json_output(self) -> None:
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

        output = OpencodeClient._find_completed_bash_tool_output(messages, "btplnav-finalize")

        self.assertIn('"outputFile"', output)
        self.assertIn('"templateCount":2', output)

    def test_extract_tender_parse_json_rejects_prepared_workflow_stage(self) -> None:
        client = OpencodeClient()
        response = {
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

        with self.assertRaisesRegex(RuntimeError, "prepared"):
            client._extract_tender_parse_json(response)

    def test_s1_finalize_output_is_terminal_only_for_finalized_stage(self) -> None:
        self.assertTrue(
            OpencodeClient._s1_finalize_output_is_terminal(
                '{"schemaVersion":"bid-business-tender-structured-v1","summary":{"workflowStage":"finalized"}}'
            )
        )
        self.assertFalse(
            OpencodeClient._s1_finalize_output_is_terminal(
                '{"schemaVersion":"bid-business-tender-structured-v1","summary":{"workflowStage":"failed"}}'
            )
        )
        self.assertFalse(
            OpencodeClient._s1_finalize_output_is_terminal(
                '{"schemaVersion":"bid-business-tender-structured-v1","summary":{"workflowStage":"prepared"}}'
            )
        )

    def test_polling_can_early_complete_without_stream_callback(self) -> None:
        client = OpencodeClient()

        def slow_send_prompt(session_id: str, prompt_text: str) -> dict:
            time.sleep(2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s4gap /tmp/s4_gap_input.json"},
                            "exit": 0,
                            "output": (
                                '{"schema_version":"bid-tech-gap-plan-v1",'
                                '"outputFile":"/tmp/gap_plan.json","summary":{},"itemCount":0}'
                            ),
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
            response = client._send_prompt_with_session_polling(
                "ses-gap",
                "prompt",
                early_tool_command="s4gap",
            )

        self.assertLess(time.monotonic() - started_at, 1.5)
        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s4gap")
        self.assertIn("bid-tech-gap-plan-v1", response["parts"][0]["text"])

    def test_polling_emits_heartbeat_when_snapshot_does_not_change(self) -> None:
        client = OpencodeClient()
        events: list[dict] = []

        def slow_send_prompt(session_id: str, prompt_text: str) -> dict:
            time.sleep(1.2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        messages = [
            {
                "info": {"role": "assistant", "id": "msg-working"},
                "parts": [{"type": "text", "text": "working"}],
            }
        ]

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
            patch("app.services.opencode_client.OPENCODE_PROGRESS_HEARTBEAT_SECONDS", 0.1),
        ):
            client._send_prompt_with_session_polling(
                "ses-heartbeat",
                "prompt",
                stream_callback=events.append,
            )

        heartbeat_events = [event for event in events if event.get("heartbeat")]
        self.assertTrue(heartbeat_events)
        self.assertGreaterEqual(heartbeat_events[-1]["idleSeconds"], 1)
        self.assertGreaterEqual(heartbeat_events[-1]["elapsedSeconds"], heartbeat_events[-1]["idleSeconds"])
        self.assertEqual(heartbeat_events[-1]["sessionId"], "ses-heartbeat")

    def test_polling_aborts_session_when_cancel_requested(self) -> None:
        client = OpencodeClient()

        def slow_send_prompt(session_id: str, prompt_text: str) -> dict:
            time.sleep(2)
            return {"parts": [{"type": "text", "text": '{"late":true}'}]}

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "abort_session", return_value=True) as abort_session,
        ):
            with self.assertRaisesRegex(RuntimeError, "解析已取消"):
                client._send_prompt_with_session_polling(
                    "ses_cancel_polling_probe",
                    "prompt",
                    early_tool_command="s1parse-finalize",
                    cancel_check=lambda: True,
                )

        abort_session.assert_called_once_with("ses_cancel_polling_probe")

    def test_generate_tender_parse_aborts_session_when_cancelled_after_session_ready(self) -> None:
        client = OpencodeClient()

        with (
            patch.object(client, "create_session", return_value={"id": "ses_cancel_ready_probe"}),
            patch.object(client, "send_prompt") as send_prompt,
            patch.object(client, "abort_session", return_value=True) as abort_session,
        ):
            with self.assertRaisesRegex(ParseCancelledError, "解析已取消"):
                client.generate_tender_parse_with_trace(
                    "prompt",
                    session_ready_callback=lambda _details: (_ for _ in ()).throw(
                        ParseCancelledError("解析已取消。")
                    ),
                    cancel_check=lambda: True,
                )

        abort_session.assert_called_once_with("ses_cancel_ready_probe")
        send_prompt.assert_not_called()

    def test_s1_parse_does_not_complete_on_prepare_stdout(self) -> None:
        client = OpencodeClient()

        def slow_send_prompt(session_id: str, prompt_text: str) -> dict:
            time.sleep(1.0)
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
            patch("app.services.opencode_client.settings.opencode_timeout_sec", 1),
            patch("app.services.opencode_client.time.monotonic", side_effect=[0.0, 121.0, 242.0]),
            patch("app.services.opencode_client.time.sleep", return_value=None),
            patch.object(client, "_raise_s1_opencode_stalled", side_effect=RuntimeError("opencode incomplete/stalled")),
        ):
            with self.assertRaisesRegex(RuntimeError, "opencode incomplete/stalled"):
                client._send_prompt_with_session_polling(
                    "ses-s1",
                    "prompt",
                    early_tool_command="s1parse-finalize",
                )

    def test_s1_parse_waits_for_finalize_after_prompt_returns_between_tool_calls(self) -> None:
        client = OpencodeClient()
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
            patch("app.services.opencode_client.time.sleep", return_value=None),
        ):
            response = client._send_prompt_with_session_polling(
                "ses-s1",
                "prompt",
                early_tool_command="s1parse-finalize",
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s1parse-finalize")
        self.assertIn('"workflowStage":"finalized"', response["parts"][0]["text"])
        self.assertGreaterEqual(list_session_messages.call_count, 2)

    def test_btplnav_waits_for_finalize_after_prompt_timeout(self) -> None:
        client = OpencodeClient()
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
            patch("app.services.opencode_client.time.sleep", return_value=None),
        ):
            response = client._send_prompt_with_session_polling(
                "ses-template-extraction",
                "prompt",
                early_tool_command="btplnav-finalize",
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "btplnav-finalize")
        self.assertIn('"templateCount":11', response["parts"][0]["text"])
        self.assertGreaterEqual(list_session_messages.call_count, 2)

    def test_btplnav_stalled_running_tool_reports_trace(self) -> None:
        client = OpencodeClient()
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
            client._raise_template_finalize_opencode_stalled("ses-btplnav", messages, 30)

        exc = context.exception
        self.assertIn("opencode incomplete/stalled", str(exc))
        trace = getattr(exc, "opencode_trace")
        self.assertEqual(trace["status"], "stalled")
        self.assertEqual(trace["sessionId"], "ses-btplnav")
        self.assertEqual(trace["lastTool"], "bash")
        self.assertEqual(trace["lastToolStatus"], "running")
        self.assertIn("btplnav read", json.dumps(trace["lastToolInput"], ensure_ascii=False))

    def test_s1_parse_stalled_running_read_reports_trace(self) -> None:
        client = OpencodeClient()

        def slow_send_prompt(session_id: str, prompt_text: str) -> dict:
            time.sleep(2.0)
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

        with (
            patch.object(client, "send_prompt", side_effect=slow_send_prompt),
            patch.object(client, "list_session_messages", return_value=messages),
            patch("app.services.opencode_client.settings.opencode_timeout_sec", 1),
            patch("app.services.opencode_client.time.monotonic", side_effect=[0.0, 0.0, 121.0]),
        ):
            with self.assertRaises(RuntimeError) as context:
                client._send_prompt_with_session_polling(
                    "ses-stalled",
                    "prompt",
                    early_tool_command="s1parse-finalize",
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

    def test_early_s2_tool_output_does_not_repair_traceback_into_outline(self) -> None:
        client = OpencodeClient()
        response = client._tool_output_response(
            session_id="ses-test",
            output='Traceback (most recent call last):\nzipfile.BadZipFile: File is not a zip file',
            trace_parts=[{"type": "text", "text": "s2toc failed"}],
        )

        with patch.object(client, "_repair_json_payload") as repair:
            with self.assertRaisesRegex(RuntimeError, "工具输出不是有效 JSON"):
                client._extract_outline_json(response)

        repair.assert_not_called()

    def test_completed_s2_tool_output_must_be_json(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2toc /tmp/s2_input.json"},
                            "exit": None,
                            "output": "Traceback (most recent call last):\nzipfile.BadZipFile: File is not a zip file",
                        },
                    }
                ]
            }
        ]

        output = OpencodeClient._find_completed_bash_tool_output(messages, "s2toc")

        self.assertEqual(output, "")

    def test_business_outline_tool_output_never_triggers_early_completion(self) -> None:
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

            output = OpencodeClient._find_completed_bash_tool_output(messages, "business-outline")
            synthesized = OpencodeClient._synthesize_tool_response_from_manifest(
                f"business-outline {manifest_path}",
                "business-outline",
            )

        self.assertEqual(output, "")
        self.assertEqual(synthesized, "")

    def test_extract_wiki_blueprint_json_accepts_valid_payload(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"summary":"Wiki 已生成","rootTitle":"技术标Wiki（自动生成）",'
                        '"nodes":[{"title":"00-Wiki使用说明","markdownContent":"# 说明",'
                        '"tags":["技术标","素材库"],"applicableTypes":["技术标"],"children":[]}]}'
                    ),
                }
            ]
        }

        parsed = client._extract_wiki_blueprint_json(response)

        self.assertEqual(parsed["summary"], "Wiki 已生成")
        self.assertEqual(parsed["nodes"][0]["title"], "00-Wiki使用说明")

    def test_extract_wiki_blueprint_json_accepts_output_file_summary(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"schema_version":"bid-wiki-blueprint-v1","outputFile":'
                        '"/data/parsed/_wiki_build/run/wiki_blueprint.json",'
                        '"summary":"Wiki 已生成","materialCount":93}'
                    ),
                }
            ]
        }

        parsed = client._extract_wiki_blueprint_json(response)

        self.assertEqual(parsed["summary"], "Wiki 已生成")
        self.assertIn("wiki_blueprint.json", parsed["outputFile"])

    def test_extract_wiki_blueprint_json_repairs_invalid_json_once(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": '{"summary":"Wiki 已生成","nodes":[{"title":"00-Wiki使用说明",}]}',
                }
            ]
        }

        with patch.object(
            client,
            "_repair_json_payload",
            return_value='{"summary":"Wiki 已生成","nodes":[{"title":"00-Wiki使用说明","children":[]}]}',
        ) as repair:
            parsed = client._extract_wiki_blueprint_json(response)

        repair.assert_called_once()
        self.assertEqual(parsed["nodes"][0]["title"], "00-Wiki使用说明")

    def test_extract_gap_plan_json_accepts_output_file_summary(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"schema_version":"bid-tech-gap-plan-v1","outputFile":'
                        '"/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/gap_plan.json",'
                        '"summary":{"totalTocItems":3,"matchedCount":1,"missingCount":1,'
                        '"resolvedCount":0,"ignoredCount":0,"structuralCount":1,'
                        '"fillableTaskCount":1,"blockingCount":1},"itemCount":3}'
                    ),
                }
            ]
        }

        parsed = client._extract_gap_plan_json(response)

        self.assertEqual(parsed["schema_version"], "bid-tech-gap-plan-v1")
        self.assertIn("gap_plan.json", parsed["outputFile"])
