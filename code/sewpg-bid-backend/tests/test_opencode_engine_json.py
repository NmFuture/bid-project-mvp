from __future__ import annotations

from unittest.mock import patch
from app.services.agent_engine.opencode_engine import OpencodeEngine

from opencode_engine_helpers import (
    OpencodeEngineTestBase,
)


class OpencodeEngineTests(OpencodeEngineTestBase):

    async def test_extract_outline_json_repairs_invalid_json_once(self) -> None:
        client = OpencodeEngine()
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
            parsed = await client._orchestrator._extract_outline_json(response)

        repair.assert_called_once()
        self.assertEqual(parsed["summary"], "目录生成完成")
        self.assertEqual(parsed["nodes"][0]["title"], "项目概况")



    async def test_extract_outline_json_promotes_repair_failure(self) -> None:
        client = OpencodeEngine()
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
                await client._orchestrator._extract_outline_json(response)

        repair.assert_called_once()
        self.assertIn("futurecode JSON 解析失败", str(context.exception))



    async def test_parse_json_payload_extracts_first_balanced_object_with_required_array(self) -> None:
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

        parsed = OpencodeEngine._parse_json_payload(content)

        self.assertEqual(parsed["decisions"][0]["candidateId"], "CAND-0001")



    async def test_extract_business_template_extraction_json_repairs_damaged_summary(self) -> None:
        client = OpencodeEngine()
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
            parsed = await client._orchestrator._extract_business_template_extraction_json(response)

        repair.assert_called_once()
        self.assertEqual(parsed["summary"]["templateCount"], 2)



    async def test_extract_business_template_extraction_json_rejects_missing_output_and_summary(self) -> None:
        client = OpencodeEngine()
        response = {"parts": [{"type": "text", "text": '{"schemaVersion":"bid-business-template-extractor-v1"}'}]}

        with self.assertRaisesRegex(RuntimeError, "商务模板提取 JSON 结构不正确"):
            await client._orchestrator._extract_business_template_extraction_json(response)



    async def test_extract_business_template_extraction_json_accepts_summary_only(self) -> None:
        client = OpencodeEngine()
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

        parsed = await client._orchestrator._extract_business_template_extraction_json(response)

        self.assertEqual(parsed["summary"]["templateCount"], 1)



    async def test_extract_outline_json_accepts_v2_toc_items(self) -> None:
        client = OpencodeEngine()
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

        parsed = await client._orchestrator._extract_outline_json(response)

        self.assertEqual(parsed["schema_version"], "bid-toc-json-v1")
        self.assertEqual(parsed["items"][0]["title"], "技术方案")



    async def test_extract_outline_json_accepts_v2_output_file_summary(self) -> None:
        client = OpencodeEngine()
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

        parsed = await client._orchestrator._extract_outline_json(response)

        self.assertEqual(parsed["itemCount"], 659)
        self.assertIn("投标文件-总目录.json", parsed["outputFile"])



    async def test_extract_wiki_blueprint_json_accepts_valid_payload(self) -> None:
        client = OpencodeEngine()
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

        parsed = await client._orchestrator._extract_wiki_blueprint_json(response)

        self.assertEqual(parsed["summary"], "Wiki 已生成")
        self.assertEqual(parsed["nodes"][0]["title"], "00-Wiki使用说明")



    async def test_extract_wiki_blueprint_json_accepts_output_file_summary(self) -> None:
        client = OpencodeEngine()
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

        parsed = await client._orchestrator._extract_wiki_blueprint_json(response)

        self.assertEqual(parsed["summary"], "Wiki 已生成")
        self.assertIn("wiki_blueprint.json", parsed["outputFile"])



    async def test_extract_wiki_blueprint_json_repairs_invalid_json_once(self) -> None:
        client = OpencodeEngine()
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
            parsed = await client._orchestrator._extract_wiki_blueprint_json(response)

        repair.assert_called_once()
        self.assertEqual(parsed["nodes"][0]["title"], "00-Wiki使用说明")



    async def test_extract_gap_plan_json_accepts_output_file_summary(self) -> None:
        client = OpencodeEngine()
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

        parsed = await client._orchestrator._extract_gap_plan_json(response)

        self.assertEqual(parsed["schema_version"], "bid-tech-gap-plan-v1")
        self.assertIn("gap_plan.json", parsed["outputFile"])



    async def test_extract_tender_parse_json_rejects_prepared_workflow_stage(self) -> None:
        client = OpencodeEngine()
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
            await client._orchestrator._extract_tender_parse_json(response)
