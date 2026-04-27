from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-toc-wiki-driven-v2"
    / "scripts"
)
ASSEMBLER_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-assembler"
    / "scripts"
)


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_assembler_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ASSEMBLER_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TocSkillScriptTests(unittest.TestCase):
    def test_bid_assembler_parse_toc_accepts_current_s2_json(self) -> None:
        parse_toc = load_assembler_script("parse_toc")

        with tempfile.TemporaryDirectory() as tmp:
            toc_path = Path(tmp) / "投标文件-总目录.json"
            toc_path.write_text(
                """{
  "schema_version": "bid-toc-json-v1",
  "document_title": "测试项目投标文件总目录",
  "items": [
    {"order": 1, "level": 1, "number": "1", "title": "项目概况", "annotation": "保留"},
    {"order": 2, "level": 2, "number": "1.1", "title": "项目背景", "annotation": "适配"},
    {"order": 3, "level": 1, "number": "附表", "title": "", "annotation": "保留"}
  ]
}""",
                encoding="utf-8",
            )

            entries = parse_toc.parse_toc_json(toc_path)

        self.assertEqual(entries[0]["chapter_no_flat"], "1")
        self.assertEqual(entries[0]["title"], "项目概况")
        self.assertEqual(entries[1]["tag"], "适配")
        self.assertEqual(entries[2]["title"], "附表")

    def test_bid_assembler_inject_prefix_collapses_heading_level_gaps(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("上海电气优势简介", style="Heading 2")
        doc.add_paragraph("基本情况", style="Heading 3")
        doc.add_paragraph("集团概况", style="Heading 4")
        doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
        doc.add_paragraph("测试验证技术", style="Heading 6")

        stats = numbering_fixer.inject_prefix_to_headings(
            doc,
            "1.9",
            toc_title="上海电气优势简介",
            skip_first_if_match=True,
        )
        headings = [para.text.strip().replace("  ", " ") for para in doc.paragraphs if para.text.strip()]

        self.assertTrue(stats["skipped_first"])
        self.assertEqual(
            headings,
            [
                "1.9.1 基本情况",
                "1.9.1.1 集团概况",
                "1.9.2 载荷仿真分析能力",
                "1.9.2.1 测试验证技术",
            ],
        )
        self.assertFalse(any(".0." in item or item.endswith(".0") for item in headings))

    def test_bid_assembler_strips_heading_style_numbering(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        with tempfile.TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "numbered-heading.docx"
            doc = Document()
            heading_style = doc.styles["Heading 2"]
            p_pr = heading_style.element.get_or_add_pPr()
            num_pr = OxmlElement("w:numPr")
            ilvl = OxmlElement("w:ilvl")
            ilvl.set(qn("w:val"), "1")
            num_id = OxmlElement("w:numId")
            num_id.set(qn("w:val"), "1")
            num_pr.append(ilvl)
            num_pr.append(num_id)
            p_pr.append(num_pr)
            doc.add_paragraph("1.7 投标方案优势说明", style="Heading 2")

            self.assertEqual(numbering_fixer.strip_numPr_from_heading_styles(doc), 1)
            doc.save(docx_path)

            with zipfile.ZipFile(docx_path) as zf:
                styles_xml = zf.read("word/styles.xml").decode("utf-8")

        match = re.search(r'(<w:style[^>]+w:styleId="Heading2"[^>]*>.*?</w:style>)', styles_xml)
        self.assertIsNotNone(match)
        self.assertNotIn("<w:numPr>", match.group(1))

    def test_bid_assembler_merges_oversize_material_instead_of_placeholder(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            source = root / "lib" / "投标机型业绩情况.docx"
            out = root / "out.docx"
            prep = root / "prep"

            master = Document()
            master.add_paragraph("")
            master.save(template)

            source.parent.mkdir(parents=True)
            doc = Document()
            doc.add_paragraph("投标机型业绩情况", style="Heading 1")
            doc.add_paragraph("这里是业绩正文")
            doc.save(source)

            plan = [
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "投标机型业绩情况",
                    "chapter_no": "1.8",
                    "chapter_no_flat": "1.8",
                    "paths": [source.name],
                }
            ]
            original_stat = Path.stat

            class FakeStat:
                def __init__(self, wrapped):
                    self._wrapped = wrapped
                    self.st_size = 234 * 1024 * 1024

                def __getattr__(self, name):
                    return getattr(self._wrapped, name)

            def fake_stat(path, *args, **kwargs):
                value = original_stat(path, *args, **kwargs)
                if Path(path).resolve() == source.resolve():
                    return FakeStat(value)
                return value

            with patch.object(Path, "stat", fake_stat):
                stats = merger.merge(template, plan, source.parent, {}, prep, out)

            result = Document(str(out))
            text = "\n".join(para.text for para in result.paragraphs)

        self.assertEqual(stats["merged_materials"], 1)
        self.assertNotIn("大素材跳过", text)
        self.assertIn("这里是业绩正文", text)

    def test_extract_template_prefers_toc_and_deduplicates_body_headings(self) -> None:
        extract_template = load_script("extract_template")

        with tempfile.TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "投标文件-正文.docx"
            doc = Document()
            doc.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
            doc.styles.add_style("toc 2", WD_STYLE_TYPE.PARAGRAPH)
            doc.add_paragraph("目录", style="TOC Heading")
            doc.add_paragraph("第1章 标前概述\t4", style="toc 1")
            doc.add_paragraph("1.1 技术评分标准索引表\t4", style="toc 2")
            doc.add_paragraph("第2章 技术标准\t150", style="toc 1")
            doc.add_paragraph("标前概述", style="Heading 1")
            doc.add_paragraph("技术评分标准索引表", style="Heading 2")
            doc.add_paragraph("12、齐齐哈尔工厂")
            doc.save(docx_path)

            result = extract_template.extract(docx_path)

        self.assertEqual([item["title"] for item in result["chapters"]], ["标前概述", "技术标准"])
        self.assertEqual(result["chapters"][0]["page"], "4")
        self.assertEqual(result["chapters"][0]["h2s"][0]["title"], "技术评分标准索引表")

    def test_wiki_lookup_splits_group_cards_into_material_entries(self) -> None:
        wiki_lookup = load_script("wiki_lookup")

        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            cards = wiki_root / "卡片"
            cards.mkdir(parents=True)
            (cards / "05-技术标通用卡片.md").write_text(
                """---
path: "技术标Wiki/05-技术标通用卡片"
scope: "通用"
category: "通用卡片"
skeleton_section: "05"
skeleton_level: "section"
material_level_range: "none"
heading_count: 0
shift: 0
attach_mode: "normal"
condition: ""
deprecated: false
---

# 技术标通用卡片

## D.技术方案类

### 投标关键数据一览表
- **id**: RAW-0007
- **docx**: 通用素材/技术标/技术标-投标关键数据一览表.docx
- **usage**: both
- **headings**: 2 (L4-L5)
- **skeleton**: 技术标准和规范响应
- **attach**: 1.6关键数据+技术附表C
- **fields**: ${轮毂高度}, ${容量}
""",
                encoding="utf-8",
            )

            items = wiki_lookup.list_by_section(wiki_root)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["section"], "1.6")
        self.assertEqual(items[0]["display_name"], "投标关键数据一览表")
        self.assertEqual(items[0]["material_ref"]["id"], "RAW-0007")
        self.assertEqual(items[0]["heading_count"], 2)

    def test_build_plan_keeps_template_h2_and_adds_wiki_child_material(self) -> None:
        build_plan = load_script("build_plan")

        tpl = {
            "source": "/tmp/template.docx",
            "chapters": [
                {
                    "num": "1",
                    "title": "标前概述",
                    "raw_text": "第1章 标前概述\t4",
                    "page": "4",
                    "h2s": [
                        {
                            "num": "1.1",
                            "title": "技术评分标准索引表",
                            "raw_text": "1.1 技术评分标准索引表\t4",
                            "page": "4",
                        }
                    ],
                }
            ],
        }
        tender = {"specials": [], "site_flags": {}, "model_flags": {}, "plot_flags": {}}
        wiki_items = [
            {
                "section": "1.1",
                "display_name": "评分点响应说明",
                "scope": "通用",
                "path": "技术标Wiki/评分点响应说明",
                "source_name": "评分点响应说明",
                "material_ref": {"id": "RAW-1001", "docx": "评分点响应说明.docx", "usage": "directory"},
            }
        ]

        plan = build_plan.build_plan(tpl, tender, {}, wiki_items, "测试目录")

        self.assertEqual(plan["items"][0]["title"], "标前概述")
        self.assertEqual(plan["items"][1]["title"], "技术评分标准索引表")
        self.assertEqual(plan["items"][2]["title"], "评分点响应说明")
        self.assertEqual(plan["items"][2]["source"], "wiki")
        self.assertEqual(plan["items"][2]["material_refs"][0]["id"], "RAW-1001")

    def test_build_plan_filters_wiki_by_project_identity(self) -> None:
        build_plan = load_script("build_plan")

        wiki_items = [
            {"display_name": "通用方案", "scope": "通用"},
            {
                "display_name": "华能专属方案",
                "scope": "定制",
                "identity_scope": "customer",
                "customer_id": "CUST-HUANENG",
            },
            {
                "display_name": "大唐专属方案",
                "scope": "定制",
                "identity_scope": "customer",
                "customer_id": "CUST-DATANG",
            },
            {
                "display_name": "本项目方案",
                "scope": "定制",
                "identity_scope": "project",
                "project_code": "P-001",
            },
            {
                "display_name": "其他项目方案",
                "scope": "定制",
                "identity_scope": "project",
                "project_code": "P-999",
            },
        ]

        filtered = build_plan.filter_wiki_by_project_identity(
            wiki_items,
            {"customerId": "CUST-HUANENG", "projectCode": "P-001"},
            {"owner": "华能集团", "code": "P-001"},
        )

        self.assertEqual(
            [item["display_name"] for item in filtered],
            ["通用方案", "华能专属方案", "本项目方案"],
        )


if __name__ == "__main__":
    unittest.main()
