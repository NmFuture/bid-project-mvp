from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skills"
    / "bid-tech-gap-planner"
    / "scripts"
    / "run_from_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location("tech_gap_planner_under_test", _SRC)
planner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(planner)


def _material_with_segments() -> dict:
    return {
        "id": "RAW-0476",
        "name": "混塔解决方案专题.docx",
        "path": "技术标/通用素材/EW5.0-202/混塔解决方案专题.docx",
        "folderPath": "技术标/通用素材/EW5.0-202",
        "materialTier": "standard",
        "confidence": 0.74,
        "evidenceSegments": [
            {"segmentId": "a", "title": "混塔结构方案", "summary": "混塔由混凝土段和钢段组成", "keywords": ["混塔", "塔筒"]},
            {"segmentId": "b", "title": "叶片净空监测", "summary": "叶片净空在线监测系统", "keywords": ["叶片净空监测"]},
            {"segmentId": "c", "title": "电网友好性", "summary": "低电压穿越能力", "keywords": ["电网友好性"]},
        ],
    }


class SegmentRecallTests(unittest.TestCase):
    def test_recall_picks_relevant_segment(self) -> None:
        recalled = planner.recall_material_segments(_material_with_segments(), "混塔塔筒制造单位要求")
        self.assertTrue(recalled)
        self.assertEqual(recalled[0]["title"], "混塔结构方案")
        self.assertGreater(recalled[0]["matchScore"], 0)

    def test_recall_respects_keyword_match(self) -> None:
        recalled = planner.recall_material_segments(_material_with_segments(), "电网友好性专题")
        self.assertTrue(recalled)
        self.assertEqual(recalled[0]["title"], "电网友好性")

    def test_irrelevant_title_recalls_nothing(self) -> None:
        self.assertEqual(planner.recall_material_segments(_material_with_segments(), "财务审计报告"), [])

    def test_no_segments_recalls_nothing(self) -> None:
        bare = {"id": "RAW-9", "name": "前言.docx", "path": "p/前言.docx", "materialTier": "standard"}
        self.assertEqual(planner.recall_material_segments(bare, "前言"), [])

    def test_recall_limit(self) -> None:
        material = _material_with_segments()
        # 复制成 5 个同主题片段，limit=2 应只返回 2 条
        material["evidenceSegments"] = [
            {"segmentId": f"s{i}", "title": "混塔结构方案", "summary": "x", "keywords": ["混塔"]}
            for i in range(5)
        ]
        self.assertEqual(len(planner.recall_material_segments(material, "混塔", limit=2)), 2)


class AttachSegmentsTests(unittest.TestCase):
    def test_attach_adds_score_and_segments(self) -> None:
        out = planner.attach_recalled_segments([_material_with_segments()], "混塔塔筒制造单位要求")
        self.assertEqual(len(out), 1)
        self.assertIn("matchScore", out[0])
        self.assertIn("recalledSegments", out[0])
        self.assertIn("段落级证据召回", out[0]["matchReason"])

    def test_attach_degrades_without_segments(self) -> None:
        bare = {"id": "RAW-9", "name": "前言.docx", "path": "p/前言.docx", "materialTier": "standard", "confidence": 0.74}
        out = planner.attach_recalled_segments([bare], "前言")
        self.assertEqual(len(out), 1)
        self.assertIn("matchScore", out[0])  # 文件级分仍在
        self.assertNotIn("recalledSegments", out[0])  # 无片段不附

    def test_attach_score_combines_file_and_segment(self) -> None:
        material = _material_with_segments()
        file_only = planner.material_score(material, "混塔塔筒制造单位要求")
        out = planner.attach_recalled_segments([material], "混塔塔筒制造单位要求")
        # 综合分应 >= 纯文件分（叠加了最佳片段分）
        self.assertGreaterEqual(out[0]["matchScore"], file_only)

    def test_match_score_normalized_capped(self) -> None:
        # 归一化口径：强命中（标题整串命中 + 片段命中）也不超过 0.99（对齐商务标封顶）。
        material = _material_with_segments()
        material["name"] = "混塔塔筒制造单位要求.docx"  # 构造标题整串命中
        material["materialTier"] = "project"
        material["cleanedFileName"] = "clean.docx"
        out = planner.attach_recalled_segments([material], "混塔塔筒制造单位要求")
        self.assertLessEqual(out[0]["matchScore"], 0.99)
        self.assertGreaterEqual(out[0]["matchScore"], 0.6)  # 整串命中至少 0.6
        for segment in out[0].get("recalledSegments") or []:
            self.assertLessEqual(segment["matchScore"], 0.99)

    def test_attach_uses_topic_relevance_floor(self) -> None:
        # 主题召回素材文件名与标题字面对不上时，matchScore 不应低于 topicRelevance。
        material = _material_with_segments()
        material["topicRelevance"] = 0.45
        out = planner.attach_recalled_segments([material], "财务审计报告")  # 字面完全不命中
        self.assertGreaterEqual(out[0]["matchScore"], 0.45)
        self.assertLessEqual(out[0]["matchScore"], 0.99)


