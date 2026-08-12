"""附表来源规则严格执行（#228）：选源不回退通用素材、待补资料拦截、质量门禁。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.services import technical_gap_ai_fill as ai_fill
from app.services.technical_gap_ai_fill import (
    AppendixSourceNotReadyError,
    _build_fill_quality_report,
    _reference_materials_for_fill,
    _selected_reference_material_ids,
    compute_technical_ai_fill,
    fill_task_source_block_reason,
    run_technical_ai_fill_for_gap,
)

TABLE_SKILL = "bid-tech-table-filler"


def _routing(status: str, **extra) -> dict:
    return {"status": status, "source": "appendix_source_matrix", "ruleId": "Sheet1!R1", **extra}


def _item_with_task(
    routing: dict | None,
    *,
    matched: list | None = None,
    recommended: list | None = None,
    routed: list | None = None,
) -> tuple[dict, dict, dict]:
    task = {"id": "T1", "skill": TABLE_SKILL, "status": "pending", "blankSource": {"id": "APP1"}}
    appendix_task = {"id": "APP1", "title": "附表A"}
    if routing is not None:
        appendix_task["sourceRouting"] = routing
    if recommended is not None:
        appendix_task["recommendedMaterials"] = recommended
    item = {
        "id": "G1",
        "title": "目录项G1",
        "fillTasks": [task],
        "appendixTasks": [appendix_task],
    }
    if matched is not None:
        item["matchedMaterials"] = matched
    if routed is not None:
        item["sourceRoutedMaterials"] = routed
    return item, task, appendix_task


def _project_with_item(item: dict) -> dict:
    return {"id": "PRJ-SRC", "name": "来源规则项目", "gap_state": {"plan": {"items": [item]}}}


class SelectedReferenceIdsTests(unittest.TestCase):
    """有来源规则时选源只用规则命中素材，为空就是空，不回退 matchedMaterials。"""

    def test_routing_hit_empty_does_not_fall_back_to_matched(self) -> None:
        item, _, appendix_task = _item_with_task(
            _routing("matched", matchedMaterials=[]),
            matched=[{"id": "RAW-MATCHED"}],
            recommended=[],
            routed=[],
        )
        self.assertEqual(_selected_reference_material_ids(item, appendix_task, {}), [])

    def test_routing_uses_only_routed_materials(self) -> None:
        item, _, appendix_task = _item_with_task(
            _routing("matched", matchedMaterials=[{"id": "RAW-TASK-1"}]),
            matched=[{"id": "RAW-MATCHED"}],
            recommended=[{"id": "RAW-TASK-1"}],
            routed=[{"id": "RAW-ITEM-1"}],
        )
        self.assertEqual(
            _selected_reference_material_ids(item, appendix_task, {}),
            ["RAW-TASK-1", "RAW-ITEM-1"],
        )

    def test_no_routing_keeps_matched_fallback(self) -> None:
        item, _, appendix_task = _item_with_task(None, matched=[{"id": "RAW-MATCHED"}])
        self.assertEqual(_selected_reference_material_ids(item, appendix_task, {}), ["RAW-MATCHED"])

    def test_explicit_selection_still_wins(self) -> None:
        item, _, appendix_task = _item_with_task(
            _routing("matched", matchedMaterials=[{"id": "RAW-TASK-1"}]),
            matched=[{"id": "RAW-MATCHED"}],
            recommended=[{"id": "RAW-TASK-1"}],
        )
        self.assertEqual(
            _selected_reference_material_ids(item, appendix_task, {"referenceMaterialIds": ["RAW-PICKED"]}),
            ["RAW-PICKED"],
        )


class ReferenceMaterialsContextTests(unittest.TestCase):
    """有来源规则时 context 不混入通用 matched/candidate 素材。"""

    def test_generic_pools_excluded_when_routing_present(self) -> None:
        item, _, appendix_task = _item_with_task(
            _routing("matched", matchedMaterials=[{"id": "RAW-TASK-1"}]),
            matched=[{"id": "RAW-MATCHED", "folderPath": "技术标/通用素材"}],
            recommended=[{"id": "RAW-TASK-1"}],
        )
        result = _reference_materials_for_fill(item, appendix_task, {}, ["RAW-TASK-1", "RAW-MATCHED"])
        by_id = {material["id"]: material for material in result}
        # 规则命中的素材带完整信息；只在通用池里的 id 解析不出详情（占位），证明未混入
        self.assertEqual(by_id["RAW-TASK-1"]["id"], "RAW-TASK-1")
        self.assertNotIn("folderPath", by_id["RAW-MATCHED"])

    def test_generic_pools_used_without_routing(self) -> None:
        item, _, appendix_task = _item_with_task(
            None,
            matched=[{"id": "RAW-MATCHED", "folderPath": "技术标/通用素材"}],
        )
        result = _reference_materials_for_fill(item, appendix_task, {}, ["RAW-MATCHED"])
        self.assertEqual(result[0]["folderPath"], "技术标/通用素材")


class FillBlockReasonTests(unittest.TestCase):
    def test_manual_required_and_missing_source_blocked(self) -> None:
        for status in ("manual_required", "missing_source"):
            item, task, _ = _item_with_task(_routing(status))
            reason = fill_task_source_block_reason(item, task)
            self.assertTrue(reason, status)

    def test_matched_and_tender_parse_fields_not_blocked(self) -> None:
        for status in ("matched", "tender_parse_fields"):
            item, task, _ = _item_with_task(_routing(status))
            self.assertEqual(fill_task_source_block_reason(item, task), "", status)

    def test_no_routing_not_blocked(self) -> None:
        item, task, _ = _item_with_task(None)
        self.assertEqual(fill_task_source_block_reason(item, task), "")

    def test_word_fill_task_not_blocked(self) -> None:
        item, task, _ = _item_with_task(_routing("manual_required"))
        task["skill"] = "bid-tech-word-placeholder-filler"
        self.assertEqual(fill_task_source_block_reason(item, task), "")


class ComputeBlockTests(unittest.TestCase):
    """manual_required / missing_source：单条填写入口（run_technical_ai_fill_for_gap）直接拒绝。"""

    def test_manual_required_rejected_with_error_code(self) -> None:
        item, _, _ = _item_with_task(_routing("manual_required"))
        with self.assertRaises(AppendixSourceNotReadyError) as ctx:
            run_technical_ai_fill_for_gap(_project_with_item(item), "G1", {"fillTaskId": "T1"})
        self.assertEqual(ctx.exception.code, "APPENDIX_SOURCE_MANUAL_REQUIRED")
        self.assertIn("人工收集", str(ctx.exception))

    def test_missing_source_rejected_with_error_code(self) -> None:
        item, _, _ = _item_with_task(_routing("missing_source"))
        with self.assertRaises(AppendixSourceNotReadyError) as ctx:
            compute_technical_ai_fill(_project_with_item(item), "G1", {"fillTaskId": "T1"})
        self.assertEqual(ctx.exception.code, "APPENDIX_SOURCE_MISSING_SOURCE")


class TenderParseFieldsFillTests(unittest.TestCase):
    """tender_parse_fields：只用招标原文，通用 matchedMaterials 不进 manifest。"""

    def test_tender_routing_uses_only_tender_documents(self) -> None:
        with TemporaryDirectory() as tmp:
            text_path = Path(tmp) / "tender.txt"
            text_path.write_text("招标文件全文", encoding="utf-8")
            item, _, _ = _item_with_task(
                _routing("tender_parse_fields", useTenderParseFields=True, matchedMaterials=[]),
                matched=[{"id": "RAW-MATCHED", "name": "通用素材.docx"}],
                recommended=[],
                routed=[],
            )
            project = _project_with_item(item)
            project["parse_storage"] = {
                "documents": [
                    {"id": "TEN-1", "name": "招标文件.txt", "textPath": str(text_path), "status": "completed"}
                ]
            }
            manifests: list[dict] = []

            def fake_fill(manifest_path, *args, **kwargs):
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                manifests.append(manifest)
                output_file = Path(manifest["outputFile"])
                output_file.write_bytes(b"docx")
                return {
                    "schema_version": "bid-tech-table-fill-v1",
                    "outputFile": str(output_file),
                    "unfilledFields": [],
                    "evidenceRefs": [{"type": "tender", "id": "TEN-1"}],
                    "fillReport": {"targetFieldCount": 1, "filledFieldCount": 1},
                }

            with mock.patch.object(ai_fill, "technical_workspace_dir", return_value=Path(tmp)), mock.patch.object(
                ai_fill, "run_technical_table_filler_skill", side_effect=fake_fill
            ):
                result = compute_technical_ai_fill(project, "G1", {"fillTaskId": "T1"})

            manifest = manifests[0]
            self.assertEqual(manifest["referenceMaterials"], [])
            self.assertEqual(manifest["materialIndex"], [])
            self.assertEqual([doc["id"] for doc in manifest["tenderDocuments"]], ["TEN-1"])
            self.assertEqual(result["qualityReport"]["status"], "passed")


class MatchedEmptyQualityTests(unittest.TestCase):
    """matched 但命中为空：填写可跑，但质量报告必须判不通过，产物不进 s7Ready。"""

    def test_matched_empty_fails_quality_gate(self) -> None:
        with TemporaryDirectory() as tmp:
            item, _, _ = _item_with_task(
                _routing("matched", matchedMaterials=[]),
                matched=[{"id": "RAW-MATCHED", "name": "通用素材.docx"}],
                recommended=[],
                routed=[],
            )
            project = _project_with_item(item)
            manifests: list[dict] = []

            def fake_fill(manifest_path, *args, **kwargs):
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                manifests.append(manifest)
                output_file = Path(manifest["outputFile"])
                output_file.write_bytes(b"docx")
                return {
                    "schema_version": "bid-tech-table-fill-v1",
                    "outputFile": str(output_file),
                    "unfilledFields": [],
                    "evidenceRefs": [{"type": "material", "id": "X"}],
                    "fillReport": {"targetFieldCount": 1, "filledFieldCount": 1},
                }

            with mock.patch.object(ai_fill, "technical_workspace_dir", return_value=Path(tmp)), mock.patch.object(
                ai_fill, "run_technical_table_filler_skill", side_effect=fake_fill
            ):
                result = compute_technical_ai_fill(project, "G1", {"fillTaskId": "T1"})

            manifest = manifests[0]
            # 命中为空就是空：通用素材不进 manifest
            self.assertEqual(manifest["referenceMaterialIds"], [])
            self.assertEqual(manifest["referenceMaterials"], [])
            report = result["qualityReport"]
            self.assertEqual(report["status"], "needs_review")
            self.assertFalse(report["sourceRuleSatisfied"])
            self.assertTrue(report["sourceRuleMessage"])
            self.assertFalse(result["artifact"]["s7Ready"])


class QualityReportRoutingTests(unittest.TestCase):
    """_build_fill_quality_report：来源规则未满足一律不得 passed/no_fill_required。"""

    _PASSING_RESULT = {
        "outputFile": "filled.docx",
        "unfilledFields": [],
        "evidenceRefs": [{"field": "来源"}],
        "fillReport": {"targetFieldCount": 1, "filledFieldCount": 1, "unfilledFieldCount": 0},
    }

    def test_manual_required_never_passes(self) -> None:
        report = _build_fill_quality_report(
            self._PASSING_RESULT,
            output_exists=True,
            routing=_routing("manual_required"),
        )
        self.assertEqual(report["status"], "needs_review")
        self.assertFalse(report["sourceRuleSatisfied"])

    def test_no_fill_required_still_blocked_by_unmet_source(self) -> None:
        report = _build_fill_quality_report(
            {"outputFile": "filled.docx", "fillReport": {"noFillRequired": True}},
            output_exists=True,
            routing=_routing("missing_source"),
        )
        self.assertEqual(report["status"], "needs_review")

    def test_matched_with_materials_passes_normally(self) -> None:
        report = _build_fill_quality_report(
            self._PASSING_RESULT,
            output_exists=True,
            routing=_routing("matched", matchedMaterials=[{"id": "RAW-1"}]),
        )
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["sourceRuleSatisfied"])

    def test_no_routing_unchanged(self) -> None:
        report = _build_fill_quality_report(self._PASSING_RESULT, output_exists=True)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["sourceRuleSatisfied"])


if __name__ == "__main__":
    unittest.main()
