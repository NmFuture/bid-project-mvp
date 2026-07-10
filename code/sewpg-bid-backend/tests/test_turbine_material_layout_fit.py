from __future__ import annotations

import unittest

from app.services.turbine_models import material_model_fit, normalize_project_turbine_model


class MaterialModelLayoutFitTests(unittest.TestCase):
    """机型布局（上置/下置）过滤：项目选定 EW10.0-220上置 时，下置素材必须判冲突。"""

    def setUp(self) -> None:
        self.selected = normalize_project_turbine_model(
            {
                "model": "EW10.0-220上置",
                "layout": "",
                "status": "manual",
                "source": "static-options",
            }
        )

    def test_same_layout_matches(self) -> None:
        material = {"folderPath": "技术标/通用素材/EW10.0-220上置/专题", "name": "待填写-方案.docx"}
        self.assertEqual(material_model_fit(material, self.selected), "match")

    def test_opposite_layout_conflicts(self) -> None:
        """核心回归：下置素材不能因为基础型号 EW10.0-220 子串命中而被判 match。"""
        material = {"folderPath": "技术标/通用素材/EW10.0-220下置/专题", "name": "待填写-方案.docx"}
        self.assertEqual(material_model_fit(material, self.selected), "conflict")

    def test_layout_agnostic_material_still_matches(self) -> None:
        """无布局标记的通用素材（只写 EW10.0-220）仍视为可用，不被布局过滤误伤。"""
        material = {"folderPath": "技术标/通用素材/EW10.0-220/专题", "name": "待填写-方案.docx"}
        self.assertEqual(material_model_fit(material, self.selected), "match")

    def test_material_without_model_token_is_generic(self) -> None:
        material = {"folderPath": "技术标/通用素材/公共/专题", "name": "投标承诺函.docx"}
        self.assertEqual(material_model_fit(material, self.selected), "generic")

    def test_selected_layout_from_explicit_field(self) -> None:
        """项目布局写在 layout 字段（model 不含上置/下置）时，同样要按布局过滤。"""
        selected = normalize_project_turbine_model(
            {"model": "EW10.0-220", "layout": "上置", "status": "manual"}
        )
        conflict_material = {"folderPath": "技术标/通用素材/EW10.0-220下置/专题", "name": "x.docx"}
        match_material = {"folderPath": "技术标/通用素材/EW10.0-220上置/专题", "name": "x.docx"}
        self.assertEqual(material_model_fit(conflict_material, selected), "conflict")
        self.assertEqual(material_model_fit(match_material, selected), "match")

    def test_different_base_model_still_conflicts(self) -> None:
        material = {"folderPath": "技术标/通用素材/EW8.5-230上置/专题", "name": "x.docx"}
        self.assertEqual(material_model_fit(material, self.selected), "conflict")


if __name__ == "__main__":
    unittest.main()