class ManifestPassThroughTests(unittest.TestCase):
    def test_material_index_passes_evidence_segments(self) -> None:
        idx = planner.material_index_from_manifest({"materialIndex": [_material_with_segments()]})
        self.assertEqual(len(idx), 1)
        self.assertEqual(len(idx[0]["evidenceSegments"]), 3)

    def test_material_index_defaults_empty_segments(self) -> None:
        idx = planner.material_index_from_manifest({"materialIndex": [{"id": "RAW-1", "name": "x.docx"}]})
        self.assertEqual(idx[0]["evidenceSegments"], [])


class TopicRecallTests(unittest.TestCase):
    """主题级弱关联召回：文件名对不上但主题相关的素材也能召回。"""

    def _lib(self):
        # 一批文件名与「试验检验监造/考核指标」章节字面对不上、但主题相关的素材。
        return [
            {"id": "RAW-A", "name": "上海电气风电试验检测能力专题.docx", "folderPath": "技术标/通用素材/EW5.0-202", "materialTier": "standard",
             "evidenceSegments": [{"title": "试验检测能力", "summary": "型式试验与检测实验室能力", "topicKeywords": ["试验检测", "型式试验", "检测能力"]}]},
            {"id": "RAW-B", "name": "全过程质量保障体系.docx", "folderPath": "技术标/通用素材/EW5.0-202", "materialTier": "standard",
             "evidenceSegments": [{"title": "质量保障体系", "summary": "全过程质量保障与监造", "topicKeywords": ["质量保障", "监造", "质量控制"]}]},
            {"id": "RAW-C", "name": "发电小时数承诺函（承诺考核值）.docx", "folderPath": "技术标/通用素材/EW5.0-202", "materialTier": "standard",
             "evidenceSegments": [{"title": "考核值承诺", "summary": "年等效满负荷小时数考核承诺", "topicKeywords": ["考核", "等效满负荷", "承诺值"]}]},
            {"id": "RAW-D", "name": "混塔解决方案专题.docx", "folderPath": "技术标/通用素材/EW5.0-202", "materialTier": "standard",
             "evidenceSegments": [{"title": "混塔方案", "summary": "混合塔架方案", "topicKeywords": ["混塔", "塔筒"]}]},
        ]

    def test_recall_inspection_supervision(self) -> None:
        # 章节"试验、检验和监造"应召回到试验检测能力专题 / 质量保障体系（文件名不含该章节标题）。
        out = planner.topic_match_materials(self._lib(), "试验、检验和监造")
        ids = [m["id"] for m in out]
        self.assertIn("RAW-A", ids)
        self.assertIn("RAW-B", ids)
        self.assertNotIn("RAW-D", ids)  # 混塔主题无关，不召回
        self.assertTrue(all("topicRelevance" in m for m in out))

    def test_recall_assessment_metrics(self) -> None:
        out = planner.topic_match_materials(self._lib(), "考核指标")
        self.assertIn("RAW-C", ids := [m["id"] for m in out])
        self.assertNotIn("RAW-D", ids)

    def test_irrelevant_title_recalls_nothing(self) -> None:
        out = planner.topic_match_materials(self._lib(), "财务审计报告")
        self.assertEqual(out, [])

    def test_synonym_hit_count(self) -> None:
        self.assertGreaterEqual(planner.tech_synonym_hit_count("试验、检验和监造", "本文介绍试验检测能力与监造安排"), 2)
        self.assertEqual(planner.tech_synonym_hit_count("财务审计", "试验检测能力"), 0)

    def test_similarity_substring(self) -> None:
        self.assertGreater(planner._tech_similarity_score("供货范围", "供货范围概述说明"), 0.5)
        self.assertEqual(planner._tech_similarity_score("", "x"), 0.0)


if __name__ == "__main__":
    unittest.main()
