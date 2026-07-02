"""技术标弱关联召回（金标反评 D1/D2/D4）单测。

fixture 为脱敏合成素材（只保留风电领域通用词面，不含真实项目/客户/数据），
覆盖正式标书反评发现的漏召回模式：近名素材、大报告章节复用、同义词组加权排序。
"""
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
_SPEC = importlib.util.spec_from_file_location("tech_weak_recall_under_test", _SRC)
planner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(planner)


def _lib() -> list[dict]:
    return [
        {"id": "M-SITE", "name": "钢塔筒招标项目场址设计安全性.docx", "folderPath": "技术标/项目素材/示例/专题",
         "materialTier": "project", "evidenceSegments": []},
        {"id": "M-REPORT", "name": "风资源评估报告.docx", "folderPath": "技术标/项目素材/示例",
         "materialTier": "project",
         "evidenceSegments": [
             {"title": "1.2 项目概况7", "summary": ""},
             {"title": "5.1 不确定性分析12", "summary": ""},
             {"title": "6.1 方案及发电量结果15", "summary": ""},
         ]},
        {"id": "M-PERF", "name": "业绩情况.docx", "folderPath": "技术标/项目素材/示例",
         "materialTier": "project", "evidenceSegments": [{"title": "合同业绩表", "summary": ""}]},
        {"id": "M-NOISE", "name": "专题.docx", "folderPath": "技术标/通用素材/示例/专题",
         "materialTier": "standard", "evidenceSegments": [{"title": "概述", "summary": ""}]},
        {"id": "M-TPL", "name": "待填写-投标方案优势说明.docx", "folderPath": "技术标/通用素材/示例",
         "materialTier": "standard", "requiresFill": True,
         "evidenceSegments": [{"title": "投标方案整体优势", "summary": ""}, {"title": "技术路线优势", "summary": ""}]},
    ]


class ApproxNameRecallTests(unittest.TestCase):
    def test_near_name_material_recalled(self) -> None:
        # 整串包含召不回的近名素材（金标漏召回模式一）
        out = planner.approx_name_match_materials(_lib(), "投标机型项目场址设计安全性专题")
        self.assertIn("M-SITE", [m["id"] for m in out])
        self.assertTrue(all(m.get("nameSimilarity") for m in out))

    def test_short_stem_excluded(self) -> None:
        # 「专题」这类 <4 字词干不参与近名召回（噪声防护）
        out = planner.approx_name_match_materials(_lib(), "数字化智慧风场专题")
        self.assertNotIn("M-NOISE", [m["id"] for m in out])

    def test_stem_strips_fill_prefix(self) -> None:
        self.assertEqual(planner._material_name_stem("待填写-投标方案优势说明.docx"), "投标方案优势说明")
        self.assertEqual(planner._material_name_stem("定制-叶片专题.docx"), "叶片专题")


class SegmentRecallTests(unittest.TestCase):
    def test_report_chapter_recalls_whole_material(self) -> None:
        # 大报告章节复用（金标漏召回模式二）：片段标题只是检索线索，
        # 召回单元是完整素材（doc 为最小单元，不切片）。
        out = planner.segment_recall_materials(_lib(), "不确定性分析")
        ids = [m["id"] for m in out]
        self.assertIn("M-REPORT", ids)
        recalled = next(m for m in out if m["id"] == "M-REPORT")
        self.assertEqual(recalled["name"], "风资源评估报告.docx")  # 整份素材原样返回
        self.assertIn("片段级召回", recalled["matchReason"])

    def test_segment_title_number_stripped(self) -> None:
        self.assertEqual(planner._segment_title_clean({"title": "1.2 项目概况7"}), "项目概况")
        self.assertEqual(planner._segment_title_clean({"title": "一、数字化运输管理2"}), "数字化运输管理")

    def test_irrelevant_title_no_recall(self) -> None:
        self.assertEqual(planner.segment_recall_materials(_lib(), "财务审计报告"), [])


class TopicWeightingTests(unittest.TestCase):
    def test_more_synonym_hits_rank_higher(self) -> None:
        # 同义词命中数加权：命中多个组词的素材排在只蹭到一两个泛词的素材前面
        rich = {"id": "A", "name": "风资源评估报告.docx", "folderPath": "x", "evidenceSegments": [
            {"title": "测风塔数据", "topicKeywords": ["风资源", "机位排布", "发电量"]}]}
        poor = {"id": "B", "name": "激光雷达前馈测风方案.docx", "folderPath": "x", "evidenceSegments": [
            {"title": "测风", "topicKeywords": ["测风"]}]}
        out = planner.weak_recall_materials([poor, rich], "风资源评估与机位排布方案")
        self.assertEqual(out[0]["id"], "A")

    def test_long_term_weighted(self) -> None:
        self.assertGreaterEqual(planner.tech_synonym_hit_count("投标机型项目场址设计安全性专题", "钢塔筒招标项目场址设计安全性"), 2)


class RouteWeakRecallTests(unittest.TestCase):
    def test_empty_library_returns_none(self) -> None:
        # D4：三路召回全空才判人工补料
        self.assertIsNone(planner.route_weak_recall({"id": "g", "title": "完全不相关的标题xyz"}, [], "完全不相关的标题xyz", "GAP-X"))

    def test_template_primary_routes_to_fill(self) -> None:
        item = {"id": "g", "title": "投标方案优势说明"}
        routed = planner.route_weak_recall(item, _lib(), "投标方案优势说明", "GAP-X")
        self.assertIsNotNone(routed)
        self.assertTrue(routed["fill_tasks"])  # 待填写模板 → AI 填写
        self.assertLessEqual(len(routed["alternatives"]), 4)

    def test_ready_primary_routes_to_material_match(self) -> None:
        item = {"id": "g", "title": "投标机型业绩情况"}
        routed = planner.route_weak_recall(item, _lib(), "投标机型业绩情况", "GAP-X")
        self.assertIsNotNone(routed)
        self.assertFalse(routed["fill_tasks"])
        self.assertLessEqual(len(routed["alternatives"]), 4)
        # material_match 可选列表里不允许出现待填写模板
        self.assertTrue(all(not planner.material_requires_fill(m) for m in routed["alternatives"]))
        self.assertTrue(all(float(m.get("matchScore") or 0) <= 0.99 for m in routed["alternatives"]))


if __name__ == "__main__":
    unittest.main()
