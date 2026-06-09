import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import outline_authoring_helper as helper


class OutlineAuthoringHelperTest(unittest.TestCase):
    def test_writes_outline_from_explicit_author_decisions_without_semantic_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1",
                        "level": 1,
                        "title_hint": "Custom Parent",
                        "source_text": "1 Custom Parent",
                    },
                    {
                        "candidate_id": "hist-cand-002",
                        "number": "1.1",
                        "level": 2,
                        "title_hint": "Custom Child",
                        "source_text": "1.1 Custom Child",
                    },
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Custom Parent",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Current parent evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                                "source_ref": {"block_id": "b-001", "source_file": "tender.docx"},
                            }
                        ],
                    },
                    {
                        "id": "BIZ-FALLBACK-0002",
                        "candidate_source_id": "hist-cand-002",
                        "title": "Custom Child",
                        "parent_id": "BIZ-FALLBACK-0001",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Current child evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                                "source_ref": {"block_id": "b-002", "source_file": "tender.docx"},
                            }
                        ],
                    },
                ],
                decisions={
                    "document_name": "Custom Bid",
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "required_status": "待确认",
                            "reason": "opencode intentionally keeps this pending",
                        },
                        {
                            "id": "BIZ-FALLBACK-0002",
                            "required_status": "可选",
                            "reason": "opencode intentionally marks this optional",
                        },
                    ],
                },
            )

            result = helper.write_outline(
                history_path=history_path,
                source_candidates_path=candidates_path,
                decisions_path=decisions_path,
                output_path=output_path,
            )

            outline = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["section_count"], 2)
            self.assertEqual(outline["schema_version"], "business_bid_outline.v1")
            parent = outline["sections"][0]
            child = parent["children"][0]
            self.assertEqual(parent["required_status"], "待确认")
            self.assertEqual(parent["reason"], "opencode intentionally keeps this pending")
            self.assertEqual(parent["source_text"], "Current parent evidence")
            self.assertEqual(parent["candidate_source_id"], "hist-cand-001")
            self.assertEqual(parent["source_candidate_item_id"], "BIZ-FALLBACK-0001")
            self.assertEqual(parent["selected_candidate_id"], "cand-001")
            self.assertEqual(child["required_status"], "可选")
            self.assertEqual(child["reason"], "opencode intentionally marks this optional")

    def test_normalized_source_ids_keep_history_candidate_traceable_when_widths_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-003",
                        "number": "3",
                        "level": 1,
                        "title_hint": "Traceable Item",
                        "source_text": "3 Traceable Item",
                    }
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0003",
                        "title": "Traceable Item",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Traceable current evidence",
                                "scope": "high_value_area",
                                "evidence_strength": "strong",
                                "evidence_category": "submission_requirement",
                                "match_reason": "normalized id link",
                            }
                        ],
                    }
                ],
                decisions={
                    "sections": [
                        {
                            "candidate_source_id": "hist-cand-003",
                            "required_status": "必要",
                            "reason": "opencode chose by history source id",
                        }
                    ]
                },
            )

            helper.write_outline(
                history_path=history_path,
                source_candidates_path=candidates_path,
                decisions_path=decisions_path,
                output_path=output_path,
            )

            section = json.loads(output_path.read_text(encoding="utf-8"))["sections"][0]
            self.assertEqual(section["id"], "BIZ-FALLBACK-0003")
            self.assertEqual(section["candidate_source_id"], "hist-cand-003")
            self.assertEqual(section["source_candidate_item_id"], "BIZ-FALLBACK-0003")

    def test_decision_row_ids_are_not_normalized_as_candidate_source_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1",
                        "level": 1,
                        "title_hint": "First Historical Item",
                        "source_text": "1 First Historical Item",
                    },
                    {
                        "candidate_id": "hist-cand-002",
                        "number": "2",
                        "level": 1,
                        "title_hint": "Second Historical Item",
                        "source_text": "2 Second Historical Item",
                    },
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "First Historical Item",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "First current evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                            }
                        ],
                    },
                    {
                        "id": "BIZ-FALLBACK-0002",
                        "candidate_source_id": "hist-cand-002",
                        "title": "Second Historical Item",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Second current evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                            }
                        ],
                    },
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-DECISION-0001",
                            "candidate_source_id": "BIZ-FALLBACK-0002",
                            "required_status": "必要",
                            "reason": "decision row id must not satisfy hist-cand-001",
                        }
                    ]
                },
            )

            with self.assertRaisesRegex(ValueError, "missing opencode decision for BIZ-FALLBACK-0001 / hist-cand-001"):
                helper.write_outline(
                    history_path=history_path,
                    source_candidates_path=candidates_path,
                    decisions_path=decisions_path,
                    output_path=output_path,
                )

    def test_strong_candidate_is_not_written_as_history_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": None,
                        "level": 1,
                        "title_hint": "Strong Item",
                        "source_text": "Strong Item",
                    }
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Strong Item",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Strong current evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "strong first candidate",
                            }
                        ],
                    }
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "required_status": "必要",
                            "reason": "opencode accepted strong evidence",
                        }
                    ]
                },
            )

            helper.write_outline(
                history_path=history_path,
                source_candidates_path=candidates_path,
                decisions_path=decisions_path,
                output_path=output_path,
            )

            section = json.loads(output_path.read_text(encoding="utf-8"))["sections"][0]
            self.assertEqual(section["source_text"], "Strong current evidence")
            self.assertEqual(section["evidence_scope"], "format_area")
            self.assertEqual(section["evidence_strength"], "strong")
            self.assertTrue(section["source_refs"])

    def test_rejects_history_fallback_required_as_necessary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1.1.1.1",
                        "level": 4,
                        "title_hint": "Historical Detail",
                        "source_text": "1.1.1.1 Historical Detail",
                    }
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Historical Detail",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "1.1.1.1 Historical Detail",
                                "scope": "history_fallback",
                                "evidence_strength": "fallback",
                                "evidence_category": "material_proof",
                                "match_reason": "history fallback only",
                            }
                        ],
                    }
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "action": "keep",
                            "required_status": "必要",
                            "reason": "opencode incorrectly treated keep as necessary",
                        }
                    ]
                },
            )

            with self.assertRaisesRegex(ValueError, "history_fallback/fallback.*必要"):
                helper.write_outline(
                    history_path=history_path,
                    source_candidates_path=candidates_path,
                    decisions_path=decisions_path,
                    output_path=output_path,
                )

    def test_allows_history_fallback_when_status_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1.1.1.1",
                        "level": 4,
                        "title_hint": "Historical Detail",
                        "source_text": "1.1.1.1 Historical Detail",
                    }
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Historical Detail",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "1.1.1.1 Historical Detail",
                                "scope": "history_fallback",
                                "evidence_strength": "fallback",
                                "evidence_category": "material_proof",
                                "match_reason": "history fallback only",
                            }
                        ],
                    }
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "action": "keep",
                            "required_status": "待确认",
                            "reason": "keep historical structure, current tender evidence is insufficient",
                        }
                    ]
                },
            )

            helper.write_outline(
                history_path=history_path,
                source_candidates_path=candidates_path,
                decisions_path=decisions_path,
                output_path=output_path,
            )

            section = json.loads(output_path.read_text(encoding="utf-8"))["sections"][0]
            self.assertEqual(section["required_status"], "待确认")
            self.assertEqual(section["evidence_scope"], "history_fallback")
            self.assertEqual(section["evidence_strength"], "fallback")

    def test_helper_requires_explicit_decision_for_each_history_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1",
                        "level": 1,
                        "title_hint": "Kept Item",
                        "source_text": "1 Kept Item",
                    },
                    {
                        "candidate_id": "hist-cand-002",
                        "number": "1.1",
                        "level": 2,
                        "title_hint": "Detail Item Requiring Decision",
                        "source_text": "1.1 Detail Item Requiring Decision",
                    },
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Kept Item",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Kept current evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                            }
                        ],
                    },
                    {
                        "id": "BIZ-FALLBACK-0002",
                        "candidate_source_id": "hist-cand-002",
                        "title": "Detail Item Requiring Decision",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "1.1 Detail Item Requiring Decision",
                                "scope": "history_fallback",
                                "evidence_strength": "fallback",
                                "evidence_category": "material_proof",
                                "match_reason": "history fallback only",
                            }
                        ],
                    },
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "required_status": "必要",
                            "reason": "opencode kept the parent",
                        }
                    ],
                    "review_items": [
                        {
                            "message": "opencode deferred detail item as body material",
                            "source_text": "1.1 Detail Item Requiring Decision",
                            "suggested_section_id": "BIZ-FALLBACK-0001",
                            "required_status": "待确认",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, "missing opencode decision"):
                helper.write_outline(
                    history_path=history_path,
                    source_candidates_path=candidates_path,
                    decisions_path=decisions_path,
                    output_path=output_path,
                )

    def test_explicit_defer_decision_skips_history_detail_without_semantic_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1",
                        "level": 1,
                        "title_hint": "Parent Item",
                        "source_text": "1 Parent Item",
                    },
                    {
                        "candidate_id": "hist-cand-002",
                        "number": "1.1",
                        "level": 2,
                        "title_hint": "Body Material Detail",
                        "source_text": "1.1 Body Material Detail",
                    },
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Parent Item",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Parent current evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                            }
                        ],
                    },
                    {
                        "id": "BIZ-FALLBACK-0002",
                        "candidate_source_id": "hist-cand-002",
                        "title": "Body Material Detail",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "1.1 Body Material Detail",
                                "scope": "history_fallback",
                                "evidence_strength": "fallback",
                                "evidence_category": "material_proof",
                                "match_reason": "history fallback only",
                            }
                        ],
                    },
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "action": "keep",
                            "required_status": "必要",
                            "reason": "opencode kept the parent",
                        },
                        {
                            "id": "BIZ-FALLBACK-0002",
                            "action": "defer",
                            "reason": "opencode classified this as body material detail",
                        },
                    ],
                    "review_items": [],
                },
            )

            result = helper.write_outline(
                history_path=history_path,
                source_candidates_path=candidates_path,
                decisions_path=decisions_path,
                output_path=output_path,
            )

            outline = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["section_count"], 1)
            self.assertEqual(outline["sections"][0]["id"], "BIZ-FALLBACK-0001")
            self.assertEqual(outline["sections"][0]["children"], [])
            deferred = outline["context"]["authoring_helper"]["deferred_items"]
            self.assertEqual(deferred[0]["id"], "BIZ-FALLBACK-0002")
            self.assertEqual(deferred[0]["candidate_source_id"], "hist-cand-002")

    def test_rejects_deferred_item_marked_necessary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1",
                        "level": 1,
                        "title_hint": "Current Evidence Detail",
                        "source_text": "1 Current Evidence Detail",
                    }
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Current Evidence Detail",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Current tender requires this material.",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "strong current evidence",
                            }
                        ],
                    }
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "action": "defer",
                            "required_status": "必要",
                            "reason": "opencode cannot both defer a directory node and mark it necessary",
                        }
                    ],
                    "review_items": [],
                },
            )

            with self.assertRaisesRegex(ValueError, "defer.*不能标为“必要”"):
                helper.write_outline(
                    history_path=history_path,
                    source_candidates_path=candidates_path,
                    decisions_path=decisions_path,
                    output_path=output_path,
                )

    def test_rejects_defer_when_reason_only_says_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1.1.1.1",
                        "level": 4,
                        "title_hint": "Historical Detail",
                        "source_text": "1.1.1.1 Historical Detail",
                    }
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Historical Detail",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "1.1.1.1 Historical Detail",
                                "scope": "history_fallback",
                                "evidence_strength": "fallback",
                                "evidence_category": "material_proof",
                                "match_reason": "history fallback only",
                            }
                        ],
                    }
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "action": "defer",
                            "required_status": "待确认",
                            "reason": "未在当前招标文件找到可信证据，保留历史目录文本作为 fallback。",
                        }
                    ],
                    "review_items": [],
                },
            )

            with self.assertRaisesRegex(ValueError, "defer reason.*正文素材"):
                helper.write_outline(
                    history_path=history_path,
                    source_candidates_path=candidates_path,
                    decisions_path=decisions_path,
                    output_path=output_path,
                )

    def test_deferred_sibling_does_not_keep_previous_sibling_as_active_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=[
                    {
                        "candidate_id": "hist-cand-001",
                        "number": "1",
                        "level": 1,
                        "title_hint": "Kept Root",
                        "source_text": "1 Kept Root",
                    },
                    {
                        "candidate_id": "hist-cand-002",
                        "number": "1.1",
                        "level": 2,
                        "title_hint": "Kept First Child",
                        "source_text": "1.1 Kept First Child",
                    },
                    {
                        "candidate_id": "hist-cand-003",
                        "number": "1.2",
                        "level": 2,
                        "title_hint": "Deferred Sibling",
                        "source_text": "1.2 Deferred Sibling",
                    },
                    {
                        "candidate_id": "hist-cand-004",
                        "number": "1.2.1",
                        "level": 3,
                        "title_hint": "Kept Descendant",
                        "source_text": "1.2.1 Kept Descendant",
                    },
                ],
                source_items=[
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "candidate_source_id": "hist-cand-001",
                        "title": "Kept Root",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Kept root evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                            }
                        ],
                    },
                    {
                        "id": "BIZ-FALLBACK-0002",
                        "candidate_source_id": "hist-cand-002",
                        "title": "Kept First Child",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Kept first child evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                            }
                        ],
                    },
                    {
                        "id": "BIZ-FALLBACK-0003",
                        "candidate_source_id": "hist-cand-003",
                        "title": "Deferred Sibling",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Deferred sibling evidence",
                                "scope": "history_fallback",
                                "evidence_strength": "fallback",
                                "evidence_category": "material_proof",
                                "match_reason": "history fallback only",
                            }
                        ],
                    },
                    {
                        "id": "BIZ-FALLBACK-0004",
                        "candidate_source_id": "hist-cand-004",
                        "title": "Kept Descendant",
                        "candidates": [
                            {
                                "candidate_id": "cand-001",
                                "source_text": "Kept descendant evidence",
                                "scope": "format_area",
                                "evidence_strength": "strong",
                                "evidence_category": "format_appendix",
                                "match_reason": "ranked first",
                            }
                        ],
                    },
                ],
                decisions={
                    "sections": [
                        {
                            "id": "BIZ-FALLBACK-0001",
                            "action": "keep",
                            "required_status": "必要",
                            "reason": "opencode kept the root",
                        },
                        {
                            "id": "BIZ-FALLBACK-0002",
                            "action": "keep",
                            "required_status": "必要",
                            "reason": "opencode kept the first child",
                        },
                        {
                            "id": "BIZ-FALLBACK-0003",
                            "action": "defer",
                            "reason": "opencode deferred the sibling wrapper",
                        },
                        {
                            "id": "BIZ-FALLBACK-0004",
                            "action": "keep",
                            "required_status": "必要",
                            "reason": "opencode kept a descendant after skipping the wrapper",
                        },
                    ],
                    "review_items": [],
                },
            )

            helper.write_outline(
                history_path=history_path,
                source_candidates_path=candidates_path,
                decisions_path=decisions_path,
                output_path=output_path,
            )

            root = json.loads(output_path.read_text(encoding="utf-8"))["sections"][0]
            first_child = root["children"][0]
            promoted_descendant = root["children"][1]
            self.assertEqual(first_child["id"], "BIZ-FALLBACK-0002")
            self.assertEqual(first_child["children"], [])
            self.assertEqual(promoted_descendant["id"], "BIZ-FALLBACK-0004")

    def test_rejects_bulk_defer_with_reused_template_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            history_candidates = [
                {
                    "candidate_id": f"hist-cand-{index:03d}",
                    "number": f"7.1.{index}",
                    "level": 4,
                    "title_hint": f"Historical Material {index}",
                    "source_text": f"7.1.{index} Historical Material {index}",
                }
                for index in range(1, 26)
            ]
            source_items = [
                {
                    "id": f"BIZ-FALLBACK-{index:04d}",
                    "candidate_source_id": f"hist-cand-{index:03d}",
                    "title": f"Historical Material {index}",
                    "candidates": [
                        {
                            "candidate_id": "cand-001",
                            "source_text": f"7.1.{index} Historical Material {index}",
                            "scope": "history_fallback",
                            "evidence_strength": "fallback",
                            "evidence_category": "material_proof",
                            "match_reason": "history fallback only",
                        }
                    ],
                }
                for index in range(1, 26)
            ]
            decisions = {
                "sections": [
                    {
                        "id": f"BIZ-FALLBACK-{index:04d}",
                        "action": "defer",
                        "required_status": "待确认",
                        "reason": "历史深层项(4+级)为具体项目业绩/证书明细，属素材库组装项，目录阶段不展开。",
                    }
                    for index in range(1, 26)
                ],
                "review_items": [],
            }
            history_path, candidates_path, decisions_path, output_path = self._write_inputs(
                tmpdir,
                history_candidates=history_candidates,
                source_items=source_items,
                decisions=decisions,
            )

            with self.assertRaisesRegex(ValueError, "bulk defer.*template reason"):
                helper.write_outline(
                    history_path=history_path,
                    source_candidates_path=candidates_path,
                    decisions_path=decisions_path,
                    output_path=output_path,
                )

    def _write_inputs(self, tmpdir, *, history_candidates, source_items, decisions):
        history_path = tmpdir / "history_bid_outline_inputs.json"
        candidates_path = tmpdir / "source_text_candidates.json"
        decisions_path = tmpdir / "outline_authoring_decisions.json"
        output_path = tmpdir / "outline.json"
        history_path.write_text(
            json.dumps(
                {
                    "document_name": "History Bid",
                    "outline_candidates": history_candidates,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        candidates_path.write_text(
            json.dumps(
                {
                    "schema_version": "business-outline-source-text-candidates-v1",
                    "artifact_role": "candidate_material",
                    "items": source_items,
                    "summary": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        decisions_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
        return history_path, candidates_path, decisions_path, output_path


if __name__ == "__main__":
    unittest.main()
