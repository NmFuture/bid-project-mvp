from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CLEANER_RUNNER = (
    BACKEND_ROOT
    / "opencode"
    / "skills"
    / "bid-tech-format-cleaner"
    / "scripts"
    / "run_from_manifest.py"
)


def load_cleaner_runner():
    spec = importlib.util.spec_from_file_location("test_technical_format_cleaner_runner", CLEANER_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载技术标格式清洗脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TechnicalFormatCleanerTests(unittest.TestCase):
    def test_run_manifest_returns_warnings_without_writing_markdown_report(self) -> None:
        runner = load_cleaner_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_file = root / "assembled.docx"
            outline_file = root / "outline.json"
            output_file = root / "assembled.formatted.docx"
            manifest_file = root / "manifest.json"

            doc = Document()
            doc.add_paragraph("技术方案", style="Heading 1")
            doc.add_paragraph("脱敏正文。")
            doc.save(input_file)
            outline_file.write_text(
                json.dumps(
                    {
                        "schema_version": "tech_bid_outline.v1",
                        "sections": [{"id": "S-1", "title": "技术方案", "level": 1}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest_file.write_text(
                json.dumps(
                    {
                        "inputFile": str(input_file),
                        "outlineFile": str(outline_file),
                        "outputFile": str(output_file),
                        "projectName": "脱敏项目",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = runner.run_manifest(manifest_file)

            self.assertTrue(output_file.exists())
            self.assertEqual(result["reportFile"], "")
            self.assertIsInstance(result["summary"], dict)
            self.assertIsInstance(result["warnings"], list)
            self.assertEqual(result["warnings"], result["summary"]["warnings"])
            self.assertTrue(all(set(item) == {"code", "message", "count"} for item in result["warnings"]))
            self.assertFalse((root / "tech_format_clean_report.md").exists())


if __name__ == "__main__":
    unittest.main()
