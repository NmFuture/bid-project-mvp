"""table-filler 填写纪律单测（AI 填表金标评测修复）。

用真实中标件反评暴露的污染模式：素材库源表里"（项目定制）"占位行留着按场景
分叉的门槛描述（"纯钢塔：需≤125；混塔：需≥140"），被通用抽取逻辑当成合法
事实直接抄进答案格；数值答案后面挂着中文场景注（"50（背风策略）"）没剥离。
fixture 用真实反评中定位到的字符串（不含项目/客户专属数据）。
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
    / "bid-tech-table-filler"
    / "scripts"
    / "run_from_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location("tech_table_filler_under_test", _SRC)
filler = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["tech_table_filler_under_test"] = filler
_SPEC.loader.exec_module(filler)


class ConditionalRequirementTextTests(unittest.TestCase):
    def test_detects_branching_threshold_clause(self) -> None:
        self.assertTrue(
            filler.is_conditional_requirement_text("纯钢塔：需≤125； 混塔、分片塔：需≥140")
        )
        self.assertTrue(filler.is_conditional_requirement_text("不低于95%"))
        self.assertTrue(filler.is_conditional_requirement_text("不高于10m/s"))
        self.assertTrue(filler.is_conditional_requirement_text("至少两套"))

    def test_does_not_flag_ordinary_technical_terms(self) -> None:
        # "应"/"须"/"要求" 这种单字判断会把"屈服应力"这类正常技术词误伤，
        # 不能用在这个更广泛的可用性判定里。
        self.assertFalse(filler.is_conditional_requirement_text("屈服应力345MPa"))
        self.assertFalse(filler.is_conditional_requirement_text("轴承材料应力等级Q355"))
        self.assertFalse(filler.is_conditional_requirement_text("60"))
        self.assertFalse(filler.is_conditional_requirement_text("IEC IB"))


class UsableValueTests(unittest.TestCase):
    def test_rejects_conditional_requirement_value(self) -> None:
        self.assertFalse(filler.usable_value("纯钢塔：需≤125； 混塔、分片塔：需≥140"))

    def test_accepts_ordinary_values(self) -> None:
        self.assertTrue(filler.usable_value("60"))
        self.assertTrue(filler.usable_value("屈服应力345MPa"))
        self.assertTrue(filler.usable_value("IEC IB"))

    def test_still_rejects_existing_weak_tokens(self) -> None:
        self.assertFalse(filler.usable_value("[待人工补充：字段名]"))
        self.assertFalse(filler.usable_value("项目定制"))


class RequirementValueIsDirectResponseTests(unittest.TestCase):
    def test_conditional_clause_is_not_a_direct_response(self) -> None:
        # 招标人要求列里若本身是按场景分叉的门槛描述，不能直接当投标人响应值抄。
        self.assertFalse(
            filler.requirement_value_is_direct_response("纯钢塔：需≤125； 混塔、分片塔：需≥140")
        )

    def test_simple_requirement_still_usable_as_direct_response(self) -> None:
        self.assertTrue(filler.requirement_value_is_direct_response("IEC IIA"))
        self.assertTrue(filler.requirement_value_is_direct_response("60"))


class StripNumericTrailingAnnotationTests(unittest.TestCase):
    def test_strips_descriptive_annotation_after_number(self) -> None:
        self.assertEqual(filler.strip_numeric_trailing_annotation("50（背风策略）"), "50")
        self.assertEqual(filler.strip_numeric_trailing_annotation("70（背风）"), "70")

    def test_keeps_annotation_containing_digits(self) -> None:
        # 括号里含数字的限定（如 ±5%）会改变数值含义，不能剥离。
        self.assertEqual(filler.strip_numeric_trailing_annotation("10（±5%）"), "10（±5%）")

    def test_non_numeric_prefix_untouched(self) -> None:
        self.assertEqual(filler.strip_numeric_trailing_annotation("EW10.0-220上置"), "EW10.0-220上置")


if __name__ == "__main__":
    unittest.main()
