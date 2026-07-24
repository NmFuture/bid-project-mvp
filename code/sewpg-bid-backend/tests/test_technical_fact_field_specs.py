from __future__ import annotations

"""技术标事实表 148 条字段 spec 与 spec 驱动骨架（reconcile）的测试。"""

import unittest

from app.services.technical_fact_field_specs import fillable_specs, load_specs
from app.services.technical_gap_fact_table import (
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_EXTRACTED,
    FACT_STATUS_MISSING_SOURCE,
    FACT_STATUS_NOT_APPLICABLE,
    FACT_STATUS_PENDING_CONFIRMATION,
    FACT_STATUS_UNEXTRACTED,
    build_project_fact_table,
    normalize_fact_status,
    normalize_project_fact_field,
    reconcile_fact_fields_with_specs,
)


class TestTechnicalFactFieldSpecs(unittest.TestCase):
    def test_specs_json_matches_0722_checklist(self) -> None:
        specs = load_specs()
        self.assertEqual(len(specs), 148)
        fillable = fillable_specs()
        self.assertEqual(len(fillable), 128)
        self.assertEqual(sum(1 for spec in specs if spec.get("needsConfirmation")), 14)
        self.assertEqual(sum(1 for spec in specs if spec.get("sourceKind") == "template"), 20)
        # 模板更新条目不进填值流程
        self.assertTrue(all(spec.get("valueRequired") for spec in fillable))
        # 每条 spec 都有稳定 key 与字段名
        self.assertTrue(all(spec.get("key") and spec.get("label") for spec in specs))
        self.assertEqual(len({spec["key"] for spec in specs}), 148)

    def test_legacy_status_mapping(self) -> None:
        self.assertEqual(normalize_fact_status("candidate", has_value=True), FACT_STATUS_EXTRACTED)
        self.assertEqual(normalize_fact_status("missing", has_value=False), FACT_STATUS_MISSING_SOURCE)
        self.assertEqual(normalize_fact_status("confirmed", has_value=True), FACT_STATUS_CONFIRMED)
        self.assertEqual(normalize_fact_status("unextracted", has_value=False), FACT_STATUS_UNEXTRACTED)
        self.assertEqual(normalize_fact_status("bogus", has_value=True), FACT_STATUS_EXTRACTED)
        self.assertEqual(normalize_fact_status("", has_value=False), FACT_STATUS_MISSING_SOURCE)


class TestReconcileFactFieldsWithSpecs(unittest.TestCase):
    def test_skeleton_fields_cover_all_fillable_specs(self) -> None:
        fields_by_key: dict[str, dict] = {}
        reconcile_fact_fields_with_specs(fields_by_key)
        self.assertEqual(len(fields_by_key), 128)
        statuses = {field["status"] for field in fields_by_key.values()}
        self.assertEqual(statuses, {FACT_STATUS_UNEXTRACTED})
        seqs = {field["specSeq"] for field in fields_by_key.values()}
        self.assertEqual(len(seqs), 128)

    def test_matched_field_gets_spec_metadata(self) -> None:
        fields_by_key = {
            "功率曲线保证率": {
                "id": "FACT-0001",
                "key": "功率曲线保证率",
                "label": "功率曲线保证率",
                "value": "95%",
                "status": FACT_STATUS_EXTRACTED,
            }
        }
        reconcile_fact_fields_with_specs(fields_by_key)
        field = fields_by_key["功率曲线保证率"]
        self.assertEqual(field["specSeq"], 4)
        self.assertEqual(field["label"], "功率曲线保证率")
        # 其余 spec 仍为骨架
        self.assertEqual(len(fields_by_key), 128)

    def test_needs_confirmation_spec_becomes_pending(self) -> None:
        # spec 87「函件签署日期」别名「日期」，无待确认；spec 7「发电小时数/电量承诺函版本」需确认
        fields_by_key = {
            "日期": {
                "id": "FACT-0001",
                "key": "日期",
                "label": "日期",
                "value": "2026年07月23日",
                "status": FACT_STATUS_EXTRACTED,
            }
        }
        reconcile_fact_fields_with_specs(fields_by_key)
        self.assertEqual(fields_by_key["日期"].get("specSeq"), 87)
        self.assertEqual(fields_by_key["日期"]["status"], FACT_STATUS_EXTRACTED)

        pending_spec = next(spec for spec in fillable_specs() if spec["seq"] == 114)  # 单机功率曲线考核阈值
        from app.services.technical_gap_fact_table import fact_label_key

        fields_by_key = {
            fact_label_key(pending_spec["label"]): {
                "id": "FACT-0002",
                "key": fact_label_key(pending_spec["label"]),
                "label": pending_spec["label"],
                "value": "保证值版",
                "status": FACT_STATUS_EXTRACTED,
            }
        }
        reconcile_fact_fields_with_specs(fields_by_key)
        field = fields_by_key[fact_label_key(pending_spec["label"])]
        self.assertEqual(field["status"], FACT_STATUS_PENDING_CONFIRMATION)
        self.assertTrue(field["needsConfirmation"])

    def test_previous_manual_result_survives_rebuild(self) -> None:
        from app.services.technical_gap_fact_table import fact_label_key

        spec = next(spec for spec in fillable_specs() if spec["seq"] == 113)  # 承诺函致函对象全称（待确认）
        existing_key = fact_label_key(spec["label"])
        existing_by_key = {
            existing_key: {
                "label": spec["label"],
                "value": "华能集团有限公司",
                "status": FACT_STATUS_CONFIRMED,
                "confirmedAt": "2026-07-23T00:00:00",
                "confirmedBy": "安博成",
            }
        }
        fields_by_key: dict[str, dict] = {}
        reconcile_fact_fields_with_specs(fields_by_key, existing_by_key)
        field = fields_by_key[existing_key]
        self.assertEqual(field["value"], "华能集团有限公司")
        self.assertEqual(field["status"], FACT_STATUS_CONFIRMED)
        self.assertEqual(field["confirmedBy"], "安博成")

    def test_one_heuristic_field_belongs_to_single_spec(self) -> None:
        # 「安全等级」可同时命中 spec 2/3，先到先得，另一个保持未提取
        fields_by_key = {
            "安全等级": {
                "id": "FACT-0001",
                "key": "安全等级",
                "label": "安全等级",
                "value": "IEC S",
                "status": FACT_STATUS_EXTRACTED,
            }
        }
        reconcile_fact_fields_with_specs(fields_by_key)
        self.assertEqual(fields_by_key["安全等级"]["specSeq"], 2)
        spec3 = next(field for field in fields_by_key.values() if field.get("specSeq") == 3)
        self.assertEqual(spec3["status"], FACT_STATUS_UNEXTRACTED)


