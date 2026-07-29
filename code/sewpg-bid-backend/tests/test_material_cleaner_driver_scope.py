from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


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
    def test_skill_documents_blank_heading_metadata_cleanup(self) -> None:
        skill_text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("空白标题", skill_text)
        self.assertIn("保留段落及其中的换行符和分页符", skill_text)
        self.assertIn("清除 Heading 样式和 outlineLvl", skill_text)

    def test_pdf_and_excel_converter_scripts_are_removed(self) -> None:
        script_dir = DRIVER_PATH.parent

        self.assertFalse((script_dir / "pdf_to_word.py").exists())
        self.assertFalse((script_dir / "excel_to_word.py").exists())

    def test_driver_only_scans_docx_after_doc_preconversion(self) -> None:
        driver = _load_driver()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            output = Path(tmp) / "cleaned"
            source.mkdir()
            for name in ["方案.docx", "旧方案.doc", "报告.pdf", "台账.xlsx", "台账.xls"]:
                (source / name).write_bytes(b"fixture")

            scanned = driver._scan_sources(source, output)

        self.assertEqual([path.name for path in scanned], ["方案.docx"])
        self.assertEqual(driver.SUPPORTED_SUFFIXES, {".docx"})

    def test_driver_has_no_pdf_or_excel_runtime_dependencies(self) -> None:
        driver = _load_driver()

        self.assertNotIn("fitz", driver.RUNTIME_DEPENDENCIES)
        self.assertNotIn("pandas", driver.RUNTIME_DEPENDENCIES)
        self.assertNotIn("openpyxl", driver.RUNTIME_DEPENDENCIES)


if __name__ == "__main__":
    unittest.main()
