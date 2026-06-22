from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document

from app.services.bid_parse_service import technical_parse_service
from app.services.store import store


class TechnicalAgenticParserTests(unittest.TestCase):
    def setUp(self) -> None:
        store.reset_for_tests(clear_persistent=False)

    def runner_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "opencode"
            / "skills"
            / "bid-tech-tender-structured-parser"
            / "scripts"
            / "run_from_manifest.py"
        )

    def skill_path(self) -> Path:
        return self.runner_path().parents[1] / "SKILL.md"

    def write_sample_docx(self, root: Path) -> tuple[Path, Path, Path]:
        source_path = root / "technical_tender.docx"
        output_path = root / "s1_structured_result.json"
        manifest_path = root / "s1_parse_manifest.json"
        doc = Document()
        doc.add_paragraph("华能赤峰市翁牛特旗等6个风电项目共计1998兆瓦风力发电机组及其附属设备集中采购预招标")
        doc.add_paragraph("第一章 招标公告")
        doc.add_paragraph("本项目招标范围为整套风力发电机组及塔筒内所有必要设备，包含主控柜、通讯电缆、电力电缆等配套。")
        doc.add_paragraph("投标人应按第三卷 技术规范书和技术规范专用部分要求提供完整技术方案。")
        doc.add_paragraph("投标机型应满足高电压穿越、低电压穿越、一次调频、仿真建模及频率、电压、功率调节能力。")
        doc.save(source_path)
        manifest_path.write_text(
            json.dumps(
                {
                    "projectId": "PRJ-TECH-AGENTIC-UNIT",
                    "bidType": "技术标",
                    "parseProfile": "technical",
                    "structuredResultPath": str(output_path),
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": source_path.name,
                            "sourcePath": str(source_path),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return source_path, manifest_path, output_path

    def run_s1parse(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(self.runner_path()), *args],
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    def test_skill_md_contains_the_fixed_excel_checklist(self) -> None:
        content = self.skill_path().read_text(encoding="utf-8")

        self.assertIn("技术标解读清单", content)
        self.assertIn("设备选型适配", content)
        self.assertIn("CMS振动监测系统", content)
        self.assertIn("二次安防系统", content)
        checklist_rows = [
            line
            for line in content.splitlines()
            if line.startswith("| ") and line.count("|") >= 4 and line.split("|")[1].strip().isdigit()
        ]
        self.assertEqual(len(checklist_rows), 58)

    def test_prepare_builds_navigation_index_and_exposes_checklist_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, manifest_path, _ = self.write_sample_docx(root)

            completed = self.run_s1parse("prepare", str(manifest_path))

            summary = json.loads(completed.stdout)
            self.assertEqual(summary["stage"], "prepared")
            self.assertEqual(summary["checklistCount"], 58)
            nav_path = Path(summary["navStorePath"])
            self.assertTrue(nav_path.is_file())
            conn = sqlite3.connect(nav_path)
            evidence_count = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            conn.close()
            self.assertGreaterEqual(evidence_count, 5)

    def test_submit_validate_finalize_writes_technical_interpretation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, manifest_path, output_path = self.write_sample_docx(root)
            self.run_s1parse("prepare", str(manifest_path))
            self.run_s1parse(
                "submit",
                str(manifest_path),
                "technicalInterpretation",
                json.dumps(
                    [
                        {
                            "rowNo": 6,
                            "status": "found",
                            "conclusion": "招标文件明确要求整套风力发电机组及塔筒内必要设备，并列明主控柜、通讯电缆、电力电缆等配套。",
                            "evidenceSummary": "整套风力发电机组及塔筒内所有必要设备。",
                            "evidenceIds": ["DOC-1:B000003"],
                        },
                        {
                            "rowNo": 21,
                            "status": "partial",
                            "conclusion": "现有文件明确涉网控制能力要求，但型式试验报告等细节需继续核对技术规范专用部分。",
                            "evidenceSummary": "高低电压穿越、一次调频、仿真建模等能力。",
                            "neededSourceName": "第三卷 技术规范书和技术规范专用部分",
                            "evidenceIds": ["DOC-1:B000005"],
                        },
                        {
                            "rowNo": 49,
                            "status": "needs_spec",
                            "conclusion": "当前第一卷/第三卷正文未列明 CMS 测点数量，需要按原文提到的技术规范专用部分核对。",
                            "evidenceSummary": "招标文件指向技术规范书和技术规范专用部分。",
                            "neededSourceName": "第三卷 技术规范书和技术规范专用部分",
                            "evidenceIds": ["DOC-1:B000004"],
                        },
                    ],
                    ensure_ascii=False,
                ),
            )

            validation = json.loads(self.run_s1parse("validate", str(manifest_path)).stdout)
            finalize = json.loads(self.run_s1parse("finalize", str(manifest_path)).stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(validation["status"], "passed")
            self.assertEqual(validation["checklistCount"], 58)
            self.assertGreaterEqual(validation["evidenceCount"], 3)
            self.assertEqual(finalize["summary"]["workflowStage"], "finalized")
            structured = payload["structured"]
            interpretation = structured["technicalInterpretation"]
            self.assertEqual(interpretation["checklistVersion"], "excel-technical-2026-06-16")
            self.assertEqual(interpretation["summary"]["total"], 58)
            self.assertEqual(len(interpretation["items"]), 58)
            by_row = {item["rowNo"]: item for item in interpretation["items"]}
            self.assertEqual(by_row[6]["displayGroup"], "供货范围界定")
            self.assertEqual(by_row[6]["status"], "found")
            self.assertEqual(by_row[49]["status"], "needs_spec")
            self.assertEqual(by_row[49]["neededSourceName"], "第三卷 技术规范书和技术规范专用部分")
            self.assertTrue(by_row[6]["evidenceRefs"])
            self.assertIn("整套风力发电机组", by_row[6]["evidenceRefs"][0]["text"])
            self.assertEqual(structured["workflow"]["mode"], "opencode-agentic-navigation")

    def test_validate_fails_for_found_item_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, manifest_path, _ = self.write_sample_docx(root)
            self.run_s1parse("prepare", str(manifest_path))
            self.run_s1parse(
                "submit",
                str(manifest_path),
                "technicalInterpretation",
                json.dumps(
                    [
                        {
                            "rowNo": 6,
                            "status": "found",
                            "conclusion": "有明确供货范围。",
                        }
                    ],
                    ensure_ascii=False,
                ),
            )

            validation = json.loads(self.run_s1parse("validate", str(manifest_path), check=False).stdout)
            codes = {item["code"] for item in validation["validationErrors"]}

            self.assertEqual(validation["status"], "failed")
            self.assertIn("missing_evidence_for_positive_status", codes)

    def test_validate_fails_for_needs_spec_without_source_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, manifest_path, _ = self.write_sample_docx(root)
            self.run_s1parse("prepare", str(manifest_path))
            self.run_s1parse(
                "submit",
                str(manifest_path),
                "technicalInterpretation",
                json.dumps(
                    [
                        {
                            "rowNo": 49,
                            "status": "needs_spec",
                            "conclusion": "需要进一步核对。",
                            "evidenceIds": ["DOC-1:B000004"],
                        }
                    ],
                    ensure_ascii=False,
                ),
            )

            validation = json.loads(self.run_s1parse("validate", str(manifest_path), check=False).stdout)
            codes = {item["code"] for item in validation["validationErrors"]}

            self.assertEqual(validation["status"], "failed")
            self.assertIn("missing_needed_source_name", codes)

    def test_results_materializes_technical_evidence_refs_from_structured_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, manifest_path, output_path = self.write_sample_docx(root)
            self.run_s1parse("prepare", str(manifest_path))
            self.run_s1parse(
                "submit",
                str(manifest_path),
                "technicalInterpretation",
                json.dumps(
                    [
                        {
                            "rowNo": 6,
                            "status": "found",
                            "conclusion": "招标文件要求整套风力发电机组及配套设备。",
                            "evidenceIds": ["DOC-1:B000003"],
                        }
                    ],
                    ensure_ascii=False,
                ),
            )
            self.run_s1parse("finalize", str(manifest_path))
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            first_item = payload["structured"]["technicalInterpretation"]["items"][0]
            first_item["evidenceRefs"] = [{"id": "DOC-1:B000003"}]
            payload["items"][0]["evidenceRefs"] = [{"id": "DOC-1:B000003"}]
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            project = store.create_project({"name": "技术标证据物化测试", "bidType": "技术标"})
            project_id = project["id"]
            technical_parse_service.complete_parse(
                project_id,
                [{"id": "TEN-1", "name": "technical_tender.docx", "size_label": "1 KB"}],
                [],
                summary={"fileCount": 1, "extractedCount": 1, "textLength": 0, "warnings": []},
                parse_storage={
                    "structuredResultPath": str(output_path),
                    "items": [],
                    "structured": {},
                },
            )

            result = asyncio.run(technical_parse_service.results(project_id))

            item = result["structured"]["technicalInterpretation"]["items"][0]
            self.assertEqual(item["evidenceRefs"][0]["id"], "DOC-1:B000003")
            self.assertIn("风力发电机组", item["evidenceRefs"][0]["text"])
            self.assertEqual(result["items"][0]["evidenceRefs"][0]["text"], item["evidenceRefs"][0]["text"])
