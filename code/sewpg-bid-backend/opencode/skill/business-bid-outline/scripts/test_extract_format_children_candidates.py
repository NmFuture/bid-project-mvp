import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("extract_format_children_candidates.py")


def block(block_id, block_type, text, **extra):
    result = {
        "block_id": block_id,
        "type": block_type,
        "text": text,
        "heading_path": extra.pop("heading_path", ["第六章 投标文件格式", "附件7 资格证明文件", "附件7A 商务部分摘要表"]),
    }
    result.update(extra)
    return result


class ExtractFormatChildrenCandidatesTest(unittest.TestCase):
    def run_script(self, data):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_path = tmpdir / "tender_map_inputs.json"
            output_path = tmpdir / "children_candidates.json"
            input_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(input_path),
                    "--parent-source-text",
                    "附件7A 商务部分摘要表",
                    "--next-sibling-source-text",
                    "附件7B 投标函格式",
                    "--output",
                    str(output_path),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(output_path.read_text(encoding="utf-8"))

    def sample_data(self):
        rows = []
        blocks = [
            block("b-0001", "paragraph", "第六章 投标文件格式", heading_path=["第六章 投标文件格式"], heading_level=1),
            block("b-0002", "paragraph", "附件7 资格证明文件", heading_path=["第六章 投标文件格式", "附件7 资格证明文件"], heading_level=2),
            block("b-0003", "paragraph", "附件7A 商务部分摘要表", heading_level=3),
            block("b-0004", "paragraph", "A 投标价格总表"),
            block("b-0005", "paragraph", "B 设备分项报价"),
            block("b-0006", "paragraph", "C 专用工具"),
            block("b-0007", "paragraph", "D 技术服务"),
            block("b-0008", "paragraph", "D-1 除质保期服务外的技术指导服务费"),
            block("b-0009", "paragraph", "D-2 质保期内服务费"),
            block("b-0010", "paragraph", "7A表 商务部分摘要表"),
            block("b-0011", "paragraph", "保密承诺书"),
        ]
        row_defs = [
            ["企业资质", "营业执照", "后附企业法人营业执照副本复印件"],
            ["企业资质", "许可证", "后附资质证书、生产许可证复印件"],
            ["认证体系", "质量认证体系", "(认证机关、有效期、证书编号)", "后附认证体系证书复印件。"],
            ["组织能力", "企业组织机构", "后附企业组织机构图、企业规模、服务能力简介"],
        ]
        next_id = 12
        for row_index, cells in enumerate(row_defs, start=1):
            row_text = " | ".join(cells)
            row = {"row_index": row_index, "row_text": row_text, "cells": []}
            for col_index, text in enumerate(cells, start=1):
                row["cells"].append({"col_index": col_index, "text": text})
                blocks.append(block(f"b-{next_id:04d}", "table_cell_marker", text, table_id="t-001", row_index=row_index, col_index=col_index))
                next_id += 1
            rows.append(row)
            blocks.append(block(f"b-{next_id:04d}", "table_row", row_text, table_id="t-001", row_index=row_index))
            next_id += 1
        blocks.extend([
            block(f"b-{next_id:04d}", "paragraph", "投标人应提供近三年类似项目业绩证明材料。"),
            block(f"b-{next_id + 1:04d}", "paragraph", "报价唯一，否则否决投标。"),
            block(f"b-{next_id + 2:04d}", "paragraph", "投标文件应签字盖章。"),
            block(f"b-{next_id + 3:04d}", "paragraph", "附件7B 投标函格式", heading_path=["第六章 投标文件格式", "附件7 资格证明文件", "附件7B 投标函格式"], heading_level=3),
        ])
        return {
            "document_name": "generic-tender.docx",
            "blocks": blocks,
            "tables": [
                {
                    "table_id": "t-001",
                    "nearby_heading": "第六章 投标文件格式 / 附件7 资格证明文件 / 附件7A 商务部分摘要表",
                    "nearby_caption": "7A表 商务部分摘要表",
                    "rows": rows,
                }
            ],
            "zones": [],
            "expert_checklist_hits": [],
        }

    def test_extracts_generalized_candidate_types_inside_full_parent_scope(self):
        output = self.run_script(self.sample_data())
        self.assertEqual(output["body_scope"]["start_block_id"], "b-0003")
        self.assertNotEqual(output["body_scope"]["end_block_id"], output["body_scope"]["start_block_id"])
        self.assertNotIn("附件7B 投标函格式", output["body_scope"]["text"])

        candidates = output["candidates"]
        by_text = {candidate["source_text"]: candidate for candidate in candidates}

        for text in ["A 投标价格总表", "B 设备分项报价", "C 专用工具", "D 技术服务"]:
            self.assertEqual(by_text[text]["anchor_type"], "explicit_numbered_heading")

        self.assertEqual(by_text["D-1 除质保期服务外的技术指导服务费"]["level_hint"], 3)
        self.assertEqual(by_text["D-2 质保期内服务费"]["level_hint"], 3)
        self.assertEqual(by_text["7A表 商务部分摘要表"]["anchor_type"], "table_title")
        self.assertEqual(by_text["保密承诺书"]["anchor_type"], "style_heading")

        for text in [
            "后附企业法人营业执照副本复印件",
            "后附资质证书、生产许可证复印件",
            "后附认证体系证书复印件。",
            "后附企业组织机构图、企业规模、服务能力简介",
        ]:
            candidate = by_text[text]
            self.assertEqual(candidate["anchor_type"], "table_attached_material")
            self.assertEqual(candidate["table_id"], "t-001")
            self.assertIn("row_text", candidate)
            self.assertIn(text, candidate["row_text"])
            self.assertIn("col_index", candidate)

        self.assertEqual(by_text["投标人应提供近三年类似项目业绩证明材料。"].get("anchor_type"), "paragraph_attached_material")

        for rule_text in ["报价唯一，否则否决投标。", "投标文件应签字盖章。"]:
            if rule_text in by_text:
                self.assertEqual(by_text[rule_text]["anchor_type"], "rule_like")
                self.assertEqual(by_text[rule_text]["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
