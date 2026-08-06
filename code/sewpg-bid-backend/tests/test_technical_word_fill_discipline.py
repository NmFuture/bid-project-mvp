"""word-placeholder-filler 填写纪律单测（AI 填写金标评测修复）。

金标反评（正式技术卷逐字段对照）暴露的污染模式：一条无关素材证据批量覆盖
承诺值占位符、事实缺失级联到错误规则、同一证据喷洒多个占位符。
fixture 为脱敏合成数据（通用领域词面，无真实项目数据）。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skills"
    / "bid-tech-word-placeholder-filler"
    / "scripts"
    / "run_from_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location("tech_word_filler_under_test", _SRC)
filler = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["tech_word_filler_under_test"] = filler
_SPEC.loader.exec_module(filler)


def _material_fact(label: str, value: str) -> dict:
    return {"label": label, "value": value, "sourceKind": "docx", "confidence": 0.95, "sourcePriority": 100}


def _table_fact(label: str, value: str) -> dict:
    return {"label": label, "value": value, "sourceKind": "manifest", "confidence": 0.9, "sourcePriority": 90}


class DirectionalMatchTests(unittest.TestCase):
    def test_material_fact_no_fuzzy_path(self) -> None:
        # 素材事实禁走模糊路径：通用占位符标签不得靠 SequenceMatcher 蹭到无关素材参数
        junk = _material_fact("冲击功", "QT350-22AL / 平均值≥10J，单个值≥7J(-40℃)")
        self.assertEqual(filler.label_score("投标响应", "任意上下文", junk), 0.0)

    def test_manifest_fact_keeps_fuzzy_path(self) -> None:
        fact = _table_fact("功率曲线保证率", "97%")
        self.assertGreater(filler.label_score("功率曲线保证", "", fact), 0.6)

    def test_short_fact_key_reverse_containment_blocked(self) -> None:
        # 反向包含（事实键 ⊂ 占位符标签）只对 ≥5 字键放行
        short = _table_fact("方案", "某方案文本")
        self.assertEqual(filler.label_score("投标技术方案说明", "", short), 0.0)


class NumericSlotGuardTests(unittest.TestCase):
    def test_ge_prefix_slot_detected(self) -> None:
        text = "功率曲线保证率应满足≥[待填写]"
        i = text.index("[")
        self.assertTrue(filler.numeric_slot(text, {"start": i, "end": i + 5}, "投标响应"))

    def test_unit_suffix_slot_detected(self) -> None:
        text = "全场配置[待填写]台机组"
        i = text.index("[")
        self.assertTrue(filler.numeric_slot(text, {"start": i, "end": text.index("]") + 1}, "待填写内容"))

    def test_long_mixed_value_rejected(self) -> None:
        self.assertFalse(filler.value_fits_numeric_slot("QT350-22AL / 平均值≥10J，单个值≥7J(-40℃)"))
        self.assertTrue(filler.value_fits_numeric_slot("2836h"))
        self.assertTrue(filler.value_fits_numeric_slot("97%"))

    def test_replace_text_guards_numeric_slot(self) -> None:
        # 端到端：数字槽位遇到长混合值 → 诚实占位而非错填
        junk = _material_fact("投标响应", "QT350-22AL / 平均值≥10J，单个值≥7J(-40℃)")
        text = "每台风电机组的功率曲线保证≥[投标响应，待填写]"
        replaced, decisions, unfilled, highlighted = filler.replace_text(text, [junk], text, {})
        self.assertIn("待人工补充", replaced)
        self.assertNotIn("QT350", replaced)
        self.assertTrue(highlighted)


class SingleUseTests(unittest.TestCase):
    def test_material_fact_single_use_across_labels(self) -> None:
        junk = _material_fact("某参数", "某参数值123")
        used: dict = {}
        first, _ = filler.choose_fact("某参数", "", [junk], used)
        self.assertIsNotNone(first)
        used[(filler.norm("某参数"), filler.norm("某参数值123"))] = filler.norm("某参数")
        second, _ = filler.choose_fact("另一个字段", "", [junk], used)
        self.assertIsNone(second)  # 不得喷洒到语义不同的占位符

    def test_manifest_fact_reuse_allowed(self) -> None:
        fact = _table_fact("总装机容量", "600MW")
        used: dict = {}
        for _ in range(3):
            sel, _alts = filler.choose_fact("总装机容量", "", [fact], used)
            self.assertIsNotNone(sel)  # 事实表值可合法复用


class ManualSentinelTests(unittest.TestCase):
    def test_missing_fact_stops_cascade(self) -> None:
        # 单机容量缺失时：规则返回哨兵 → 人工占位，不得级联填成总装机容量
        facts = [_table_fact("总装机容量", "600MW")]
        text = "单机容量[投标方案，待填写]MW"
        context = "单机容量（风电机组出口端）/ " + text
        replaced, decisions, unfilled, _ = filler.replace_text(text, facts, context, {})
        self.assertNotIn("600", replaced)
        self.assertIn("待人工补充", replaced)

    def test_chapter_index_never_gets_model_name(self) -> None:
        # 章节索引列短路：即使行上下文含机型词也不得被机型值覆盖
        facts = [_table_fact("投标机型", "EW10.0-220上置")]
        selected = filler.context_fact("章节索引", "机型 EW10.0-220 相关行上下文", {"start": 0, "end": 0}, 0, facts)
        self.assertIsNotNone(selected)
        self.assertNotIn("EW10.0", str(selected.get("value")))


def _spec_fact(label: str, value: str, placeholders: list[str], targets: list[str]) -> dict:
    return {
        "label": label,
        "value": value,
        "reviewLabel": label,
        "sourceKind": "manifest",
        "confidence": 0.97,
        "sourcePriority": 90,
        "specPlaceholders": [filler.placeholder_key(item) for item in placeholders],
        "specTargets": [filler.file_key(item) for item in targets],
    }


class NormalizationTests(unittest.TestCase):
    def test_norm_strips_punctuation(self) -> None:
        # 修复前字符类在 `\\]` 处提前闭合，norm() 实际不剥离任何标点
        self.assertEqual(filler.norm("第1段（底）塔节底部直径（m）"), "第1段底塔节底部直径m")

    def test_placeholder_key_bridges_bracket_and_comma_variants(self) -> None:
        keys = {
            filler.placeholder_key("[安全等级，待填写]"),
            filler.placeholder_key("【安全等级, 待填写】"),
            filler.placeholder_key("[待填写：安全等级]"),
        }
        self.assertEqual(keys, {"安全等级"})

    def test_split_spec_cell_handles_newline_and_semicolons(self) -> None:
        self.assertEqual(filler.split_spec_cell("[甲，待填写]；[乙，待填写]\n[丙，待填写]"), ["[甲，待填写]", "[乙，待填写]", "[丙，待填写]"])

    def test_file_key_ignores_path_and_extension(self) -> None:
        self.assertEqual(filler.file_key("华能/待填写-塔筒设计方案.docx"), filler.file_key("待填写-塔筒设计方案"))


class SpecLocateTests(unittest.TestCase):
    def _index(self, facts: list[dict], blank: str = "待填写-塔筒设计方案.docx") -> filler.SpecIndex:
        manifest = {"projectFactTable": {"fields": [
            {"placeholder": "；".join(f"[{key}，待填写]" for key in fact["specPlaceholders"])} for fact in facts
        ]}}
        return filler.build_spec_index(manifest, facts, {filler.file_key(blank)})

    def test_unique_placeholder_fills_without_guessing(self) -> None:
        fact = _spec_fact("场址要求安全等级", "S级", ["[场址安全等级，待填写]"], ["华能/待填写-塔筒设计方案.docx"])
        index = self._index([fact])
        selected, _alts, status = filler.spec_locate(index, {"label": "场址安全等级"}, "任意上下文")
        self.assertEqual(status, "unique")
        self.assertEqual(selected["value"], "S级")

    def test_table_column_header_separates_adjacent_fields(self) -> None:
        # 同列相邻字段只差「底部/顶部」，靠行标签 + 列头的完整包含区分
        facts = [
            _spec_fact("第1段（底）塔节底部直径（m）", "4.5", ["[技术方案，待填写]"], ["待填写-塔筒设计方案.docx"]),
            _spec_fact("第1段（底）塔节顶部直径（m）", "3.8", ["[技术方案，待填写]"], ["待填写-塔筒设计方案.docx"]),
            _spec_fact("第2段塔节底部直径（m）", "3.8", ["[技术方案，待填写]"], ["待填写-塔筒设计方案.docx"]),
        ]
        index = self._index(facts)
        context = "T1R2C2 / 第1段（底） / [技术方案，待填写] / 底部直径（m）"
        selected, _alts, status = filler.spec_locate(index, {"label": "技术方案"}, context)
        self.assertEqual(status, "disambiguated")
        self.assertEqual(selected["label"], "第1段（底）塔节底部直径（m）")

    def test_indistinguishable_candidates_go_manual(self) -> None:
        # 上下文没有区分信息时宁空勿错，交人工并进诊断表
        facts = [
            _spec_fact("场址要求安全等级", "S级", ["[安全等级，待填写]"], ["待填写-塔筒设计方案.docx"]),
            _spec_fact("机型认证安全等级", "IEC IA", ["[安全等级，待填写]"], ["待填写-塔筒设计方案.docx"]),
        ]
        index = self._index(facts)
        selected, alternatives, status = filler.spec_locate(index, {"label": "安全等级"}, "本项目安全等级为")
        self.assertEqual(status, "ambiguous")
        self.assertIsNone(selected)
        self.assertEqual(len(alternatives), 2)

    def test_placeholder_outside_spec_goes_manual(self) -> None:
        fact = _spec_fact("塔筒段数", "5", ["[塔筒段数，待填写]"], ["待填写-塔筒设计方案.docx"])
        index = self._index([fact])
        selected, _alts, status = filler.spec_locate(index, {"label": "服务承诺"}, "售后服务响应时间")
        self.assertEqual(status, "not_in_spec")
        self.assertIsNone(selected)

    def test_placeholder_equal_to_field_name_hits_directly(self) -> None:
        # 素材库多数占位符已拆细成字段名本身，这条是零歧义的确定性路径
        fact = _spec_fact("单台机组功率曲线保证率（%）", "97", ["[投标方案，待填写]"], ["待填写-塔筒设计方案.docx"])
        index = self._index([fact])
        selected, _alts, status = filler.spec_locate(index, {"label": "单台机组功率曲线保证率（%）"}, "任意上下文")
        self.assertEqual(status, "field_name")
        self.assertEqual(selected["value"], "97")

    def test_derived_facts_never_hijack_generic_placeholders(self) -> None:
        # 派生事实（无清单元数据）不得进字段名索引：label 恰好等于泛占位符文字时会劫持全文
        hijacker = {"label": "投标方案", "value": "EW10.0-220", "sourceKind": "manifest", "confidence": 0.9}
        index = filler.build_spec_index({}, [hijacker], {filler.file_key("待填写-塔筒设计方案.docx")})
        self.assertFalse(index.enabled)

    def test_target_file_is_soft_filter(self) -> None:
        # 清单文件名与实际待填写文件对不上时不做排除，否则整份文件静默填不进任何字段
        fact = _spec_fact("塔筒段数（段）", "5", ["[技术方案，待填写]"], ["别的文件.docx"])
        index = self._index([fact], blank="待填写-塔筒设计方案.docx")
        selected, _alts, status = filler.spec_locate(index, {"label": "技术方案"}, "上下文")
        self.assertEqual(status, "unique")
        self.assertEqual(selected["value"], "5")

    def test_same_placeholder_shared_by_synonym_fields_fills_when_values_agree(self) -> None:
        # 清单里同一个占位符被多个同义字段共用（年等效满负荷小时数 / 等效上网小时数 …），
        # 取值一致时没有歧义，照填
        facts = [
            _spec_fact("年等效满负荷小时数（保证值，h）", "2836", ["[投标方案，待填写]"], ["待填写-塔筒设计方案.docx"]),
            _spec_fact("等效上网小时数（保证值，h）", "2836", ["[投标方案，待填写]"], ["待填写-塔筒设计方案.docx"]),
        ]
        index = self._index(facts)
        selected, _alts, status = filler.spec_locate(index, {"label": "年等效满负荷小时数（保证值，h）"}, "上下文")
        self.assertEqual(status, "field_name")
        self.assertEqual(selected["value"], "2836")

    def test_same_placeholder_shared_by_conflicting_fields_goes_manual(self) -> None:
        # 取值不一致时不得静默取第一个：上下文分不开就交人工
        facts = [
            _spec_fact("年等效满负荷小时数（保证值，h）", "2836", ["[投标方案，待填写]"], ["待填写-塔筒设计方案.docx"]),
            _spec_fact("年等效满负荷小时数（考核值，h）", "2650", ["[投标方案，待填写]"], ["待填写-塔筒设计方案.docx"]),
        ]
        facts[1]["reviewLabel"] = "年等效满负荷小时数（保证值，h）"  # 别名撞上另一个字段的正式名
        index = self._index(facts)
        selected, alternatives, status = filler.spec_locate(index, {"label": "年等效满负荷小时数（保证值，h）"}, "无区分信息")
        self.assertEqual(status, "ambiguous")
        self.assertIsNone(selected)
        self.assertEqual(len(alternatives), 2)

    def test_composite_placeholder_is_reported_not_filled(self) -> None:
        # 一格填多个字段（`[投标机型、台数，待填写]`）不自动填：分隔方式是产品决策
        facts = [_spec_fact("投标机型", "EW10.0-220", ["[机型，待填写]"], ["待填写-塔筒设计方案.docx"])]
        index = self._index(facts)
        self.assertEqual(filler.composite_field_names(index, "投标机型、台数"), ["投标机型"])
        # 字段名自带括号逗号时不得被切碎
        self.assertEqual(filler.composite_field_names(index, "折减系数（考核值，%）"), [])

    def test_missing_fact_table_falls_back_to_legacy_chain(self) -> None:
        index = filler.build_spec_index({}, [], {"任意文件"})
        self.assertFalse(index.enabled)
        _selected, _alts, status = filler.spec_locate(index, {"label": "任意占位符"}, "上下文")
        self.assertEqual(status, "skipped")


if __name__ == "__main__":
    unittest.main()
