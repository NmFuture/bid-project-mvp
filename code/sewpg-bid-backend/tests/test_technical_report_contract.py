from __future__ import annotations

import ast
import json
import types
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TECH_ASSEMBLY = BACKEND_ROOT / "app" / "services" / "tech_assembly.py"
OPENCODE_CLIENT = BACKEND_ROOT / "app" / "services" / "opencode_client.py"
ASSEMBLER_SKILL = BACKEND_ROOT / "opencode" / "skills" / "bid-tech-assembler" / "SKILL.md"
ASSEMBLER_CONSTRAINTS = (
    BACKEND_ROOT / "opencode" / "skills" / "bid-tech-assembler" / "references" / "constraints.md"
)
CLEANER_SKILL = BACKEND_ROOT / "opencode" / "skills" / "bid-tech-format-cleaner" / "SKILL.md"


def load_isolated_function(
    path: Path,
    name: str,
    *,
    class_name: str | None = None,
    dependencies: tuple[str, ...] = (),
    namespace_overrides: dict | None = None,
):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    scope = tree.body
    if class_name:
        owner = next(node for node in scope if isinstance(node, ast.ClassDef) and node.name == class_name)
        scope = owner.body
    requested_names = {name, *dependencies}
    functions = [
        node for node in scope if isinstance(node, ast.FunctionDef) and node.name in requested_names
    ]
    function = next(node for node in functions if node.name == name)
    function.decorator_list = []
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *functions],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {"Path": Path, "json": json, **(namespace_overrides or {})}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


class TechnicalReportContractTests(unittest.TestCase):
    def test_format_cleaner_failure_keeps_stable_structured_shape(self) -> None:
        run_cleaner = load_isolated_function(
            TECH_ASSEMBLY,
            "_run_tech_format_cleaner_step",
            namespace_overrides={
                "TECH_FORMAT_CLEANER_SKILL_NAME": "bid-tech-format-cleaner",
                "ASSEMBLER_SKILL_DIR": Path("assembler"),
                "_prepare_tech_format_outline": lambda _toc, work: work / "outline.json",
                "_run_local_tech_format_cleaner": lambda _manifest: (_ for _ in ()).throw(RuntimeError("offline")),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_cleaner(
                project={},
                toc_json_path=root / "toc.json",
                assembled_path=root / "assembled.docx",
                work_dir=root,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["outputFile"], str(root / "assembled.docx"))
        self.assertEqual(result["reportFile"], "")
        self.assertEqual(result["summary"], {})
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["opencodeOutput"], {})

    def test_service_helpers_filter_dirty_plan_cards_and_numeric_summary(self) -> None:
        optional_helpers = ("_iter_dicts", "_safe_int")
        load_json_list = load_isolated_function(
            TECH_ASSEMBLY, "_load_json_list", dependencies=optional_helpers
        )
        sections_from_plan = load_isolated_function(
            TECH_ASSEMBLY, "_sections_from_plan", dependencies=optional_helpers
        )
        build_coverage = load_isolated_function(
            TECH_ASSEMBLY,
            "_build_material_coverage",
            dependencies=("_coverage_card_used", "_coverage_path_keys", *optional_helpers),
            namespace_overrides={"defaultdict": defaultdict},
        )
        build_fallback = load_isolated_function(
            TECH_ASSEMBLY, "_build_fallback_content", dependencies=optional_helpers
        )
        dirty_plan = [
            None,
            "bad",
            [],
            {"toc_idx": 1, "level": "bad", "title": "错误层级", "status": "MATCHED"},
            {
                "toc_idx": 2,
                "level": 1,
                "chapter_no": "1",
                "title": "技术方案",
                "status": "MATCHED",
                "paths": ["material.docx"],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            plan_file = Path(tmp) / "plan.json"
            plan_file.write_text(json.dumps(dirty_plan, ensure_ascii=False), encoding="utf-8")
            loaded_plan = load_json_list(plan_file)

        sections = sections_from_plan(dirty_plan)
        coverage = build_coverage(
            dirty_plan,
            [None, "bad", [], {"id": "M-1", "title": "素材", "path": "material.docx", "available": True}],
        )
        content = build_fallback(
            dirty_plan,
            {"total": "bad", "warningCount": "bad"},
            [{"code": "FORMAT_RISK", "message": "结构风险", "count": 1}],
        )

        self.assertEqual(len(loaded_plan), 2)
        self.assertEqual([item["title"] for item in sections], ["技术方案"])
        self.assertEqual(coverage["fullCover"], 1)
        self.assertIn("技术方案", content)
        self.assertIn("结构风险", content)

    def test_skill_documents_forbid_markdown_reports_and_keep_empty_compatibility_fields(self) -> None:
        documents = {
            path: path.read_text(encoding="utf-8")
            for path in (ASSEMBLER_SKILL, ASSEMBLER_CONSTRAINTS, CLEANER_SKILL)
        }
        combined = "\n".join(documents.values())

        for report_name in ("assembly_report.md", "needs_review.md", "tech_format_clean_report.md"):
            self.assertNotIn(report_name, combined)
        self.assertNotIn("写入原 Markdown 报告", combined)
        self.assertIn("紧凑 JSON", documents[ASSEMBLER_CONSTRAINTS])
        self.assertIn("不生成 Markdown", documents[ASSEMBLER_CONSTRAINTS])
        self.assertIn("`assemblyReport`、`needsReview` 保留但固定为空字符串", documents[ASSEMBLER_SKILL])
        self.assertIn("`reportFile` 固定为空字符串", documents[CLEANER_SKILL])

    def test_fallback_content_uses_plan_summary_and_warnings_without_report_paths(self) -> None:
        build_fallback = load_isolated_function(
            TECH_ASSEMBLY,
            "_build_fallback_content",
            dependencies=("_iter_dicts", "_safe_int"),
        )
        content = build_fallback(
            [{"chapter_no": "1", "title": "技术方案", "status": "STRUCTURAL"}],
            {"total": 1, "warningCount": 1},
            [{"code": "FORMAT_RISK", "message": "存在 1 项结构风险", "count": 1}],
        )

        self.assertIn("技术方案", content)
        self.assertIn("存在 1 项结构风险", content)
        self.assertNotIn("assembly_report", content)
        self.assertNotIn("needs_review", content)

    def test_repair_examples_keep_technical_reports_empty_and_business_reports_unchanged(self) -> None:
        repair = load_isolated_function(OPENCODE_CLIENT, "_repair_json_payload", class_name="OpencodeClient")
        prompts: list[str] = []
        fake_client = types.SimpleNamespace(
            create_session=lambda _title: {"id": "repair"},
            send_prompt=lambda _session_id, prompt: (
                prompts.append(prompt) or {"parts": [{"type": "text", "text": "{}"}]}
            ),
        )

        repair(fake_client, "broken", "assembly")
        repair(fake_client, "broken", "business_format")

        technical_prompt, business_prompt = prompts
        self.assertIn('"assemblyReport":""', technical_prompt)
        self.assertIn('"needsReview":""', technical_prompt)
        self.assertIn('"summary":', technical_prompt)
        self.assertIn('"warnings":[', technical_prompt)
        self.assertNotIn("assembly_report.md", technical_prompt)
        self.assertNotIn("needs_review.md", technical_prompt)
        self.assertIn("business_format_clean_report.md", business_prompt)


if __name__ == "__main__":
    unittest.main()
