from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import httpx

from app.core.config import settings
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.opencode_client import OpencodeClient
from app.services.system_settings import system_settings_service


def _db_llm_config(**overrides: object) -> dict:
    config = {
        "enabled": True,
        "providerId": "custom-provider",
        "modelId": "custom-model",
        "model": "custom-model",
        "baseUrl": "https://llm.example.com/v1",
        "opencodeBaseUrl": "http://db-opencode:4096",
        "timeoutMs": 30000,
    }
    config.update(overrides)
    return config


class OpencodeClientTests(unittest.TestCase):
    @staticmethod
    def _http_client_with_post_side_effect(side_effect: object) -> MagicMock:
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.side_effect = side_effect
        return client

    def test_init_uses_db_config_when_llm_active(self) -> None:
        with patch.object(
            system_settings_service,
            "get_opencode_model_config_sync",
            return_value=_db_llm_config(),
        ):
            client = OpencodeClient()
        self.assertEqual(client.base_url, "http://db-opencode:4096")
        self.assertEqual(client.provider_id, "custom-provider")
        self.assertEqual(client.model_id, "custom-model")

    def test_init_falls_back_to_env_config_when_llm_not_active(self) -> None:
        for config in (
            _db_llm_config(enabled=False),
            _db_llm_config(baseUrl=""),
        ):
            with self.subTest(config=config), patch.object(
                system_settings_service,
                "get_opencode_model_config_sync",
                return_value=config,
            ):
                client = OpencodeClient()
            self.assertEqual(client.base_url, settings.opencode_base_url.rstrip("/"))
            self.assertEqual(client.provider_id, settings.opencode_provider_id)
            self.assertEqual(client.model_id, settings.opencode_model_id)

    def test_repair_examples_keep_technical_reports_empty_and_business_reports_unchanged(self) -> None:
        client = OpencodeClient()
        prompts: list[str] = []

        def fake_send_prompt(_session_id: str, prompt: str) -> dict:
            prompts.append(prompt)
            return {"parts": [{"type": "text", "text": "{}"}]}

        with (
            patch.object(client, "create_session", return_value={"id": "repair"}),
            patch.object(client, "send_prompt", side_effect=fake_send_prompt),
        ):
            client._repair_json_payload("broken", "assembly")
            client._repair_json_payload("broken", "business_format")

        technical_prompt, business_prompt = prompts
        self.assertIn('"assemblyReport":""', technical_prompt)
        self.assertIn('"needsReview":""', technical_prompt)
        self.assertIn('"summary":', technical_prompt)
        self.assertIn('"warnings":[', technical_prompt)
        self.assertNotIn("assembly_report.md", technical_prompt)
        self.assertNotIn("needs_review.md", technical_prompt)
        self.assertIn("business_format_clean_report.md", business_prompt)

    def test_constructor_uses_supplied_model_config_without_loading_system_settings(self) -> None:
        model_config = _db_llm_config(
            opencodeBaseUrl="http://configured-opencode:4096",
            providerId="configured-provider",
            modelId="configured-model",
            timeoutMs=45000,
        )

        with patch(
            "app.services.opencode_client.system_settings_service.get_opencode_model_config_sync"
        ) as load_config:
            client = OpencodeClient(model_config=model_config)

        load_config.assert_not_called()
        self.assertEqual(client.base_url, "http://configured-opencode:4096")
        self.assertEqual(client.provider_id, "configured-provider")
        self.assertEqual(client.model_id, "configured-model")
        self.assertEqual(client.timeout.read, 45.0)

    def test_constructor_falls_back_when_supplied_model_config_is_inactive(self) -> None:
        model_config = _db_llm_config(enabled=False)

        with patch(
            "app.services.opencode_client.system_settings_service.get_opencode_model_config_sync"
        ) as load_config:
            client = OpencodeClient(model_config=model_config)

        load_config.assert_not_called()
        self.assertEqual(client.base_url, settings.opencode_base_url.rstrip("/"))
        self.assertEqual(client.provider_id, settings.opencode_provider_id)
        self.assertEqual(client.model_id, settings.opencode_model_id)

    def test_create_session_retries_connection_refused_until_service_recovers(self) -> None:
        client = OpencodeClient()
        request = httpx.Request("POST", "http://opencode:4096/session")
        response = MagicMock()
        response.json.return_value = {"id": "ses-recovered"}
        http_client = self._http_client_with_post_side_effect(
            [
                httpx.ConnectError("[Errno 111] Connection refused", request=request),
                httpx.ConnectError("[Errno 111] Connection refused", request=request),
                response,
            ]
        )

        with (
            patch("app.services.opencode_client.httpx.Client", return_value=http_client),
            patch("app.services.opencode_client.time.sleep") as sleep,
        ):
            session = client.create_session("技术标素材预览")

        self.assertEqual(session["id"], "ses-recovered")
        self.assertEqual(http_client.post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

    def test_create_session_retries_transient_service_unavailable(self) -> None:
        client = OpencodeClient()
        request = httpx.Request("POST", "http://opencode:4096/session")
        unavailable = httpx.Response(503, request=request)
        recovered = MagicMock()
        recovered.json.return_value = {"id": "ses-after-503"}
        http_client = self._http_client_with_post_side_effect([unavailable, recovered])

        with (
            patch("app.services.opencode_client.httpx.Client", return_value=http_client),
            patch("app.services.opencode_client.time.sleep") as sleep,
        ):
            session = client.create_session("技术标素材预览")

        self.assertEqual(session["id"], "ses-after-503")
        self.assertEqual(http_client.post.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_create_session_reports_error_after_transient_retry_budget_exhausted(self) -> None:
        client = OpencodeClient()
        request = httpx.Request("POST", "http://opencode:4096/session")
        http_client = self._http_client_with_post_side_effect(
            httpx.ConnectError("[Errno 111] Connection refused", request=request)
        )

        with (
            patch("app.services.opencode_client.httpx.Client", return_value=http_client),
            patch("app.services.opencode_client.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "Connection refused"):
                client.create_session("技术标素材预览")

        self.assertEqual(http_client.post.call_count, 7)
        self.assertEqual(sleep.call_count, 6)

    def test_create_session_does_not_retry_non_transient_http_error(self) -> None:
        client = OpencodeClient()
        request = httpx.Request("POST", "http://opencode:4096/session")
        response = httpx.Response(400, request=request)
        http_client = self._http_client_with_post_side_effect([response])

        with (
            patch("app.services.opencode_client.httpx.Client", return_value=http_client),
            patch("app.services.opencode_client.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "400 Bad Request"):
                client.create_session("技术标素材预览")

        self.assertEqual(http_client.post.call_count, 1)
        sleep.assert_not_called()

    def test_send_prompt_includes_explicit_tool_overrides(self) -> None:
        client = OpencodeClient(
            base_url="http://opencode:4096",
            provider_id="provider-test",
            model_id="model-test",
        )
        response = MagicMock()
        response.text = '{"parts": []}'
        response.json.return_value = {"parts": []}
        http_client = self._http_client_with_post_side_effect(response)
        tool_overrides = {"bash": False, "read": False, "write": False}

        with patch("app.services.opencode_client.httpx.Client", return_value=http_client):
            client.send_prompt("session-safe", "只返回文字", tools=tool_overrides)

        payload = http_client.post.call_args.kwargs["json"]
        self.assertEqual(payload["tools"], tool_overrides)

    def test_send_text_prompt_omits_tool_overrides_by_default(self) -> None:
        client = OpencodeClient()

        with patch.object(
            client,
            "create_session",
            return_value={"id": "session-default-tools"},
        ), patch.object(
            client,
            "send_prompt",
            return_value={"parts": [{"type": "text", "text": "普通回复"}]},
        ) as send_prompt:
            client.send_text_prompt("普通任务", "继续执行")

        send_prompt.assert_called_once_with("session-default-tools", "继续执行")

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

    def test_generate_outline_with_trace_defaults_to_no_early_tool_completion(self) -> None:
        client = OpencodeClient()

        with (
            patch.object(client, "create_session", return_value={"id": "ses-outline"}),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                '{"schema_version":"bid-toc-json-v1",'
                                '"summary":{"total_items":0},"items":[]}'
                            ),
                        }
                    ]
                },
            ) as send_prompt,
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            result = client.generate_outline_with_trace("prompt")

        send_prompt.assert_called_once()
        self.assertEqual(send_prompt.call_args.kwargs["early_tool_command"], "")
        self.assertEqual(result["schema_version"], "bid-toc-json-v1")

    def test_run_outline_decision_session_uses_persisted_chapter_completion(self) -> None:
        client = OpencodeClient()
        validator = MagicMock(return_value={"complete": True, "decidedCount": 18})
        with (
            patch.object(client, "create_session", return_value={"id": "ses-chapter-1"}),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={"parts": [{"type": "text", "text": "done"}]},
            ) as send_prompt,
            patch.object(
                client,
                "_build_output_trace",
                return_value={"status": "received", "sessionId": "ses-chapter-1"},
            ),
        ):
            result = client.run_outline_decision_session(
                "chapter prompt",
                session_title="S2 目录决策·第一章",
                completion_validator=validator,
            )

        self.assertEqual(result["sessionId"], "ses-chapter-1")
        self.assertTrue(result["state"]["complete"])
        self.assertEqual(send_prompt.call_args.kwargs["early_tool_command"], "")
        self.assertTrue(callable(send_prompt.call_args.kwargs["assistant_stop_validator"]))

    def test_generate_outline_with_trace_uses_fresh_sessions_for_bounded_handoffs(self) -> None:
        client = OpencodeClient()
        final_response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"schema_version":"bid-toc-json-v1",'
                        '"summary":{"total_items":1},'
                        '"items":[{"title":"技术方案"}]}'
                    ),
                }
            ]
        }

        with (
            patch.object(
                client,
                "create_session",
                side_effect=[
                    {"id": "ses-checkpoint-1"},
                    {"id": "ses-checkpoint-2"},
                    {"id": "ses-final"},
                ],
            ) as create_session,
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                side_effect=[
                    {"parts": [{"type": "text", "text": '{"checkpoint":1}'}]},
                    {"parts": [{"type": "text", "text": '{"checkpoint":2}'}]},
                    final_response,
                ],
            ) as send_prompt,
            patch.object(
                client,
                "_build_output_trace",
                return_value={"status": "received", "sessionId": "ses-final"},
            ),
        ):
            result = client.generate_outline_with_trace(
                "final prompt",
                early_tool_command="s2outline-finalize",
                handoff_prompt_factory=lambda index: f"checkpoint prompt {index}",
                handoff_state_callback=MagicMock(
                    side_effect=[
                        {"complete": False, "decidedCount": 6},
                        {"complete": True, "decidedCount": 10},
                    ]
                ),
            )

        self.assertEqual(create_session.call_count, 3)
        self.assertEqual(
            [call.args[1] for call in send_prompt.call_args_list],
            ["checkpoint prompt 1", "checkpoint prompt 2", "final prompt"],
        )
        self.assertEqual(
            [call.kwargs["early_tool_command"] for call in send_prompt.call_args_list],
            ["s2outline-decision-batch", "s2outline-decision-batch", "s2outline-finalize"],
        )
        self.assertEqual(
            result["opencodeOutput"]["sessionIds"],
            ["ses-checkpoint-1", "ses-checkpoint-2", "ses-final"],
        )
        self.assertEqual(result["opencodeOutput"]["handoffSessionCount"], 2)

    def test_assistant_stop_validator_releases_a_completed_handoff_request(self) -> None:
        client = OpencodeClient()
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

        def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            release_worker.wait(timeout=5)
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
            response = client._send_prompt_with_session_polling(
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

    def test_handoff_stops_after_first_completed_decision_batch(self) -> None:
        client = OpencodeClient()
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

        def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            release_worker.wait(timeout=5)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "list_session_messages", return_value=decision_messages),
            patch.object(client, "abort_session", side_effect=abort_session) as abort,
        ):
            response = client._send_prompt_with_session_polling(
                "ses-checkpoint",
                "prompt",
                stream_callback=MagicMock(),
                early_tool_command="s2outline-decision-batch",
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-decision-batch")
        abort.assert_called_once_with("ses-checkpoint")

    def test_s2_outline_finalize_tool_output_is_terminal(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"},
                            "exit": 0,
                            "output": final_output,
                        },
                    }
                ]
            }
        ]

        output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertIn('"total_nodes":64', output)

    def test_s2_outline_terminal_output_rejects_noncanonical_agent_commands(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        commands = [
            (
                "cd /workspace/.opencode/skills/bid-tech-outline-generator && "
                "python3 -m scripts.run_from_manifest finalize "
                "/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json 2>&1"
            ),
            (
                "python3 /workspace/.opencode/skills/bid-tech-outline-generator/"
                "scripts/run_from_manifest.py finalize "
                "/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
            ),
            "python3 /opt/agent-tools/custom_outline_writer.py --project PRJ",
        ]

        for command in commands:
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
                                    "exit": 0,
                                    "output": final_output,
                                },
                            }
                        ]
                    }
                ]

                output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

                self.assertEqual(output, "")

    def test_s2_outline_terminal_output_rejects_finalize_command_suffixes(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        manifest = "/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
        commands = [
            f"s2outline finalize {manifest} && python3 /tmp/fake.py",
            f"s2outline finalize {manifest} || python3 /tmp/fake.py",
            f"s2outline finalize {manifest} ; python3 /tmp/fake.py",
            f"s2outline finalize {manifest};true",
            f"s2outline finalize {manifest}>/tmp/final.json",
            f"/tmp/s2outline finalize {manifest}",
            f"s2outline finalize {manifest} --force",
            f"s2outline finalize {manifest} 2>&1",
        ]

        for command in commands:
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
                                    "exit": 0,
                                    "output": final_output,
                                },
                            }
                        ]
                    }
                ]

                output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

                self.assertEqual(output, "")

    def test_s2_outline_terminal_output_accepts_tool_metadata_stdout(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
                            },
                            "metadata": {"exit": 0, "output": final_output},
                        },
                    }
                ]
            }
        ]

        output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertIn('"workflowStage":"finalized"', output)

    def test_s2_outline_terminal_output_requires_bash_tool_name(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "agent-outline-writer",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
                            },
                            "metadata": {"exit": 0, "output": final_output},
                        },
                    }
                ]
            }
        ]

        output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertEqual(output, "")

    def test_s2_outline_terminal_output_rejects_failed_tool_metadata_exit(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
                            },
                            "metadata": {"exit": 1, "output": final_output},
                        },
                    }
                ]
            }
        ]

        output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertEqual(output, "")

    def test_s2_outline_non_terminal_outputs_do_not_trigger_early_completion(self) -> None:
        non_terminal_output = '{"status":"passed","summary":{"workflowStage":"validated"}}'
        for command in [
            "s2outline prepare /data/documents/PRJ/s2_input.json",
            "s2outline status /data/documents/PRJ/s2_input.json",
            "s2outline validate /data/documents/PRJ/s2_input.json",
            "s2toc /data/documents/PRJ/s2_input.json",
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
                                    "exit": 0,
                                    "output": non_terminal_output,
                                },
                            }
                        ]
                    }
                ]

                output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

                self.assertEqual(output, "")

    def test_s2_outline_finalize_requires_terminal_json_output(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": '{"status":"waiting","summary":{"total_items":0}}',
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": (
                                '{"schema_version":"technical-outline.v1",'
                                '"outputFile":"/data/documents/PRJ/toc.json",'
                                '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
                            ),
                        },
                    },
                ]
            }
        ]

        output = OpencodeClient._find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertIn('"outputFile"', output)
        self.assertIn('"total_nodes":64', output)

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

        def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
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

    def test_factcurate_never_returns_early(self) -> None:
        """factcurate 不提前返回：建议文件由 LLM 多轮迭代写出（先草稿后填值），
        「脚本完成 / 文件已落地」都不代表终稿——提前返回会回收草稿并孤儿化会话
        （实测三轮三种竞态）。必须等会话自然完成，走正常返回路径。"""
        client = OpencodeClient()

        def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            time.sleep(1.2)
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
            response = client._send_prompt_with_session_polling(
                "ses-factcurate",
                "prompt",
                early_tool_command="factcurate",
            )
            self.assertGreaterEqual(time.monotonic() - started_at, 1.0)
            self.assertNotIn("_earlyCompletion", response)
            self.assertIn('{"late":true}', response["parts"][0]["text"])

    def test_polling_run_timeout_not_shorter_than_idle_supervision(self) -> None:
        """系统设置 timeoutMs 较短（如默认 30s）时，轮询监管的长任务 HTTP 读超时
        必须抬到 idle 监管时限以上，否则脚本/生成阶段请求先被 30s 读超时杀掉，
        后端 400 而 futurecode 会话仍在后台运行（产物无人回收）。"""
        client = OpencodeClient()
        client.timeout = httpx.Timeout(30.0, connect=10.0)
        captured: dict = {}

        def capturing_send_prompt(session_id: str, prompt_text: str, **kwargs) -> dict:
            captured.update(kwargs)
            return {"parts": [{"type": "text", "text": '{"ok":true}'}]}

        with (
            patch.object(client, "send_prompt", side_effect=capturing_send_prompt),
            patch.object(client, "list_session_messages", return_value=[]),
        ):
            client._send_prompt_with_session_polling(
                "ses-timeout-floor",
                "prompt",
                early_tool_command="factcurate",
            )

        run_timeout = captured.get("timeout")
        self.assertIsInstance(run_timeout, httpx.Timeout)
        idle_timeout = client._session_polling_idle_timeout("factcurate")
        self.assertGreaterEqual(run_timeout.read, idle_timeout)

    def test_idle_timeout_aborts_session_and_joins_worker(self) -> None:
        client = OpencodeClient()
        release_worker = threading.Event()

        def blocked_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
            release_worker.wait(2.0)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "abort_session", side_effect=abort_session) as abort,
            patch.object(client, "list_session_messages", return_value=[]),
            patch.object(client, "_session_polling_idle_timeout", return_value=0.01),
        ):
            with self.assertRaisesRegex(RuntimeError, "idle timeout"):
                client._send_prompt_with_session_polling(
                    "ses-idle-abort",
                    "prompt",
                    early_tool_command="factcurate",
                )

        abort.assert_called_once_with("ses-idle-abort")
        self.assertFalse(
            any(thread.name == "opencode-message-ses-idle-abort" for thread in threading.enumerate())
        )

    def test_polling_emits_heartbeat_when_snapshot_does_not_change(self) -> None:
        client = OpencodeClient()
        events: list[dict] = []

        def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
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

        def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
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

        def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
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

    def test_s2_outline_waits_for_finalize_after_prompt_timeout(self) -> None:
        client = OpencodeClient()
        finalize_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
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
                            "input": {"command": "s2outline validate /data/documents/PRJ/s2_input.json"},
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
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
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
            patch.object(client, "send_prompt", side_effect=RuntimeError("futurecode generate timeout")),
            patch.object(client, "list_session_messages", side_effect=list_messages) as list_session_messages,
            patch.object(client, "abort_session", return_value=True) as abort_session,
            patch("app.services.opencode_client.time.sleep", return_value=None),
        ):
            response = client._send_prompt_with_session_polling(
                "ses-s2-outline",
                "prompt",
                early_tool_command="s2outline-finalize",
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-finalize")
        self.assertIn('"total_nodes":64', response["parts"][0]["text"])
        self.assertGreaterEqual(list_session_messages.call_count, 2)
        abort_session.assert_called_once_with("ses-s2-outline")

    def test_s2_outline_early_completion_aborts_and_waits_for_active_prompt_worker(self) -> None:
        client = OpencodeClient()
        release_worker = threading.Event()
        worker_finished = threading.Event()
        finalize_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        finalized_messages = [
            {
                "info": {"role": "assistant", "id": "msg-finalize"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": finalize_output,
                        },
                    }
                ],
            }
        ]

        def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            release_worker.wait(timeout=5)
            worker_finished.set()
            return {"parts": [{"type": "text", "text": finalize_output}]}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        try:
            with (
                patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
                patch.object(client, "list_session_messages", return_value=finalized_messages),
                patch.object(
                    client,
                    "_get_session_output_snapshot",
                    return_value={"signature": ("finalized", ())},
                ),
                patch.object(client, "abort_session", side_effect=abort_session) as abort_session_mock,
            ):
                response = client._send_prompt_with_session_polling(
                    "ses-s2-active",
                    "prompt",
                    early_tool_command="s2outline-finalize",
                )
        finally:
            release_worker.set()

        self.assertTrue(response["_earlyCompletion"])
        abort_session_mock.assert_called_once_with("ses-s2-active")
        self.assertTrue(worker_finished.is_set())

    def test_s2_outline_stopped_session_uses_terminal_validator_for_noncanonical_command(self) -> None:
        client = OpencodeClient()
        finalized_payload = {
            "schema_version": "technical-outline.v1",
            "outputFile": "/data/documents/PRJ/toc.json",
            "summary": {"total_nodes": 64, "workflowStage": "finalized"},
        }
        commands = [
            "s2outline finalize /data/documents/PRJ/s2_input.json",
            "s2outline finalize /data/documents/PRJ/s2_input.json 333>&1",
        ]

        for command in commands:
            with self.subTest(command=command):
                release_worker = threading.Event()
                stopped_messages = [
                    {
                        "info": {"role": "assistant", "id": "msg-final", "finish": "stop"},
                        "parts": [
                            {
                                "type": "tool",
                                "tool": "bash",
                                "state": {
                                    "status": "completed",
                                    "input": {"command": command},
                                    "exit": 0,
                                    "output": json.dumps(finalized_payload),
                                },
                            }
                        ],
                    }
                ]

                def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
                    release_worker.wait(timeout=5)
                    return {"parts": []}

                def abort_session(_session_id: str) -> bool:
                    release_worker.set()
                    return True

                with (
                    patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
                    patch.object(client, "list_session_messages", return_value=stopped_messages),
                    patch.object(
                        client,
                        "_get_session_output_snapshot",
                        return_value={"signature": ("stopped", ())},
                    ),
                    patch.object(client, "abort_session", side_effect=abort_session) as abort_session_mock,
                    patch("app.services.opencode_client.time.sleep", return_value=None),
                ):
                    response = client._send_prompt_with_session_polling(
                        "ses-s2-stopped",
                        "prompt",
                        early_tool_command="s2outline-finalize",
                        terminal_validator=lambda: finalized_payload,
                    )

                self.assertTrue(response["_earlyCompletion"])
                self.assertEqual(response["_completionSource"], "s2outline-terminal-validator")
                self.assertIn('"workflowStage": "finalized"', response["parts"][0]["text"])
                abort_session_mock.assert_called_once_with("ses-s2-stopped")

    def test_s2_outline_finalize_tool_stops_before_assistant_finishes(self) -> None:
        client = OpencodeClient()
        finalized_payload = {
            "schema_version": "technical-outline.v1",
            "outputFile": "/data/documents/PRJ/toc.json",
            "summary": {"total_nodes": 64, "workflowStage": "finalized"},
        }
        finalized_messages = [
            {
                "info": {"role": "assistant", "id": "msg-finalize", "finish": "tool-calls"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/s2_input.json"
                            },
                            "exit": 0,
                            "output": json.dumps(finalized_payload),
                        },
                    }
                ],
            }
        ]

        with (
            patch.object(client, "list_session_messages", return_value=finalized_messages),
            patch.object(client, "_stop_s2_outline_session_after_finalize") as stop_session,
        ):
            response = client._wait_for_s2_outline_finalize_after_prompt_return(
                session_id="ses-s2-finalized",
                idle_timeout=0.01,
                stream_callback=None,
                terminal_validator=lambda: finalized_payload,
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-terminal-validator")
        stop_session.assert_called_once_with("ses-s2-finalized")

    def test_s2_outline_combined_finalize_tool_stops_before_assistant_finishes(self) -> None:
        client = OpencodeClient()
        finalized_payload = {
            "schema_version": "technical-outline.v1",
            "outputFile": "/data/documents/PRJ/toc.json",
            "summary": {"total_nodes": 270, "workflowStage": "finalized"},
        }
        finalized_messages = [
            {
                "info": {"role": "assistant", "id": "msg-finalize", "finish": "tool-calls"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": (
                                    "s2outline section /data/documents/PRJ/s2_input.json TEN-2:S0279 "
                                    "--max-chars 30000 && "
                                    "s2outline finalize /data/documents/PRJ/s2_input.json"
                                )
                            },
                            "exit": 0,
                            "output": "...output truncated...",
                        },
                    }
                ],
            }
        ]

        with (
            patch.object(client, "list_session_messages", return_value=finalized_messages),
            patch.object(client, "_stop_s2_outline_session_after_finalize") as stop_session,
        ):
            response = client._wait_for_s2_outline_finalize_after_prompt_return(
                session_id="ses-s2-combined-finalize",
                idle_timeout=0.01,
                stream_callback=None,
                terminal_validator=lambda: finalized_payload,
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-terminal-validator")
        stop_session.assert_called_once_with("ses-s2-combined-finalize")

    def test_s2_outline_terminal_validator_runs_once_per_finalize_tool_call(self) -> None:
        client = OpencodeClient()
        failed_finalize_messages = [
            {
                "info": {"role": "assistant", "id": "msg-failed-finalize", "finish": "tool-calls"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/s2_input.json"
                            },
                            "exit": 0,
                            "output": "evidenceId not authorized",
                        },
                    }
                ],
            }
        ]
        validator_calls = 0

        def invalid_terminal_output() -> dict:
            nonlocal validator_calls
            validator_calls += 1
            raise RuntimeError("not finalized")

        with (
            patch.object(client, "list_session_messages", return_value=failed_finalize_messages),
            patch.object(client, "_raise_s2_outline_finalize_opencode_stalled", return_value=None),
            patch("app.services.opencode_client.time.sleep", return_value=None),
        ):
            response = client._wait_for_s2_outline_finalize_after_prompt_return(
                session_id="ses-s2-failed-finalize",
                idle_timeout=0.01,
                stream_callback=None,
                terminal_validator=invalid_terminal_output,
            )

        self.assertIsNone(response)
        self.assertEqual(validator_calls, 1)

    def test_s2_outline_stopped_session_releases_prompt_when_terminal_validation_fails(self) -> None:
        client = OpencodeClient()
        release_worker = threading.Event()
        stopped_messages = [
            {
                "info": {"role": "assistant", "id": "msg-final", "finish": "stop"},
                "parts": [{"type": "text", "text": "done"}],
            }
        ]

        def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            release_worker.wait(timeout=5)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "list_session_messages", return_value=stopped_messages),
            patch.object(
                client,
                "_get_session_output_snapshot",
                return_value={"signature": ("stopped", ())},
            ),
            patch.object(client, "abort_session", side_effect=abort_session) as abort_session_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "未通过 finalize 校验"):
                client._send_prompt_with_session_polling(
                    "ses-s2-invalid",
                    "prompt",
                    early_tool_command="s2outline-finalize",
                    terminal_validator=lambda: (_ for _ in ()).throw(RuntimeError("invalid output")),
                )

        abort_session_mock.assert_called_once_with("ses-s2-invalid")

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

        def slow_send_prompt(session_id: str, prompt_text: str, **_kwargs) -> dict:
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

    def test_early_tool_output_does_not_repair_traceback_into_outline(self) -> None:
        client = OpencodeClient()
        response = client._tool_output_response(
            session_id="ses-test",
            output='Traceback (most recent call last):\nzipfile.BadZipFile: File is not a zip file',
            trace_parts=[{"type": "text", "text": "tool failed"}],
        )

        with patch.object(client, "_repair_json_payload") as repair:
            with self.assertRaisesRegex(RuntimeError, "工具输出不是有效 JSON"):
                client._extract_outline_json(response)

        repair.assert_not_called()

    def test_completed_early_tool_output_must_be_json(self) -> None:
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

        output = OpencodeClient._find_completed_bash_tool_output(messages, "wikibuild")

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
