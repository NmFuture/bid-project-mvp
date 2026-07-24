from __future__ import annotations

import unittest

from app.services.technical_gap_domain import recompute_technical_gap_decisions
from app.services.technical_gap_planner import _attach_topic_recall_to_plan


def _segments():
    return [
        {
            "segmentId": "a",
            "title": "投标方案优势说明",
            "summary": "上海电气针对本项目风资源、地形等资料进行综合分析",
            "keywords": ["投标方案", "优势"],
            "topicKeywords": ["投标方案优势说明"],
        }
    ]


def _material_required_item(gap_id: str, title: str):
    return {
        "id": gap_id,
        "title": title,
        "decision": "material_required",
        "status": "missing",
        "appendixTasks": [],
        "candidateMaterials": [],
        "fillTasks": [],
    }


class TopicRecallTemplateRoutingTests(unittest.TestCase):
    """主题召回分流：待填写模板→AI填写(fillTask)，现成素材→素材匹配。对齐商务标。"""

    def test_fill_template_routes_to_ai_fill(self) -> None:
        plan = {"items": [_material_required_item("GAP-0008", "投标方案优势说明")]}
        material_index = [
            {
                "id": "RAW-0120",
                "name": "待填写-标方案优势说明（双TRB+碳纤叶片）.docx",
                "folderPath": "技术标/通用素材/EW10.0-220上置/专题",
                "evidenceSegments": _segments(),
            }
        ]
        enriched = _attach_topic_recall_to_plan(plan, material_index)
        item = plan["items"][0]
        self.assertEqual(enriched, 1)
        self.assertEqual(item["decision"], "fill_required")
        self.assertEqual(len(item.get("fillTasks") or []), 1)
        self.assertEqual(item["fillTasks"][0]["skill"], "bid-tech-word-placeholder-filler")
        # 终审后仍应是 fill_required（有待完成 fillTask）→ 前端展示 AI填写，而非素材匹配。
        recompute_technical_gap_decisions(plan)
        self.assertEqual(item["decision"], "fill_required")

    def test_ready_material_routes_to_material_match(self) -> None:
        plan = {"items": [_material_required_item("GAP-0009", "投标方案优势说明")]}
        material_index = [
            {
                "id": "RAW-0999",
                "name": "标方案优势说明.docx",
                "folderPath": "技术标/通用素材/EW10.0-220上置/专题",
                "evidenceSegments": _segments(),
            }
        ]
        enriched = _attach_topic_recall_to_plan(plan, material_index)
        item = plan["items"][0]
        self.assertEqual(enriched, 1)
        self.assertEqual(len(item.get("fillTasks") or []), 0)
        # 无 fillTask + 有候选 → 终审归 review_required → 前端素材匹配（选择合并）。
        recompute_technical_gap_decisions(plan)
        self.assertEqual(item["decision"], "review_required")


if __name__ == "__main__":
    unittest.main()
