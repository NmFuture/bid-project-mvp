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
                        '"/data/parsed/PRJ-0001/s2_toc_workdir/投标文件-总目录.json",'
                        '"summary":{"total_items":659},"itemCount":659}'
                    ),
                }
            ]
        }

        parsed = client._extract_outline_json(response)

        self.assertEqual(parsed["itemCount"], 659)
        self.assertIn("投标文件-总目录.json", parsed["outputFile"])

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
                        '"/data/parsed/PRJ-0001/s4_gap_workdir/gap_plan.json",'
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
