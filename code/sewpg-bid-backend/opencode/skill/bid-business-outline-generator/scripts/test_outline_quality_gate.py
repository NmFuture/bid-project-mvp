import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import outline_quality_gate as gate


SCRIPT = Path(__file__).with_name("outline_quality_gate.py")


class OutlineQualityGateTest(unittest.TestCase):
    def test_quality_gate_passes_when_current_evidence_and_reasons_are_sufficient(self):
        outline = {
            "schema_version": "business_bid_outline.v1",
            "document_name": "招标文件",
            "outline_source": {"section_title": "历史目录", "source_text": "历史目录", "confidence": "low"},
            "context": {},
            "sections": [
                {
                    "id": "sec-1",
                    "title": "保密承诺书",
                    "number": None,
                    "level": 1,
                    "required_status": "必要",
                    "source_text": "附件9 保密承诺书",
                    "source_refs": [{"type": "tender", "source_ref": {"block_id": "b-1"}}],
                    "reason": "证据 scope=format_area strength=strong。",
                    "evidence_scope": "format_area",
                    "evidence_strength": "strong",
                    "children": [],
                },
                {
                    "id": "sec-2",
                    "title": "历史保留项",
                    "number": None,
                    "level": 1,
                    "required_status": "待确认",
                    "source_text": "历史保留项 20",
                    "source_refs": [],
                    "reason": "仅命中历史目录，未在当前招标文件找到强证据，需要人工确认。",
                    "evidence_scope": "history_fallback",
                    "evidence_strength": "fallback",
                    "children": [],
                },
            ],
            "review_items": [],
        }
        tender = {"blocks": [{"block_id": "b-1", "type": "paragraph", "text": "附件9 保密承诺书", "heading_path": ["第六章 投标文件格式"]}], "tables": [], "zones": []}
        report = gate.evaluate_quality(
            outline,
            tender,
            baseline_outline=outline,
            min_current_evidence_ratio=0.5,
            max_history_fallback_ratio=0.6,
        )

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["metrics"]["history_fallback_without_reason"], 0)
        self.assertEqual(report["metrics"]["source_text_matched_current"], 1)
        self.assertEqual(report["metrics"]["source_text_history_fallback"], 1)

    def test_quality_gate_fails_for_toc_strong_evidence_and_missing_fallback_reason(self):
        outline = {
            "schema_version": "business_bid_outline.v1",
            "document_name": "招标文件",
            "outline_source": {"section_title": "历史目录", "source_text": "历史目录", "confidence": "low"},
            "context": {},
            "sections": [
                {
                    "id": "sec-1",
                    "title": "保密承诺书",
                    "number": None,
                    "level": 1,
                    "required_status": "必要",
                    "source_text": "保密承诺书 ........ 88",
                    "reason": "",
                    "evidence_scope": "format_area",
                    "evidence_strength": "strong",
                    "children": [],
                },
                {
                    "id": "sec-2",
                    "title": "历史保留项",
                    "number": None,
                    "level": 1,
                    "required_status": "待确认",
                    "source_text": "历史保留项 20",
                    "reason": "",
                    "evidence_scope": "history_fallback",
                    "evidence_strength": "fallback",
                    "children": [],
                },
            ],
            "review_items": [],
        }
        tender = {"blocks": [{"block_id": "b-1", "type": "paragraph", "text": "保密承诺书 ........ 88", "heading_path": ["目录"]}], "tables": [], "zones": []}

        report = gate.evaluate_quality(outline, tender, baseline_outline=outline, min_current_evidence_ratio=0.8)

        self.assertFalse(report["passed"])
        messages = "\n".join(issue["message"] for issue in report["issues"])
        self.assertIn("目录页", messages)
        self.assertIn("fallback", messages)

    def test_cli_writes_report_and_returns_nonzero_on_failure(self):
        outline = {
            "schema_version": "business_bid_outline.v1",
            "document_name": "招标文件",
            "outline_source": {"section_title": "历史目录", "source_text": "历史目录", "confidence": "low"},
            "context": {},
            "sections": [{
                "id": "sec-1",
                "title": "历史保留项",
                "number": None,
                "level": 1,
                "required_status": "待确认",
                "source_text": "历史保留项 20",
                "source_refs": [],
                "reason": "",
                "children": [],
            }],
            "review_items": [],
        }
        tender = {"blocks": [], "tables": [], "zones": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            outline_path = tmpdir / "outline.json"
            tender_path = tmpdir / "tender.json"
            report_path = tmpdir / "report.json"
            outline_path.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
            tender_path.write_text(json.dumps(tender, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--outline", str(outline_path), "--tender-map", str(tender_path), "--output-report", str(report_path)],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
