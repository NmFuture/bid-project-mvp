"""展示分诚实化（产品裁决 2026-08-04）单测。

一、弱召回封顶：字面证据不足、仅靠弱召回/片段加成撑起的展示分封顶 0.49（低置信档），
排序分不再冒充置信度。
二、整章覆盖率展示分：整章定案素材按标题树覆盖率给展示分并写明证据，不再显示
误导性的字面低分。fixture 为脱敏合成素材。
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
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
_SPEC = importlib.util.spec_from_file_location("tech_gap_display_scores_under_test", _SRC)
planner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(planner)

_ROOT = "技术标/通用素材/示例"


class WeakRecallDisplayCapTests(unittest.TestCase):
    def test_weak_recall_only_material_capped_at_low_confidence(self) -> None:
        # 文件名/路径与标题完全无关，仅靠主题相关度与片段加成撑分。
        material = {
            "id": "M-WEAK",
            "name": "服务承诺书.docx",
            "folderPath": f"{_ROOT}/专题",
            "topicRelevance": 0.9,
            "segmentRecallScore": 0.6,
            "wikiHintScore": 0.5,
        }
        enriched = planner.attach_recalled_segments([material], "风资源评估与机位排布方案")
        self.assertEqual(len(enriched), 1)
        self.assertLessEqual(float(enriched[0]["matchScore"]), planner.WEAK_RECALL_DISPLAY_CAP)

    def test_literal_evidence_material_not_capped(self) -> None:
        # 标题整串出现在目录路径里：字面分足档，不受弱召回封顶影响。
        material = {
            "id": "M-LITERAL",
            "name": "方案正文.docx",
            "folderPath": f"{_ROOT}/风资源评估与机位排布方案",
        }
        enriched = planner.attach_recalled_segments([material], "风资源评估与机位排布方案")
        self.assertGreater(float(enriched[0]["matchScore"]), planner.WEAK_RECALL_DISPLAY_CAP)

    def test_exact_filename_hit_keeps_099(self) -> None:
        material = {"id": "M-EXACT", "name": "风资源评估与机位排布方案.docx", "folderPath": _ROOT}
        enriched = planner.attach_recalled_segments([material], "风资源评估与机位排布方案")
        self.assertEqual(float(enriched[0]["matchScore"]), planner.EXACT_MATCH_SCORE)


class ChapterMasterDisplayScoreTests(unittest.TestCase):
    def _build_plan(self) -> dict:
        rows = [
            ("第3章", "风资源评估与机位排布方案", 1),
            ("3.1", "风资源分析", 2),
            ("3.2", "机位排布方案", 2),
            ("3.3", "发电量测算结果", 2),
        ]
        toc_items = [
            {"order": i, "number": number, "title": title, "level": level, "material_refs": []}
            for i, (number, title, level) in enumerate(rows, start=1)
        ]
        # 文件名与章名字面对不上，但标题树覆盖全部子节 → 整章定案的强证据。
        material_index = [
            {
                "id": "M-MASTER",
                "name": "风资源评估报告.docx",
                "folderPath": f"{_ROOT}/项目定制",
                "materialTier": "project",
                "documentOutline": [
                    {"title": "风资源分析"},
                    {"title": "机位排布方案"},
                    {"title": "发电量测算结果"},
                ],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            toc_path = work / "toc.json"
            toc_path.write_text(
                json.dumps({"schema_version": "toc-v1", "items": toc_items}, ensure_ascii=False),
                encoding="utf-8",
            )
            parse_path = work / "parse_result.json"
            parse_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "bidType": "technical",
                "workDir": str(work),
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "wikiDir": "",
                "materialIndex": material_index,
                "materialScope": {"readableScopes": [{"path": _ROOT}]},
            }
            return planner.build_gap_plan(manifest)

    def test_chapter_master_display_reflects_outline_coverage(self) -> None:
        plan = self._build_plan()
        chapter = next(item for item in plan["items"] if item["number"] == "第3章")
        self.assertEqual(chapter.get("coverageRole"), "chapter_master")
        matched = chapter["matchedMaterials"][0]
        self.assertGreaterEqual(float(matched["matchScore"]), 0.7)
        self.assertIn("标题树覆盖", str(matched.get("matchReason") or ""))


if __name__ == "__main__":
    unittest.main()
