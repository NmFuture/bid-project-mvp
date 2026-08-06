from __future__ import annotations

"""技术标事实表 148 条字段 spec 与 spec 驱动骨架（reconcile）的测试。"""

import unittest
from unittest.mock import patch

from app.services import technical_gap_fact_table as fact_table_module
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
    summarize_project_fact_fields,
)


class TestTechnicalFactFieldSpecs(unittest.TestCase):
    def test_specs_json_matches_0722_checklist(self) -> None:
        specs = load_specs()
        self.assertEqual(len(specs), 148)
        fillable = fillable_specs()
        # 0722 清单来源列没有整格留空的条目，20 条「/」是来源未指定而非模板占位，同样要取值
        self.assertEqual(len(fillable), 148)
        self.assertEqual(sum(1 for spec in specs if spec.get("needsConfirmation")), 14)
        self.assertEqual(sum(1 for spec in specs if spec.get("sourceKind") == "template"), 0)
        self.assertEqual(sum(1 for spec in specs if spec.get("sourceKind") == "unspecified"), 20)
        # 模板更新条目不进填值流程
        self.assertTrue(all(spec.get("valueRequired") for spec in fillable))
        # 每条 spec 都有稳定 key 与字段名
        self.assertTrue(all(spec.get("key") and spec.get("label") for spec in specs))
        self.assertEqual(len({spec["key"] for spec in specs}), 148)

    def test_slash_reference_is_unspecified_not_template(self) -> None:
        """来源列「/」= 来源未指定但仍需取值；只有整格留空才是模板占位。"""
        from app.services.technical_fact_field_specs import normalize_spec_source_kind
        from app.services.technical_fact_spec_import import classify_source

        self.assertEqual(classify_source("/"), "unspecified")
        self.assertEqual(classify_source(""), "template")
        self.assertEqual(classify_source("项目定制-风资源报告"), "material")

        # 历史快照里「/」被归成 template，加载时按原始 referenceFile 重算
        migrated = normalize_spec_source_kind(
            {"label": "主机舱-超细干粉灭火装置数量（件）", "referenceFile": "/", "sourceKind": "template", "valueRequired": False}
        )
        self.assertEqual(migrated["sourceKind"], "unspecified")
        self.assertTrue(migrated["valueRequired"])

        # 口径一致的 spec 原样返回，不产生多余拷贝
        intact = {"label": "x", "referenceFile": "招标文件", "sourceKind": "tender", "valueRequired": True}
        self.assertIs(normalize_spec_source_kind(intact), intact)

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
        self.assertEqual(len(fields_by_key), 148)
        statuses = {field["status"] for field in fields_by_key.values()}
        self.assertEqual(statuses, {FACT_STATUS_UNEXTRACTED})
        seqs = {field["specSeq"] for field in fields_by_key.values()}
        self.assertEqual(len(seqs), 148)

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
        self.assertEqual(len(fields_by_key), 148)

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

    def test_out_of_spec_compatibility_marker_is_preserved(self) -> None:
        field = self._normalize(
            {
                "label": "旧规则字段",
                "value": "人工确认值",
                "status": FACT_STATUS_CONFIRMED,
                "outOfSpec": True,
            }
        )

        self.assertTrue(field["outOfSpec"])


