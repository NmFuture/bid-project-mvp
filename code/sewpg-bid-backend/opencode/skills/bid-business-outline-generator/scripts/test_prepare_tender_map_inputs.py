import unittest
import xml.etree.ElementTree as ET

import prepare_tender_map_inputs as tender


def block(block_id, text, heading_level=None, **extra):
    result = {
        "block_id": block_id,
        "type": "paragraph",
        "text": text,
        "heading_path": [],
    }
    if heading_level is not None:
        result["heading_level"] = heading_level
    result.update(extra)
    return result


def table_blocks(table_id="t-001", start=10):
    return [
        {
            "block_id": f"b-{start:04d}",
            "type": "table_cell_marker",
            "text": "实质性要求",
            "heading_path": [],
            "table_id": table_id,
            "row_index": 1,
            "col_index": 1,
        },
        {
            "block_id": f"b-{start + 1:04d}",
            "type": "table_cell_marker",
            "text": "不满足则否决投标",
            "heading_path": [],
            "table_id": table_id,
            "row_index": 1,
            "col_index": 2,
        },
        {
            "block_id": f"b-{start + 2:04d}",
            "type": "table_row",
            "text": "实质性要求 | 不满足则否决投标",
            "heading_path": [],
            "table_id": table_id,
            "row_index": 1,
        },
    ]


CHECKLIST = [
    {"title": "投标人资格要求", "scan_hints": ["资格要求", "业绩", "证明材料"]},
    {"title": "资格审查资料", "scan_hints": ["资格审查", "营业执照"]},
    {"title": "初步评审", "scan_hints": ["初步评审", "否决投标"]},
    {"title": "响应和偏差", "scan_hints": ["偏差", "响应"]},
    {"title": "实质性要求", "scan_hints": ["实质性", "否决投标"]},
]


