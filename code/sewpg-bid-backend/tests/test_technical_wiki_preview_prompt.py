from __future__ import annotations

import json
import unittest
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.wiki_blueprint_common import extract_docx_profile
from app.services.technical_wiki_preview_prompt import (
    PREVIEW_BATCH_SIZE,
    PREVIEW_SCHEMA_VERSION,
    build_batch_preview_prompt,
    build_evidence_segments,
    build_preview_prompt,
    document_outline_from_profile,
    parse_batch_preview_reply,
    parse_preview_reply,
)


def _loader(text: str) -> dict:
    """简易 json_loader：剥代码块后 json.loads，模拟 OpencodeClient._parse_json_payload。"""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return json.loads(cleaned)


PROFILE = {
    "headings": [{"level": 1, "title": "总体方案"}, {"level": 2, "title": "供货范围"}],
    "paragraphs": ["本机组适用于低温环境。", "额定功率 5.0MW。"],
    "tableCount": 1,
}


class PreviewPromptModuleTests(unittest.TestCase):
    def test_constants_exposed(self) -> None:
        self.assertIsInstance(PREVIEW_SCHEMA_VERSION, int)
        self.assertIsInstance(PREVIEW_BATCH_SIZE, int)
        self.assertGreaterEqual(PREVIEW_BATCH_SIZE, 1)

    def test_build_preview_prompt_contains_context(self) -> None:
        prompt = build_preview_prompt("总体方案.docx", "技术标/标准文件/EW5.0/总体方案.docx", "标准文件", PROFILE)
        self.assertIn("总体方案.docx", prompt)
        self.assertIn("技术标/标准文件/EW5.0/总体方案.docx", prompt)
        self.assertIn("标准文件", prompt)
        self.assertIn("供货范围", prompt)  # heading 树
        self.assertIn("额定功率 5.0MW", prompt)  # 正文摘录
        self.assertIn("严格 JSON", prompt)

    def test_document_outline_preserves_all_headings_and_levels(self) -> None:
        headings = [{"level": (index % 3) + 1, "title": f"章节 {index}"} for index in range(100)]
        outline = document_outline_from_profile({"headings": headings})

        self.assertEqual(len(outline), 100)
        self.assertEqual(outline[0], {"level": 1, "title": "章节 0"})
        self.assertEqual(outline[-1], {"level": 1, "title": "章节 99"})

    def test_document_outline_drops_numeric_table_values(self) -> None:
        outline = document_outline_from_profile(
            {
                "headings": [
                    {"level": 1, "title": "6.25-220-160混合塔架参数"},
                    {"level": 1, "title": "131.88"},
                    {"level": 1, "title": "9.08/5"},
                    {"level": 2, "title": "二、钢塔段（含法兰）"},
                ]
            }
        )

        self.assertEqual(
            outline,
            [
                {"level": 1, "title": "6.25-220-160混合塔架参数"},
                {"level": 2, "title": "二、钢塔段（含法兰）"},
            ],
        )

    def test_document_outline_uses_body_headings_for_original_word_only(self) -> None:
        profile = {
            "headings": [
                {"level": 1, "title": "正文方案"},
                {"level": 2, "title": "表格参数"},
                {"level": 2, "title": "实施计划"},
            ],
            "bodyHeadings": [
                {"level": 1, "title": "正文方案"},
                {"level": 2, "title": "实施计划"},
            ],
        }

        self.assertEqual(
            document_outline_from_profile(profile, source_ext="docx"),
            [
                {"level": 1, "title": "正文方案"},
                {"level": 2, "title": "实施计划"},
            ],
        )
        self.assertEqual(document_outline_from_profile(profile, source_ext="xlsx"), [])
        self.assertEqual(document_outline_from_profile(profile, source_ext="pdf"), [])
        self.assertEqual(
            document_outline_from_profile(
                {"bodyHeadings": [{"level": 1, "title": "只有文档标题"}]},
                source_ext="docx",
            ),
            [],
        )

    def test_docx_profile_separates_table_headings_from_body_headings(self) -> None:
        body_heading = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>正文方案</w:t></w:r></w:p>'
        table_heading = '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>表格参数</w:t></w:r></w:p>'
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            f'{body_heading}<w:tbl><w:tr><w:tc>{table_heading}</w:tc></w:tr></w:tbl>'
            '</w:body></w:document>'
        )
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", document_xml)

        profile = extract_docx_profile(buffer.getvalue(), heading_limit=None)

        self.assertEqual([item["title"] for item in profile["headings"]], ["正文方案", "表格参数"])
        self.assertEqual(profile["bodyHeadings"], [{"level": 1, "title": "正文方案"}])

    def test_parse_preview_reply_normal_and_clip(self) -> None:
        reply = json.dumps(
            {
                "lead": "L" * 200,  # 超长，应裁到 120
                "points": ["a", "b", "c", "d", "e", "f", "g"],  # 超 5 条
                "keyParams": [{"label": "功率", "value": "5.0MW"}, {"bad": 1}],
                "retrievalHints": ["低温", "5MW", "", "海上"],
            }
        )
        preview = parse_preview_reply(reply, _loader)
        self.assertIsNotNone(preview)
        self.assertEqual(len(preview["lead"]), 120)
        self.assertEqual(len(preview["points"]), 5)
        self.assertEqual(preview["keyParams"], [{"label": "功率", "value": "5.0MW"}])
        self.assertEqual(preview["retrievalHints"], ["低温", "5MW", "海上"])

    def test_parse_preview_reply_empty_and_invalid(self) -> None:
        self.assertIsNone(parse_preview_reply("", _loader))
        self.assertIsNone(parse_preview_reply("not json at all", _loader))
        # lead 与 points 都空 -> 视为无效
        self.assertIsNone(parse_preview_reply(json.dumps({"lead": "", "points": []}), _loader))

    def test_parse_preview_reply_strips_code_fence(self) -> None:
        reply = "```json\n" + json.dumps({"lead": "导读", "points": ["要点"]}) + "\n```"
        preview = parse_preview_reply(reply, _loader)
        self.assertEqual(preview["lead"], "导读")

    def test_build_batch_prompt_contains_all_file_ids(self) -> None:
        items = [
            {"fileId": "RAW-0002", "name": "a.docx", "path": "p/a.docx", "tier_label": "标准文件", "profile": PROFILE},
            {"fileId": "RAW-0007", "name": "b.docx", "path": "p/b.docx", "tier_label": "客户定制", "profile": PROFILE},
        ]
        prompt = build_batch_preview_prompt(items)
        self.assertIn("RAW-0002", prompt)
        self.assertIn("RAW-0007", prompt)
        self.assertIn("previews", prompt)

    def test_parse_batch_splits_by_file_id(self) -> None:
        reply = json.dumps(
            {
                "previews": {
                    "RAW-0002": {"lead": "导读A", "points": ["A1"]},
                    "RAW-0007": {"lead": "导读B", "points": ["B1", "B2"]},
                }
            }
        )
        out = parse_batch_preview_reply(reply, _loader)
        self.assertEqual(set(out.keys()), {"RAW-0002", "RAW-0007"})
        self.assertEqual(out["RAW-0002"]["lead"], "导读A")
        self.assertEqual(out["RAW-0007"]["points"], ["B1", "B2"])

    def test_parse_batch_bad_one_does_not_drop_others(self) -> None:
        reply = json.dumps(
            {
                "previews": {
                    "RAW-0002": {"lead": "好的", "points": ["x"]},
                    "RAW-0003": {"lead": "", "points": []},  # 无效，应被丢弃
                }
            }
        )
        out = parse_batch_preview_reply(reply, _loader)
        self.assertIn("RAW-0002", out)
        self.assertNotIn("RAW-0003", out)

    def test_parse_batch_missing_file_absent_from_result(self) -> None:
        # 模型只回了部分 fileId：缺的不应出现在结果里（上层据此标 failed）。
        reply = json.dumps({"previews": {"RAW-0002": {"lead": "只有这个", "points": ["x"]}}})
        out = parse_batch_preview_reply(reply, _loader)
        self.assertEqual(set(out.keys()), {"RAW-0002"})

    def test_parse_batch_invalid_returns_empty(self) -> None:
        self.assertEqual(parse_batch_preview_reply("", _loader), {})
        self.assertEqual(parse_batch_preview_reply("not json", _loader), {})
        self.assertEqual(parse_batch_preview_reply(json.dumps({"nope": 1}), _loader), {})


