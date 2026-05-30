import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("resolve_source_text_candidates.py")


def block(block_id, text, **extra):
    item = {
        "block_id": block_id,
        "type": extra.pop("type", "paragraph"),
        "text": text,
        "heading_path": extra.pop("heading_path", []),
    }
    item.update(extra)
    return item


class ResolveSourceTextCandidatesTest(unittest.TestCase):
    def run_resolver(self, tender, outline):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            tender_path = tmpdir / "tender_map_inputs.json"
            outline_path = tmpdir / "outline.json"
            output_path = tmpdir / "source_text_candidates.json"
            tender_path.write_text(json.dumps(tender, ensure_ascii=False), encoding="utf-8")
            outline_path.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(tender_path), str(outline_path), "--output", str(output_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(output_path.read_text(encoding="utf-8"))

    def by_id(self, result):
        return {item["id"]: item for item in result["items"]}

    def test_resolves_format_area_parent_and_child_candidates(self):
        tender = {
            "blocks": [
                block("b-001", "第六章 投标文件格式", heading_path=["第六章 投标文件格式"]),
                block("b-002", "附件7 投标人证明其是合格投标人并有资格履行合同的证明文件", heading_path=["第六章 投标文件格式"]),
                block("b-003", "附件7A 商务部分摘要表", heading_path=["第六章 投标文件格式"]),
                block("b-004", "后附企业组织机构图、企业规模、服务能力简介等", heading_path=["第六章 投标文件格式"]),
                block("b-005", "投标单位股权结构说明及相关证明文件(附件7B)", heading_path=["第六章 投标文件格式"]),
                block("b-006", "保密承诺书", heading_path=["第六章 投标文件格式"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {
            "sections": [
                {"id": "sec-009", "title": "投标人证明其是合格投标人并有资格履行合同的证明文件", "level": 1, "source_text": "七、投标人证明其是合格投标人并有资格履行合同的证明文件", "children": [
                    {"id": "sec-009-001", "title": "商务部分摘要表", "level": 2, "source_text": "7.1 商务部分摘要表", "children": [
                        {"id": "sec-009-001-004", "title": "企业组织机构图、企业规模、服务能力简介", "level": 3, "source_text": "7.1.4 企业组织机构图、企业规模、服务能力简介", "children": []}
                    ]},
                    {"id": "sec-009-002", "title": "投标单位股权结构说明及相关证明文件", "level": 2, "source_text": "7.2 投标单位股权结构说明及相关证明文件", "children": []}
                ]},
                {"id": "sec-011", "title": "投标人需要说明的其他内容", "level": 1, "source_text": "九、投标人需要说明的其他内容", "children": [
                    {"id": "sec-011-002", "title": "保密承诺书", "level": 2, "source_text": "9.2 保密承诺书", "children": []}
                ]},
            ]
        }
        result = self.run_resolver(tender, outline)
        by_id = self.by_id(result)

        self.assertTrue(any("附件7A 商务部分摘要表" in c["source_text"] for c in by_id["sec-009-001"]["candidates"]))
        self.assertTrue(any("后附企业组织机构图、企业规模、服务能力简介等" in c["source_text"] for c in by_id["sec-009-001-004"]["candidates"]))
        self.assertTrue(any("投标单位股权结构说明及相关证明文件(附件7B)" in c["source_text"] for c in by_id["sec-009-002"]["candidates"]))
        self.assertTrue(any("保密承诺书" == c["source_text"] for c in by_id["sec-011-002"]["candidates"]))
        self.assertIn(by_id["sec-009-001-004"]["candidates"][0]["scope"], {"parent_context", "format_area"})

    def test_excludes_toc_lines_and_zone_text_from_candidates(self):
        tender = {
            "blocks": [
                block("b-001", "目 录", heading_path=["目录"]),
                block("b-002", "商务部分摘要表 ........ 12", heading_path=["目录"]),
                block("b-003", "附件7A 商务部分摘要表", heading_path=["第六章 投标文件格式"]),
            ],
            "tables": [],
            "zones": [
                {"zone_id": "z-001", "text": "商务部分摘要表\n这里是一整段很长的格式章节 zone 文本，不应直接作为 source_text 候选。" * 20, "heading_path": ["第六章 投标文件格式"]}
            ],
        }
        outline = {"sections": [{"id": "sec-1", "title": "商务部分摘要表", "source_text": "7.1 商务部分摘要表", "children": []}]}
        result = self.run_resolver(tender, outline)
        candidates = self.by_id(result)["sec-1"]["candidates"]
        texts = [candidate["source_text"] for candidate in candidates]

        self.assertNotIn("商务部分摘要表 ........ 12", texts)
        self.assertFalse(any(candidate.get("source_type") == "zone" for candidate in candidates))
        self.assertTrue(any(text == "附件7A 商务部分摘要表" for text in texts))
        self.assertNotEqual(candidates[0]["source_text"], "商务部分摘要表 ........ 12")
        self.assertIn(candidates[0]["scope"], {"format_area", "parent_context"})

    def test_layered_retrieval_reports_current_source_refs_and_history_fallback(self):
        tender = {
            "document_name": "招标文件.docx",
            "source_path": "C:/work/招标文件.docx",
            "blocks": [
                block("b-001", "目录", heading_path=["目录"]),
                block("b-002", "保密承诺书 ........ 88", heading_path=["目录"]),
                block("b-003", "第二章 投标人须知", heading_path=["第二章 投标人须知"], heading_level=1),
                block("b-004", "投标文件包括保密承诺书，详见第六章附件9。", heading_path=["第二章 投标人须知", "投标文件组成"]),
                block("b-005", "第六章 投标文件格式", heading_path=["第六章 投标文件格式"], heading_level=1),
                block("b-006", "附件9 保密承诺书", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-007", "投标人承诺对招标文件及项目资料承担保密义务。", heading_path=["第六章 投标文件格式", "附件9 保密承诺书"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [
            {"id": "sec-1", "title": "保密承诺书", "source_text": "9.2 保密承诺书", "children": []},
            {"id": "sec-2", "title": "历史保留但当前无依据", "source_text": "9.99 历史保留但当前无依据", "children": []},
        ]}
        result = self.run_resolver(tender, outline)
        by_id = self.by_id(result)

        first = by_id["sec-1"]["candidates"][0]
        self.assertEqual(first["source_text"], "附件9 保密承诺书")
        self.assertEqual(first["scope"], "format_area")
        self.assertIn("source_ref", first)
        self.assertEqual(first["source_ref"]["source_file"], "招标文件.docx")
        self.assertEqual(first["source_ref"]["block_id"], "b-006")
        self.assertEqual(first["source_kind"], "paragraph")
        fallback = by_id["sec-2"]["candidates"][0]
        self.assertEqual(fallback["scope"], "history_fallback")
        self.assertEqual(fallback["source_text"], "9.99 历史保留但当前无依据")
        self.assertEqual(fallback["confidence"], "low")

    def test_scoring_appendix_is_high_value_not_format_area(self):
        tender = {
            "blocks": [
                block("b-001", "第三章 评标办法", heading_path=["第三章 评标办法"]),
                block("b-002", "附表 商务评分标准", heading_path=["第三章 评标办法", "商务评分"]),
                block("b-003", "投标人业绩证明材料", heading_path=["第三章 评标办法", "商务评分"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-1", "title": "投标人业绩证明材料", "source_text": "业绩证明材料", "children": []}]}
        result = self.run_resolver(tender, outline)
        candidate = self.by_id(result)["sec-1"]["candidates"][0]

        self.assertEqual(candidate["source_text"], "投标人业绩证明材料")
        self.assertEqual(candidate["scope"], "high_value_area")
        format_area_texts = [area["source_text"] for area in result["format_areas"]]
        self.assertNotIn("附表 商务评分标准", format_area_texts)

    def test_child_prefers_table_cell_inside_parent_scope_before_global_match(self):
        tender = {
            "blocks": [
                block("b-001", "第六章 投标文件格式", heading_path=["第六章 投标文件格式"]),
                block("b-002", "附件7A 商务部分摘要表", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-003", "企业组织机构图、企业规模、服务能力简介", type="table_cell_marker", table_id="t-001", row_index=1, col_index=1, heading_path=["第六章 投标文件格式"]),
                block("b-004", "后附企业组织机构图、企业规模、服务能力简介等", type="table_cell_marker", table_id="t-001", row_index=1, col_index=2, heading_path=["第六章 投标文件格式"]),
                block("b-005", "附件7B 股权结构说明", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-006", "评分项：企业组织机构图、企业规模、服务能力简介，最高得分。", heading_path=["第三章 评标办法", "商务评分"]),
            ],
            "tables": [{
                "table_id": "t-001",
                "nearby_heading": "第六章 投标文件格式 / 附件7A 商务部分摘要表",
                "rows": [{"row_index": 1, "row_text": "企业组织机构图、企业规模、服务能力简介 | 后附企业组织机构图、企业规模、服务能力简介等", "cells": [
                    {"col_index": 1, "text": "企业组织机构图、企业规模、服务能力简介"},
                    {"col_index": 2, "text": "后附企业组织机构图、企业规模、服务能力简介等"},
                ]}],
            }],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-parent", "title": "商务部分摘要表", "source_text": "7.1 商务部分摘要表", "children": [
            {"id": "sec-child", "title": "企业组织机构图、企业规模、服务能力简介", "source_text": "7.1.4 企业组织机构图、企业规模、服务能力简介", "children": []}
        ]}]}
        result = self.run_resolver(tender, outline)
        candidates = self.by_id(result)["sec-child"]["candidates"]

        self.assertEqual(candidates[0]["scope"], "parent_context")
        self.assertIn("后附企业组织机构图、企业规模、服务能力简介等", candidates[0]["source_text"])
        self.assertNotEqual(candidates[0]["source_text"], "附件7A 商务部分摘要表")

    def test_parent_scope_stops_before_next_sibling_and_then_degrades_to_high_value(self):
        tender = {
            "blocks": [
                block("b-001", "第六章 投标文件格式", heading_path=["第六章 投标文件格式"]),
                block("b-002", "附件7A 商务部分摘要表", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-003", "填写投标人基本信息", heading_path=["第六章 投标文件格式"]),
                block("b-004", "附件7B 股权结构说明", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-005", "股权结构证明材料", heading_path=["第六章 投标文件格式"]),
                block("b-006", "投标人须提交近年财务状况证明材料", heading_path=["第三章 资格审查"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-parent", "title": "商务部分摘要表", "source_text": "7.1 商务部分摘要表", "children": [
            {"id": "sec-child", "title": "近年财务状况证明材料", "source_text": "财务状况证明材料", "children": []}
        ]}]}
        result = self.run_resolver(tender, outline)
        candidates = self.by_id(result)["sec-child"]["candidates"]
        texts = [candidate["source_text"] for candidate in candidates]

        self.assertNotIn("股权结构证明材料", texts)
        self.assertEqual(candidates[0]["source_text"], "投标人须提交近年财务状况证明材料")
        self.assertEqual(candidates[0]["scope"], "high_value_area")

    def test_parent_child_uses_later_format_body_anchor_over_early_reference(self):
        tender = {
            "blocks": [
                block("b-001", "(6) 投标人证明其是合格投标人并有资格履行合同的证明文件(附件7)。", heading_path=["第二章 投标人须知"]),
                block("b-002", "商务部分：评标办法前附表", heading_path=["第三章 评标办法", "商务评分"]),
                block("b-003", "附表3：商务部分评审评分标准", type="table_cell_marker", heading_path=["第三章 评标办法", "商务评分"]),
                block("b-004", "附表1：符合性审查标准表", heading_path=["第三章 评标办法", "符合性审查"]),
                block("b-005", "1. 商务部分摘要表（附件7A）。", heading_path=["附件7 资格证明文件"]),
                block("b-006", "2. 投标单位股权结构说明及相关证明文件(附件7B)。", heading_path=["附件7 资格证明文件"]),
                block("b-007", "附件7A 商务部分摘要表", heading_path=["附件7 资格证明文件"]),
                block("b-008", "企业组织机构图、企业规模、服务能力简介", type="table_cell_marker", table_id="t-001", row_index=1, col_index=1, heading_path=["附件7 资格证明文件"]),
                block("b-009", "后附企业组织机构图、企业规模、服务能力简介等", type="table_cell_marker", table_id="t-001", row_index=1, col_index=2, heading_path=["附件7 资格证明文件"]),
                block("b-010", "附件7B", heading_path=["附件7 资格证明文件"]),
            ],
            "tables": [{
                "table_id": "t-001",
                "nearby_heading": "第六章 投标文件格式 / 附件7A 商务部分摘要表",
                "rows": [{"row_index": 1, "row_text": "企业组织机构图、企业规模、服务能力简介 | 后附企业组织机构图、企业规模、服务能力简介等", "cells": [
                    {"col_index": 1, "text": "企业组织机构图、企业规模、服务能力简介"},
                    {"col_index": 2, "text": "后附企业组织机构图、企业规模、服务能力简介等"},
                ]}],
            }],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-parent", "title": "投标人证明其是合格投标人并有资格履行合同的证明文件", "source_text": "投标人证明其是合格投标人并有资格履行合同的证明文件", "children": [
            {"id": "sec-child", "title": "商务部分摘要表", "source_text": "7.1 商务部分摘要表", "children": [
                {"id": "sec-grandchild", "title": "企业组织机构图、企业规模、服务能力简介", "source_text": "7.1.4 企业组织机构图、企业规模、服务能力简介", "children": []}
            ]}
        ]}]}
        result = self.run_resolver(tender, outline)
        by_id = self.by_id(result)

        self.assertEqual(by_id["sec-child"]["candidates"][0]["source_text"], "1. 商务部分摘要表（附件7A）。")
        self.assertNotIn("商务部分评审评分标准", by_id["sec-child"]["candidates"][0]["source_text"])
        self.assertEqual(by_id["sec-grandchild"]["candidates"][0]["scope"], "parent_context")
        self.assertIn("后附企业组织机构图、企业规模、服务能力简介等", by_id["sec-grandchild"]["candidates"][0]["source_text"])

    def test_format_area_excludes_cross_references_outside_format_body(self):
        tender = {
            "blocks": [
                block("b-001", "3.1.1 商务文件包括履约保证函格式承诺书，见第六章附件6。", heading_path=["第二章 投标人须知", "投标文件的组成"]),
                block("b-002", "附表3：商务部分评审评分标准", heading_path=["第三章 评标办法", "商务评分"]),
                block("b-003", "附件6 履约保证函格式承诺书", heading_path=["第六章 投标文件格式"]),
                block("b-004", "投标人承诺按招标文件要求提交履约保证金。", heading_path=["第六章 投标文件格式", "附件6 履约保证函格式承诺书"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-1", "title": "履约保证函格式承诺书", "source_text": "履约保证函格式承诺书", "children": []}]}
        result = self.run_resolver(tender, outline)
        format_area_texts = [area["source_text"] for area in result["format_areas"]]

        self.assertNotIn("3.1.1 商务文件包括履约保证函格式承诺书，见第六章附件6。", format_area_texts)
        self.assertNotIn("附表3：商务部分评审评分标准", format_area_texts)
        self.assertIn("附件6 履约保证函格式承诺书", format_area_texts)

    def test_tender_letter_child_prefers_format_block_over_bid_price_clause(self):
        tender = {
            "blocks": [
                block("b-001", "投标报价应包含投标函附录中列明的所有费用。", heading_path=["第二章 投标人须知", "投标报价"]),
                block("b-002", "附件1 投标函", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-003", "1A 投标函", heading_path=["第六章 投标文件格式", "附件1 投标函"]),
                block("b-004", "致：招标人", heading_path=["第六章 投标文件格式", "附件1 投标函"]),
                block("b-005", "1B 法定代表人身份证明", heading_path=["第六章 投标文件格式", "附件1 投标函"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-parent", "title": "投标函、法定代表人身份证明、授权委托书", "source_text": "附件1 投标函", "children": [
            {"id": "sec-child", "title": "投标函", "source_text": "1.1 投标函", "children": []}
        ]}]}
        result = self.run_resolver(tender, outline)
        candidate = self.by_id(result)["sec-child"]["candidates"][0]

        self.assertEqual(candidate["scope"], "parent_context")
        self.assertEqual(candidate["source_text"], "1A 投标函")
        self.assertNotIn("投标报价", candidate["source_text"])

    def test_top_level_prefers_format_heading_over_submission_list(self):
        tender = {
            "blocks": [
                block("b-001", "投标价格表(不含价格)；", heading_path=["第二章 投标人须知", "投标文件的组成"]),
                block("b-002", "投标价格表。", heading_path=["第二章 投标人须知", "投标文件的组成"]),
                block("b-003", "附件2 投标价格表", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-004", "本表应按招标文件要求填写。", heading_path=["第六章 投标文件格式", "附件2 投标价格表"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-004", "title": "二、投标价格表", "source_text": "二、投标价格表", "children": []}]}
        result = self.run_resolver(tender, outline)
        candidate = self.by_id(result)["sec-004"]["candidates"][0]

        self.assertEqual(candidate["scope"], "format_area")
        self.assertEqual(candidate["source_text"], "附件2 投标价格表")

    def test_top_level_prefers_format_heading_over_response_sentence(self):
        tender = {
            "blocks": [
                block("b-001", "商务文件：除随本投标文件提交的商务条件及合同条款偏差表列明的偏差外，其他均完全响应招标文件要求。", heading_path=["第六章 投标文件格式", "投标函"]),
                block("b-002", "附件4 商务条款偏差表", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-003", "商务条件及合同条款偏差表；", heading_path=["第二章 投标人须知", "投标文件的组成"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-006", "title": "四、商务条款偏差表", "source_text": "四、商务条款偏差表", "children": []}]}
        result = self.run_resolver(tender, outline)
        candidate = self.by_id(result)["sec-006"]["candidates"][0]

        self.assertEqual(candidate["scope"], "format_area")
        self.assertEqual(candidate["source_text"], "附件4 商务条款偏差表")

    def test_table_cell_short_evidence_beats_equally_scored_table_row(self):
        tender = {
            "blocks": [
                block("b-001", "附件5 信息表", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-002", "企业规模生产能力 | 企业总人数及技术人员数量 | 后附企业组织机构图、企业规模、服务能力简介等", type="table_row", table_id="t-001", row_index=1, heading_path=["第六章 投标文件格式", "附件5 信息表"]),
                block("b-003", "后附企业组织机构图、企业规模、服务能力简介等", type="table_cell_marker", table_id="t-001", row_index=1, col_index=3, heading_path=["第六章 投标文件格式", "附件5 信息表"]),
            ],
            "tables": [{
                "table_id": "t-001",
                "nearby_heading": "附件5 信息表",
                "rows": [{"row_index": 1, "row_text": "企业规模生产能力 | 企业总人数及技术人员数量 | 后附企业组织机构图、企业规模、服务能力简介等", "cells": [
                    {"col_index": 1, "text": "企业规模生产能力"},
                    {"col_index": 2, "text": "企业总人数及技术人员数量"},
                    {"col_index": 3, "text": "后附企业组织机构图、企业规模、服务能力简介等"},
                ]}],
            }],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-parent", "title": "信息表", "source_text": "附件5 信息表", "children": [
            {"id": "sec-child", "title": "企业组织机构图、企业规模、服务能力简介", "source_text": "企业组织机构图、企业规模、服务能力简介", "children": []}
        ]}]}
        result = self.run_resolver(tender, outline)
        candidate = self.by_id(result)["sec-child"]["candidates"][0]

        self.assertEqual(candidate["scope"], "parent_context")
        self.assertEqual(candidate["source_text"], "后附企业组织机构图、企业规模、服务能力简介等")
        self.assertNotIn("|", candidate["source_text"])

    def test_child_prefers_numbered_item_inside_parent_format_scope(self):
        tender = {
            "blocks": [
                block("b-001", "附件7 资格证明文件", heading_path=["第六章 投标文件格式"], heading_level=2),
                block("b-002", "1. 商务部分摘要表（附件7A）。", heading_path=["第六章 投标文件格式", "附件7 资格证明文件"]),
                block("b-003", "3. 投标人/工厂简介（附件7C）。", heading_path=["第六章 投标文件格式", "附件7 资格证明文件"]),
                block("b-004", "5. 资信证明、商业信誉（附件7E）。", heading_path=["第六章 投标文件格式", "附件7 资格证明文件"]),
                block("b-005", "投标人认为应当提交的其他材料。", heading_path=["第二章 投标人须知", "投标文件的组成"]),
            ],
            "tables": [],
            "zones": [],
        }
        outline = {"sections": [{"id": "sec-parent", "title": "资格证明文件", "source_text": "附件7 资格证明文件", "children": [
            {"id": "sec-child", "title": "投标人/工厂简介", "source_text": "7.3 投标人/工厂简介", "children": []}
        ]}]}
        result = self.run_resolver(tender, outline)
        candidate = self.by_id(result)["sec-child"]["candidates"][0]

        self.assertEqual(candidate["scope"], "parent_context")
        self.assertEqual(candidate["source_text"], "3. 投标人/工厂简介（附件7C）。")

    def test_flags_toc_like_final_source_text_with_page_number(self):
        outline = {"sections": [{"id": "sec-parent", "title": "投标函", "source_text": "附件1 投标函 89", "children": []}]}
        result = self.run_resolver({"blocks": [], "tables": [], "zones": []}, outline)
        messages = [issue["message"] for issue in result.get("quality_issues", [])]

        self.assertTrue(any("目录页" in message or "目次页" in message for message in messages))

    def test_flags_sibling_children_reusing_parent_title_source_text(self):
        outline = {"sections": [{"id": "sec-parent", "title": "附件7A 商务部分摘要表", "source_text": "附件7A 商务部分摘要表", "children": [
            {"id": "sec-child-1", "title": "企业组织机构图", "source_text": "附件7A 商务部分摘要表", "children": []},
            {"id": "sec-child-2", "title": "服务能力简介", "source_text": "附件7A 商务部分摘要表", "children": []},
        ]}]}
        result = self.run_resolver({"blocks": [], "tables": [], "zones": []}, outline)
        messages = [issue["message"] for issue in result.get("quality_issues", [])]

        self.assertTrue(any("child 的 source_text 与父项 source_text 完全相同" in message for message in messages))
        self.assertTrue(any("多个 sibling child 复用同一个父项 source_text" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
