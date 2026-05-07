from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.material_store import (
    BUSINESS_CUSTOMIZED_SUBFOLDERS,
    MATERIAL_LIBRARY_ALLOWED_SUFFIXES,
    business_customized_child_tier_for_parent_path,
    business_customized_tier_from_path,
    clean_status_for_new_file,
)


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


if __name__ == "__main__":
    unittest.main()
