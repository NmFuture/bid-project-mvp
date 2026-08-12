from __future__ import annotations

"""技术标事实表 148 条字段 spec 与 spec 驱动骨架（reconcile）的测试。"""

import unittest
from unittest.mock import patch

from app.services import technical_gap_fact_table as fact_table_module
from app.services.technical_fact_field_specs import fillable_specs, load_specs
from app.services.technical_gap_fact_table import (
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_NOT_APPLICABLE,
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

    def test_legacy_status_collapses_to_three_states(self) -> None:
        # 历史四/七态一律按有无取值收敛，不需要迁移脚本
        for legacy in ("candidate", "extracted", "pending_confirmation", "conflict", "bogus", ""):
            self.assertEqual(normalize_fact_status(legacy, has_value=True), FACT_STATUS_CONFIRMED)
        for legacy in ("missing", "missing_source", "unextracted", "bogus", ""):
            self.assertEqual(normalize_fact_status(legacy, has_value=False), FACT_STATUS_UNEXTRACTED)
        self.assertEqual(normalize_fact_status("confirmed", has_value=True), FACT_STATUS_CONFIRMED)
        # 不适用是人工裁定，与有无取值无关
        self.assertEqual(normalize_fact_status("not_applicable", has_value=False), FACT_STATUS_NOT_APPLICABLE)
        self.assertEqual(normalize_fact_status("not_applicable", has_value=True), FACT_STATUS_NOT_APPLICABLE)


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
                "status": FACT_STATUS_CONFIRMED,
            }
        }
        reconcile_fact_fields_with_specs(fields_by_key)
        field = fields_by_key["功率曲线保证率"]
        self.assertEqual(field["specSeq"], 4)
        self.assertEqual(field["label"], "功率曲线保证率")
        # 其余 spec 仍为骨架
        self.assertEqual(len(fields_by_key), 148)

    def test_spec_placeholder_and_target_file_reach_fields(self) -> None:
        # 正文填写按「待填写文件 + 占位符原文」定位字段，这两列必须随字段下发
        fields_by_key: dict[str, dict] = {}
        reconcile_fact_fields_with_specs(fields_by_key)
        with_placeholder = [field for field in fields_by_key.values() if field.get("placeholder")]
        self.assertEqual(len(with_placeholder), 148)
        self.assertTrue(all(field.get("targetFile") for field in fields_by_key.values()))
        tower = next(field for field in fields_by_key.values() if field["label"] == "第1段（底）塔节底部直径（m）")
        self.assertIn("待填写-塔筒设计方案专题报告.docx", tower["targetFile"])
        self.assertEqual(tower["placeholder"], "[技术方案，待填写]")

    def test_spec_metadata_survives_normalization(self) -> None:
        fields_by_key: dict[str, dict] = {}
        reconcile_fact_fields_with_specs(fields_by_key)
        source = next(field for field in fields_by_key.values() if field["label"] == "场址要求安全等级")
        normalized = normalize_project_fact_field(
            source, index=1, confirm=False, operator="测试用户", saved_at="2026-08-06T00:00:00Z"
        )
        self.assertEqual(normalized["placeholder"], source["placeholder"])
        self.assertEqual(normalized["targetFile"], source["targetFile"])

    def test_needs_confirmation_spec_keeps_status(self) -> None:
        # needsConfirmation 只作为「口径要人工核」的展示标记随字段下发，不再改状态
        fields_by_key = {
            "日期": {
                "id": "FACT-0001",
                "key": "日期",
                "label": "日期",
                "value": "2026年07月23日",
                "status": FACT_STATUS_CONFIRMED,
            }
        }
        reconcile_fact_fields_with_specs(fields_by_key)
        self.assertEqual(fields_by_key["日期"].get("specSeq"), 87)
        self.assertEqual(fields_by_key["日期"]["status"], FACT_STATUS_CONFIRMED)

        pending_spec = next(spec for spec in fillable_specs() if spec["seq"] == 114)  # 单机功率曲线考核阈值
        from app.services.technical_gap_fact_table import fact_label_key

        fields_by_key = {
            fact_label_key(pending_spec["label"]): {
                "id": "FACT-0002",
                "key": fact_label_key(pending_spec["label"]),
                "label": pending_spec["label"],
                "value": "保证值版",
                "status": FACT_STATUS_CONFIRMED,
            }
        }
        reconcile_fact_fields_with_specs(fields_by_key)
        field = fields_by_key[fact_label_key(pending_spec["label"])]
        self.assertEqual(field["status"], FACT_STATUS_CONFIRMED)
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
                # 人工标记是跨轮保留的唯一依据：status 三态收敛后规则抽取的值也是
                # confirmed，只看状态会把整张表都当成人工结论保留下来
                "sourceRefs": [{"type": "manualEdit", "title": "人工填写"}],
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
                "status": FACT_STATUS_CONFIRMED,
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

    def test_status_follows_value_presence(self) -> None:
        self.assertEqual(self._normalize({"label": "A", "value": "1"}, confirm=True)["status"], FACT_STATUS_CONFIRMED)
        self.assertEqual(self._normalize({"label": "B"}, confirm=True)["status"], FACT_STATUS_UNEXTRACTED)
        self.assertEqual(
            self._normalize({"label": "C", "value": "x", "status": "candidate"})["status"],
            FACT_STATUS_CONFIRMED,
        )

    def test_confirm_marks_field_as_human_authored(self) -> None:
        # 人在页面上保存过 → 打人工标记，重建时才认得出这是人工结论
        field = self._normalize({"label": "A", "value": "1"}, confirm=True)
        self.assertTrue(any(ref.get("type") == "manualEdit" for ref in field["sourceRefs"]))
        self.assertTrue(fact_table_module.is_human_authored_fact_field(field))
        # 规则抽取路径（confirm=False）不打标记，重建时该值重来
        auto = self._normalize({"label": "A", "value": "1"})
        self.assertFalse(any(ref.get("type") == "manualEdit" for ref in auto["sourceRefs"]))
        self.assertFalse(fact_table_module.is_human_authored_fact_field(auto))

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
        self.assertEqual(name_field["status"], FACT_STATUS_CONFIRMED)
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

    def test_single_turbine_pins_project_selected_fields(self) -> None:
        """单机型：人选的机型参数不带序号、提到表首，只比改动前多一行清单外的「基础形式」。"""
        project = {
            "id": "P-SPEC",
            "name": "单机型项目",
            "parse_result": {},
            "turbineModels": [{"model": "EW10.0-220", "turbineCount": "25", "foundationType": "桩基础"}],
        }
        table = build_project_fact_table(project, self._spec_gap_state())

        self.assertEqual(len(table["fields"]), 149)
        self.assertEqual(table["summary"]["specTotal"], 148)
        self.assertEqual(
            [field["label"] for field in table["fields"][:6]],
            ["投标机型", "机组台数", "基础形式", "单机容量", "叶轮直径", "轮毂高度"],
        )
        by_label = {field["label"]: field for field in table["fields"]}
        self.assertEqual(by_label["投标机型"]["value"], "EW10.0-220")
        self.assertEqual(by_label["机组台数"]["value"], "25")
        self.assertEqual(by_label["基础形式"]["value"], "桩基础")
        # 命中清单的仍带 specSeq、照常计进度；基础形式是清单外行，不计
        self.assertEqual(by_label["投标机型"]["specSeq"], 11)
        self.assertEqual(by_label["机组台数"]["specSeq"], 84)
        self.assertIsNone(by_label["基础形式"].get("specSeq"))
        self.assertTrue(all(field["turbineGroup"] == 1 for field in table["fields"][:6]))

    def test_multi_turbine_expands_rows_per_model(self) -> None:
        """多机型：每个机型一组带序号的行置顶，不带序号的机型/台数留给清单行取全场口径。"""
        project = {
            "id": "P-SPEC",
            "name": "混排项目",
            "parse_result": {},
            "turbineModels": [
                {"model": "EW10.0-220", "turbineCount": "15", "foundationType": "桩基础"},
                {"model": "EW8.5-230", "turbineCount": "10", "foundationType": "重力基础"},
            ],
        }
        table = build_project_fact_table(project, self._spec_gap_state())

        self.assertEqual(len(table["fields"]), 160)
        self.assertEqual(table["summary"]["specTotal"], 148)
        self.assertEqual(
            [field["label"] for field in table["fields"][:12]],
            [
                "投标机型1", "机型1台数", "机型1基础形式", "机型1单机容量", "机型1叶轮直径", "机型1轮毂高度",
                "投标机型2", "机型2台数", "机型2基础形式", "机型2单机容量", "机型2叶轮直径", "机型2轮毂高度",
            ],
        )
        by_label = {field["label"]: field for field in table["fields"]}
        self.assertEqual(by_label["投标机型1"]["value"], "EW10.0-220")
        self.assertEqual(by_label["机型1台数"]["value"], "15")
        self.assertEqual(by_label["机型2基础形式"]["value"], "重力基础")
        self.assertEqual(by_label["投标机型1"]["turbineModelLabel"], "EW10.0-220")
        self.assertEqual(by_label["投标机型2"]["turbineGroup"], 2)
        # 清单第 11/84 行给全场口径：机型合并串、台数各行之和
        self.assertEqual(by_label["投标机型"]["value"], "EW10.0-220、EW8.5-230")
        self.assertEqual(by_label["机组台数"]["value"], "25")
        self.assertIsNone(by_label["投标机型"].get("turbineGroup"))
        # 多机型不再出不带序号的「基础形式」
        self.assertNotIn("基础形式", by_label)

    def test_multi_turbine_count_sum_skips_incomplete_rows(self) -> None:
        """任一行没填台数就不给总数，回落到招标文件与素材抽取。"""
        project = {
            "id": "P-SPEC",
            "name": "混排项目",
            "parse_result": {},
            "turbineModels": [
                {"model": "EW10.0-220", "turbineCount": "15"},
                {"model": "EW8.5-230", "turbineCount": ""},
            ],
        }
        table = build_project_fact_table(project, self._spec_gap_state())
        # 没有项目表单候选时，台数那行退回清单骨架（标签用清单原文），值为空
        count_field = next(field for field in table["fields"] if field.get("specSeq") == 84)
        self.assertEqual(count_field["value"], "")

    @staticmethod
    def _gap_state_with_confirmed_legacy_field(rule_id: str) -> dict:
        return {
            "projectFactTable": {
                "schemaVersion": "bid-project-fact-table-v2",
                "factSpecsRef": {"source": "project", "ruleId": rule_id},
                "fields": [
                    {
                        "id": "FACT-9002",
                        "key": "旧规则字段",
                        "label": "旧规则字段",
                        "value": "已人工确认的历史值",
                        "status": FACT_STATUS_CONFIRMED,
                        "specSeq": 88,
                        "specKey": "legacy-field",
                        # 人工标记是跨轮保留的依据，不再看 status
                        "sourceRefs": [
                            {"type": "manualEdit", "title": "人工填写"},
                            {"type": "project", "title": "旧项目资料"},
                        ],
                    }
                ],
            }
        }

    _CURRENT_SPECS = [
        {
            "seq": 0,
            "key": "current-field",
            "label": "当前规则字段",
            "valueRequired": True,
            "sourceKind": "tender",
        }
    ]

    def _build_with_current_specs(self, gap_state: dict) -> dict:
        with (
            patch.object(
                fact_table_module,
                "resolve_fact_specs",
                return_value=(self._CURRENT_SPECS, {"source": "global", "ruleId": "fsr-current"}),
            ),
            patch.object(fact_table_module, "project_material_fact_fields", return_value=[]),
        ):
            return build_project_fact_table({"id": "P-SPEC", "name": "规则项目", "parse_result": {}}, gap_state)

    def test_build_preserves_confirmed_field_on_same_rule_version(self) -> None:
        """同一份 Excel 刷新：已人工确认但不在当前清单的字段保留为清单外历史事实。"""
        table = self._build_with_current_specs(self._gap_state_with_confirmed_legacy_field("fsr-current"))

        self.assertEqual(table["summary"]["specTotal"], 1)
        current = next(field for field in table["fields"] if field["label"] == "当前规则字段")
        self.assertEqual(current["specSeq"], 0)
        legacy = next(field for field in table["fields"] if field["label"] == "旧规则字段")
        self.assertEqual(legacy["value"], "已人工确认的历史值")
        self.assertEqual(legacy["status"], FACT_STATUS_CONFIRMED)
        self.assertTrue(legacy["outOfSpec"])
        self.assertNotIn("specSeq", legacy)
        self.assertEqual(table["factSpecsRef"]["ruleId"], "fsr-current")

    def test_build_drops_ai_values_but_keeps_human_edits_on_refresh(self) -> None:
        """同一份 Excel 刷新：AI 填的值一律重来，人改过的格子（manualEdit）保留。

        回归 PRJ-0002：AI 在缺素材时给字段凑了错值，旧逻辑「有值就继承」让错值
        跨轮黏住，AI 自己也不再纠正。
        """
        gap_state = {
            "projectFactTable": {
                "schemaVersion": "bid-project-fact-table-v2",
                "factSpecsRef": {"source": "project", "ruleId": "fsr-current"},
                "fields": [
                    {
                        "id": "FACT-0001",
                        "key": "ai填的字段",
                        "label": "AI 填的字段",
                        "value": "AI 凑的错值",
                        "status": FACT_STATUS_CONFIRMED,
                        "specSeq": 1,
                        "specKey": "ai-field",
                        "sourceRefs": [{"type": "factCurator", "title": "AI 匹配填充"}],
                    },
                    {
                        "id": "FACT-0002",
                        "key": "人改的字段",
                        "label": "人改的字段",
                        "value": "人工订正值",
                        "status": FACT_STATUS_CONFIRMED,
                        "specSeq": 2,
                        "specKey": "human-field",
                        "sourceRefs": [{"type": "manualEdit", "title": "人工修改"}],
                    },
                ],
            }
        }
        specs = [
            {"seq": 1, "key": "ai-field", "label": "AI 填的字段", "valueRequired": True, "sourceKind": "tender"},
            {"seq": 2, "key": "human-field", "label": "人改的字段", "valueRequired": True, "sourceKind": "tender"},
        ]
        with (
            patch.object(
                fact_table_module,
                "resolve_fact_specs",
                return_value=(specs, {"source": "global", "ruleId": "fsr-current"}),
            ),
            patch.object(fact_table_module, "project_material_fact_fields", return_value=[]),
        ):
            table = build_project_fact_table({"id": "P-SPEC", "name": "刷新项目", "parse_result": {}}, gap_state)

        ai_field = next(field for field in table["fields"] if field["label"] == "AI 填的字段")
        self.assertEqual(ai_field["value"], "")
        self.assertEqual(ai_field["status"], FACT_STATUS_UNEXTRACTED)
        human_field = next(field for field in table["fields"] if field["label"] == "人改的字段")
        self.assertEqual(human_field["value"], "人工订正值")
        self.assertTrue(
            any(ref.get("type") == "manualEdit" for ref in human_field["sourceRefs"]),
            "人工标记必须跨轮保留，否则下一轮重建会把它当 AI 值冲掉",
        )

    def test_build_drops_previous_fields_when_rule_version_changes(self) -> None:
        """重传新 Excel（规则版本变更）视作从头来：上一版的值连人工确认的也不继承。"""
        table = self._build_with_current_specs(self._gap_state_with_confirmed_legacy_field("fsr-previous"))

        self.assertEqual(table["summary"]["specTotal"], 1)
        self.assertNotIn("旧规则字段", [field["label"] for field in table["fields"]])
        self.assertEqual(table["factSpecsRef"]["ruleId"], "fsr-current")

    def test_build_uses_global_specs_for_every_project(self) -> None:
        """清单全局唯一：任何项目都以全局清单为骨架，不需要项目自己上传。"""
        project = {"id": "P-GLOBAL", "name": "全局清单项目", "parse_result": {}}
        table = build_project_fact_table(project, {})
        spec_fields = [field for field in table["fields"] if field.get("specSeq")]
        self.assertEqual(len(spec_fields), len(load_specs()))
        self.assertEqual(table["summary"]["specTotal"], len(load_specs()))

    def test_build_keeps_union_behavior_when_no_specs_available(self) -> None:
        """极端兜底：全局清单尚未上传或加载失败，维持来源并集行为并记 warning。"""
        project = {"id": "P-NOSPEC", "name": "无清单项目", "parse_result": {}}
        with patch.object(
            fact_table_module,
            "resolve_fact_specs",
            return_value=([], {"source": "global"}),
        ):
            with self.assertLogs(fact_table_module.logger, level="WARNING"):
                table = build_project_fact_table(project, {})
        self.assertTrue(table["fields"])
        self.assertTrue(all(not field.get("specSeq") for field in table["fields"]))
        self.assertEqual(table["summary"]["specTotal"], 0)


