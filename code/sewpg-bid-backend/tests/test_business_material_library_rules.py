from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.material_store import (
    BUSINESS_CUSTOMIZED_SUBFOLDERS,
    MATERIAL_LIBRARY_ALLOWED_SUFFIXES,
    RAW_MATERIAL_PROTECTED_FOLDER_PATHS,
    business_customized_child_tier_for_parent_path,
    business_customized_tier_from_path,
    clean_status_for_new_file,
    ext_of,
    is_raw_material_protected_folder_path,
    material_suffix,
    material_store,
)
from app.services.peripheral import PeripheralError


class BusinessMaterialLibraryRulesTests(unittest.TestCase):
    def test_image_files_are_marked_original_only(self) -> None:
        status, message = clean_status_for_new_file("机型认证证书.png")
        self.assertEqual(status, "original_only")
        self.assertIn("原件", message)

    def test_cleanable_documents_still_queue_cleaning(self) -> None:
        status, message = clean_status_for_new_file("授权书.docx")
        self.assertEqual(status, "pending")
        self.assertIn("清洗", message)

    def test_existing_business_customer_project_paths_are_detected_for_backfill(self) -> None:
        self.assertEqual(
            business_customized_tier_from_path("商务标/客户素材/华能集团"),
            "customer",
        )
        self.assertEqual(
            business_customized_tier_from_path("商务标/项目素材/MAT-BIZ-HN-001"),
            "project",
        )
        self.assertEqual(
            business_customized_tier_from_path("商务标/客户素材/华能集团/01-客户关系与专项证明"),
            "",
        )

    def test_manual_customer_project_folder_creation_under_business_roots_gets_subfolders(self) -> None:
        self.assertEqual(
            business_customized_child_tier_for_parent_path("商务标/客户素材"),
            "customer",
        )
        self.assertEqual(
            business_customized_child_tier_for_parent_path("商务标/项目素材"),
            "project",
        )
        self.assertEqual(
            business_customized_child_tier_for_parent_path("技术标/客户素材"),
            "",
        )

    def test_business_customized_subfolder_specs_remain_three_modules(self) -> None:
        self.assertEqual(
            [item["name"] for item in BUSINESS_CUSTOMIZED_SUBFOLDERS],
            [
                "01-客户关系与专项证明",
                "02-商务响应文件",
                "03-模板底稿与过程文件",
            ],
        )

    def test_material_library_whitelist_includes_images_without_touching_parse_whitelist(self) -> None:
        for suffix in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"]:
            self.assertIn(suffix, MATERIAL_LIBRARY_ALLOWED_SUFFIXES)

    def test_ds_store_is_allowed_as_original_only_material(self) -> None:
        self.assertEqual(material_suffix(".DS_Store"), ".ds_store")
        self.assertEqual(ext_of(".DS_Store"), "ds_store")
        self.assertIn(".ds_store", MATERIAL_LIBRARY_ALLOWED_SUFFIXES)
        status, message = clean_status_for_new_file(".DS_Store")
        self.assertEqual(status, "original_only")
        self.assertIn("DS_Store", message)

    def test_material_cleaning_uses_short_paths_for_long_names(self) -> None:
        from app.services.material_cleaning import _short_file_name_for_path, cleaned_object_key

        long_name = (
            "【标段一】华能蒙东新能源公司赤峰市200万千瓦自建调峰能力风光储多能互补一体化+荒漠治理基地项目"
            "（翁牛特旗120万千瓦风电项目区）风力发电机组（不含塔筒）及附属设备采购文件.docx"
        )
        short_name = _short_file_name_for_path(long_name)
        key = cleaned_object_key(95, long_name)

        self.assertTrue(short_name.endswith(".docx"))
        self.assertLessEqual(len(short_name.encode("utf-8")), 96)
        self.assertIn("cleaned/RAW-0095/", key)
        self.assertLessEqual(max(len(part.encode("utf-8")) for part in key.split("/")), 120)


class RawMaterialProtectedFolderTests(unittest.IsolatedAsyncioTestCase):
    async def test_bid_material_tier_roots_can_be_deleted(self) -> None:
        expected_deletable = {
            "技术标/通用素材",
            "技术标/客户素材",
            "技术标/项目素材",
            "商务标/通用素材",
            "商务标/客户素材",
            "商务标/项目素材",
        }

        for folder_path in expected_deletable:
            self.assertNotIn(folder_path, RAW_MATERIAL_PROTECTED_FOLDER_PATHS)
            self.assertFalse(is_raw_material_protected_folder_path(folder_path))

        for folder_path in {"技术标", "商务标"}:
            self.assertIn(folder_path, RAW_MATERIAL_PROTECTED_FOLDER_PATHS)
            self.assertTrue(is_raw_material_protected_folder_path(folder_path))

    async def test_auto_bootstrapped_business_folders_cannot_be_deleted(self) -> None:
        expected_static_paths = {
            "商务标/通用素材/01-资质合规库",
            "商务标/通用素材/02-企业能力库",
            "商务标/通用素材/03-业绩资产池",
            "商务标/通用素材/04-财务资料库",
            "商务标/通用素材/05-专题证书库",
            "商务标/通用素材/05-专题证书库/01-机型认证证书",
            "商务标/通用素材/05-专题证书库/02-大部件型式认证证书",
            "商务标/通用素材/06-通用模板底稿库",
        }
        self.assertTrue(expected_static_paths.issubset(RAW_MATERIAL_PROTECTED_FOLDER_PATHS))

        dynamic_paths = {
            "商务标/客户素材/华能集团/01-客户关系与专项证明",
            "商务标/客户素材/华能集团/02-商务响应文件",
            "商务标/客户素材/华能集团/03-模板底稿与过程文件",
            "商务标/项目素材/MAT-BIZ-HN-001/01-客户关系与专项证明",
            "商务标/项目素材/MAT-BIZ-HN-001/02-商务响应文件",
            "商务标/项目素材/MAT-BIZ-HN-001/03-模板底稿与过程文件",
        }
        for folder_path in expected_static_paths | dynamic_paths:
            self.assertTrue(is_raw_material_protected_folder_path(folder_path))
            with self.assertRaises(PeripheralError) as context:
                await material_store.raw_delete_folder(folder_path)
            self.assertEqual(context.exception.code, "RAW_FOLDER_DELETE_PROTECTED")

        self.assertFalse(is_raw_material_protected_folder_path("商务标/客户素材/华能集团/临时目录"))


if __name__ == "__main__":
    unittest.main()
