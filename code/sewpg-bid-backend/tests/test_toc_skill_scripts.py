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

    def test_bid_assembler_inject_prefix_clears_stale_direct_outline(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("上海电气优势简介", style="Heading 2")
        stale = doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
        p_pr = stale._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        p_pr.append(outline)

        numbering_fixer.inject_prefix_to_headings(
            doc,
            "1.9",
            toc_title="上海电气优势简介",
            skip_first_if_match=True,
        )

        remaining = [para for para in doc.paragraphs if "载荷仿真分析能力" in para.text][0]
        self.assertEqual(remaining.style.name, "Heading 3")
        p_pr = remaining._p.find(qn("w:pPr"))
        self.assertIsNotNone(p_pr)
        self.assertIsNone(p_pr.find(qn("w:outlineLvl")))

    def test_bid_assembler_demotes_material_headings_to_body(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("上海电气优势简介", style="Heading 2")
        doc.add_paragraph("基本情况", style="Heading 3")
        stale = doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
        p_pr = stale._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        p_pr.append(outline)

        stats = numbering_fixer.demote_headings_to_body(
            doc,
            toc_title="上海电气优势简介",
            remove_first_if_match=True,
        )

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(stats["demoted"], 2)
        self.assertEqual([para.text for para in doc.paragraphs], ["基本情况", "载荷仿真分析能力"])
        self.assertFalse(any((para.style.name or "").startswith("Heading") for para in doc.paragraphs))
        self.assertTrue(all(para._p.find(qn("w:pPr")).find(qn("w:outlineLvl")) is None for para in doc.paragraphs))

    def test_bid_assembler_demotes_direct_outline_without_body_style(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        styled = doc.add_paragraph("发电小时数承诺函", style="Heading 2")
        direct_only = doc.add_paragraph("发电量保证矩阵表")
        direct_p_pr = direct_only._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        direct_p_pr.append(outline)

        styles_el = doc.styles._element
        for style in list(styles_el.findall(qn("w:style"))):
            if style.get(qn("w:styleId")) == "Normal":
                styles_el.remove(style)

        stats = numbering_fixer.demote_headings_to_body(doc)

        self.assertEqual(stats["demoted"], 2)
        for para in (styled, direct_only):
            p_pr = para._p.find(qn("w:pPr"))
            self.assertIsNotNone(p_pr)
            self.assertIsNone(p_pr.find(qn("w:pStyle")))
            self.assertIsNone(p_pr.find(qn("w:outlineLvl")))

    def test_bid_assembler_keeps_s2_child_headings_from_material(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("项目技术承诺函", style="Heading 1")
        child = doc.add_paragraph("发电小时数承诺函", style="Heading 2")
        extra = doc.add_paragraph("发电量保证矩阵表")
        p_pr = extra._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        p_pr.append(outline)

        stats = numbering_fixer.demote_headings_to_body(
            doc,
            toc_title="项目技术承诺函",
            remove_first_if_match=True,
            keep_heading_map={
                "发电小时数承诺函": {
                    "chapter_no": "4.1",
                    "title": "发电小时数承诺函",
                    "level": 2,
                }
            },
        )

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["demoted"], 1)
        self.assertEqual(child.text.strip().replace("  ", " "), "4.1 发电小时数承诺函")
        self.assertEqual(child.style.name, "Heading 2")
        extra_p_pr = extra._p.find(qn("w:pPr"))
        self.assertIsNone(extra_p_pr.find(qn("w:pStyle")))
        self.assertIsNone(extra_p_pr.find(qn("w:outlineLvl")))

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

    def test_bid_assembler_merger_keeps_only_toc_heading_in_navigation(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            source = root / "lib" / "上海电气优势简介.docx"
            out = root / "out.docx"
            prep = root / "prep"

            master = Document()
            master.add_paragraph("")
            master.save(template)

            source.parent.mkdir(parents=True)
            doc = Document()
            doc.add_paragraph("上海电气优势简介", style="Heading 2")
            doc.add_paragraph("基本情况", style="Heading 3")
            stale = doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
            p_pr = stale._p.get_or_add_pPr()
            outline = OxmlElement("w:outlineLvl")
            outline.set(qn("w:val"), "0")
            p_pr.append(outline)
            doc.add_paragraph("这里是正文")
            doc.save(source)

            plan = [
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "上海电气优势简介",
                    "chapter_no": "1.9",
                    "chapter_no_flat": "1.9",
                    "paths": [source.name],
                }
            ]
            merger.merge(template, plan, source.parent, {}, prep, out)

            result = Document(str(out))
            headings = [
                para.text.strip().replace("  ", " ")
                for para in result.paragraphs
                if (para.style.name or "").startswith("Heading") and para.text.strip()
            ]
            text = "\n".join(para.text for para in result.paragraphs)

        self.assertEqual(headings, ["1.9 上海电气优势简介"])
        self.assertIn("基本情况", text)
        self.assertIn("载荷仿真分析能力", text)

    def test_bid_assembler_merger_keeps_matching_child_heading_in_place(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            source = root / "lib" / "项目技术承诺函.docx"
            out = root / "out.docx"
            prep = root / "prep"

            master = Document()
            master.add_paragraph("")
            master.save(template)

            source.parent.mkdir(parents=True)
            doc = Document()
            doc.add_paragraph("项目技术承诺函", style="Heading 1")
            doc.add_paragraph("发电小时数承诺函", style="Heading 2")
            doc.add_paragraph("这里是 4.1 正文")
            doc.save(source)

            plan = [
                {
                    "status": "MATCHED",
                    "level": 1,
                    "title": "项目技术承诺函",
                    "chapter_no": "第四章",
                    "chapter_no_flat": "4",
                    "paths": [source.name],
                },
                {
                    "status": "UNMATCHED",
                    "level": 2,
                    "title": "发电小时数承诺函",
                    "chapter_no": "4.1",
                    "chapter_no_flat": "4.1",
                    "paths": [],
                },
            ]
            merger.merge(template, plan, source.parent, {}, prep, out)

            result = Document(str(out))
            headings = [
                para.text.strip().replace("  ", " ")
                for para in result.paragraphs
                if (para.style.name or "").startswith("Heading") and para.text.strip()
            ]
            text = "\n".join(para.text for para in result.paragraphs)

        self.assertEqual(headings, ["第四章 项目技术承诺函", "4.1 发电小时数承诺函"])
        self.assertIn("这里是 4.1 正文", text)
        self.assertNotIn("[缺失：发电小时数承诺函", text)

    def test_bid_assembler_verify_uses_direct_outline_level_priority(self) -> None:
        verify = load_assembler_script("verify")

        with tempfile.TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "stale-outline.docx"
            doc = Document()
            stale = doc.add_paragraph("1.9.4  载荷仿真分析能力", style="Heading 3")
            p_pr = stale._p.get_or_add_pPr()
            outline = OxmlElement("w:outlineLvl")
            outline.set(qn("w:val"), "0")
            p_pr.append(outline)
            doc.save(docx_path)

            scan = verify.scan_docx(docx_path)

        self.assertEqual(scan["heading_counts"], {"Heading 1": 1})
        self.assertIn("1.9.4  载荷仿真分析能力", scan["invalid_h1"])

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

    def test_build_plan_merges_directory_template_profiles_as_reviewable_sources(self) -> None:
        build_plan = load_script("build_plan")

        tpl = {
            "source": "/tmp/template.docx",
            "chapters": [
                {
                    "num": "1",
                    "title": "标前概述",
                    "raw_text": "第1章 标前概述",
                    "h2s": [],
                }
            ],
        }
        tender = {"specials": [], "site_flags": {}, "model_flags": {}, "plot_flags": {}}
        directory_templates = [
            {
                "id": "tech-huaneng",
                "name": "华能类技术标目录模板",
                "chapters": [
                    {
                        "num": "1",
                        "title": "标前概述",
                        "h2s": [{"num": "1.1", "title": "技术评分标准索引表"}],
                    },
                    {
                        "num": "5",
                        "title": "专题技术方案",
                        "h2s": [{"num": "5.1", "title": "环境适应性专题"}],
                    },
                ],
            }
        ]

        plan = build_plan.build_plan(tpl, tender, {}, [], "测试目录", directory_templates=directory_templates)

        title_to_item = {item["title"]: item for item in plan["items"]}
        self.assertEqual(title_to_item["技术评分标准索引表"]["source"], "directory_template")
        self.assertEqual(title_to_item["技术评分标准索引表"]["source_refs"][0]["type"], "directory_template")
        self.assertEqual(title_to_item["专题技术方案"]["source"], "directory_template")
        self.assertEqual(title_to_item["环境适应性专题"]["number"], "5.1")

    def test_build_plan_avoids_number_collisions_between_general_and_customer_templates(self) -> None:
        build_plan = load_script("build_plan")

        tpl = {"source": "/tmp/template.docx", "chapters": []}
        tender = {"specials": [], "site_flags": {}, "model_flags": {}, "plot_flags": {}}
        directory_templates = [
            {
                "id": "tech-general",
                "name": "技术标通用目录模板",
                "chapters": [
                    {
                        "num": "1",
                        "title": "标前概述",
                        "h2s": [{"num": "1.1", "title": "投标关键数据一览表"}],
                    }
                ],
            },
            {
                "id": "tech-huaneng",
                "name": "华能类技术标目录模板",
                "chapters": [
                    {
                        "num": "1",
                        "title": "标前概述",
                        "h2s": [{"num": "1.1", "title": "技术评分标准索引表"}],
                    }
                ],
            },
        ]

        plan = build_plan.build_plan(tpl, tender, {}, [], "测试目录", directory_templates=directory_templates)
        chapter_one_children = [
            item for item in plan["items"] if str(item.get("number") or "").startswith("1.")
        ]

        self.assertEqual(chapter_one_children[0]["title"], "技术评分标准索引表")
        self.assertEqual(len({item["number"] for item in chapter_one_children}), len(chapter_one_children))

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