class TestSummarizeSpecProgressBuckets(unittest.TestCase):
    def test_buckets_are_exclusive_and_sum_to_spec_total(self) -> None:
        # 历史七态混在存量数据里，统计前按有无取值归一，重建前也要数对
        fields = [
            {"label": "A", "specSeq": 1, "status": "confirmed", "value": "x"},
            {"label": "B", "specSeq": 2, "status": "pending_confirmation", "value": "x"},
            {"label": "C", "specSeq": 3, "status": "unextracted", "value": ""},
            {"label": "D", "specSeq": 4, "status": "missing_source", "value": ""},
            {"label": "E", "specSeq": 5, "status": "extracted", "value": "x"},
            {"label": "F", "specSeq": 6, "status": "conflict", "value": "x"},
            {"label": "H", "specSeq": 7, "status": "not_applicable", "value": ""},
            # 人工新增字段（无 specSeq）不计入清单统计
            {"label": "G", "status": "confirmed", "value": "x", "sourceRefs": [{"type": "manualFact"}]},
        ]
        summary = summarize_project_fact_fields(fields)
        self.assertEqual(summary["specTotal"], 7)
        # 有值的 A/B/E/F 全部可用；C/D 待填写；H 不适用不算待办
        self.assertEqual(summary["specConfirmedCount"], 4)
        self.assertEqual(summary["specUnfilledCount"], 2)
        self.assertEqual(
            summary["specConfirmedCount"] + summary["specUnfilledCount"] + 1,
            summary["specBuiltTotal"],
        )
        # 状态计数是全表口径（含人工行）
        self.assertEqual(summary["totalCount"], 8)
        self.assertEqual(summary["confirmedCount"], 5)
        self.assertEqual(summary["unextractedCount"], 2)
        self.assertEqual(summary["notApplicableCount"], 1)

    def test_spec_seq_zero_is_counted_with_stable_bound_total(self) -> None:
        fields = [{"label": "A", "specSeq": 0, "status": "confirmed", "value": "x"}]

        summary = summarize_project_fact_fields(fields, spec_total=2)

        self.assertEqual(summary["specTotal"], 2)
        self.assertEqual(summary["specBuiltTotal"], 1)
        self.assertEqual(summary["specMatched"], 1)
        self.assertEqual(summary["specConfirmedCount"], 1)


if __name__ == "__main__":
    unittest.main()
