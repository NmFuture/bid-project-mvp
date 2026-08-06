"""AI 填写素材准备落地 Excel 原件的单测（B 报价类 / D 曲线类 0 填写攻坚）。

金标反评定位：素材缓存只落地清洗后的 docx 文本稿，sheet 结构丢失，
table-filler 里依赖 openpyxl 的分支（报价分项转写、功率曲线矩阵、
参数表机型列定位）拿到的 kind 恒为 docx，条件不成立直接跳过。
本组测试覆盖 _prepare_material_index_files 新增的原件落地路径：
Excel 素材额外下载原件并暴露 originalPath、非 Excel 素材不多打一次回源、
原件已落地或下载失败时的行为。下载与 OCR 全部 mock。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import technical_gap_ai_fill as ai_fill


class PrepareMaterialIndexOriginalExcelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work_dir = Path(self._tmp.name)
        self.cache_dir = self.work_dir / "material_index"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _prepare(self, materials, *, raw_names: dict[str, str], fail_original: bool = False):
        """raw_names: material_id -> 原件文件名（raw_download_content 返回值）。"""

        async def fake_cleaned(material_id):
            return {
                "bucket": "b",
                "key": f"cleaned/{material_id}.docx",
                "fileName": f"{material_id}.docx",
            }, "cleaned"

        async def fake_raw(material_id):
            name = raw_names.get(material_id)
            if name is None:
                raise RuntimeError("no raw")
            return {"bucket": "b", "key": f"raw/{name}", "fileName": name}

        downloads: list[str] = []

        def fake_download_file(_bucket, key, target_path):
            if fail_original and str(key).startswith("raw/"):
                raise RuntimeError("MinIO 原件下载失败")
            downloads.append(str(key))
            Path(target_path).write_bytes(b"fake")

        with (
            patch.object(
                ai_fill,
                "_downloadable_technical_fill_source_payload",
                side_effect=fake_cleaned,
            ),
            patch.object(
                ai_fill.technical_material_store,
                "raw_download_content",
                side_effect=fake_raw,
            ) as raw_mock,
            patch.object(ai_fill.minio_client, "download_file", side_effect=fake_download_file),
        ):
            prepared = ai_fill._prepare_material_index_files(
                materials,
                self.work_dir,
                cache_dir=self.cache_dir,
            )
        return prepared, raw_mock, downloads

    def test_excel_material_lands_original_alongside_cleaned_docx(self) -> None:
        prepared, _raw_mock, downloads = self._prepare(
            [{"id": "RAW-0136", "name": "报价文件.xlsx"}],
            raw_names={"RAW-0136": "报价文件.xlsx"},
        )
        item = prepared[0]
        # 清洗稿仍是 path（正文/文本抽取用），原件另行落地供 sheet 结构分支使用
        self.assertTrue(item["path"].endswith(".docx"))
        self.assertTrue(item["originalPath"].endswith(".xlsx"))
        self.assertTrue(Path(item["originalPath"]).exists())
        self.assertEqual(item["originalFileName"], "RAW-0136-报价文件.xlsx")
        self.assertEqual(len(downloads), 2)

    def test_word_material_does_not_hit_raw_download(self) -> None:
        prepared, raw_mock, downloads = self._prepare(
            [{"id": "RAW-0161", "name": "风资源评估报告.docx"}],
            raw_names={"RAW-0161": "风资源评估报告.docx"},
        )
        # Word 素材的清洗稿已等价于原件，不该为此多打一次 DB/MinIO
        raw_mock.assert_not_called()
        self.assertNotIn("originalPath", prepared[0])
        self.assertEqual(len(downloads), 1)

    def test_pdf_material_does_not_land_original(self) -> None:
        prepared, raw_mock, _downloads = self._prepare(
            [{"id": "RAW-0152", "name": "载荷安全性评估报告.pdf"}],
            raw_names={"RAW-0152": "载荷安全性评估报告.pdf"},
        )
        raw_mock.assert_not_called()
        self.assertNotIn("originalPath", prepared[0])

    def test_original_download_failure_keeps_cleaned_docx(self) -> None:
        prepared, _raw_mock, _downloads = self._prepare(
            [{"id": "RAW-0132", "name": "功率曲线.xlsx"}],
            raw_names={"RAW-0132": "功率曲线.xlsx"},
            fail_original=True,
        )
        item = prepared[0]
        # 原件取不到时退回清洗稿，不阻断整个填写任务
        self.assertTrue(item["path"].endswith(".docx"))
        self.assertNotIn("originalPath", item)

    def test_already_landed_original_is_reused(self) -> None:
        """清洗稿缺失时 path 本身就是 xlsx 原件，不重复下载。"""

        async def fake_raw_source(material_id):
            return {"bucket": "b", "key": f"raw/{material_id}.xlsx", "fileName": f"{material_id}.xlsx"}, "raw"

        downloads: list[str] = []

        def fake_download_file(_bucket, key, target_path):
            downloads.append(str(key))
            Path(target_path).write_bytes(b"fake")

        with (
            patch.object(
                ai_fill,
                "_downloadable_technical_fill_source_payload",
                side_effect=fake_raw_source,
            ),
            patch.object(ai_fill.technical_material_store, "raw_download_content") as raw_mock,
            patch.object(ai_fill.minio_client, "download_file", side_effect=fake_download_file),
        ):
            prepared = ai_fill._prepare_material_index_files(
                [{"id": "RAW-0150", "name": "大部件品牌.xlsx"}],
                self.work_dir,
                cache_dir=self.cache_dir,
            )
        item = prepared[0]
        self.assertEqual(item["originalPath"], item["path"])
        raw_mock.assert_not_called()
        self.assertEqual(len(downloads), 1)


class MaterialMayHaveExcelOriginalTests(unittest.TestCase):
    def test_suffix_decides(self) -> None:
        self.assertTrue(ai_fill._material_may_have_excel_original({"name": "a.xlsx"}))
        self.assertTrue(ai_fill._material_may_have_excel_original({"name": "a.XLSM"}))
        self.assertFalse(ai_fill._material_may_have_excel_original({"name": "a.docx"}))
        self.assertFalse(ai_fill._material_may_have_excel_original({"name": "a.pdf"}))

    def test_unknown_name_probes(self) -> None:
        # 名称缺失或后缀不认识时不提前否决，交由下载分支探测
        self.assertTrue(ai_fill._material_may_have_excel_original({}))
        self.assertTrue(ai_fill._material_may_have_excel_original({"name": "机型参数表"}))


if __name__ == "__main__":
    unittest.main()
