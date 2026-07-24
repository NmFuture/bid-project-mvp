from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class S1ParseRouterScriptTests(unittest.TestCase):
    def router_path(self) -> Path:
        backend_root = Path(__file__).resolve().parents[1]
        return backend_root / "opencode" / "skills" / "s1parse_router.py"

    def test_router_executes_technical_manifest(self) -> None:
        router_path = self.router_path()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "技术招标文件.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# 招标文件",
                        "项目名称：测试技术项目",
                        "招标编号：TECH-2026-001",
                        "招标人：测试招标人",
                        "技术承诺：投标人应承诺满足全部技术规范。",
                    ]
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-TECH-ROUTER",
                        "bidType": "技术标",
                        "parseProfile": "technical",
                        "structuredResultPath": str(output_path),
                        "documents": [
                            {
                                "id": "DOC-1",
                                "name": source_path.name,
                                "sourcePath": str(source_path),
                                "textPath": str(source_path),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(router_path), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            summary = json.loads(completed.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(summary["schemaVersion"], "bid-tender-structured-v1")
            self.assertEqual(payload["structured"]["schemaVersion"], "bid-tender-structured-v1")
            self.assertEqual(payload["structured"]["targetSkill"], "bid-tech-tender-structured-parser")

    def _run_router_json(self, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, str(self.router_path()), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def _submit(self, manifest_path: Path, target_key: str, value: object) -> dict:
        return self._run_router_json("submit", str(manifest_path), target_key, json.dumps(value, ensure_ascii=False))

    def test_router_prepares_business_manifest_then_finalizes_submitted_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "business_tender.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# Business tender",
                        "Project name: Router business project",
                        "Tender No: BUS-2026-001",
                        "Tenderer: Example Tenderer",
                        "Qualification requirements: bidder must be an independent legal person.",
                        "Bidder instructions table",
                        "| No | Name | Content |",
                        "| --- | --- | --- |",
                        "| 1 | Deadline | Submit before 2026-05-06 10:00 |",
                        "Commercial rejection: response is invalid if price exceeds ceiling.",
                        "Business scoring table",
                        "| No | Item | Score | Standard |",
                        "| 1 | Service plan | 2 | Best reasonable plan gets full score. |",
                    ]
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BUSINESS-ROUTER",
                        "bidType": "business",
                        "parseProfile": "business",
                        "structuredResultPath": str(output_path),
                        "documents": [
                            {
                                "id": "DOC-1",
                                "name": source_path.name,
                                "sourcePath": str(source_path),
                                "textPath": str(source_path),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            prepared = self._run_router_json(str(manifest_path))
            self.assertEqual(prepared["schemaVersion"], "bid-business-agentic-nav-v1")
            self.assertEqual(prepared["stage"], "prepared")
            self.assertEqual(prepared["targetSkill"], "bid-business-tender-structured-parser")
            self.assertTrue(Path(prepared["navStorePath"]).is_file())
            self.assertFalse(output_path.exists())

            self._submit(
                manifest_path,
                "projectBasics",
                [
                    {"key": "projectName", "value": "Router business project", "evidenceIds": ["DOC-1:B000002"]},
                    {"key": "tenderNo", "value": "BUS-2026-001", "evidenceIds": ["DOC-1:B000003"]},
                    {"key": "tenderer", "value": "Example Tenderer", "evidenceIds": ["DOC-1:B000004"]},
                    {"key": "projectOwner", "value": "Example project owner", "evidenceIds": ["DOC-1:B000004"]},
                    {"key": "biddingAgency", "value": "Example bidding agency", "evidenceIds": ["DOC-1:B000004"]},
                ],
            )
            self._submit(
                manifest_path,
                "qualificationRequirements",
                [{"content": "bidder must be an independent legal person", "evidenceIds": ["DOC-1:B000005"]}],
            )
            self._submit(
                manifest_path,
                "bidderInstructions",
                [{"clauseNo": "1", "clauseName": "Deadline", "content": "Submit before 2026-05-06 10:00", "evidenceIds": ["DOC-1:T0001:R0002"]}],
            )
            self._submit(
                manifest_path,
                "commercialRejectionClauses",
                [{"riskLevel": "high", "content": "response is invalid if price exceeds ceiling", "evidenceIds": ["DOC-1:B000008"]}],
            )
            self._submit(
                manifest_path,
                "businessScoringCriteria",
                [{"scoringItem": "Service plan", "score": "2", "scoringStandard": "Best reasonable plan gets full score.", "evidenceIds": ["DOC-1:T0002:R0002"]}],
            )
            self._submit(
                manifest_path,
                "projectDates",
                {"endDate": "2026-05-06 10:00", "evidenceIds": ["DOC-1:T0001:R0002"]},
            )
            finalized = self._run_router_json("finalize", str(manifest_path))

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            structured = payload["structured"]
            self.assertEqual(finalized["schemaVersion"], "bid-business-tender-structured-v1")
            self.assertEqual(structured["targetSkill"], "bid-business-tender-structured-parser")
            self.assertEqual(structured["workflow"]["mode"], "opencode-agentic-navigation")
            self.assertNotIn("candidatePackagePath", structured["workflow"])
            self.assertNotIn("reviewPlanPath", structured["workflow"])
            self.assertNotIn("aiTasksDir", structured["workflow"])
            self.assertEqual(structured["fieldGroups"]["projectBasics"][0]["value"], "Router business project")
            basics_by_key = {row["key"]: row for row in structured["fieldGroups"]["projectBasics"]}
            self.assertEqual(basics_by_key["projectUnit"]["value"], "Example project owner")
            self.assertEqual(basics_by_key["tenderAgency"]["value"], "Example bidding agency")
            self.assertEqual(structured["fieldGroups"]["qualificationRequirements"][0]["content"], "bidder must be an independent legal person")
            self.assertEqual(structured["fieldGroups"]["bidderInstructions"][0]["clauseName"], "Deadline")
            self.assertEqual(structured["fieldGroups"]["commercialRejectionClauses"][0]["content"], "response is invalid if price exceeds ceiling")
            self.assertEqual(structured["scoringCriteria"]["business"][0]["scoringItem"], "Service plan")
            self.assertEqual(structured["projectDates"]["endDate"], "2026-05-06 10:00")

    def test_business_router_finalizes_submitted_qualification_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "business_qualification.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# Business tender",
                        "Qualification requirements",
                        "The bidder must be registered in China as an independent legal person.",
                        "The bidder must provide three similar project contracts.",
                        "This project does not accept consortium bidding.",
                    ]
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BUSINESS-QUAL-ROUTER",
                        "bidType": "business",
                        "parseProfile": "business",
                        "structuredResultPath": str(output_path),
                        "documents": [
                            {
                                "id": "DOC-1",
                                "name": source_path.name,
                                "sourcePath": str(source_path),
                                "textPath": str(source_path),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self._run_router_json(str(manifest_path))
            self._submit(
                manifest_path,
                "qualificationRequirements",
                [
                    {"content": "registered in China as an independent legal person", "evidenceIds": ["DOC-1:B000003"]},
                    {"content": "provide three similar project contracts", "evidenceIds": ["DOC-1:B000004"]},
                    {"content": "does not accept consortium bidding", "evidenceIds": ["DOC-1:B000005"]},
                ],
            )
            self._run_router_json("finalize", str(manifest_path))

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            rows = payload["structured"]["fieldGroups"]["qualificationRequirements"]
            contents = "\n".join(row["content"] for row in rows)
            self.assertIn("registered in China", contents)
            self.assertIn("three similar project contracts", contents)
            self.assertIn("does not accept consortium", contents)
            self.assertEqual(payload["structured"]["workflow"]["mode"], "opencode-agentic-navigation")

    def test_business_s1parse_router_still_targets_structured_parser_when_template_extraction_path_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            combined_path = temp_dir / "combined.txt"
            structured_path = temp_dir / "structured.json"
            extraction_path = temp_dir / "business_template_extraction.json"
            manifest_path = temp_dir / "s1_parse_manifest.json"
            combined_path.write_text("Business scoring Enterprise performance 5 points", encoding="utf-8")
            structured_path.write_text(json.dumps({"structured": {"appendices": []}}, ensure_ascii=False), encoding="utf-8")
            extraction_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-business-template-extractor-v1",
                        "appendices": [],
                        "summary": {"templateCount": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "proj-1",
                        "parseProfile": "business",
                        "combinedTextPath": str(combined_path),
                        "structuredResultPath": str(structured_path),
                        "businessTemplateExtractionPath": str(extraction_path),
                        "documents": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            prepared = self._run_router_json(str(manifest_path))
            self.assertEqual(prepared["targetSkill"], "bid-business-tender-structured-parser")
            self.assertEqual(prepared["schemaVersion"], "bid-business-agentic-nav-v1")
            finalized = self._run_router_json("finalize", str(manifest_path))

            payload = json.loads(structured_path.read_text(encoding="utf-8"))
            self.assertEqual(finalized["targetSkill"], "bid-business-tender-structured-parser")
            self.assertEqual(payload["structured"]["targetSkill"], "bid-business-tender-structured-parser")
            self.assertEqual(payload["structured"]["schemaVersion"], "bid-business-tender-structured-v1")
