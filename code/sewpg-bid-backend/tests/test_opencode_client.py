from __future__ import annotations

import unittest
from unittest.mock import patch

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
