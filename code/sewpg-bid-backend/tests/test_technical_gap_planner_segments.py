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


class ScoreCapPolicyTests(unittest.TestCase):
    """展示分口径（产品裁决 2026-07-16）：0.99 只留文件名精确命中，启发式封顶 0.98。"""

    def test_exact_file_name_hit_scores_099(self) -> None:
        material = _material_with_segments()
        material["name"] = "混塔塔筒制造单位要求.docx"
        out = planner.attach_recalled_segments([material], "混塔塔筒制造单位要求")
        self.assertEqual(out[0]["matchScore"], 0.99)

    def test_heuristic_scores_capped_at_098(self) -> None:
        # 目录名命中章节标题（文件名不含标题）：原始分远超 1，但展示分必须 ≤0.98。
        material = _material_with_segments()
        material["folderPath"] = "技术标/客户素材/混塔塔筒制造单位要求"
        material["path"] = "技术标/客户素材/混塔塔筒制造单位要求/混塔解决方案专题.docx"
        material["materialTier"] = "project"
        material["topicRelevance"] = 0.98
        material["nameSimilarity"] = 0.98
        material["segmentRecallScore"] = 0.98
        out = planner.attach_recalled_segments([material], "混塔塔筒制造单位要求")
        self.assertLessEqual(out[0]["matchScore"], 0.98)
        for segment in out[0].get("recalledSegments") or []:
            self.assertLessEqual(segment["matchScore"], 0.98)

    def test_weak_recall_sub_scores_capped_at_098(self) -> None:
        # 素材名/主题/片段与标题完全一致（原始相似度 1.0）时，三路子分均封顶 0.98。
        twin = {
            "id": "RAW-TWIN",
            "name": "风资源评估与机位排布方案.docx",
            "folderPath": "技术标/通用素材",
            "materialTier": "standard",
            "evidenceSegments": [{"title": "风资源评估与机位排布方案"}],
        }
        title = "风资源评估与机位排布方案"
        for field, pool in (
            ("topicRelevance", planner.topic_match_materials([dict(twin)], title)),
            ("nameSimilarity", planner.approx_name_match_materials([dict(twin)], title)),
            ("segmentRecallScore", planner.segment_recall_materials([dict(twin)], title)),
        ):
            self.assertTrue(pool, field)
            self.assertTrue(all(m[field] <= 0.98 for m in pool), field)


class TrailingAppendixCoverageTests(unittest.TestCase):
    """整章覆盖延伸：chapter_master 章后的正文型附表按证据分级归入父章覆盖。"""

    def _items(self) -> list[dict]:
        master = {
            "id": "M-CH3",
            "name": "风资源评估与机位排布方案.docx",
            "evidenceSegments": [
                {"title": "总体方案概览"},
                {"title": "附表2 推荐机型各机位发电量成果表"},
            ],
        }
        return [
            {"id": "GAP-1", "number": "第3章", "title": "风资源评估与机位排布方案", "level": 1,
             "coverageRole": "chapter_master", "decision": "ready", "matchedMaterials": [master]},
            {"id": "GAP-2", "number": "3.1", "title": "总体方案概览", "level": 2,
             "decision": "ready", "coveredByParent": "GAP-1"},
            {"id": "GAP-3", "number": "附表1", "title": "风资源评估与机位排布方案", "level": 1,
             "decision": "fill_required", "candidateMaterials": [{"id": "M-X"}]},
            {"id": "GAP-4", "number": "附表2", "title": "推荐机型各机位发电量成果表", "level": 1,
             "decision": "fill_required", "candidateMaterials": [{"id": "M-Y"}]},
            {"id": "GAP-5", "number": "附表3", "title": "投标机型安全等级统计", "level": 1,
             "decision": "fill_required", "gapReason": "弱关联召回命中。", "candidateMaterials": [{"id": "M-Z"}]},
            {"id": "GAP-6", "number": "第4章", "title": "项目技术承诺函", "level": 1,
             "decision": "fill_required"},
            {"id": "GAP-7", "number": "附表A.1", "title": "投标机型总方案信息表", "level": 1,
             "decision": "fill_required", "appendixTasks": [{"id": "APPX-A1"}]},
        ]

    def test_same_name_and_segment_hit_covered(self) -> None:
        items = self._items()
        planner.extend_chapter_master_to_trailing_appendices(items)
        by_id = {item["id"]: item for item in items}
        # 附表1 同名 → 覆盖；附表2 片段命中 → 覆盖
        for gid in ("GAP-3", "GAP-4"):
            self.assertEqual(by_id[gid]["coveredByParent"], "GAP-1", gid)
            self.assertEqual(by_id[gid]["decision"], "ready", gid)
            self.assertEqual(by_id[gid]["candidateMaterials"], [], gid)

    def test_no_evidence_only_suggests(self) -> None:
        items = self._items()
        planner.extend_chapter_master_to_trailing_appendices(items)
        by_id = {item["id"]: item for item in items}
        appx3 = by_id["GAP-5"]
        # 附表3 无同名/片段证据 → 不改判，只挂疑似覆盖提示
        self.assertEqual(appx3["decision"], "fill_required")
        self.assertEqual(appx3["suspectedParentCoverage"]["gapId"], "GAP-1")
        self.assertIn("疑似由同一份整章素材覆盖", appx3["gapReason"])
        self.assertIn("弱关联召回命中", appx3["gapReason"])

    def test_matrix_appendix_and_next_chapter_untouched(self) -> None:
        items = self._items()
        planner.extend_chapter_master_to_trailing_appendices(items)
        by_id = {item["id"]: item for item in items}
        self.assertNotIn("coveredByParent", by_id["GAP-6"])
        self.assertNotIn("coveredByParent", by_id["GAP-7"])
        self.assertNotIn("suspectedParentCoverage", by_id["GAP-7"])

    def test_appendix_with_own_resolution_skipped_but_scan_continues(self) -> None:
        items = self._items()
        items[2]["matchedMaterials"] = [{"id": "M-OWN", "name": "附表1成品.docx"}]
        planner.extend_chapter_master_to_trailing_appendices(items)
        by_id = {item["id"]: item for item in items}
        # 附表1 有自有定案 → 不吸收；附表2 仍被覆盖（扫描继续）
        self.assertNotIn("coveredByParent", by_id["GAP-3"])
        self.assertEqual(by_id["GAP-4"]["coveredByParent"], "GAP-1")


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


