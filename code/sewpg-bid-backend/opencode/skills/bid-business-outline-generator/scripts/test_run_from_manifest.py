import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_from_manifest as runner


class BusinessOutlineRunnerMatchingTest(unittest.TestCase):
    def test_run_manifest_prepares_inputs_without_writing_final_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            template_file = tmpdir / "history.docx"
            tender_file = tmpdir / "tender.docx"
            template_file.write_text("history", encoding="utf-8")
            tender_file.write_text("tender", encoding="utf-8")
            manifest = {
                "projectName": "测试项目",
                "workDir": str(tmpdir),
                "templateFile": str(template_file),
                "tenderFiles": [{"id": "tender-1", "name": "招标文件.docx", "path": str(tender_file)}],
            }

            result = self._run_preparation_manifest(manifest, tmpdir)

            self.assertFalse((tmpdir / "outline.json").exists())
            summary = result["summary"]
            self.assertEqual(summary["schema_version"], "business-outline-inputs-v1")
            self.assertNotEqual(summary.get("schema_version"), "business_bid_outline.v1")
            self.assertNotIn("sections", summary)
            self.assertNotIn("businessOutlineFile", summary)

    def test_run_manifest_writes_candidate_materials_for_opencode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            template_file = tmpdir / "history.docx"
            tender_file = tmpdir / "tender.docx"
            template_file.write_text("history", encoding="utf-8")
            tender_file.write_text("tender", encoding="utf-8")
            manifest = {
                "projectName": "测试项目",
                "workDir": str(tmpdir),
                "templateFile": str(template_file),
                "tenderFiles": [{"id": "tender-1", "name": "招标文件.docx", "path": str(tender_file)}],
            }

            result = self._run_preparation_manifest(manifest, tmpdir)

            expected_files = {
                "historyBidOutlineInputsFile": tmpdir / "history_bid_outline_inputs.json",
                "tenderMapInputsFile": tmpdir / "tender_map_inputs.json",
                "documentStructureIndexFile": tmpdir / "document_structure_index.json",
                "sourceTextCandidatesFile": tmpdir / "source_text_candidates.json",
            }
            for summary_key, path in expected_files.items():
                self.assertTrue(path.exists(), f"{path.name} should be created")
                self.assertEqual(result["summary"][summary_key], str(path))

            source_candidates = runner.json.loads((tmpdir / "source_text_candidates.json").read_text(encoding="utf-8"))
            self.assertIn("items", source_candidates)
            self.assertIn("summary", source_candidates)

    def test_preparation_artifacts_do_not_look_like_final_business_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            template_file = tmpdir / "history.docx"
            tender_file = tmpdir / "tender.docx"
            template_file.write_text("history", encoding="utf-8")
            tender_file.write_text("tender", encoding="utf-8")
            manifest = {
                "projectName": "测试项目",
                "workDir": str(tmpdir),
                "templateFile": str(template_file),
                "tenderFiles": [{"id": "tender-1", "name": "招标文件.docx", "path": str(tender_file)}],
            }

            self._run_preparation_manifest(manifest, tmpdir)

            for artifact_name in (
                "history_bid_outline_inputs.json",
                "tender_map_inputs.json",
                "document_structure_index.json",
                "source_text_candidates.json",
            ):
                artifact = runner.json.loads((tmpdir / artifact_name).read_text(encoding="utf-8"))
                self.assertNotEqual(artifact.get("schema_version"), "business_bid_outline.v1")
                self.assertNotIn("sections", artifact)

    def _run_preparation_manifest(self, manifest, tmpdir):
        history_inputs = {
            "document_name": "历史商务标.docx",
            "outline_candidates": [
                {
                    "number": "1",
                    "level": 1,
                    "title_hint": "投标保证金承诺函",
                    "source_text": "1 投标保证金承诺函",
                }
            ],
        }
        tender_map_inputs = {
            "document_name": "招标文件.docx",
            "source_path": str(tmpdir / "tender.docx"),
            "blocks": [
                {
                    "block_id": "b-001",
                    "type": "paragraph",
                    "text": "投标人须提供投标保证金承诺函。",
                    "heading_path": ["投标文件格式"],
                }
            ],
            "tables": [],
            "zones": [],
        }
        document_index = {
            "summary": {"source_count": 1},
            "sources": [
                {
                    "block_id": "b-001",
                    "source_text": "投标人须提供投标保证金承诺函。",
                    "scope_hint": "format_area",
                }
            ],
        }
        source_text_candidates = {
            "items": [
                {
                    "id": "HIST-0001",
                    "title": "投标保证金承诺函",
                    "candidates": [
                        {
                            "candidate_id": "cand-001",
                            "source_text": "投标人须提供投标保证金承诺函。",
                            "scope": "format_area",
                            "evidence_strength": "strong",
                        }
                    ],
                }
            ],
            "summary": {"candidate_count": 1, "history_fallback_count": 0, "elapsed_seconds": 0.0},
        }
        with (
            patch.object(runner, "build_history_outline_inputs", return_value=history_inputs),
            patch.object(runner, "build_tender_map_inputs", return_value=tender_map_inputs),
            patch.object(runner, "build_document_structure_index", return_value=document_index),
            patch.object(runner, "build_source_text_candidates", return_value=source_text_candidates),
        ):
            return runner.run_manifest(manifest, tmpdir / "manifest.json")

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

    def test_source_text_candidate_payload_uses_current_tender_evidence_without_finalizing_sections(self):
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

        payload = runner.build_source_text_candidate_payload(sections, tender_map_inputs)

        self.assertEqual(payload["schema_version"], "business-outline-source-text-candidates-v1")
        self.assertEqual(payload["artifact_role"], "candidate_material")
        self.assertEqual(payload["summary"]["candidate_outline_item_count"], 3)
        self.assertEqual(len(sections[0]["children"]), 2)
        current = sections[0]["children"][0]
        fallback = sections[0]["children"][1]
        candidate_items = {item["id"]: item for item in payload["items"]}
        current_candidates = candidate_items[current["id"]]["candidates"]
        fallback_candidates = candidate_items[fallback["id"]]["candidates"]
        self.assertEqual(current["source_text"], "9.1 保密承诺书")
        self.assertNotIn("required_status", current)
        self.assertNotIn("source_refs", current)
        self.assertEqual(current_candidates[0]["source_text"], "附件9 保密承诺书")
        self.assertEqual(current_candidates[0]["scope"], "format_area")
        self.assertEqual(current_candidates[0]["source_ref"]["block_id"], "b-004")
        self.assertEqual(fallback["source_text"], "9.2 历史保留但当前无依据")
        self.assertNotIn("required_status", fallback)
        self.assertEqual(fallback_candidates[0]["scope"], "history_fallback")
        self.assertIn("未在当前招标文件找到可信证据", fallback_candidates[0]["match_reason"])

    def test_source_text_candidates_preserve_history_candidate_source_id(self):
        template_outline = [
            {
                "candidate_id": "hist-cand-003",
                "number": "3",
                "title": "Traceable Item",
                "level": 1,
                "rawText": "3 Traceable Item",
            }
        ]
        tender_map_inputs = {
            "document_name": "tender.docx",
            "source_path": "C:/work/tender.docx",
            "blocks": [
                {
                    "block_id": "b-003",
                    "type": "paragraph",
                    "text": "Traceable Item must be submitted",
                    "heading_path": ["Format"],
                }
            ],
            "tables": [],
            "zones": [],
        }
        sections = runner.outline_sections_from_template(template_outline, [])

        payload = runner.build_source_text_candidate_payload(sections, tender_map_inputs)

        self.assertEqual(sections[0]["id"], "BIZ-FALLBACK-0003")
        self.assertEqual(sections[0]["candidate_source_id"], "hist-cand-003")
        self.assertEqual(payload["items"][0]["id"], "BIZ-FALLBACK-0003")
        self.assertEqual(payload["items"][0]["candidate_source_id"], "hist-cand-003")


if __name__ == "__main__":
    unittest.main()
