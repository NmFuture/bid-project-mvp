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


class ManifestPassThroughTests(unittest.TestCase):
    def test_material_index_passes_evidence_segments(self) -> None:
        idx = planner.material_index_from_manifest({"materialIndex": [_material_with_segments()]})
        self.assertEqual(len(idx), 1)
        self.assertEqual(len(idx[0]["evidenceSegments"]), 3)

    def test_material_index_defaults_empty_segments(self) -> None:
        idx = planner.material_index_from_manifest({"materialIndex": [{"id": "RAW-1", "name": "x.docx"}]})
        self.assertEqual(idx[0]["evidenceSegments"], [])


if __name__ == "__main__":
    unittest.main()
