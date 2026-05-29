import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_from_manifest.py"
SCRIPT_DIR = str(ROOT / "scripts")


def _run_manifest(manifest_path: Path, *, response: str = "summary"):
    module_name = "bid_tech_format_cleaner_run_from_manifest"
    inserted = False
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load runner: {RUNNER_PATH}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module.run_manifest(manifest_path, response=response)
    finally:
        sys.modules.pop(module_name, None)
        if inserted:
            sys.path.remove(SCRIPT_DIR)


def _write_style(path: Path) -> None:
    style = {
        "schema_version": "tech_heading_style.test",
        "page": {
            "top_cm": 2.54,
            "bottom_cm": 2.54,
            "left_cm": 3.18,
            "right_cm": 3.18,
            "header_top_cm": 1.0,
            "footer_bottom_cm": 0.6,
            "orientation": "portrait",
        },
        "heading": {
            str(level): {
                "zh_font": "等线",
                "en_font": "Times New Roman",
                "size_pt": 12 + max(0, 4 - level),
                "bold": True,
                "align": "left",
                "space_before_pt": 6,
                "space_after_pt": 6,
                "line_spacing": 1.5,
                "first_line_indent_chars": 0,
                "left_indent_cm": 0,
            }
            for level in range(1, 5)
        },
    }
    path.write_text(json.dumps(style, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_outline(path: Path) -> None:
    outline = {
        "schema_version": "tech_bid_outline.v1",
        "sections": [
            {
                "id": "h1",
                "number": "1",
                "title": "一级标题",
                "level": 1,
                "children": [
                    {
                        "id": "h2",
                        "number": "1.1",
                        "title": "二级标题",
                        "level": 2,
                        "children": [
                            {
                                "id": "h3",
                                "number": "1.1.1",
                                "title": "三级标题",
                                "level": 3,
                                "children": [
                                    {
                                        "id": "h4",
                                        "number": "1.1.1.1",
                                        "title": "四级标题",
                                        "level": 4,
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_deep_heading_docx(path: Path) -> None:
    doc = Document()
    for text in ("1 一级标题", "1.1 二级标题", "1.1.1 三级标题", "1.1.1.1 四级标题"):
        doc.add_paragraph(text)
        doc.add_paragraph("正文内容")
    doc.save(path)


def _write_portrait_and_landscape_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("1 一级标题")
    doc.add_paragraph("竖版正文")
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    doc.add_paragraph("1.1 二级标题")
    doc.add_paragraph("横版正文")
    doc.save(path)


def _write_manifest(
    path: Path,
    *,
    input_docx: Path,
    outline_path: Path,
    output_docx: Path,
    style_path: Path,
) -> None:
    path.write_text(
        json.dumps(
            {
                "inputFile": str(input_docx),
                "outlineFile": str(outline_path),
                "outputFile": str(output_docx),
                "projectName": "测试项目",
                "styleSpecPath": str(style_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


class TechFormatCleanerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="tech-format-cleaner-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_promotes_level_three_and_four_headings(self):
        input_docx = self.tmp_dir / "input.docx"
        outline_path = self.tmp_dir / "outline.json"
        style_path = self.tmp_dir / "style.json"
        output_docx = self.tmp_dir / "output.docx"
        manifest_path = self.tmp_dir / "manifest.json"

        _write_deep_heading_docx(input_docx)
        _write_outline(outline_path)
        _write_style(style_path)
        _write_manifest(
            manifest_path,
            input_docx=input_docx,
            outline_path=outline_path,
            output_docx=output_docx,
            style_path=style_path,
        )

        result = _run_manifest(manifest_path, response="details")

        self.assertEqual(result["summary"]["matchedHeadingCount"], 4)
        self.assertEqual(result["summary"]["headingLevelCounts"]["3"], 1)
        self.assertEqual(result["summary"]["headingLevelCounts"]["4"], 1)

        output = Document(str(output_docx))
        style_by_text = {paragraph.text.strip(): paragraph.style.name for paragraph in output.paragraphs}
        self.assertEqual(style_by_text["1.1.1 三级标题"], "Heading 3")
        self.assertEqual(style_by_text["1.1.1.1 四级标题"], "Heading 4")

    def test_preserves_landscape_sections_during_cleaning(self):
        input_docx = self.tmp_dir / "input.docx"
        outline_path = self.tmp_dir / "outline.json"
        style_path = self.tmp_dir / "style.json"
        output_docx = self.tmp_dir / "output.docx"
        manifest_path = self.tmp_dir / "manifest.json"

        _write_portrait_and_landscape_docx(input_docx)
        _write_outline(outline_path)
        _write_style(style_path)
        _write_manifest(
            manifest_path,
            input_docx=input_docx,
            outline_path=outline_path,
            output_docx=output_docx,
            style_path=style_path,
        )

        result = _run_manifest(manifest_path, response="details")

        self.assertGreaterEqual(result["summary"]["orientation"]["portrait"], 1)
        self.assertGreaterEqual(result["summary"]["orientation"]["landscape"], 1)

        output = Document(str(output_docx))
        has_landscape = any(int(section.page_width) > int(section.page_height) for section in output.sections)
        has_portrait = any(int(section.page_height) >= int(section.page_width) for section in output.sections)
        self.assertTrue(has_landscape)
        self.assertTrue(has_portrait)

    def test_infers_deep_appendix_heading_levels_from_numbers(self):
        input_docx = self.tmp_dir / "input.docx"
        outline_path = self.tmp_dir / "outline.json"
        style_path = self.tmp_dir / "style.json"
        output_docx = self.tmp_dir / "output.docx"
        manifest_path = self.tmp_dir / "manifest.json"

        doc = Document()
        doc.add_paragraph("附表B.1.1 风力发电机组供货范围清单")
        doc.add_paragraph("三级附表内容")
        doc.add_paragraph("附表B.1.1.1 叶片供货范围")
        doc.add_paragraph("四级附表内容")
        doc.save(input_docx)
        outline_path.write_text(
            json.dumps(
                {
                    "schema_version": "tech_bid_outline.v1",
                    "sections": [
                        {
                            "id": "app-3",
                            "number": "附表B.1.1",
                            "title": "风力发电机组供货范围清单",
                            "level": 1,
                            "children": [],
                        },
                        {
                            "id": "app-4",
                            "number": "附表B.1.1.1",
                            "title": "叶片供货范围",
                            "level": 1,
                            "children": [],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _write_style(style_path)
        _write_manifest(
            manifest_path,
            input_docx=input_docx,
            outline_path=outline_path,
            output_docx=output_docx,
            style_path=style_path,
        )

        result = _run_manifest(manifest_path, response="details")

        self.assertEqual(result["summary"]["headingLevelCounts"]["3"], 1)
        self.assertEqual(result["summary"]["headingLevelCounts"]["4"], 1)
        output = Document(str(output_docx))
        style_by_text = {paragraph.text.strip(): paragraph.style.name for paragraph in output.paragraphs}
        self.assertEqual(style_by_text["附表B.1.1 风力发电机组供货范围清单"], "Heading 3")
        self.assertEqual(style_by_text["附表B.1.1.1 叶片供货范围"], "Heading 4")

    def test_promotes_internal_material_headings_without_promoting_captions(self):
        input_docx = self.tmp_dir / "input.docx"
        outline_path = self.tmp_dir / "outline.json"
        style_path = self.tmp_dir / "style.json"
        output_docx = self.tmp_dir / "output.docx"
        manifest_path = self.tmp_dir / "manifest.json"

        doc = Document()
        doc.add_paragraph("1 一级标题")
        doc.add_paragraph("1.1 二级标题")
        h3 = doc.add_paragraph()
        h3.add_run("供应链能力保障").bold = True
        doc.add_paragraph("供应链正文内容")
        h4 = doc.add_paragraph("（1）签订产能协议")
        doc.add_paragraph("四级正文内容")
        caption = doc.add_paragraph()
        caption.add_run("表C.1 总体技术参数与规格").bold = True
        doc.save(input_docx)
        _write_outline(outline_path)
        _write_style(style_path)
        _write_manifest(
            manifest_path,
            input_docx=input_docx,
            outline_path=outline_path,
            output_docx=output_docx,
            style_path=style_path,
        )

        result = _run_manifest(manifest_path, response="details")

        self.assertEqual(result["summary"]["internalHeadingCount"], 1)
        output = Document(str(output_docx))
        style_by_text = {paragraph.text.strip(): paragraph.style.name for paragraph in output.paragraphs}
        self.assertEqual(style_by_text["供应链能力保障"], "Heading 3")
        self.assertNotEqual(style_by_text["（1）签订产能协议"], "Heading 4")
        self.assertNotEqual(style_by_text["表C.1 总体技术参数与规格"], "Heading 3")


if __name__ == "__main__":
    unittest.main()
