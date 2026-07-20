from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ASSEMBLER_SCRIPTS = (
    BACKEND_ROOT / "opencode" / "skills" / "bid-tech-assembler" / "scripts"
)


def load_assembler_script(name: str):
    sys.path.insert(0, str(ASSEMBLER_SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            f"test_technical_final_assembly_{name}",
            ASSEMBLER_SCRIPTS / f"{name}.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载 assembler 脚本: {name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class TechnicalFinalAssemblyTests(unittest.TestCase):
    def test_runner_returns_structured_contract_without_markdown_reports(self) -> None:
        runner = load_assembler_script("run_from_manifest")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_file = root / "toc.json"
            wiki_dir = root / "wiki"
            library_dir = root / "library"
            template_file = root / "template.docx"
            output_file = root / "output.docx"
            manifest_file = root / "manifest.json"
            wiki_dir.mkdir()
            library_dir.mkdir()
            toc_file.write_text("{}", encoding="utf-8")
            Document().save(template_file)
            manifest_file.write_text(
                json.dumps(
                    {
                        "workDir": str(root),
                        "tocJsonPath": str(toc_file),
                        "wikiDir": str(wiki_dir),
                        "materialLibraryDir": str(library_dir),
                        "templateFile": str(template_file),
                        "outputFile": str(output_file),
                    }
                ),
                encoding="utf-8",
            )

            def fake_run_capture(command: list[str]) -> str:
                script = Path(command[1]).name
                if script == "parse_toc.py":
                    Path(command[command.index("--out") + 1]).write_text("[]", encoding="utf-8")
                elif script == "init_params.py":
                    Path(command[command.index("--out") + 1]).write_text("{}", encoding="utf-8")
                elif script == "build_assembly.py":
                    Path(command[command.index("--out") + 1]).write_text(
                        json.dumps([{"status": "STRUCTURAL", "level": 1, "title": "技术方案", "paths": []}]),
                        encoding="utf-8",
                    )
                elif script == "merger.py":
                    Document().save(Path(command[command.index("--out") + 1]))
                    Path(command[command.index("--result") + 1]).write_text(
                        json.dumps({"merged_materials": 0, "warnings": []}), encoding="utf-8"
                    )
                elif script == "finalize.py":
                    Document().save(Path(command[command.index("--out") + 1]))
                elif script == "verify.py":
                    self.assertNotIn("--report", command)
                    self.assertNotIn("--review", command)
                    Path(command[command.index("--result") + 1]).write_text(
                        json.dumps(
                            {
                                "placeholders": [],
                                "empty_leaf_headings": [],
                                "dup_alerts": [],
                                "ghost_chapters": [],
                                "invalid_h1": [],
                                "invalid_prefix": [],
                            }
                        ),
                        encoding="utf-8",
                    )
                return ""

            with patch.object(runner, "run_capture", side_effect=fake_run_capture):
                result = runner.run_from_manifest(manifest_file)

            self.assertTrue(output_file.exists())
            self.assertTrue(Path(result["planFile"]).exists())
            self.assertEqual(result["assemblyReport"], "")
            self.assertEqual(result["needsReview"], "")
            self.assertIsInstance(result["summary"], dict)
            self.assertIsInstance(result["warnings"], list)
            self.assertFalse((root / "assembly_report.md").exists())
            self.assertFalse((root / "needs_review.md").exists())

    def test_verify_returns_compact_json_without_markdown_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docx_path = root / "assembled.docx"
            plan_path = root / "assembly_plan.json"
            params_path = root / "project_params.json"
            result_path = root / "assembly_verify_result.json"

            doc = Document()
            doc.add_paragraph("技术方案", style="Heading 1")
            doc.add_paragraph("脱敏正文。")
            doc.save(docx_path)
            plan_path.write_text("[]", encoding="utf-8")
            params_path.write_text("{}", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ASSEMBLER_SCRIPTS / "verify.py"),
                    "--docx",
                    str(docx_path),
                    "--plan",
                    str(plan_path),
                    "--params",
                    str(params_path),
                    "--result",
                    str(result_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(payload, json.loads(result_path.read_text(encoding="utf-8")))
            self.assertIn("heading_counts", payload)
            self.assertFalse((root / "assembly_report.md").exists())
            self.assertFalse((root / "needs_review.md").exists())

    def test_merger_deduplicates_heading_from_first_usable_material(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            library = root / "library"
            corrupt = library / "corrupt.docx"
            valid = library / "valid.docx"
            output = root / "assembled.docx"

            library.mkdir()
            Document().save(template)
            corrupt.write_bytes(b"not-a-docx")
            valid_doc = Document()
            valid_doc.add_paragraph("正常素材", style="Heading 2")
            valid_doc.add_paragraph("这是首份可用素材的正文。")
            valid_doc.save(valid)
            plan = [
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "正常素材",
                    "chapter_no": "1.1",
                    "chapter_no_flat": "1.1",
                    "paths": ["missing.docx", corrupt.name, valid.name],
                }
            ]

            stats = merger.merge(template, plan, library, {}, root / "prep", output)
            result = Document(str(output))
            matching_paragraphs = [
                paragraph.text
                for paragraph in result.paragraphs
                if "正常素材" in paragraph.text
            ]

        self.assertEqual(matching_paragraphs, ["1.1  正常素材"])
        self.assertEqual(stats["merged_materials"], 1)

    def test_failed_compose_does_not_suppress_following_unmatched_child(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            library = root / "library"
            source = library / "parent.docx"
            output = root / "assembled.docx"

            library.mkdir()
            Document().save(template)
            source_doc = Document()
            source_doc.add_paragraph("父章节", style="Heading 1")
            source_doc.add_paragraph("待补子节", style="Heading 2")
            source_doc.add_paragraph("尚未成功合并的正文。")
            source_doc.save(source)
            plan = [
                {
                    "status": "MATCHED",
                    "level": 1,
                    "title": "父章节",
                    "chapter_no": "第一章",
                    "chapter_no_flat": "1",
                    "paths": [source.name],
                },
                {
                    "status": "UNMATCHED",
                    "level": 2,
                    "title": "待补子节",
                    "chapter_no": "1.1",
                    "chapter_no_flat": "1.1",
                    "paths": [],
                },
            ]

            with patch.object(merger.Composer, "append", side_effect=RuntimeError("compose failed")):
                stats = merger.merge(template, plan, library, {}, root / "prep", output)
            result = Document(str(output))
            text = "\n".join(paragraph.text for paragraph in result.paragraphs)

        self.assertIn("1.1  待补子节", text)
        self.assertIn("[缺失：待补子节——wiki 无匹配卡片，请人工处理]", text)
        self.assertEqual(stats.get("superseded", 0), 0)

    def test_merger_keeps_going_when_materials_are_missing_or_corrupt(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            library = root / "library"
            valid = library / "valid.docx"
            corrupt = library / "corrupt.docx"
            output = root / "assembled.docx"

            library.mkdir()
            Document().save(template)
            valid_doc = Document()
            valid_doc.add_paragraph("正常素材", style="Heading 2")
            valid_doc.add_paragraph("这是可用的脱敏正文。")
            valid_doc.save(valid)
            corrupt.write_bytes(b"not-a-docx")

            plan = [
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "正常素材",
                    "chapter_no": "1.1",
                    "chapter_no_flat": "1.1",
                    "paths": [valid.name],
                },
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "缺失素材",
                    "chapter_no": "1.2",
                    "chapter_no_flat": "1.2",
                    "paths": ["missing.docx"],
                },
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "损坏素材",
                    "chapter_no": "1.3",
                    "chapter_no_flat": "1.3",
                    "paths": [corrupt.name],
                },
            ]

            stats = merger.merge(template, plan, library, {}, root / "prep", output)
            result = Document(str(output))
            text = "\n".join(paragraph.text for paragraph in result.paragraphs)

        self.assertIn("这是可用的脱敏正文。", text)
        self.assertIn("1.2  缺失素材", text)
        self.assertIn("1.3  损坏素材", text)
        self.assertIn("[缺失：缺失素材——没有可用素材，请补充后重试]", text)
        self.assertIn("[缺失：损坏素材——没有可用素材，请补充后重试]", text)
        self.assertEqual(stats["merged_materials"], 1)
        self.assertEqual(
            stats["warnings"],
            [
                {
                    "code": "MATERIAL_MISSING",
                    "message": "1 份素材不存在，已跳过",
                    "count": 1,
                },
                {
                    "code": "MATERIAL_MERGE_FAILED",
                    "message": "1 份素材处理或合并失败，已跳过",
                    "count": 1,
                },
                {
                    "code": "DIRECTORY_WITHOUT_MATERIAL",
                    "message": "2 个目录节点没有可用素材，已保留标题并插入占位提示",
                    "count": 2,
                },
            ],
        )

    def test_runner_builds_stable_warning_summary_from_plan_and_verify_scan(self) -> None:
        runner = load_assembler_script("run_from_manifest")
        plan = [
            {"status": "MATCHED", "paths": ["valid.docx"]},
            {"status": "UNMATCHED", "paths": []},
            {"status": "NEEDS_REVIEW", "paths": []},
            {"status": "STRUCTURAL", "paths": []},
        ]
        merger_result = {
            "merged_materials": 1,
            "warnings": [
                {"code": "MATERIAL_MISSING", "message": "素材不存在", "count": 1},
                {"code": "MATERIAL_MERGE_FAILED", "message": "素材合并失败", "count": 1},
            ],
        }
        scan = {
            "placeholders": ["[待填写：参数]", "[缺失：章节]"],
            "empty_leaf_headings": ["L2 1.2 空章节"],
            "dup_alerts": ["L2 相邻重复：1.3 标题"],
            "ghost_chapters": [],
            "invalid_h1": ["错误一级标题"],
            "invalid_prefix": [],
        }

        summary, warnings = runner.build_summary_and_warnings(plan, merger_result, scan)

        self.assertEqual(summary["assembledCount"], 1)
        self.assertEqual(summary["unmatchedCount"], 1)
        self.assertEqual(summary["needsReviewCount"], 1)
        self.assertEqual(summary["structuralCount"], 1)
        self.assertEqual(summary["verification"]["placeholderCount"], 2)
        self.assertEqual(summary["verification"]["emptySectionCount"], 1)
        self.assertEqual(summary["verification"]["duplicateHeadingCount"], 1)
        self.assertEqual(summary["verification"]["abnormalHeadingCount"], 1)
        self.assertEqual(summary["warningCount"], sum(item["count"] for item in warnings))
        self.assertEqual(
            {item["code"] for item in warnings},
            {
                "MATERIAL_MISSING",
                "MATERIAL_MERGE_FAILED",
                "DIRECTORY_UNMATCHED",
                "PLACEHOLDER_REMAINS",
                "FORMAT_RISK",
            },
        )
        self.assertTrue(all(set(item) == {"code", "message", "count"} for item in warnings))

    def test_runner_ignores_invalid_intermediate_counts(self) -> None:
        runner = load_assembler_script("run_from_manifest")
        merger_result = {
            "merged_materials": "bad",
            "warnings": [
                {"code": "BAD_TEXT", "message": "非法文本", "count": "bad"},
                {"code": "BAD_NONE", "message": "空值", "count": None},
                {"code": "BAD_BOOL", "message": "布尔值", "count": True},
                {"code": "BAD_NEGATIVE", "message": "负数", "count": -1},
                {"code": "VALID", "message": "合法告警", "count": 2},
            ],
        }
        scan = {
            "placeholders": [],
            "empty_leaf_headings": [],
            "dup_alerts": [],
            "ghost_chapters": [],
            "invalid_h1": [],
            "invalid_prefix": [],
        }

        summary, warnings = runner.build_summary_and_warnings([], merger_result, scan)

        self.assertEqual(summary["assembledCount"], 0)
        self.assertEqual(summary["warningCount"], 2)
        self.assertEqual(warnings, [{"code": "VALID", "message": "合法告警", "count": 2}])


if __name__ == "__main__":
    unittest.main()
