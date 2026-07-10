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


class FolderLiteralRouteTests(unittest.TestCase):
    """目录名命中不自动定案：目录=章、目录下多份子素材，转人工选用拼装。"""

    def _folder_lib(self) -> list[dict]:
        folder = "技术标/客户素材/示例客户/数字化智慧风场专题"
        return [
            {"id": "F1", "name": "智能监控系统.docx", "folderPath": folder, "materialTier": "customer"},
            {"id": "F2", "name": "智能运维系统.docx", "folderPath": f"{folder}/子系统", "materialTier": "customer"},
            {"id": "F3", "name": "待填写-总结.docx", "folderPath": folder, "materialTier": "customer", "requiresFill": True},
            {"id": "OUT", "name": "塔筒专题.docx", "folderPath": "技术标/通用素材/示例", "materialTier": "standard"},
        ]

    def test_folder_only_hit_routes_to_material_match(self) -> None:
        lib = self._folder_lib()
        # 字面候选=目录命中的子素材（文件名都不含章节名）
        candidates = [lib[0], lib[1]]
        routed = planner.route_folder_literal(candidates, lib, "数字化智慧风场专题")
        self.assertIsNotNone(routed)
        self.assertEqual(routed["matched"], [])  # 不自动定案
        self.assertFalse(routed["fill_tasks"])
        names = [m["name"] for m in routed["alternatives"]]
        self.assertIn("智能监控系统.docx", names)
        self.assertIn("智能运维系统.docx", names)  # 子目录成员也纳入
        self.assertNotIn("待填写-总结.docx", names)  # 待填写模板剔除
        self.assertTrue(all(m.get("literalFolderHit") for m in routed["alternatives"]))

    def test_file_name_hit_keeps_fixed_material(self) -> None:
        # 文件名命中（一份 doc = 一整章）不走目录路由，保留固定素材通道
        mat = {"id": "W1", "name": "投标项目塔筒专题.docx", "folderPath": "技术标/通用素材/示例/专题", "materialTier": "standard"}
        self.assertTrue(planner.title_matches_file_name(mat, "投标项目塔筒专题"))
        self.assertIsNone(planner.route_folder_literal([mat], [mat], "投标项目塔筒专题"))

    def test_short_folder_name_not_treated_as_hit(self) -> None:
        # 「专题」这类 <4 字目录名不构成目录命中
        mat = {"id": "S1", "name": "某某设计.docx", "folderPath": "技术标/通用素材/专题", "materialTier": "standard"}
        self.assertEqual(planner.folder_prefix_for_title(mat, "数字化智慧风场专题"), "")

    def test_folder_members_collected_across_branches(self) -> None:
        # 同名目录在 通用素材/<机型> 与 客户素材/<客户> 两个分支各有一份 → 成员都收
        lib = [
            {"id": "STD1", "name": "前言.docx", "folderPath": "技术标/通用素材/机型X/专题/数字化智慧风场专题", "materialTier": "standard"},
            {"id": "CUS1", "name": "功能介绍.docx", "folderPath": "技术标/客户素材/示例客户/数字化智慧风场专题/子系统", "materialTier": "customer"},
            {"id": "OUT", "name": "塔筒专题.docx", "folderPath": "技术标/通用素材/机型X/专题", "materialTier": "standard"},
        ]
        members = planner.folder_member_materials(lib, "技术标/客户素材/示例客户/数字化智慧风场专题", "数字化智慧风场专题")
        ids = {m["id"] for m in members}
        self.assertEqual(ids, {"STD1", "CUS1"})