class TestBuildProjectFactTableWithSpecs(unittest.TestCase):
    def _spec_gap_state(self) -> dict:
        """字段骨架来自项目实时表（gap_state["factSpecs"]）；测试用全局清单做项目 specs。"""
        return {
            "factSpecs": {
                "fileName": "测试实时表.xlsx",
                "uploadedAt": "2026-07-27T00:00:00",
                "specs": fillable_specs(),
            }
        }

    def test_build_contains_all_spec_fields_and_v2_schema(self) -> None:
        project = {
            "id": "P-SPEC",
            "name": "翁牛特旗120万千瓦风电项目",
            "customerName": "华能",
            "identity": {"owner": "华能集团"},
            "parse_result": {},
        }
        gap_state = self._spec_gap_state()
        table = build_project_fact_table(project, gap_state)
        self.assertEqual(table["schemaVersion"], "bid-project-fact-table-v2")
        spec_fields = [field for field in table["fields"] if field.get("specSeq")]
        self.assertEqual(len(spec_fields), 148)
        self.assertEqual(table["summary"]["specTotal"], 148)
        # 项目名称命中 spec 112
        name_field = next(field for field in spec_fields if field["specSeq"] == 112)
        self.assertEqual(name_field["value"], "翁牛特旗120万千瓦风电项目")
        self.assertEqual(name_field["status"], FACT_STATUS_EXTRACTED)
        # 无来源的 spec 骨架保持未提取
        cert_field = next(field for field in spec_fields if field["specSeq"] == 1)
        self.assertEqual(cert_field["status"], FACT_STATUS_UNEXTRACTED)
        self.assertEqual(cert_field["value"], "")

    def test_build_fields_are_spec_rows_only_and_merge_off_checklist_values(self) -> None:
        """以清单为唯一骨架：字段数 == spec 条数；清单外来源的值并入匹配 spec 行的取值与
        来源证据（sourceRefs），匹配不到 spec 的候选不再单独成行。"""
        project = {
            "id": "P-SPEC",
            "name": "翁牛特旗120万千瓦风电项目",
            "customerName": "华能",
            "identity": {"owner": "华能集团"},
            "parse_result": {},
        }
        table = build_project_fact_table(project, self._spec_gap_state())
        self.assertEqual(len(table["fields"]), 148)
        self.assertTrue(all(field.get("specSeq") for field in table["fields"]))
        # 项目名称（硬编码候选，type=project）并入 spec 112 行
        name_field = next(field for field in table["fields"] if field["specSeq"] == 112)
        self.assertEqual(name_field["value"], "翁牛特旗120万千瓦风电项目")
        self.assertTrue(any(ref.get("type") == "project" for ref in name_field["sourceRefs"]))
        # 匹配不到任何 spec 的候选（招标方/客户名称）不成行
        labels = {field["label"] for field in table["fields"]}
        self.assertNotIn("招标方", labels)
        self.assertNotIn("客户名称", labels)

    def test_build_keeps_manual_fields_appended_after_spec_rows(self) -> None:
        """人工新增字段（sourceRefs 含 manualFact）保留为行、追加在 spec 行之后，且不计入 spec 统计。"""
        project = {"id": "P-SPEC", "name": "人工字段项目", "parse_result": {}}
        gap_state = {
            **self._spec_gap_state(),
            "projectFactTable": {
                "schemaVersion": "bid-project-fact-table-v2",
                "fields": [
                    {
                        "id": "FACT-9001",
                        "key": "业主特殊要求",
                        "label": "业主特殊要求",
                        "value": "按补充协议执行",
                        "status": "confirmed",
                        "sourceRefs": [{"type": "manualFact", "title": "人工新增", "field": "业主特殊要求"}],
                    }
                ],
            },
        }
        table = build_project_fact_table(project, gap_state)
        self.assertEqual(len(table["fields"]), 149)
        manual = table["fields"][-1]
        self.assertEqual(manual["label"], "业主特殊要求")
        self.assertEqual(manual["value"], "按补充协议执行")
        self.assertFalse(manual.get("specSeq"))
        self.assertEqual(table["summary"]["specTotal"], 148)

    def test_build_preserves_confirmed_field_removed_from_current_specs(self) -> None:
        """规则换版后，旧规则下已确认字段保留为清单外历史事实，不污染新规则进度。"""
        project = {"id": "P-SPEC", "name": "规则换版项目", "parse_result": {}}
        gap_state = {
            "projectFactTable": {
                "schemaVersion": "bid-project-fact-table-v2",
                "fields": [
                    {
                        "id": "FACT-9002",
                        "key": "旧规则字段",
                        "label": "旧规则字段",
                        "value": "已人工确认的历史值",
                        "status": FACT_STATUS_CONFIRMED,
                        "specSeq": 88,
                        "specKey": "legacy-field",
                        "sourceRefs": [{"type": "project", "title": "旧项目资料"}],
                    }
                ],
            }
        }
        current_specs = [
            {
                "seq": 0,
                "key": "current-field",
                "label": "当前规则字段",
                "valueRequired": True,
                "sourceKind": "tender",
            }
        ]

        with (
            patch.object(
                fact_table_module,
                "resolve_project_specs",
                return_value=(current_specs, {"source": "project", "ruleId": "fsr-current"}),
            ),
            patch.object(fact_table_module, "project_material_fact_fields", return_value=[]),
        ):
            table = build_project_fact_table(project, gap_state)

        self.assertEqual(table["summary"]["specTotal"], 1)
        current = next(field for field in table["fields"] if field["label"] == "当前规则字段")
        self.assertEqual(current["specSeq"], 0)
        legacy = next(field for field in table["fields"] if field["label"] == "旧规则字段")
        self.assertEqual(legacy["value"], "已人工确认的历史值")
        self.assertEqual(legacy["status"], FACT_STATUS_CONFIRMED)
        self.assertTrue(legacy["outOfSpec"])
        self.assertNotIn("specSeq", legacy)
        self.assertEqual(table["factSpecsRef"]["ruleId"], "fsr-current")

    def test_build_falls_back_to_global_specs_when_project_not_uploaded(self) -> None:
        """项目未上传清单时以全局默认清单为骨架。"""
        project = {"id": "P-GLOBAL", "name": "全局清单项目", "parse_result": {}}
        table = build_project_fact_table(project, {})
        spec_fields = [field for field in table["fields"] if field.get("specSeq")]
        self.assertEqual(len(spec_fields), len(load_specs()))
        self.assertEqual(table["summary"]["specTotal"], len(load_specs()))

    def test_build_keeps_union_behavior_when_no_specs_available(self) -> None:
        """极端兜底：项目未上传且全局清单加载失败，维持来源并集行为并记 warning。"""
        project = {"id": "P-NOSPEC", "name": "无清单项目", "parse_result": {}}
        with patch.object(
            fact_table_module,
            "resolve_project_specs",
            return_value=([], {"source": "default"}),
        ):
            with self.assertLogs(fact_table_module.logger, level="WARNING"):
                table = build_project_fact_table(project, {})
        self.assertTrue(table["fields"])
        self.assertTrue(all(not field.get("specSeq") for field in table["fields"]))
        self.assertEqual(table["summary"]["specTotal"], 0)


