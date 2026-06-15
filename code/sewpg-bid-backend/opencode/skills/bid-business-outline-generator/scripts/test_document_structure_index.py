import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import document_structure_index as indexer


SCRIPT = Path(__file__).with_name("document_structure_index.py")


def block(block_id, text, **extra):
    item = {
        "block_id": block_id,
        "type": extra.pop("type", "paragraph"),
        "text": text,
        "heading_path": extra.pop("heading_path", []),
    }
    item.update(extra)
    return item


class DocumentStructureIndexTest(unittest.TestCase):
    def test_builds_stable_index_with_toc_format_high_value_and_table_cells(self):
        tender = {
            "document_name": "招标文件.docx",
            "source_path": "C:/work/招标文件.docx",
            "blocks": [
                block("b-001", "目 录", heading_path=["目录"]),
                block("b-002", "附件7A 商务部分摘要表 ........ 56", heading_path=["目录"]),
                block("b-003", "第三章 评标办法", heading_path=["第三章 评标办法"], heading_level=1),
                block("b-004", "商务评分标准：投标人须提供业绩证明材料。", heading_path=["第三章 评标办法", "商务评分"]),
                block("b-005", "第六章 投标文件格式", heading_path=["第六章 投标文件格式"], heading_level=1),
                block("b-006", "附件7A 商务部分摘要表", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-007", "后附企业组织机构图、企业规模、服务能力简介等", type="table_cell_marker", table_id="t-001", row_index=1, col_index=2, heading_path=["第六章 投标文件格式", "附件7A 商务部分摘要表"]),
            ],
            "tables": [{
                "table_id": "t-001",
                "nearby_heading": "第六章 投标文件格式 / 附件7A 商务部分摘要表",
                "rows": [{"row_index": 1, "row_text": "材料 | 后附企业组织机构图、企业规模、服务能力简介等", "cells": [
                    {"col_index": 1, "text": "材料"},
                    {"col_index": 2, "text": "后附企业组织机构图、企业规模、服务能力简介等"},
                ]}],
            }],
            "zones": [{"zone_id": "z-001", "text": "投标文件格式区域", "heading_path": ["第六章 投标文件格式"]}],
        }

        result = indexer.build_document_structure_index(tender)
        blocks = result["blocks"]

        self.assertEqual([item["order"] for item in blocks], list(range(len(blocks))))
        self.assertTrue(blocks[1]["is_toc"])
        self.assertEqual(blocks[6]["source_kind"], "table_cell")
        self.assertEqual(blocks[6]["source_ref"]["table_id"], "t-001")
        self.assertEqual(blocks[6]["source_ref"]["row_index"], 1)
        self.assertEqual(blocks[6]["source_ref"]["col_index"], 2)
        self.assertTrue(any(r["start_order"] <= blocks[5]["order"] <= r["end_order"] for r in result["format_ranges"]))
        self.assertFalse(any(r["start_order"] <= blocks[3]["order"] <= r["end_order"] for r in result["format_ranges"]))
        high_value_types = {r["category"] for r in result["high_value_ranges"]}
        self.assertIn("scoring_response", high_value_types)
        self.assertGreaterEqual(result["summary"]["toc_blocks"], 2)
        self.assertGreaterEqual(result["summary"]["table_cells"], 1)

    def test_cli_writes_summary_and_json(self):
        tender = {"blocks": [block("b-001", "第六章 投标文件格式", heading_path=["第六章 投标文件格式"])]}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_path = tmpdir / "tender_map_inputs.json"
            output_path = tmpdir / "document_structure_index.json"
            input_path.write_text(json.dumps(tender, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(input_path), "--output", str(output_path)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("elapsed_seconds", payload["summary"])
            self.assertIn("blocks", result.stdout)


if __name__ == "__main__":
    unittest.main()
