"""人工「父章节覆盖」动作（产品需求 2026-07-27）单测。

评审时一、二级目录选定素材后，下级小节常常跟着这份素材一起写。本动作把这个判断
开放给人工：以本节点为覆盖源批量标下级，可撤销；人工已单独选过素材的下级不动。
"""
from __future__ import annotations

import unittest

from app.services.technical_gap_actions import (
    apply_technical_gap_parent_coverage,
    technical_gap_descendant_items,
    technical_gap_number_key,
)


def _project(items: list[dict]) -> dict:
    return {"id": "PRJ-TEST", "bidType": "技术标", "gap_state": {"plan": {"items": items}}}


def _items() -> list[dict]:
    return [
        {
            "id": "GAP-0001",
            "number": "第3章",
            "title": "风资源评估与机位排布方案",
            "decision": "ready",
            "status": "matched",
            "matchedMaterials": [{"id": "RAW-1", "name": "风资源评估报告.docx"}],
        },
        {"id": "GAP-0002", "number": "3.1", "title": "风资源分析", "decision": "material_required", "status": "missing"},
        {"id": "GAP-0003", "number": "3.1.1", "title": "测风数据", "decision": "material_required", "status": "missing"},
        # 人工已单独选用素材的下级：一键覆盖不能抹掉它。
        {
            "id": "GAP-0004",
            "number": "3.2",
            "title": "机位排布",
            "decision": "ready",
            "status": "resolved",
            "resolvedArtifacts": [{"id": "ART-1", "fileName": "机位排布.docx"}],
        },
        {"id": "GAP-0005", "number": "4.1", "title": "别的章节", "decision": "material_required", "status": "missing"},
    ]


class ParentCoverageActionTests(unittest.TestCase):
    def test_number_key_and_descendants(self) -> None:
        self.assertEqual(technical_gap_number_key("第3章"), "3")
        self.assertEqual(technical_gap_number_key("第十二章"), "12")
        self.assertEqual(technical_gap_number_key("3.1.1"), "3.1.1")
        items = _items()
        descendants = technical_gap_descendant_items(items, items[0])
        self.assertEqual([item["id"] for item in descendants], ["GAP-0002", "GAP-0003", "GAP-0004"])

    def test_apply_sets_children_and_skips_manual_selection(self) -> None:
        items = _items()
        project = _project(items)
        result = apply_technical_gap_parent_coverage(project, "GAP-0001", {"covered": True})
        self.assertEqual(result["applied"], ["3.1", "3.1.1"])
        self.assertEqual(result["skipped"], ["3.2"])
        for gap_id in ("GAP-0002", "GAP-0003"):
            child = next(item for item in items if item["id"] == gap_id)
            self.assertEqual(child["coverageRole"], "covered_by_parent")
            self.assertEqual(child["coveredByParent"], "GAP-0001")
            self.assertEqual(child["decision"], "ready")
            self.assertEqual(child["status"], "matched")
            self.assertEqual(child["parentCoverageSource"], "manual")
        # 已自行选用素材的下级保持原样。
        untouched = next(item for item in items if item["id"] == "GAP-0004")
        self.assertEqual(untouched["status"], "resolved")
        self.assertNotIn("coveredByParent", untouched)
        # 不是本节点的后代不受影响。
        other = next(item for item in items if item["id"] == "GAP-0005")
        self.assertEqual(other["decision"], "material_required")

    def test_fill_required_parent_propagates_needs_input(self) -> None:
        items = _items()
        items[0]["decision"] = "fill_required"
        project = _project(items)
        apply_technical_gap_parent_coverage(project, "GAP-0001", {"covered": True})
        child = next(item for item in items if item["id"] == "GAP-0002")
        self.assertEqual(child["decision"], "fill_required")
        self.assertEqual(child["status"], "needs_input")
        self.assertEqual(child["nextActions"], ["ai_fill_word"])

    def test_undo_restores_previous_state(self) -> None:
        items = _items()
        project = _project(items)
        apply_technical_gap_parent_coverage(project, "GAP-0001", {"covered": True})
        apply_technical_gap_parent_coverage(project, "GAP-0001", {"covered": False})
        child = next(item for item in items if item["id"] == "GAP-0002")
        self.assertEqual(child["decision"], "material_required")
        self.assertEqual(child["status"], "missing")
        self.assertEqual(child["coverageRole"], None)
        self.assertNotIn("parentCoverageSource", child)
        self.assertNotIn("parentCoverageBackup", child)

    def test_requires_material_on_source_node(self) -> None:
        items = _items()
        items[0].pop("matchedMaterials")
        project = _project(items)
        with self.assertRaises(ValueError):
            apply_technical_gap_parent_coverage(project, "GAP-0001", {"covered": True})

    def test_requires_descendants(self) -> None:
        items = _items()
        project = _project(items)
        with self.assertRaises(ValueError):
            apply_technical_gap_parent_coverage(project, "GAP-0005", {"covered": True})


if __name__ == "__main__":
    unittest.main()