class TestSummarizeSpecProgressBuckets(unittest.TestCase):
    def test_four_buckets_are_exclusive_and_sum_to_spec_total(self) -> None:
        fields = [
            {"label": "A", "specSeq": 1, "status": "confirmed", "value": "x"},
            {"label": "B", "specSeq": 2, "status": "pending_confirmation", "value": "x"},
            {"label": "C", "specSeq": 3, "status": "unextracted", "value": ""},
            {"label": "D", "specSeq": 4, "status": "missing_source", "value": ""},
            {"label": "E", "specSeq": 5, "status": "extracted", "value": "x"},
            {"label": "F", "specSeq": 6, "status": "conflict", "value": "x"},
            # 人工新增字段（无 specSeq）不计入清单统计
            {"label": "G", "status": "confirmed", "value": "x", "sourceRefs": [{"type": "manualFact"}]},
        ]
        summary = summarize_project_fact_fields(fields)
        self.assertEqual(summary["specTotal"], 6)
        self.assertEqual(summary["specConfirmedCount"], 1)
        self.assertEqual(summary["specPendingConfirmationCount"], 1)
        self.assertEqual(summary["specUnfilledCount"], 2)
        self.assertEqual(summary["specFilledUnconfirmedCount"], 2)
        self.assertEqual(
            summary["specConfirmedCount"]
            + summary["specPendingConfirmationCount"]
            + summary["specUnfilledCount"]
            + summary["specFilledUnconfirmedCount"],
            summary["specBuiltTotal"],
        )
        # 七态计数仍是全表口径（含人工行）
        self.assertEqual(summary["totalCount"], 7)
        self.assertEqual(summary["confirmedCount"], 2)

    def test_spec_seq_zero_is_counted_with_stable_bound_total(self) -> None:
        fields = [{"label": "A", "specSeq": 0, "status": "confirmed", "value": "x"}]

        summary = summarize_project_fact_fields(fields, spec_total=2)

        self.assertEqual(summary["specTotal"], 2)
        self.assertEqual(summary["specBuiltTotal"], 1)
        self.assertEqual(summary["specMatched"], 1)
        self.assertEqual(summary["specConfirmedCount"], 1)


if __name__ == "__main__":
    unittest.main()
