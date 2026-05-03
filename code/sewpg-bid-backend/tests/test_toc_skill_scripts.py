from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ASSEMBLER_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-assembler"
    / "scripts"
)
OUTLINE_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-outline-generator"
    / "scripts"
)
WIKI_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-wiki-material-builder"
    / "scripts"
)


def load_assembler_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ASSEMBLER_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_outline_script(name: str):
    module_name = f"outline_{name}"
    spec = importlib.util.spec_from_file_location(module_name, OUTLINE_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_wiki_script(name: str):
    module_name = f"wiki_{name}"
    spec = importlib.util.spec_from_file_location(module_name, WIKI_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TocSkillScriptTests(unittest.TestCase):
    def test_bid_wiki_builder_writes_full_blueprint_and_returns_small_summary(self) -> None:
        wiki_runner = load_wiki_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "wiki_manifest.json"
            output_file = root / "wiki_blueprint.json"
            manifest = {
                "targetBidType": "技术标",
                "rootTitle": "技术标Wiki（自动生成）",
                "workDir": str(root),
                "outputFile": str(output_file),
                "materialInventory": {
                    "items": [
                        {
                            "id": "M1",
                            "title": "总体方案",
                            "name": "总体方案.docx",
                            "path": "技术标/通用素材/总体方案.docx",
                            "identityScope": "general",
                            "materialTier": "general",
                            "group": "总体方案",
                            "headings": [{"title": "总体方案"}],
                        }
                    ]
                },
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            response = wiki_runner.run_manifest(manifest, manifest_path)

            self.assertEqual(response["outputFile"], str(output_file))
            self.assertIn("nodeTitles", response)
            self.assertLess(len(json.dumps(response, ensure_ascii=False)), 1000)
            blueprint = json_load(output_file)
            self.assertEqual(blueprint["rootTitle"], "技术标Wiki（自动生成）")
            self.assertEqual(
                [node["title"] for node in blueprint["nodes"]],
                ["01-素材总表", "02-章节映射表", "03-素材卡片", "04-待填写清单", "05-使用规则"],
            )
            cards_node = next(node for node in blueprint["nodes"] if node["title"] == "03-素材卡片")
            self.assertEqual(cards_node["children"][0]["children"][0]["children"][0]["title"], "总体方案")

    def test_bid_outline_generator_preserves_appendix_search_text_and_appends_last(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.add_paragraph("第1章 风资源评估与机位排布方案", style="Heading 1")
            template_doc.add_paragraph("1.1 项目风资源评估与机组选型排布及发电量计算", style="Heading 2")
            template_doc.add_paragraph("第2章 产品交付、考核及验收", style="Heading 1")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("技术附表E 项目风资源评估及机组选型排布及发电量计算 194")
            tender_doc.add_paragraph("附表E.3推荐机型各机位发电量成果表 195")
            tender_doc.save(tender)

            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "workDir": str(root),
                "templateFile": str(template),
                "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                "outputFile": str(output),
                "evidenceFile": str(evidence),
            }
            result = outline_runner.run_manifest(manifest, root / "s2_input.json")

            toc = json_load(output)
            titles = [item["title"] for item in toc["items"]]
            self.assertEqual(titles[-1], "推荐机型各机位发电量成果表")
            self.assertEqual(toc["items"][-1]["number"], "附表E.3")
            self.assertEqual(
                toc["items"][-1]["source_refs"][0]["searchText"],
                "附表E.3推荐机型各机位发电量成果表",
            )
            self.assertTrue(Path(result["summary"]["agentReviewFile"]).exists())

    def test_bid_outline_generator_excludes_tender_attachments_and_appendices_from_toc(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.add_paragraph("第1章 技术方案", style="Heading 1")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("附表A.1 投标机型总方案信息表")
            tender_doc.add_paragraph("附件一 中国华能集团有限公司陆上风电工程设备监理大纲")
            tender_doc.add_paragraph("附录A 设备制造监理内容")
            tender_doc.save(tender)

            outline_runner.run_manifest(
                {
                    "projectId": "PRJ-TEST",
                    "workDir": str(root),
                    "templateFile": str(template),
                    "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                    "outputFile": str(output),
                    "evidenceFile": str(evidence),
                },
                root / "s2_input.json",
            )

            toc = json_load(output)
            titles = [item["title"] for item in toc["items"]]
            self.assertIn("投标机型总方案信息表", titles)
            self.assertNotIn("中国华能集团有限公司陆上风电工程设备监理大纲", titles)
            self.assertNotIn("设备制造监理内容", titles)

            evidence_data = json_load(evidence)
            reference_titles = [
                decision["title"]
                for decision in evidence_data["decisions"]
                if decision.get("action") == "reference_only"
            ]
            self.assertIn("附件一 中国华能集团有限公司陆上风电工程设备监理大纲", reference_titles)
            self.assertIn("附录A 设备制造监理内容", reference_titles)

    def test_bid_outline_generator_prefers_toc_region_over_body_headings(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.styles.add_style("toc 2", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.add_paragraph("目录")
            template_doc.add_paragraph("第1章 模板总述\t1", style="toc 1")
            template_doc.add_paragraph("1.1 基本情况\t2", style="toc 2")
            template_doc.add_paragraph("第2章 正文标题不能进入目录", style="Heading 1")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("投标人应提供实施方案。")
            tender_doc.save(tender)

            outline_runner.run_manifest(
                {
                    "projectId": "PRJ-TEST",
                    "workDir": str(root),
                    "templateFile": str(template),
                    "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                    "outputFile": str(output),
                    "evidenceFile": str(evidence),
                },
                root / "s2_input.json",
            )

            toc = json_load(output)
            template_titles = [item["title"] for item in toc["items"] if item["source"] == "template"]
            self.assertEqual(template_titles, ["模板总述", "基本情况"])
            self.assertFalse(any("不能进入目录" in item["title"] for item in toc["items"]))

    def test_bid_outline_generator_ignores_body_numbered_lists_after_toc_region(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.styles.add_style("toc 2", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.add_paragraph("目录")
            template_doc.add_paragraph("第1章 模板总述\t1", style="toc 1")
            template_doc.add_paragraph("1.1 基本情况\t2", style="toc 2")
            template_doc.add_paragraph("正文开始")
            template_doc.add_paragraph("（4） 风储一体化构网型风机")
            template_doc.add_paragraph("(1) 叶根部驱动转矩")
            template_doc.add_paragraph("(2) 变桨电机转矩")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("投标人应提供实施方案。")
            tender_doc.save(tender)

            outline_runner.run_manifest(
                {
                    "projectId": "PRJ-TEST",
                    "workDir": str(root),
                    "templateFile": str(template),
                    "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                    "outputFile": str(output),
                    "evidenceFile": str(evidence),
                },
                root / "s2_input.json",
            )

            toc = json_load(output)
            titles = [item["title"] for item in toc["items"]]
            self.assertEqual(titles, ["模板总述", "基本情况"])
            self.assertNotIn("风储一体化构网型风机", titles)
            self.assertNotIn("叶根部驱动转矩", titles)
            self.assertNotIn("变桨电机转矩", titles)

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

if __name__ == "__main__":
    unittest.main()