class PrepareTenderMapInputsTest(unittest.TestCase):
    def test_heading_level_uses_only_explicit_word_heading_evidence(self):
        self.assertEqual(tender.heading_level("投标人资格要求", "Heading1"), 1)
        self.assertEqual(tender.heading_level("投标人资格要求", "Heading 2"), 2)
        self.assertEqual(tender.heading_level("投标人资格要求", "标题3"), 3)
        self.assertEqual(tender.heading_level("投标人资格要求", "", 4), 4)

        self.assertIsNone(tender.heading_level("1. 投标人资格要求", ""))
        self.assertIsNone(tender.heading_level("1.1 投标人资格要求", ""))
        self.assertIsNone(tender.heading_level("一、投标人资格要求", ""))
        self.assertIsNone(tender.heading_level("（一）资格审查资料", ""))

    def test_paragraph_outline_level_reads_word_outline_level(self):
        xml = """
        <w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:pPr><w:outlineLvl w:val="2"/></w:pPr>
          <w:r><w:t>资格审查资料</w:t></w:r>
        </w:p>
        """
        paragraph = ET.fromstring(xml)
        self.assertEqual(tender.paragraph_outline_level(paragraph), 3)

    def test_heading_scope_keeps_continuous_context_until_true_same_or_higher_heading(self):
        blocks = [
            block("b-0001", "第二章 评标办法", heading_level=1),
            block("b-0002", "投标人资格要求", heading_level=2),
            block("b-0003", "投标人应具备独立法人资格。"),
            block("b-0004", "1. 具有有效营业执照。"),
            block("b-0005", "（一）近三年类似项目业绩证明材料。"),
            block("b-0006", "1.1 这只是正文编号，不是真标题。"),
            block("b-0007", "响应和偏差", heading_level=2),
            block("b-0008", "投标人应逐条响应。"),
        ]

        zones = tender.build_zones(blocks, [], CHECKLIST)
        qualification_zone = next(
            zone for zone in zones
            if zone["matched_checklist_item"] == "投标人资格要求"
        )

        self.assertEqual(qualification_zone["zone_type"], "heading_scope")
        self.assertEqual(qualification_zone["start_block_id"], "b-0002")
        self.assertEqual(qualification_zone["end_block_id"], "b-0006")
        self.assertGreater(len(qualification_zone["block_ids"]), 1)
        self.assertIn("近三年类似项目业绩证明材料", qualification_zone["text"])
        self.assertNotIn("投标人应逐条响应", qualification_zone["text"])

    def test_conservative_window_expands_unstyled_high_value_anchor_but_not_broad_body_hit(self):
        blocks = [
            block("b-0001", "投标人资格要求"),
            block("b-0002", "投标人应具备独立法人资格。"),
            block("b-0003", "应提供营业执照、资质证书。"),
            block("b-0004", "应提供近三年业绩证明材料。"),
            block("b-0005", "其他普通正文。"),
            block("b-0006", "响应和偏差", heading_level=2),
            block("b-0007", "投标人应逐条响应。"),
        ]

        zones = tender.build_zones(blocks, [], CHECKLIST)
        qualification_zones = [
            zone for zone in zones
            if zone["matched_checklist_item"] == "投标人资格要求"
        ]

        self.assertEqual(len(qualification_zones), 1)
        self.assertEqual(qualification_zones[0]["start_block_id"], "b-0001")
        self.assertGreater(len(qualification_zones[0]["block_ids"]), 1)
        self.assertIn("营业执照", qualification_zones[0]["text"])
        self.assertNotIn("投标人应逐条响应", qualification_zones[0]["text"])

        broad_only_blocks = [
            block("b-0101", "投标人应提供近三年业绩证明材料。"),
            block("b-0102", "其他正文。"),
        ]
        broad_zones = tender.build_zones(broad_only_blocks, [], CHECKLIST)
        self.assertEqual(broad_zones, [])

    def test_table_scope_still_aggregates_whole_table_once(self):
        blocks = [
            block("b-0001", "初步评审表"),
            *table_blocks("t-001", 2),
        ]
        tables = [
            {
                "table_id": "t-001",
                "nearby_heading": "第三章 评标办法",
                "nearby_caption": "初步评审表",
                "rows": [
                    {
                        "row_index": 1,
                        "row_text": "实质性要求 | 不满足则否决投标",
                        "cells": [
                            {"col_index": 1, "text": "实质性要求"},
                            {"col_index": 2, "text": "不满足则否决投标"},
                        ],
                    }
                ],
            }
        ]

        zones = tender.build_zones(blocks, tables, CHECKLIST)
        table_zones = [zone for zone in zones if zone["zone_type"] == "table_scope"]

        self.assertEqual(len(table_zones), 1)
        self.assertEqual(table_zones[0]["table_ids"], ["t-001"])
        self.assertEqual(table_zones[0]["start_block_id"], "b-0001")
        self.assertIn("b-0002", table_zones[0]["block_ids"])
        self.assertIn("b-0003", table_zones[0]["block_ids"])
        self.assertIn("b-0004", table_zones[0]["block_ids"])

    def test_checklist_hits_include_quality_type_fields(self):
        blocks = [
            block("b-0001", "投标人资格要求"),
            block("b-0002", "详见投标人资格要求。"),
            block("b-0003", "投标人应提供近三年业绩证明材料。"),
            {
                "block_id": "b-0004",
                "type": "table_row",
                "text": "响应和偏差 | 不允许重大偏差",
                "heading_path": [],
                "table_id": "t-001",
                "row_index": 1,
            },
        ]
        tables = [
            {
                "table_id": "t-001",
                "nearby_heading": "第三章 评标办法",
                "nearby_caption": "响应和偏差表",
                "rows": [
                    {
                        "row_index": 1,
                        "row_text": "响应和偏差 | 不允许重大偏差",
                        "cells": [
                            {"col_index": 1, "text": "响应和偏差"},
                            {"col_index": 2, "text": "不允许重大偏差"},
                        ],
                    }
                ],
            }
        ]

        hits = tender.build_checklist_hits(blocks, tables, [], CHECKLIST)
        by_item = {hit["checklist_item"]: hit for hit in hits}

        qualification_hits = by_item["投标人资格要求"]["block_hits"]
        title_hit = next(hit for hit in qualification_hits if hit["block_id"] == "b-0001")
        self.assertTrue(title_hit["title_hit"])
        self.assertTrue(title_hit["body_hit"])
        self.assertFalse(title_hit["table_content_hit"])
        self.assertFalse(title_hit["cross_reference_hit"])

        cross_ref_hit = next(hit for hit in qualification_hits if hit["block_id"] == "b-0002")
        self.assertTrue(cross_ref_hit["cross_reference_hit"])

        broad_hit = next(hit for hit in qualification_hits if hit["block_id"] == "b-0003")
        self.assertFalse(broad_hit["title_hit"])
        self.assertTrue(broad_hit["body_hit"])
        self.assertTrue(broad_hit["broad_term_hit"])

        table_hit = by_item["响应和偏差"]["table_hits"][0]
        self.assertTrue(table_hit["title_hit"])
        self.assertTrue(table_hit["table_caption_hit"])
        self.assertTrue(table_hit["table_content_hit"])
        self.assertFalse(table_hit["body_hit"])


if __name__ == "__main__":
    unittest.main()