class TestNormalizeProjectFactFieldV2(unittest.TestCase):
    def _normalize(self, field: dict, *, confirm: bool = False) -> dict:
        return normalize_project_fact_field(
            field,
            index=1,
            confirm=confirm,
            operator="测试用户",
            saved_at="2026-07-23T00:00:00",
        )

    def test_confirm_keeps_not_applicable(self) -> None:
        field = self._normalize({"label": "叶片产能", "status": "not_applicable", "notes": "本项目无叶片"}, confirm=True)
        self.assertEqual(field["status"], FACT_STATUS_NOT_APPLICABLE)

    def test_confirm_maps_legacy_and_empty(self) -> None:
        self.assertEqual(self._normalize({"label": "A", "value": "1"}, confirm=True)["status"], FACT_STATUS_CONFIRMED)
        self.assertEqual(self._normalize({"label": "B"}, confirm=True)["status"], FACT_STATUS_MISSING_SOURCE)
        self.assertEqual(
            self._normalize({"label": "C", "value": "x", "status": "candidate"})["status"],
            FACT_STATUS_EXTRACTED,
        )

    def test_spec_metadata_is_preserved(self) -> None:
        field = self._normalize(
            {
                "label": "单台机组功率曲线保证率（%）",
                "value": "95%",
                "specSeq": 4,
                "specKey": "单台机组功率曲线保证率(%)",
                "reviewLabel": "单台机组功率曲线保证率（%）",
                "needsConfirmation": False,
                "sourceKind": "tender",
            }
        )
        self.assertEqual(field["specSeq"], 4)
        self.assertEqual(field["sourceKind"], "tender")


class TestBuildProjectFactTableWithSpecs(unittest.TestCase):
    def test_build_contains_all_spec_fields_and_v2_schema(self) -> None:
        project = {
            "id": "P-SPEC",
            "name": "翁牛特旗120万千瓦风电项目",
            "customerName": "华能",
            "identity": {"owner": "华能集团"},
            "parse_result": {},
        }
        table = build_project_fact_table(project, {})
        self.assertEqual(table["schemaVersion"], "bid-project-fact-table-v2")
        spec_fields = [field for field in table["fields"] if field.get("specSeq")]
        self.assertEqual(len(spec_fields), 128)
        self.assertEqual(table["summary"]["specTotal"], 128)
        # 项目名称命中 spec 112
        name_field = next(field for field in spec_fields if field["specSeq"] == 112)
        self.assertEqual(name_field["value"], "翁牛特旗120万千瓦风电项目")
        self.assertEqual(name_field["status"], FACT_STATUS_EXTRACTED)
        # 无来源的 spec 骨架保持未提取
        cert_field = next(field for field in spec_fields if field["specSeq"] == 1)
        self.assertEqual(cert_field["status"], FACT_STATUS_UNEXTRACTED)
        self.assertEqual(cert_field["value"], "")


if __name__ == "__main__":
    unittest.main()