class ProjectTierRecallTests(unittest.TestCase):
    """金标反评 B/A 类：项目素材加成/阈值放宽、无片段素材伪片段召回。"""

    def test_project_tier_ranks_above_standard_on_tie(self) -> None:
        std = {"id": "S", "name": "通用方案.docx", "folderPath": "x", "materialTier": "standard", "topicRelevance": 0.5}
        prj = {"id": "P", "name": "项目方案.docx", "folderPath": "x", "materialTier": "project", "topicRelevance": 0.5}
        self.assertGreater(planner._weak_recall_rank(prj), planner._weak_recall_rank(std))

    def test_segmentless_pdf_recalled_via_name_stem(self) -> None:
        # PDF 无 evidenceSegments：以文件名词干做伪片段，片段路由不失效
        pdf = {"id": "PDF1", "name": "载荷安全性评估报告.pdf", "folderPath": "技术标/项目素材/示例",
               "materialTier": "project", "evidenceSegments": []}
        out = planner.segment_recall_materials([pdf], "载荷安全性评估")
        self.assertEqual([m["id"] for m in out], ["PDF1"])

    def test_project_tier_relaxed_threshold(self) -> None:
        # 同样的弱信号：standard 被阈值挡掉，project 放宽 ×0.6 后可入池
        base = {"name": "生产制造基地专题_锡盟基地.docx", "folderPath": "x", "evidenceSegments": []}
        std = {**base, "id": "S", "materialTier": "standard"}
        prj = {**base, "id": "P", "materialTier": "project"}
        title = "供货保障能力"  # 命中同义词组加权 4 → topic 0.55
        out_ids = {m["id"] for m in planner.topic_match_materials([std, prj], title, threshold=0.6)}
        self.assertIn("P", out_ids)
        self.assertNotIn("S", out_ids)


class RouteWeakRecallTests(unittest.TestCase):
    def test_empty_library_returns_none(self) -> None:
        # D4：三路召回全空才判人工补料
        self.assertIsNone(planner.route_weak_recall({"id": "g", "title": "完全不相关的标题xyz"}, [], "完全不相关的标题xyz", "GAP-X"))

    def test_template_primary_routes_to_fill(self) -> None:
        item = {"id": "g", "title": "投标方案优势说明"}
        routed = planner.route_weak_recall(item, _lib(), "投标方案优势说明", "GAP-X")
        self.assertIsNotNone(routed)
        self.assertTrue(routed["fill_tasks"])  # 模板名与章节名相关 → AI 填写
        self.assertLessEqual(len(routed["alternatives"]), 4)

    def test_untrusted_template_demoted_to_material_match(self) -> None:
        # 金标反评错误路由防护：模板与章节主题无关且分数与现成素材并列 → 不挂 AI 填写
        template = {"id": "T", "name": "待填写-投标方案优势说明.docx", "folderPath": "x",
                    "requiresFill": True, "topicRelevance": 0.6}
        ready = {"id": "R", "name": "变桨系统专题.docx", "folderPath": "x", "topicRelevance": 0.6,
                 "evidenceSegments": [{"title": "变桨系统专题"}]}
        self.assertFalse(planner._fill_template_trusted(template, [template, ready], "项目风机各子系统专题"))
        # 名称相关（章节名≈模板词干）→ 可信
        self.assertTrue(planner._fill_template_trusted(template, [template, ready], "投标方案优势说明"))
        # 分数明显领先（≥0.15）→ 可信
        lead = dict(template, topicRelevance=0.8)
        self.assertTrue(planner._fill_template_trusted(lead, [lead, dict(ready, topicRelevance=0.5)], "项目风机各子系统专题"))

    def test_all_template_pool_untrusted_returns_none(self) -> None:
        # 池里只有不可信模板 → 宁判人工补料，不给错误方向
        template = {"id": "T", "name": "待填写-投标方案优势说明.docx", "folderPath": "x",
                    "requiresFill": True,
                    "evidenceSegments": [{"title": "叶片专题", "topicKeywords": ["叶片", "变桨", "齿轮箱"]}]}
        routed = planner.route_weak_recall({"id": "g", "title": "项目风机各子系统专题"}, [template], "项目风机各子系统专题", "GAP-X")
        self.assertIsNone(routed)

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
