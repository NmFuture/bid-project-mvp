from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE


SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-toc-wiki-driven-v2"
    / "scripts"
)


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TocSkillScriptTests(unittest.TestCase):
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
