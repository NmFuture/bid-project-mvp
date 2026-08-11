"""多机型项目的素材候选与章节推荐。

项目机型明细可以有多行，正文要把各机型的对应素材串行铺开，而不是只用第一个机型。
"""
from __future__ import annotations

import importlib.util
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
_SPEC = importlib.util.spec_from_file_location("tech_multi_turbine_under_test", _SRC)
planner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(planner)

MODEL_A = "EW8.5-220上置"
MODEL_B = "EW10.0-230下置"


def _material(mid: str, model: str, name: str = "智能传感系统.docx") -> dict:
    return {
        "id": mid,
        "name": name,
        "folderPath": f"技术标/标准文件/{model}/专题/数字化智慧风场专题",
        "materialTier": "standard",
    }


class SkillMultiTurbineTests(unittest.TestCase):
    def test_turbine_model_names_keeps_detail_order(self) -> None:
        manifest = {
            "projectTurbineModels": [{"model": MODEL_B}, {"model": MODEL_A}, {"model": MODEL_B}],
            "projectTurbineModel": {"model": MODEL_A},
        }
        self.assertEqual(planner.turbine_model_names(manifest), [MODEL_B, MODEL_A])

    def test_turbine_model_names_falls_back_to_single(self) -> None:
        self.assertEqual(
            planner.turbine_model_names({"projectTurbineModel": {"model": MODEL_A}}),
            [MODEL_A],
        )
        self.assertEqual(planner.turbine_model_names({}), [])

    def test_expand_picks_one_material_per_model_in_detail_order(self) -> None:
        primary = {**_material("M-B", MODEL_B), "usage": "section_merge"}
        candidates = [primary, _material("M-A", MODEL_A), _material("M-A2", MODEL_A, "无关说明.docx")]

        result = planner.expand_matched_by_turbine_models(
            primary, candidates, "智能传感系统", [MODEL_A, MODEL_B]
        )

        # 机型明细顺序是 A 在前，主素材属于 B，仍按明细顺序排列
        self.assertEqual([item["id"] for item in result], ["M-A", "M-B"])
        self.assertEqual(result[0]["usage"], "section_merge")

    def test_expand_keeps_single_material_for_single_model_project(self) -> None:
        primary = _material("M-A", MODEL_A)
        candidates = [primary, _material("M-B", MODEL_B)]

        result = planner.expand_matched_by_turbine_models(primary, candidates, "智能传感系统", [MODEL_A])

        self.assertEqual([item["id"] for item in result], ["M-A"])

    def test_expand_leaves_non_standard_material_untouched(self) -> None:
        """客户/项目定制素材与机型无关，不做多机型展开。"""

        primary = {
            "id": "M-PRJ",
            "name": "智能传感系统.docx",
            "folderPath": "技术标/项目定制/某项目/专题",
            "materialTier": "project",
        }
        candidates = [primary, _material("M-A", MODEL_A), _material("M-B", MODEL_B)]

        result = planner.expand_matched_by_turbine_models(
            primary, candidates, "智能传感系统", [MODEL_A, MODEL_B]
        )

        self.assertEqual([item["id"] for item in result], ["M-PRJ"])

    def test_expand_skips_model_without_material(self) -> None:
        primary = _material("M-A", MODEL_A)
        result = planner.expand_matched_by_turbine_models(
            primary, [primary], "智能传感系统", [MODEL_A, MODEL_B]
        )
        self.assertEqual([item["id"] for item in result], ["M-A"])


class PlannerMultiTurbineTests(unittest.TestCase):
    def test_project_turbine_models_uses_all_rows(self) -> None:
        from app.services.turbine_models import project_turbine_models

        project = {"turbineModels": [{"model": MODEL_A}, {"model": MODEL_B}]}
        self.assertEqual([m["model"] for m in project_turbine_models(project)], [MODEL_A, MODEL_B])

        legacy = {"turbineModel": {"model": MODEL_A}}
        self.assertEqual([m["model"] for m in project_turbine_models(legacy)], [MODEL_A])
        self.assertEqual(project_turbine_models({}), [])

    def test_standard_scope_queries_each_model_folder(self) -> None:
        from app.services.technical_gap_planner import _standard_scope_query_paths

        paths = _standard_scope_query_paths("技术标/标准文件", [{"model": MODEL_A}, {"model": MODEL_B}])

        self.assertEqual(
            [path for path, _ in paths],
            [f"技术标/标准文件/{MODEL_A}", f"技术标/标准文件/{MODEL_B}"],
        )

    def test_standard_scope_falls_back_to_root_without_models(self) -> None:
        from app.services.technical_gap_planner import _standard_scope_query_paths

        self.assertEqual(_standard_scope_query_paths("技术标/标准文件", []), [("技术标/标准文件", {})])

    def test_keep_by_turbine_model_accepts_any_selected_model(self) -> None:
        from app.services.technical_gap_planner import _keep_by_turbine_model

        selected = [{"model": MODEL_A}, {"model": MODEL_B}]
        self.assertTrue(_keep_by_turbine_model(_material("M-A", MODEL_A), selected))
        self.assertTrue(_keep_by_turbine_model(_material("M-B", MODEL_B), selected))
        # 未选中的机型仍然进不了标准档池
        self.assertFalse(_keep_by_turbine_model(_material("M-C", "EW6.25-202"), selected))

    def test_fact_table_filter_does_not_narrow_multi_model_projects(self) -> None:
        """事实表「投标机型」是给选错机型兜底的，不能把多机型项目收紧成单机型。"""

        from app.services.technical_gap_planner import _filter_material_index_by_fact_table

        items = [_material("M-A", MODEL_A), _material("M-B", MODEL_B)]
        gap_state = {"projectFactTable": {"fields": [{"label": "投标机型", "value": MODEL_A}]}}

        kept = _filter_material_index_by_fact_table(
            items, gap_state, [{"model": MODEL_A}, {"model": MODEL_B}]
        )
        self.assertEqual([item["id"] for item in kept], ["M-A", "M-B"])

        # 事实表机型不在项目选定机型里 → 仍按事实表收紧
        narrowed = _filter_material_index_by_fact_table(items, gap_state, [{"model": MODEL_B}])
        self.assertEqual([item["id"] for item in narrowed], ["M-A"])

    def test_fact_table_filter_handles_merged_multi_model_value(self) -> None:
        """多机型时事实表「投标机型」是合并串，按整串过滤会把标准档素材全部剔除。"""

        from app.services.technical_gap_planner import _filter_material_index_by_fact_table

        items = [_material("M-A", MODEL_A), _material("M-B", MODEL_B)]
        gap_state = {"projectFactTable": {"fields": [{"label": "投标机型", "value": f"{MODEL_A}、{MODEL_B}"}]}}

        kept = _filter_material_index_by_fact_table(
            items, gap_state, [{"model": MODEL_A}, {"model": MODEL_B}]
        )
        self.assertEqual([item["id"] for item in kept], ["M-A", "M-B"])


if __name__ == "__main__":
    unittest.main()