class PureLetterAppendixMatchTests(unittest.TestCase):
    """纯字母技术附表匹配兜底：编号正则要求带数字，'技术附表I' 这种纯字母章级
    附表提取不出 code，靠字母兜底匹配；有同字母子附表的容器（B/C/F）排除。"""

    def _appendices(self) -> list[dict]:
        # B/C/F 有子附表（附表X.数字）→ 容器；I 无子附表 → 独立叶子表
        return [
            {"id": "APPX-B", "title": "技术附表B 供货范围、消耗品及安装调试人员计划"},
            {"id": "APPX-B1", "title": "附表B.1 供货范围清单（计入投标总价）"},
            {"id": "APPX-C", "title": "技术附表C 项目投标设备综合技术参数"},
            {"id": "APPX-C1", "title": "附表C.1 总体技术参数与规格"},
            {"id": "APPX-F", "title": "技术附表F 投标机型样机认证与测试情况"},
            {"id": "APPX-F1", "title": "附表F.1 投标机型样机基本信息"},
            {"id": "APPX-I", "title": "技术附表I 技术条款偏差表"},
        ]

    def test_pure_letter_code_only_for_letter_without_number(self) -> None:
        self.assertEqual(planner.pure_letter_appendix_code("技术附表I 技术条款偏差表"), "I")
        self.assertEqual(planner.pure_letter_appendix_code("技术附表B"), "B")
        self.assertEqual(planner.pure_letter_appendix_code("附表B.1 供货范围清单"), "")
        self.assertEqual(planner.pure_letter_appendix_code("附表C.8 升降机"), "")
        self.assertEqual(planner.pure_letter_appendix_code("附表1 风资源评估与机位排布方案"), "")

    def test_container_letters_exclude_leaf(self) -> None:
        letters = planner.appendix_container_letters(self._appendices())
        self.assertIn("B", letters)
        self.assertIn("C", letters)
        self.assertIn("F", letters)
        self.assertNotIn("I", letters)

    def test_leaf_letter_appendix_matches(self) -> None:
        item = {"number": "技术附表I", "title": "技术条款偏差表"}
        matched = planner.matching_appendices(item, self._appendices(), allow_title_match=True)
        self.assertEqual([a["id"] for a in matched], ["APPX-I"])

    def test_container_letter_appendix_not_matched(self) -> None:
        for num, title in [("技术附表B", "供货范围、消耗品及安装调试人员计划"),
                           ("技术附表C", "项目投标设备综合技术参数"),
                           ("技术附表F", "投标机型样机认证与测试情况")]:
            matched = planner.matching_appendices({"number": num, "title": title}, self._appendices())
            self.assertEqual(matched, [], f"{num} 是分组容器，不应配表")

    def test_numbered_appendix_unaffected(self) -> None:
        # 带数字附表仍走原 code 精确匹配，不受纯字母兜底影响
        item = {"number": "附表B.1", "title": "供货范围清单（计入投标总价）"}
        matched = planner.matching_appendices(item, self._appendices())
        self.assertEqual([a["id"] for a in matched], ["APPX-B1"])


if __name__ == "__main__":
    unittest.main()
