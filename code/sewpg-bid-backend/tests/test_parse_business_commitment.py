from __future__ import annotations

from unittest.mock import patch
from app.services import parsing as parsing_service

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    field_by_key,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_business_bid_generates_semantic_business_commitment_and_filters_technical_commitments(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺优化项目",
                "招标编号：BUS-2026-COM-001",
                "招标人：测试招标人",
                "投标人需同时承诺两个保证年等效满负荷小时数值（需提供书面承诺函）。",
                "投标人保证年等效满负荷小时数（需提供书面承诺函）。",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
                "投标人不得存在下列情形之一。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        letters = response.json()["structured"]["commitmentLetters"]
        titles = [item["title"] for item in letters]
        all_text = "".join(titles + [str(item.get("triggerContext") or "") for item in letters])
        self.assertIn("材料取得承诺书", titles)
        self.assertIn("投标人不存在下列情形之一承诺函", titles)
        self.assertNotIn("等效满负荷小时", all_text)
        self.assertNotIn("发电量", all_text)



    def test_business_bid_commitment_semantic_review_can_override_strong_rule_candidate(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺 AI 复核项目",
                "招标编号：BUS-2026-AI-001",
                "招标人：测试招标人",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeEngine,
            "review_business_commitments_with_trace",
            return_value={
                "decisions": [
                    {
                        "id": "RAW-0001",
                        "action": "ignore",
                        "topicKey": "certificate_obtainment",
                        "preferredTitle": "",
                        "reason": "AI 判断该项不需要自动生成商务承诺书。",
                    }
                ]
            },
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_review.call_count, 1)
        self.assertEqual(response.json()["structured"]["commitmentLetters"], [])



    def test_business_bid_commitment_strong_rule_fallback_when_semantic_review_unavailable(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺兜底项目",
                "招标编号：BUS-2026-FB-001",
                "招标人：测试招标人",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeEngine,
            "review_business_commitments_with_trace",
            side_effect=RuntimeError("semantic review unavailable"),
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_review.call_count, 1)
        letters = response.json()["structured"]["commitmentLetters"]
        self.assertEqual([item["title"] for item in letters], ["材料取得承诺书"])
        self.assertIn("rule_fallback_generated", letters[0]["riskFlags"])



    def test_business_bid_commitment_titles_use_semantic_review_and_dedupe_same_topic(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺测试项目",
                "招标编号：BUS-2026-SEM-001",
                "招标人：测试招标人",
                "第八章 投标人需要说明的其他内容",
                "保密承诺书",
                "本项仅为目录标题，不构成单独提交要求。",
                "另附保密承诺书。",
                "投标人须提供保密承诺书。",
                "保密承诺书",
                "投标人应提供保密承诺书。",
                "发电量承诺书另附。",
                "投标人不得存在下列情形之一。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeEngine,
            "review_business_commitments_with_trace",
            return_value={
                "decisions": [
                    {
                        "id": "RAW-0001",
                        "action": "ignore",
                        "topicKey": "confidentiality",
                        "preferredTitle": "",
                        "reason": "仅标题，无明确单独提交要求。",
                    }
                ]
            },
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        letters = structured["commitmentLetters"]
        titles = [item["title"] for item in letters]

        self.assertEqual(mocked_review.call_count, 1)
        self.assertEqual(len(letters), 2)
        self.assertEqual(titles.count("保密承诺书"), 1)
        self.assertIn("投标人不存在下列情形之一承诺函", titles)
        self.assertNotIn("发电量承诺书", "".join(titles))
        self.assertEqual(
            field_by_key(structured["fieldGroups"]["commitmentRequirements"], "generatedCommitmentCount")["value"],
            "2",
        )



    def test_business_bid_commitment_title_only_candidate_becomes_clue_when_semantic_review_uncertain(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺线索测试项目",
                "招标编号：BUS-2026-SEM-002",
                "招标人：测试招标人",
                "第八章 投标人需要说明的其他内容",
                "保密承诺书",
                "本节为模板目录，具体内容见附件。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeEngine,
            "review_business_commitments_with_trace",
            return_value={
                "decisions": [
                    {
                        "id": "RAW-0001",
                        "action": "clue",
                        "topicKey": "confidentiality",
                        "preferredTitle": "",
                        "reason": "仅识别到标题，建议人工确认是否需要单独成文。",
                    }
                ]
            },
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        self.assertEqual(mocked_review.call_count, 1)
        self.assertEqual(structured["commitmentLetters"], [])
        self.assertEqual(len(structured["commitmentClues"]), 1)
        self.assertEqual(structured["commitmentClues"][0]["topicKey"], "confidentiality")
        self.assertIn("人工确认", structured["commitmentClues"][0]["recommendedAction"])
        self.assertEqual(
            field_by_key(structured["fieldGroups"]["commitmentRequirements"], "pendingCommitmentCount")["value"],
            "1",
        )
