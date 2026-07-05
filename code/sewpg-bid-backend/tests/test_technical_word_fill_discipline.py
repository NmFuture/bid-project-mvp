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


if __name__ == "__main__":
    unittest.main()
