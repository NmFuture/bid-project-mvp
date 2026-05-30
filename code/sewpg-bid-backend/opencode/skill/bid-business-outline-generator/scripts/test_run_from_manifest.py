import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_from_manifest as runner


class BusinessOutlineRunnerMatchingTest(unittest.TestCase):
    def test_short_generic_candidate_title_does_not_match_unrelated_history_title(self):
        candidates = [
            {
                "title": "用",
                "rawText": "科技创新及“自主可控”技术应用：按照以下自主可控技术研发和推广工作开展情况，进行评分。",
            },
            {
                "title": "文件",
                "rawText": "1.1.5 技术资料：指各种纸质及电子载体的相关文件。",
            },
        ]

        self.assertIsNone(runner.first_matching_candidate("1.5 投标专用章效力说明 26", candidates))
        self.assertIsNone(runner.first_matching_candidate("7.2 投标单位股权结构说明及相关证明文件", candidates))

    def test_specific_candidate_title_can_match_history_title(self):
        candidates = [
            {
                "title": "投标单位股权结构说明及相关证明文件",
                "rawText": "投标单位股权结构说明及相关证明文件(附件7B)。",
            },
        ]

        matched = runner.first_matching_candidate("7.2 投标单位股权结构说明及相关证明文件 117", candidates)

        self.assertIsNotNone(matched)
        self.assertEqual(matched["rawText"], "投标单位股权结构说明及相关证明文件(附件7B)。")

    def test_source_ref_marks_tender_basis_for_frontend_focus(self):
        ref = runner.source_ref(
            {
                "fileId": "TEN-1",
                "fileName": "招标文件.docx",
                "paragraphIndex": 12,
                "rawText": "附件7B 投标单位股权结构说明及相关证明文件。",
            }
        )

        self.assertEqual(ref["type"], "tender")
        self.assertEqual(ref["role"], "basis")
        self.assertEqual(ref["searchText"], "附件7B 投标单位股权结构说明及相关证明文件。")
        self.assertEqual(ref["basisText"], "附件7B 投标单位股权结构说明及相关证明文件。")

    def test_outline_sections_preserve_fourth_level_template_candidates(self):
        template_outline = [
            {"number": "7", "title": "资格证明文件", "level": 1, "rawText": "7 资格证明文件"},
            {"number": "7.1", "title": "资格证明材料", "level": 2, "rawText": "7.1 资格证明材料"},
            {"number": "7.1.1", "title": "认证证书", "level": 3, "rawText": "7.1.1 认证证书"},
            {"number": "7.1.1.1", "title": "EW10.0-220 设计认证证书", "level": 4, "rawText": "7.1.1.1 EW10.0-220 设计认证证书"},
        ]

        sections = runner.outline_sections_from_template(template_outline, [])

        self.assertEqual(sections[0]["number"], "7")
        child = sections[0]["children"][0]
        grandchild = child["children"][0]
        fourth_level = grandchild["children"][0]
        self.assertEqual(fourth_level["number"], "7.1.1.1")
        self.assertEqual(fourth_level["level"], 4)
        self.assertEqual(fourth_level["title"], "EW10.0-220 设计认证证书")

    def test_evidence_pipeline_uses_current_tender_evidence_without_changing_history_structure(self):
        template_outline = [
            {"number": "9", "title": "其他内容", "level": 1, "rawText": "9 其他内容"},
            {"number": "9.1", "title": "保密承诺书", "level": 2, "rawText": "9.1 保密承诺书"},
            {"number": "9.2", "title": "历史保留但当前无依据", "level": 2, "rawText": "9.2 历史保留但当前无依据"},
        ]
        tender_map_inputs = {
            "document_name": "招标文件.docx",
            "source_path": "C:/work/招标文件.docx",
            "blocks": [
                {"block_id": "b-001", "type": "paragraph", "text": "目录", "heading_path": ["目录"]},
                {"block_id": "b-002", "type": "paragraph", "text": "保密承诺书 ........ 88", "heading_path": ["目录"]},
                {"block_id": "b-003", "type": "paragraph", "text": "第六章 投标文件格式", "heading_path": ["第六章 投标文件格式"], "heading_level": 1},
                {"block_id": "b-004", "type": "paragraph", "text": "附件9 保密承诺书", "heading_path": ["第六章 投标文件格式"], "heading_level": 2},
            ],
            "tables": [],
            "zones": [],
        }
        sections = runner.outline_sections_from_template(template_outline, [])

        summary = runner.enrich_outline_with_current_evidence(sections, tender_map_inputs)

        self.assertEqual(summary["outline_section_count"], 3)
        self.assertEqual(len(sections[0]["children"]), 2)
        current = sections[0]["children"][0]
        fallback = sections[0]["children"][1]
        self.assertEqual(current["source_text"], "附件9 保密承诺书")
        self.assertEqual(current["required_status"], "必要")
        self.assertEqual(current["evidence_scope"], "format_area")
        self.assertEqual(current["source_refs"][0]["type"], "tender")
        self.assertEqual(current["source_refs"][0]["source_ref"]["block_id"], "b-004")
        self.assertEqual(fallback["source_text"], "9.2 历史保留但当前无依据")
        self.assertEqual(fallback["required_status"], "待确认")
        self.assertEqual(fallback["evidence_scope"], "history_fallback")
        self.assertIn("未在当前招标文件找到强证据", fallback["reason"])


if __name__ == "__main__":
    unittest.main()
