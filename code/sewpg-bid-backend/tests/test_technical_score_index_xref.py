from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from docx import Document


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = BACKEND_ROOT / "opencode" / "skills" / "bid-tech-score-index-xref"
RUNNER_PATH = SKILL_DIR / "scripts" / "run_from_manifest.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load("score_index_xref_runner_test", RUNNER_PATH)
xref = runner.xref_module


def _build_docx(path: Path, *, index_entries: list[str] | None, with_table: bool = True) -> None:
    """造一份「文本编号标题 + 评分索引表」的成稿，形状与格式清洗产物一致。"""
    doc = Document()
    doc.add_heading("5 投标技术方案", level=1)
    doc.add_paragraph("总述正文。")
    doc.add_heading("5.1 投标总体方案概述", level=2)
    doc.add_paragraph("概述正文。")
    doc.add_heading("5.3.3 叶片设计", level=3)
    doc.add_paragraph("叶片正文。")
    doc.add_heading("附表2 发电量计算表", level=1)
    doc.add_paragraph("附表正文。")

    if with_table:
        rows = 1 + len(index_entries or [""])
        table = doc.add_table(rows=rows, cols=3)
        table.cell(0, 0).text = "序号"
        table.cell(0, 1).text = "评审因素"
        table.cell(0, 2).text = "章节索引"
        for offset, entry in enumerate(index_entries or [""], start=1):
            table.cell(offset, 0).text = str(offset)
            table.cell(offset, 1).text = "风轮系统先进性及可靠性"
            table.cell(offset, 2).text = entry
    doc.save(str(path))


def _document_xml(path: Path) -> str:
    with ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _write_manifest(path: Path, **fields) -> Path:
    path.write_text(json.dumps(fields, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class ScoreIndexXrefTest(unittest.TestCase):
    def test_builds_hyperlink_and_pageref_for_filled_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            output = work / "成稿_xref.docx"
            _build_docx(source, index_entries=["5.1 投标总体方案概述", "5.3.3 叶片设计"])
            manifest = _write_manifest(
                work / "manifest.json",
                inputFile=str(source),
                outputFile=str(output),
            )

            result = runner.run_manifest(manifest)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["linkedCount"], 2)
            self.assertEqual(result["summary"]["unresolvedCount"], 0)
            self.assertEqual(result["summary"]["pagerefCount"], 2)
            self.assertTrue(result["summary"]["bookmarksResolvable"])
            self.assertTrue(output.exists())

            xml = _document_xml(output)
            self.assertIn("PAGEREF _Xref_", xml)
            self.assertIn('w:anchor="_Xref_0001"', xml)
            # 未算页码时留占位符，并明确提示需要 F9
            codes = {item["code"] for item in result["warnings"]}
            self.assertIn("xref_page_number_pending", codes)

    def test_matches_bare_chapter_number_after_format_cleaning(self) -> None:
        """格式清洗后标题是「文本编号 + Heading 样式」，映射只写章节号也要能命中。"""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            output = work / "成稿_xref.docx"
            _build_docx(source, index_entries=[""])
            mapping = work / "mapping.json"
            mapping.write_text(
                json.dumps({"风轮系统先进性及可靠性": ["5.1", "5.3.3", "附表2"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            manifest = _write_manifest(
                work / "manifest.json",
                inputFile=str(source),
                outputFile=str(output),
                mappingFile=str(mapping),
            )

            result = runner.run_manifest(manifest)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["filledRowCount"], 1)
            self.assertEqual(result["summary"]["linkedCount"], 3)
            self.assertEqual(result["summary"]["unresolvedCount"], 0)

    def test_skips_when_no_score_index_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            output = work / "成稿_xref.docx"
            _build_docx(source, index_entries=None, with_table=False)
            manifest = _write_manifest(
                work / "manifest.json",
                inputFile=str(source),
                outputFile=str(output),
            )

            result = runner.run_manifest(manifest)

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["outputFile"], "")
            self.assertFalse(output.exists())
            self.assertEqual([item["code"] for item in result["warnings"]], ["index_table_not_found"])

    def test_unresolved_entry_is_reported_and_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            output = work / "成稿_xref.docx"
            _build_docx(source, index_entries=["9.9 并不存在的章节"])
            manifest = _write_manifest(
                work / "manifest.json",
                inputFile=str(source),
                outputFile=str(output),
            )

            result = runner.run_manifest(manifest)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["linkedCount"], 0)
            self.assertEqual(result["summary"]["unresolvedCount"], 1)
            codes = {item["code"] for item in result["warnings"]}
            self.assertIn("xref_unresolved_entry", codes)
            texts = [p.text for row in Document(str(output)).tables[0].rows for p in row.cells[2].paragraphs]
            self.assertIn("9.9 并不存在的章节", texts)

    def test_rerun_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            first = work / "一次.docx"
            second = work / "二次.docx"
            _build_docx(source, index_entries=["5.1 投标总体方案概述"])
            runner.run_manifest(
                _write_manifest(work / "m1.json", inputFile=str(source), outputFile=str(first))
            )
            result = runner.run_manifest(
                _write_manifest(work / "m2.json", inputFile=str(first), outputFile=str(second))
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["linkedCount"], 1)
            self.assertEqual(result["summary"]["pagerefCount"], 1)
            # 复用已有书签，不新增
            self.assertEqual(result["summary"]["bookmarksCreated"], 0)
            cell_text = Document(str(second)).tables[0].rows[1].cells[2].text
            self.assertEqual(cell_text.count("，P"), 1)

    def test_mapping_with_unknown_section_skips_instead_of_writing_wrong_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            output = work / "成稿_xref.docx"
            _build_docx(source, index_entries=[""])
            mapping = work / "mapping.json"
            mapping.write_text(json.dumps({"风轮系统先进性及可靠性": ["8.8"]}, ensure_ascii=False), encoding="utf-8")

            result = runner.run_manifest(
                _write_manifest(
                    work / "manifest.json",
                    inputFile=str(source),
                    outputFile=str(output),
                    mappingFile=str(mapping),
                )
            )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual([item["code"] for item in result["warnings"]], ["mapping_unresolved"])
            self.assertFalse(output.exists())

    def test_rejects_output_equal_to_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            _build_docx(source, index_entries=["5.1 投标总体方案概述"])
            with self.assertRaises(ValueError):
                runner.run_manifest(
                    _write_manifest(work / "manifest.json", inputFile=str(source), outputFile=str(source))
                )


class ScoreIndexXrefPipelineTest(unittest.TestCase):
    def test_pipeline_step_falls_back_to_cleaner_output_on_failure(self) -> None:
        from app.services import tech_assembly

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            missing = work / "不存在.docx"
            result = tech_assembly._run_tech_score_index_xref_step(
                input_path=missing,
                output_path=work / "out.docx",
                work_dir=work,
            )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["outputFile"], "")
            self.assertEqual([item["code"] for item in result["warnings"]], ["score_index_xref_failed"])

    def test_pipeline_step_reports_skip_without_output(self) -> None:
        from app.services import tech_assembly

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "成稿.docx"
            _build_docx(source, index_entries=None, with_table=False)
            result = tech_assembly._run_tech_score_index_xref_step(
                input_path=source,
                output_path=work / "成稿_xref.docx",
                work_dir=work,
            )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["outputFile"], "")


if __name__ == "__main__":
    unittest.main()