class EvidenceSegmentTests(unittest.TestCase):
    def test_heading_sections(self) -> None:
        profile = {
            "headings": [
                {"level": 1, "title": "混塔解决方案专题"},
                {"level": 2, "title": "一、混塔结构方案"},
            ],
            "paragraphs": ["本方案针对EW5.0-202机型提供混合塔架解决方案。", "混塔由下部混凝土段和上部钢段组成。"],
        }
        segs = build_evidence_segments(
            "RAW-0476", "混塔解决方案专题.docx", "技术标/通用素材/EW5.0-202/混塔解决方案专题.docx", profile
        )
        self.assertEqual(len(segs), 2)
        self.assertTrue(all(s["segmentScope"] == "heading_section" for s in segs))
        self.assertEqual(segs[0]["title"], "混塔解决方案专题")
        self.assertEqual(segs[0]["materialId"], "RAW-0476")
        # segmentId 稳定且唯一
        self.assertEqual(len({s["segmentId"] for s in segs}), 2)
        self.assertTrue(all(s["segmentId"].startswith("tech-seg-") for s in segs))
        # 领域 marker 命中关键词，路径骨架被过滤
        self.assertIn("混塔", segs[0]["keywords"])
        self.assertNotIn("通用素材", segs[0]["keywords"])
        self.assertNotIn("docx", segs[0]["keywords"])

    def test_paragraph_overflow_when_few_headings(self) -> None:
        profile = {
            "headings": [{"level": 1, "title": "前言"}],
            "paragraphs": ["第一段。", "第二段。", "第三段。"],
        }
        segs = build_evidence_segments("RAW-1", "前言.docx", "p/前言.docx", profile)
        scopes = [s["segmentScope"] for s in segs]
        self.assertIn("heading_section", scopes)
        self.assertIn("paragraph_overflow", scopes)

    def test_file_fallback_without_headings(self) -> None:
        profile = {"headings": [], "paragraphs": ["上海电气是领先的整机制造商。"]}
        segs = build_evidence_segments("RAW-2", "概述.docx", "p/概述.docx", profile)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["segmentScope"], "file_fallback")
        self.assertEqual(segs[0]["sourcePages"], "整件/待定位")

    def test_empty_profile_yields_no_segments(self) -> None:
        self.assertEqual(build_evidence_segments("RAW-3", "扫描件.pdf", "p/扫描件.pdf", {"headings": [], "paragraphs": []}), [])
        self.assertEqual(build_evidence_segments("RAW-4", "x.docx", "p/x.docx", {"parseError": "读取失败"}), [])

    def test_segment_id_deterministic(self) -> None:
        profile = {"headings": [{"level": 1, "title": "总体方案"}], "paragraphs": ["内容。"]}
        a = build_evidence_segments("RAW-9", "x.docx", "p/x.docx", profile)
        b = build_evidence_segments("RAW-9", "x.docx", "p/x.docx", profile)
        self.assertEqual([s["segmentId"] for s in a], [s["segmentId"] for s in b])


if __name__ == "__main__":
    unittest.main()
