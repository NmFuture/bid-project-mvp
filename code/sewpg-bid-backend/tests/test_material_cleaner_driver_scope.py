from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


DRIVER_PATH = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skills"
    / "bid-material-format-cleaner"
    / "scripts"
    / "driver.py"
)
SKILL_PATH = DRIVER_PATH.parents[1] / "SKILL.md"


def _load_driver():
    module_name = "test_bid_material_format_cleaner_driver"
    spec = importlib.util.spec_from_file_location(module_name, DRIVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class MaterialCleanerDriverScopeTests(unittest.TestCase):
    def test_skill_documents_blank_heading_cleanup_contract(self) -> None:
        skill_text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("空白标题", skill_text)
        self.assertIn("清除 Heading 样式和 outlineLvl", skill_text)
        self.assertIn("含手工换行或分页符的段落予以保留", skill_text)
        self.assertIn("纯空段落按空行合并和空白页清理规则处理", skill_text)
        self.assertNotIn("保留段落及其中的换行符和分页符", skill_text)

    def test_pdf_and_excel_converter_scripts_exist(self) -> None:
        script_dir = DRIVER_PATH.parent

        self.assertTrue((script_dir / "pdf_to_word.py").exists())
        self.assertTrue((script_dir / "excel_to_word.py").exists())

    def test_driver_scans_docx_and_deep_convertible_suffixes(self) -> None:
        driver = _load_driver()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            output = Path(tmp) / "cleaned"
            source.mkdir()
            for name in ["方案.docx", "旧方案.doc", "报告.pdf", "台账.xlsx", "台账.xls", "台账.xlsm", "图片.png"]:
                (source / name).write_bytes(b"fixture")

            scanned = driver._scan_sources(source, output)

        self.assertEqual(
            [path.name for path in scanned],
            ["台账.xls", "台账.xlsm", "台账.xlsx", "报告.pdf", "方案.docx"],
        )
        self.assertEqual(driver.SUPPORTED_SUFFIXES, {".pdf", ".xlsx", ".xls", ".xlsm", ".docx"})

    def test_driver_maps_pdf_excel_output_to_docx(self) -> None:
        driver = _load_driver()
        source_dir = Path("/tmp/fc-src")
        output_dir = Path("/tmp/fc-out")

        self.assertEqual(
            driver._output_path_for(source_dir / "报告.pdf", source_dir, output_dir),
            output_dir / "报告.docx",
        )
        self.assertEqual(
            driver._output_path_for(source_dir / "sub" / "台账.xlsx", source_dir, output_dir),
            output_dir / "sub" / "台账.docx",
        )
        self.assertEqual(
            driver._output_path_for(source_dir / "方案.docx", source_dir, output_dir),
            output_dir / "方案.docx",
        )

    def test_driver_declares_pdf_excel_runtime_dependencies(self) -> None:
        driver = _load_driver()

        self.assertEqual(driver.RUNTIME_DEPENDENCIES["fitz"], "pymupdf")
        self.assertEqual(driver.RUNTIME_DEPENDENCIES["pandas"], "pandas")
        self.assertEqual(driver.RUNTIME_DEPENDENCIES["openpyxl"], "openpyxl")


class _RawFileSession:
    def __init__(self, item: SimpleNamespace) -> None:
        self.item = item

    async def __aenter__(self) -> "_RawFileSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        return SimpleNamespace(scalar_one_or_none=lambda: self.item)


def _pdf_raw_file() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="报告.pdf",
        minio_bucket="materials",
        minio_key="raw/报告.pdf",
        version=1,
        folder=None,
    )


class MaterialCleaningAllowConvertTests(unittest.IsolatedAsyncioTestCase):
    def test_deep_convertible_suffixes(self) -> None:
        from app.services import material_cleaning

        for name in ["报告.pdf", "台账.xlsx", "台账.xls", "台账.xlsm", "a/PDF 报告.PDF"]:
            self.assertTrue(material_cleaning.is_deep_convertible_material(name), name)
        for name in ["方案.docx", "旧方案.doc", "图片.png", "笔记.md", ""]:
            self.assertFalse(material_cleaning.is_deep_convertible_material(name), name)

    async def test_pdf_without_allow_convert_stays_original_only(self) -> None:
        from app.services import material_cleaning

        item = _pdf_raw_file()
        status_mock = AsyncMock(return_value={"cleanStatus": "original_only"})
        with (
            patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
            patch.object(material_cleaning, "set_material_clean_status", new=status_mock),
        ):
            result = await material_cleaning.clean_material_file("RAW-0001")

        self.assertEqual(result["cleanStatus"], "original_only")
        status_mock.assert_awaited_once()
        self.assertEqual(status_mock.await_args.args[1], "original_only")

    async def test_pdf_with_allow_convert_enters_conversion_path(self) -> None:
        from app.services import material_cleaning

        item = _pdf_raw_file()
        status_mock = AsyncMock(
            side_effect=[
                {"cleanStatus": "cleaning"},
                {"cleanStatus": "failed", "cleanMessage": "素材原件读取失败"},
            ]
        )
        with (
            patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
            patch.object(material_cleaning, "set_material_clean_status", new=status_mock),
            patch.object(
                material_cleaning,
                "_prepare_cleaning_source",
                new=AsyncMock(side_effect=RuntimeError("minio down")),
            ),
        ):
            result = await material_cleaning.clean_material_file(
                "RAW-0001",
                {"convertNonWord": True},
                allow_convert=True,
            )

        self.assertEqual(result["cleanStatus"], "failed")
        self.assertEqual(status_mock.await_count, 2)
        cleaning_call = status_mock.await_args_list[0]
        self.assertEqual(cleaning_call.args[1], "cleaning")
        self.assertEqual(cleaning_call.args[2], "正在后台转换为 Word 素材。")
        failure_call = status_mock.await_args_list[-1]
        self.assertIn("minio down", failure_call.kwargs["extra"]["cleanError"])

    async def test_non_convertible_suffix_ignores_allow_convert(self) -> None:
        from app.services import material_cleaning

        item = _pdf_raw_file()
        item.name = "图片.png"
        item.minio_key = "raw/图片.png"
        status_mock = AsyncMock(return_value={"cleanStatus": "original_only"})
        with (
            patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
            patch.object(material_cleaning, "set_material_clean_status", new=status_mock),
        ):
            result = await material_cleaning.clean_material_file(
                "RAW-0001",
                {"convertNonWord": True},
                allow_convert=True,
            )

        self.assertEqual(result["cleanStatus"], "original_only")
        status_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
