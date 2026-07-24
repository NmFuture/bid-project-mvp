import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_source_text.py")


class CheckSourceTextTest(unittest.TestCase):
    def test_cli_ignores_outline_source_when_checking_current_tender_traceability(self):
        outline = {
            "schema_version": "business_bid_outline.v1",
            "document_name": "sample tender",
            "outline_source": {
                "section_title": "history outline",
                "source_text": "generated history outline summary, not tender evidence",
                "confidence": "high",
            },
            "context": {},
            "sections": [
                {
                    "id": "sec-1",
                    "title": "Confidentiality undertaking",
                    "number": None,
                    "level": 1,
                    "required_status": "必要",
                    "source_text": "Attachment 9 Confidentiality undertaking",
                    "children": [],
                }
            ],
            "review_items": [],
        }
        tender = {
            "blocks": [
                {
                    "block_id": "b-1",
                    "type": "paragraph",
                    "text": "Attachment 9 Confidentiality undertaking",
                    "heading_path": [],
                }
            ],
            "tables": [],
            "zones": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            outline_path = tmpdir / "outline.json"
            tender_path = tmpdir / "tender_map_inputs.json"
            outline_path.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
            tender_path.write_text(json.dumps(tender, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(tender_path), str(outline_path)],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["metrics"]["source_text_total"], 1)
            self.assertEqual(report["unmatched"], [])
            self.assertEqual([item["path"] for item in report["results"]], ["sections[0].source_text"])


if __name__ == "__main__":
    unittest.main()
