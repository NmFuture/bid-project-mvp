import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "generate_outline.py"
RESOLVER = Path(__file__).with_name("resolve_source_text_candidates.py")


def load_generate_outline():
    spec = importlib.util.spec_from_file_location("generate_outline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenerateOutlineCandidatesTest(unittest.TestCase):
    def make_history(self):
        return {
            "document_name": "历史商务标.docx",
            "outline_source": {"source_text": "历史目录", "source_type": "history_bid_toc", "confidence": "high"},
            "outline_candidates": [
                {"title_hint": "三、投标函、法定代表人身份证明、授权委托书", "level": 1, "source_text": "附件1 投标函 89"},
                {"title_hint": "投标函", "level": 2, "source_text": "附件1 投标函 89"},
                {"title_hint": "法定代表人身份证明", "level": 2, "source_text": "附件1 投标函 89"},
                {"title_hint": "九、投标人证明其是合格投标人并有资格履行合同的证明文件", "level": 1, "source_text": "附件7 资格证明文件"},
                {"title_hint": "商务部分摘要表", "level": 2, "source_text": "商务部分摘要表 104"},
                {"title_hint": "企业组织机构图、企业规模、服务能力简介", "level": 3, "source_text": "商务部分摘要表 104"},
            ],
        }

    def make_tender(self):
        return {
            "document_name": "招标文件.docx",
            "blocks": [
                {"block_id": "b-001", "type": "paragraph", "text": "投标报价应包含投标函附录中列明的所有费用。", "heading_path": ["第二章 投标人须知", "投标报价"]},
                {"block_id": "b-002", "type": "paragraph", "text": "附件1 投标函", "heading_path": ["第六章 投标文件格式"], "heading_level": 2},
                {"block_id": "b-003", "type": "paragraph", "text": "1A 投标函", "heading_path": ["第六章 投标文件格式", "附件1 投标函"]},
                {"block_id": "b-004", "type": "paragraph", "text": "1B 法定代表人身份证明", "heading_path": ["第六章 投标文件格式", "附件1 投标函"]},
                {"block_id": "b-005", "type": "paragraph", "text": "附件7 资格证明文件", "heading_path": ["第六章 投标文件格式"], "heading_level": 2},
                {"block_id": "b-006", "type": "paragraph", "text": "附件7A 商务部分摘要表", "heading_path": ["第六章 投标文件格式", "附件7 资格证明文件"]},
                {"block_id": "b-007", "type": "table_cell_marker", "text": "后附企业组织机构图、企业规模、服务能力简介等", "table_id": "t-001", "row_index": 1, "col_index": 2, "heading_path": ["第六章 投标文件格式", "附件7 资格证明文件"]},
            ],
            "tables": [{
                "table_id": "t-001",
                "nearby_heading": "附件7A 商务部分摘要表",
                "rows": [{"row_index": 1, "row_text": "企业组织机构图、企业规模、服务能力简介 | 后附企业组织机构图、企业规模、服务能力简介等", "cells": [
                    {"col_index": 1, "text": "企业组织机构图、企业规模、服务能力简介"},
                    {"col_index": 2, "text": "后附企业组织机构图、企业规模、服务能力简介等"},
                ]}],
            }],
            "zones": [],
        }

    def run_resolver(self, tmpdir, tender_path, outline_path):
        output_path = tmpdir / "source_text_candidates.json"
        result = subprocess.run(
            [sys.executable, str(RESOLVER), str(tender_path), str(outline_path), "--output", str(output_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return output_path

    def test_generate_outline_consumes_source_text_candidates(self):
        module = load_generate_outline()
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path = tmpdir / "history_bid_outline_inputs.json"
            tender_path = tmpdir / "tender_map_inputs.json"
            draft_path = tmpdir / "outline.draft.json"
            output_path = tmpdir / "outline.json"
            history_path.write_text(json.dumps(self.make_history(), ensure_ascii=False), encoding="utf-8")
            tender_path.write_text(json.dumps(self.make_tender(), ensure_ascii=False), encoding="utf-8")

            history = module.load_json(history_path)
            draft_sections = [module.convert_node(node, [index], lambda title, parent_title="": (module.compact(node["candidate"].get("source_text", "")), False), [], "") for index, node in enumerate(module.build_history_tree(history["outline_candidates"]), start=1)]
            draft_path.write_text(json.dumps({"sections": draft_sections}, ensure_ascii=False), encoding="utf-8")
            candidates_path = self.run_resolver(tmpdir, tender_path, draft_path)

            outline = module.generate_outline(history_path, tender_path, None, output_path, candidates_path)
            by_id = {}
            def walk(items):
                for item in items:
                    by_id[item["id"]] = item
                    walk(item.get("children", []))
            walk(outline["sections"])

            self.assertEqual(by_id["sec-001-001"]["source_text"], "1A 投标函")
            self.assertEqual(by_id["sec-002-001-001"]["source_text"], "后附企业组织机构图、企业规模、服务能力简介等")
            self.assertNotEqual(by_id["sec-001-001"]["source_text"], "附件1 投标函 89")
            self.assertFalse(any(item["source_text"].endswith(" 89") for item in by_id.values()))

    def test_choose_candidate_prefers_format_heading_and_short_table_cell(self):
        module = load_generate_outline()
        candidates_by_id = {
            "sec-top": {
                "candidates": [
                    {"scope": "format_area", "score": 1.0, "source_text": "投标价格表(不含价格)；", "source_type": "block"},
                    {"scope": "format_area", "score": 1.0, "source_text": "附件2 投标价格表", "source_type": "block"},
                ]
            },
            "sec-response": {
                "candidates": [
                    {"scope": "format_area", "score": 1.0, "source_text": "商务文件：除随本投标文件提交的商务条件及合同条款偏差表列明的偏差外，其他均完全响应招标文件要求。", "source_type": "block"},
                    {"scope": "format_area", "score": 1.0, "source_text": "附件4 商务条款偏差表", "source_type": "block"},
                ]
            },
            "sec-child": {
                "candidates": [
                    {"scope": "parent_context", "score": 1.0, "source_text": "企业规模生产能力 | 企业总人数及技术人员数量 | 后附企业组织机构图、企业规模、服务能力简介等", "source_type": "table_row"},
                    {"scope": "parent_context", "score": 1.0, "source_text": "后附企业组织机构图、企业规模、服务能力简介等", "source_type": "table_cell"},
                ]
            },
        }

        top_source, top_matched, top_scope = module.choose_candidate("sec-top", candidates_by_id)
        response_source, response_matched, response_scope = module.choose_candidate("sec-response", candidates_by_id)
        child_source, child_matched, child_scope = module.choose_candidate("sec-child", candidates_by_id)

        self.assertTrue(top_matched)
        self.assertEqual(top_scope, "format_area")
        self.assertEqual(top_source, "附件2 投标价格表")
        self.assertTrue(response_matched)
        self.assertEqual(response_scope, "format_area")
        self.assertEqual(response_source, "附件4 商务条款偏差表")
        self.assertTrue(child_matched)
        self.assertEqual(child_scope, "parent_context")
        self.assertEqual(child_source, "后附企业组织机构图、企业规模、服务能力简介等")


if __name__ == "__main__":
    unittest.main()
