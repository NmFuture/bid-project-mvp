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


class AppendixPrefixTests(unittest.TestCase):
    """通用附表编号前缀：旧实现只识别 C1/C2/C3，H2/G1/F2/D7 关键词分支是死代码。"""

    def test_general_letter_number(self) -> None:
        self.assertEqual(filler.appendix_prefix("附表G.2.2 投标人对招标项目场址载荷计算选取风参数结果"), "G2")
        self.assertEqual(filler.appendix_prefix("附表H.2 交货进度表"), "H2")
        self.assertEqual(filler.appendix_prefix("附表F.2.1 投标机组设计认证"), "F2")
        self.assertEqual(filler.appendix_prefix("附表D.7 性能及考核承诺保证表"), "D7")

    def test_c_series_unchanged(self) -> None:
        self.assertEqual(filler.appendix_prefix("附表C.1 总体技术参数与规格"), "C1")
        self.assertEqual(filler.appendix_prefix("附表C.2 风轮系统技术参数"), "C2")

    def test_no_code_falls_back_gen(self) -> None:
        self.assertEqual(filler.appendix_prefix("某个正文表格"), "GEN")

    def test_keyword_branches_now_reachable(self) -> None:
        self.assertIn("物流解决方案", filler.component_keywords_for("H2"))
        self.assertIn("风资源评估报告", filler.component_keywords_for("G2"))


class OwnTableLimitTests(unittest.TestCase):
    """S1 越界表剔除：blankDocx 内第二个（编号不同）附表标题/附件标题后的表不属于本附表。"""

    @staticmethod
    def _doc(blocks):
        from docx import Document as _D

        doc = _D()
        for kind, text in blocks:
            if kind == "P":
                doc.add_paragraph(text)
            else:
                doc.add_table(rows=2, cols=2)
        return doc

    def test_bleed_after_next_heading_excluded(self) -> None:
        doc = self._doc([("P", "附表D.1 标准及风电场空气密度功率曲线"), ("T", ""), ("P", "附表D.2 推力系数曲线"), ("T", "")])
        self.assertEqual(filler.own_table_limit(doc), 1)

    def test_same_number_continuation_not_boundary(self) -> None:
        doc = self._doc([("P", "附表D.3 标准功率曲线下功率桨距角曲线"), ("T", ""), ("P", "附表D.3 标准功率曲线下功率桨距角曲线（续）"), ("T", "")])
        self.assertEqual(filler.own_table_limit(doc), 2)

    def test_attachment_heading_is_boundary(self) -> None:
        doc = self._doc([("P", "技术附表I 技术条款偏差表"), ("T", ""), ("P", "附  件"), ("T", ""), ("T", "")])
        self.assertEqual(filler.own_table_limit(doc), 1)

    def test_genuine_multi_table_kept(self) -> None:
        doc = self._doc([("P", "附表E.3 推荐机型各机位发电量成果表"), ("T", ""), ("T", "")])
        self.assertEqual(filler.own_table_limit(doc), 2)


class UnitNormalizationTests(unittest.TestCase):
    """单位归一化：金标反评 C.1 暴露的 kW/MW 混填、值尾重复单位、机型布局后缀。"""

    def test_kw_to_mw_with_template_unit(self) -> None:
        field = {"field": "额定功率", "unit": "MW"}
        selected = {"value": "10000", "unit": "kW", "label": "额定功率"}
        self.assertEqual(filler.normalize_value_for_field(field, selected), "10")

    def test_capacity_without_template_unit_normalizes_to_mw(self) -> None:
        field = {"field": "单机容量", "unit": ""}
        selected = {"value": "10000", "unit": "kW", "label": "机组额定功率"}
        self.assertEqual(filler.normalize_value_for_field(field, selected), "10")
        self.assertEqual(selected["unit"], "MW")

    def test_value_with_embedded_mw(self) -> None:
        field = {"field": "标段规模", "unit": ""}
        selected = {"value": "600MW", "unit": "", "label": "标段规模"}
        self.assertEqual(filler.normalize_value_for_field(field, selected), "600")

    def test_duplicated_unit_suffix_stripped(self) -> None:
        field = {"field": "切出风速", "unit": "m/s"}
        selected = {"value": "70m/s", "unit": "", "label": "切出风速"}
        self.assertEqual(filler.normalize_value_for_field(field, selected), "70")

    def test_turbine_model_layout_suffix_stripped(self) -> None:
        field = {"field": "投标机型", "unit": ""}
        selected = {"value": "EW10.0-220上置", "unit": "", "label": "投标机型"}
        self.assertEqual(filler.normalize_value_for_field(field, selected), "EW10.0-220")

    def test_swept_area_rejects_per_kw_fact(self) -> None:
        field = {"field": "扫风面积", "unit": "m^2", "concepts": [], "remark": "", "requirementValue": ""}
        fact = {
            "label": "单位千瓦扫风面积", "value": "3.80", "unit": "m2/kW", "concepts": ["swept_area_per_kw"],
            "sourceKind": "xlsx", "sourcePriority": 100, "baseConfidence": 0.9, "usable": True,
            "source": "参数表", "row": 1, "sheet": "s", "notes": "", "risk": "", "actionHint": "fill", "id": "F1",
        }
        self.assertEqual(filler.score(field, fact, "auto_or_manual"), 0.0)


if __name__ == "__main__":
    unittest.main()
