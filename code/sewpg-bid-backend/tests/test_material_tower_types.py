"""素材塔型判型与候选池塔型过滤测试。

命名样本取自技术标素材库（2026-08 全量核验的真实结构特征）。
"""

from __future__ import annotations

import unittest

from app.services.material_tower_types import material_tower_family
from app.services.technical_gap_planner import _keep_by_tower_type


class MaterialTowerFamilyTests(unittest.TestCase):
    def test_steel_suffix_and_paren(self) -> None:
        self.assertEqual(
            material_tower_family("保供能力-EW6.7-220-钢塔.docx", "技术标/标准文件/EW6.7-220/专题"),
            "钢塔",
        )
        self.assertEqual(
            material_tower_family(
                "螺栓在线监测分析系统（钢塔）.docx",
                "技术标/标准文件/EW6.7-220/专题/数字化智慧风场专题/智能传感系统",
            ),
            "钢塔",
        )

    def test_mixed_suffix_paren_and_fixed_name(self) -> None:
        self.assertEqual(
            material_tower_family("保供能力-EW6.7-220-混塔.docx", "技术标/标准文件/EW6.7-220/专题"),
            "混塔",
        )
        self.assertEqual(
            material_tower_family(
                "混塔锚索索力监测系统（混塔）.docx",
                "技术标/标准文件/EW6.7-220/专题/数字化智慧风场专题/智能传感系统",
            ),
            "混塔",
        )
        self.assertEqual(
            material_tower_family("混塔解决方案专题.docx", "技术标/标准文件/EW6.7-220/专题"),
            "混塔",
        )

    def test_directory_markers(self) -> None:
        self.assertEqual(
            material_tower_family("塔筒及基础.docx", "技术标/标准文件/EW6.7-220/专题/投标项目塔筒专题-钢塔"),
            "钢塔",
        )
        self.assertEqual(
            material_tower_family(
                "EW5.0-202-185-00525DA0078R0（上海电气）HT185m混塔设计认证A-20250820.pdf",
                "技术标/标准文件/EW5.0-202/认证证书/部件认证/混塔",
            ),
            "混塔",
        )

    def test_generic_materials_stay_unclassified(self) -> None:
        # 附表 G.3「钢塔筒招标项目场址设计安全性」各塔型项目都要填（混塔填钢段），
        # 不能被「钢塔」裸子串误判成钢塔专用。
        self.assertEqual(
            material_tower_family("钢塔筒招标项目场址设计安全性.docx", "技术标/标准文件/EW6.7-220/专题"),
            "",
        )
        self.assertEqual(
            material_tower_family("塔筒晃度与基础沉降监测分析系统.docx", "技术标/标准文件/EW6.7-220/专题"),
            "",
        )
        self.assertEqual(
            material_tower_family("低功率X3平台机组整机抗涡激方案.docx", "技术标/标准文件/EW5.0-202/专题"),
            "",
        )
        self.assertEqual(material_tower_family("", ""), "")


class KeepByTowerTypeTests(unittest.TestCase):
    @staticmethod
    def _material(name: str, folder_path: str = "技术标/标准文件/EW6.7-220/专题") -> dict[str, str]:
        return {"id": "RAW-0001", "name": name, "folderPath": folder_path, "materialTier": "standard"}

    def test_steel_project_drops_mixed_family(self) -> None:
        selected = [{"model": "EW6.7-220", "foundationType": "钢塔"}]
        self.assertTrue(_keep_by_tower_type(self._material("保供能力-EW6.7-220-钢塔.docx"), selected))
        self.assertFalse(_keep_by_tower_type(self._material("保供能力-EW6.7-220-混塔.docx"), selected))
        self.assertFalse(_keep_by_tower_type(self._material("混塔解决方案专题.docx"), selected))
        # 塔型无关素材保留
        self.assertTrue(_keep_by_tower_type(self._material("电网友好性专题.docx"), selected))

    def test_mixed_project_drops_steel_family(self) -> None:
        selected = [{"model": "EW6.7-220", "foundationType": "混塔"}]
        self.assertTrue(_keep_by_tower_type(self._material("混塔解决方案专题.docx"), selected))
        self.assertFalse(_keep_by_tower_type(self._material("保供能力-EW6.7-220-钢塔.docx"), selected))
        self.assertFalse(
            _keep_by_tower_type(
                self._material("塔筒及基础.docx", "技术标/标准文件/EW6.7-220/专题/投标项目塔筒专题-钢塔"),
                selected,
            )
        )

    def test_multi_row_union(self) -> None:
        selected = [
            {"model": "EW6.7-220", "foundationType": "钢塔"},
            {"model": "EW8.5-220下置", "foundationType": "混塔"},
        ]
        self.assertTrue(_keep_by_tower_type(self._material("保供能力-EW6.7-220-钢塔.docx"), selected))
        self.assertTrue(_keep_by_tower_type(self._material("混塔解决方案专题.docx"), selected))

    def test_offshore_drops_all_tower_families(self) -> None:
        for foundation in ("单桩", "导管架", "多桩承台"):
            selected = [{"model": "EW6.7-220", "foundationType": foundation}]
            self.assertFalse(_keep_by_tower_type(self._material("保供能力-EW6.7-220-钢塔.docx"), selected))
            self.assertFalse(_keep_by_tower_type(self._material("混塔解决方案专题.docx"), selected))
            self.assertTrue(_keep_by_tower_type(self._material("电网友好性专题.docx"), selected))

    def test_no_foundation_type_no_filter(self) -> None:
        self.assertTrue(_keep_by_tower_type(self._material("保供能力-EW6.7-220-混塔.docx"), [{"model": "EW6.7-220"}]))
        self.assertTrue(_keep_by_tower_type(self._material("保供能力-EW6.7-220-混塔.docx"), []))


if __name__ == "__main__":
    unittest.main()
