from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from docx import Document
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services import parsing as parsing_service

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    build_business_attachment_templates_docx_bytes,
    build_business_section_tree_docx_bytes,
    build_business_section_tree_toc_docx_bytes,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_business_tender_parse_prompt_allows_agentic_navigation_workflow(self) -> None:
        prompt = parsing_service._build_tender_parse_prompt(
            Path("C:/tmp/s1_parse_manifest.json"),
            parsing_service.BUSINESS_PARSE_PROFILE,
        )

        self.assertIn("s1parse prepare", prompt)
        self.assertIn("s1parse overview", prompt)
        self.assertIn("--page-size 60", prompt)
        self.assertIn("s1parse search", prompt)
        self.assertIn("--limit 40", prompt)
        self.assertIn("s1parse read", prompt)
        self.assertIn("--max-chars 4000", prompt)
        self.assertIn("s1parse window", prompt)
        self.assertIn("s1parse table", prompt)
        self.assertIn("--rows 1-24", prompt)
        self.assertIn("--max-chars 8000", prompt)
        self.assertIn("s1parse submit", prompt)
        self.assertIn("s1parse validate", prompt)
        self.assertIn("s1parse status", prompt)
        self.assertIn("s1parse finalize", prompt)
        self.assertIn("opencode-agentic-navigation", prompt)
        self.assertIn("manifest.structuredResultPath", prompt)
        self.assertIn("解析中间产物的大 JSON", prompt)
        self.assertIn("s1parse 小输出导航命令", prompt)
        self.assertNotIn("candidate_package.json", prompt)
        self.assertNotIn("review_plan.json", prompt)
        self.assertNotIn("ai_tasks/**", prompt)
        self.assertNotIn("s1parse tasks", prompt)
        self.assertNotIn("s1parse task ", prompt)
        self.assertNotIn("s1parse decision-all", prompt)
        self.assertNotIn("s1parse decision-set", prompt)
        self.assertNotIn("s1parse validate-decision", prompt)
        self.assertNotIn("decisionPath", prompt)
        self.assertIn("opencode", prompt)
        self.assertIn("read", prompt)
        self.assertIn("Task/subagent", prompt)
        self.assertIn("evidenceId", prompt)
        self.assertIn("finalize", prompt)
        self.assertIn("表格类内容必须完整读取后再提交", prompt)
        self.assertIn("不得基于预览、summary 或局部行推断", prompt)
        self.assertNotIn("Bash 工具执行下面命令", prompt)
        self.assertLess(len(prompt), 2500)
        self.assertNotIn("必须覆盖这些目标", prompt)
        self.assertNotIn("完整性硬约束", prompt)
        self.assertNotIn("原文具备的条款必须逐条提交", prompt)
        self.assertNotIn("每条资格要求必须包含 applicableScope", prompt)
        self.assertNotIn("商务部分评分项目、分值、评分标准", prompt)



    def test_business_tender_parser_skill_declares_frontend_delivery_contract(self) -> None:
        skill_path = (
            Path(__file__).resolve().parents[1]
            / "opencode"
            / "skills"
            / "bid-business-tender-structured-parser"
            / "SKILL.md"
        )
        content = skill_path.read_text(encoding="utf-8")

        self.assertLess(len(content), 5000)
        self.assertIn("s1parse overview <manifest> --page 1 --page-size 60", content)
        self.assertIn('s1parse search <manifest> "<query>" --limit 40', content)
        self.assertIn("s1parse read <manifest> <evidenceId> --mode summary --max-chars 4000", content)
        self.assertIn("s1parse table <manifest> <tableId> --rows 1-24 --max-chars 8000", content)
        self.assertIn("表格类内容必须完整读取后再提交", content)
        self.assertIn("不得基于预览、summary 或局部行推断", content)
        self.assertIn("你是招投标专家，不是关键词匹配器", content)
        self.assertIn("只提交前端清单需要的业务字段", content)
        self.assertIn("资格要求和商务评分的序号不需要提交", content)
        self.assertIn("项目基础信息", content)
        self.assertIn("投标人资格要求", content)
        self.assertIn("投标人须知前附表", content)
        self.assertIn("商务废标项", content)
        self.assertIn("商务评分标准", content)
        self.assertIn("不要为了前端不用的字段额外提交证明材料要求", content)



    def test_business_template_skill_runs_before_structured_parser_and_passes_manifest(self) -> None:
        project_id = self.create_business_project()
        calls: list[str] = []
        seen_manifest: dict[str, object] = {}
        seen_cancel_check: dict[str, bool] = {}

        def fake_section_tree(documents: list[dict], project_dir: Path):
            calls.append("section_tree")
            tree_path = project_dir / "business_section_tree.json"
            payload = {
                "schemaVersion": "bid-business-section-tree-v1",
                "maxLevel": 3,
                "documents": [{"id": documents[0]["id"], "name": documents[0]["name"]}],
                "nodes": [],
                "toc": {"detected": False, "entries": []},
                "validation": {
                    "status": "not_applicable",
                    "tocEntryCount": 0,
                    "matchedTocEntryCount": 0,
                    "unmatchedTocTitles": [],
                },
                "summary": {
                    "documentCount": 1,
                    "nodeCount": 0,
                    "tocEntryCount": 0,
                    "validationStatus": "not_applicable",
                    "warnings": [],
                },
            }
            tree_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return tree_path, payload

        def fake_template_extractor(
            *,
            project_id: str,
            documents: list[dict],
            project_dir: Path,
            progress_callback=None,
            cancel_check,
        ):
            calls.append("template")
            seen_cancel_check["callable"] = callable(cancel_check)
            output_dir = project_dir / "business_template_extraction"
            template_dir = output_dir / "templates"
            template_dir.mkdir(parents=True, exist_ok=True)
            template_docx = template_dir / "TPL-0001.docx"
            Document().save(str(template_docx))
            payload = {
                "schemaVersion": "bid-business-template-extractor-v1",
                "skillName": "bid-business-template-extractor",
                "summary": {"templateCount": 1},
                "appendices": [
                    {
                        "id": "APPX-0001",
                        "title": "Bid Letter",
                        "artifactType": "business_attachment_template",
                        "templateType": "bid_letter",
                        "status": "generated",
                        "docxPath": str(template_docx),
                        "sourceDocumentId": documents[0]["id"],
                        "sourceDocumentName": documents[0]["name"],
                        "extractionMode": "business_template_extractor_skill",
                    }
                ],
            }
            extraction_path = output_dir / "business_template_extraction.json"
            extraction_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return payload["appendices"], payload, ""

        def fake_structured_parser(skill_manifest_path: Path, **kwargs):
            calls.append("structured")
            manifest = json.loads(skill_manifest_path.read_text(encoding="utf-8"))
            seen_manifest.update(manifest)
            extraction_path = Path(str(manifest.get("businessTemplateExtractionPath") or ""))
            appendices = []
            if extraction_path.is_file():
                extraction_payload = json.loads(extraction_path.read_text(encoding="utf-8"))
                appendices = extraction_payload.get("appendices") or []
            return {
                "items": [],
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "targetSkill": "bid-business-tender-structured-parser",
                    "mode": "opencode-skill",
                    "sourceDocuments": [],
                    "scoringCriteria": {"business": []},
                    "fieldGroups": {},
                    "requirementPresence": {},
                    "coverage": [],
                    "projectDates": {"endDate": ""},
                    "appendices": appendices,
                    "commitmentLetters": [],
                    "commitmentClues": [],
                    "projectFactFields": [],
                    "categoryCounts": {},
                },
            }, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing.write_business_section_tree",
            side_effect=fake_section_tree,
        ), patch(
            "app.services.parsing.run_business_template_extractor",
            side_effect=fake_template_extractor,
            create=True,
        ), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_structured_parser,
        ), patch(
            "app.services.parsing._needs_business_s1_finalize_guard",
            return_value=False,
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[
                    (
                        "tenderFiles",
                        (
                            "business-tender.docx",
                            build_business_attachment_templates_docx_bytes(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ),
                    )
                ],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["section_tree", "template", "structured"])
        self.assertTrue(seen_cancel_check["callable"])
        extraction_path = Path(str(seen_manifest.get("businessTemplateExtractionPath") or ""))
        self.assertTrue(extraction_path.is_file())
        self.assertEqual(seen_manifest.get("businessTemplateExtractionSummary"), {"templateCount": 1})
        self.assertTrue(Path(str(seen_manifest.get("businessSectionTreePath") or "")).is_file())
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")



    def test_business_section_tree_is_ready_before_structured_parser(self) -> None:
        project_id = self.create_business_project()
        calls: list[str] = []
        seen_manifest: dict[str, object] = {}

        def fake_template_extractor(
            *,
            project_id: str,
            documents: list[dict],
            project_dir: Path,
            progress_callback=None,
            cancel_check=None,
        ):
            calls.append("template")
            return [], {"schemaVersion": "bid-business-template-extractor-v1", "summary": {"templateCount": 0}}, ""

        def fake_structured_parser(skill_manifest_path: Path, **kwargs):
            calls.append("structured")
            manifest = json.loads(skill_manifest_path.read_text(encoding="utf-8"))
            seen_manifest.update(manifest)
            tree_path = Path(str(manifest.get("businessSectionTreePath") or ""))
            self.assertTrue(tree_path.is_file(), manifest)
            tree_payload = json.loads(tree_path.read_text(encoding="utf-8"))
            self.assertEqual(tree_payload["schemaVersion"], "bid-business-section-tree-v1")
            titles = [node["title"] for node in tree_payload["nodes"]]
            self.assertIn("3. 供应商资格要求", titles)
            self.assertIn("供应商须知前附表", titles)
            self.assertIn("商务评分标准", titles)
            qualification_node = next(node for node in tree_payload["nodes"] if node["title"] == "3. 供应商资格要求")
            self.assertLessEqual(qualification_node["contentStartLine"], qualification_node["endLine"])
            self.assertEqual(qualification_node["documentId"], manifest["documents"][0]["id"])
            return {
                "items": [],
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "targetSkill": "bid-business-tender-structured-parser",
                    "mode": "opencode-skill",
                    "sourceDocuments": [],
                    "scoringCriteria": {"business": []},
                    "fieldGroups": {},
                    "requirementPresence": {},
                    "coverage": [],
                    "projectDates": {"endDate": ""},
                    "appendices": [],
                    "commitmentLetters": [],
                    "commitmentClues": [],
                    "projectFactFields": [],
                    "categoryCounts": {},
                },
            }, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing.run_business_template_extractor",
            side_effect=fake_template_extractor,
            create=True,
        ), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_structured_parser,
        ), patch(
            "app.services.parsing._needs_business_s1_finalize_guard",
            return_value=False,
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[
                    (
                        "tenderFiles",
                        (
                            "business-section-tree.docx",
                            build_business_section_tree_docx_bytes(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ),
                    )
                ],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["template", "structured"])
        self.assertTrue(Path(str(seen_manifest.get("businessSectionTreePath") or "")).is_file())



    def test_business_section_tree_keeps_plain_toc_lines_out_of_nodes(self) -> None:
        project_id = self.create_business_project()
        seen_tree: dict[str, object] = {}

        def fake_template_extractor(
            *,
            project_id: str,
            documents: list[dict],
            project_dir: Path,
            progress_callback=None,
            cancel_check=None,
        ):
            return [], {"schemaVersion": "bid-business-template-extractor-v1", "summary": {"templateCount": 0}}, ""

        def fake_structured_parser(skill_manifest_path: Path, **kwargs):
            manifest = json.loads(skill_manifest_path.read_text(encoding="utf-8"))
            tree_path = Path(str(manifest.get("businessSectionTreePath") or ""))
            seen_tree.update(json.loads(tree_path.read_text(encoding="utf-8")))
            return {
                "items": [],
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "targetSkill": "bid-business-tender-structured-parser",
                    "mode": "opencode-skill",
                    "sourceDocuments": [],
                    "scoringCriteria": {"business": []},
                    "fieldGroups": {},
                    "requirementPresence": {},
                    "coverage": [],
                    "projectDates": {"endDate": ""},
                    "appendices": [],
                    "commitmentLetters": [],
                    "commitmentClues": [],
                    "projectFactFields": [],
                    "categoryCounts": {},
                },
            }, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing.run_business_template_extractor",
            side_effect=fake_template_extractor,
            create=True,
        ), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_structured_parser,
        ), patch(
            "app.services.parsing._needs_business_s1_finalize_guard",
            return_value=False,
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[
                    (
                        "tenderFiles",
                        (
                            "business-section-tree-toc.docx",
                            build_business_section_tree_toc_docx_bytes(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ),
                    )
                ],
            )

        self.assertEqual(response.status_code, 200)
        titles = [node["title"] for node in seen_tree["nodes"]]
        self.assertNotIn("第一章 招标公告 2", titles)
        self.assertNotIn("3. 供应商资格要求 5", titles)
        self.assertIn("3. 供应商资格要求", titles)
        self.assertEqual(seen_tree["validation"]["status"], "passed")



    def test_business_finalized_skill_workflow_is_not_rewritten_by_local_transform(self) -> None:
        project_id = self.create_business_project()
        validation_report_path = settings.parsed_dir / project_id / "agentic_validation_report.json"
        validation_report_path.parent.mkdir(parents=True, exist_ok=True)
        validation_report_path.write_text(
            json.dumps({"schemaVersion": "bid-business-agentic-validation-v1", "status": "passed"}, ensure_ascii=False),
            encoding="utf-8",
        )
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：后端覆盖回归测试项目",
                "第一章 招标公告",
                "3. 投标人资格要求",
                "3.1 本地旧转换不应覆盖 finalized skill 结果。",
            ]
        ).encode("utf-8")

        skill_payload = {
            "items": [
                {
                    "id": "AI-ITEM-0001",
                    "category": "资格要求",
                    "content": "AI 已接收的资格要求",
                    "sourceFile": "商务招标文件.md",
                    "sourceDocumentId": "DOC-AI",
                    "section": "第一章 招标公告 > 3. 投标人资格要求",
                    "evidence": "AI 已接收的资格要求",
                    "evidenceLocation": "DOC-AI:L4",
                }
            ],
            "structured": {
                "schemaVersion": "bid-business-tender-structured-v1",
                "targetSkill": "bid-business-tender-structured-parser",
                "mode": "opencode-skill",
                "workflow": {
                    "stage": "finalized",
                    "aiReviewTrusted": True,
                    "mode": "opencode-agentic-navigation",
                    "validationReportPath": str(validation_report_path),
                },
                "sourceDocuments": [],
                "scoringCriteria": {"business": [], "price": [], "compliance": [], "lcoe": []},
                "fieldGroups": {
                    "projectBasics": [],
                    "businessResponse": [],
                    "qualificationSupport": [],
                    "qualificationRequirements": [
                        {
                            "id": "QUAL-AI-0001",
                            "content": "AI 已接收的资格要求",
                            "applicableScope": "全部标段",
                            "sourceText": "商务招标文件.md：第一章招标公告第3条",
                            "sourceFile": "商务招标文件.md",
                            "sourceDocumentId": "DOC-AI",
                            "section": "第一章 招标公告 > 3. 投标人资格要求",
                            "evidence": "AI 已接收的资格要求",
                            "evidenceLocation": "DOC-AI:L4",
                            "evidenceIds": ["DOC-AI:L4"],
                        }
                    ],
                    "bidderInstructions": [],
                    "commercialRejectionClauses": [],
                    "commitmentRequirements": [],
                },
                "requirementPresence": {},
                "coverage": [],
                "projectDates": {"startDate": "", "endDate": ""},
                "appendices": [],
                "commitmentLetters": [],
                "commitmentClues": [],
                "projectFactFields": [],
                "categoryCounts": {},
            },
        }

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._run_parse_skill",
            return_value=(skill_payload, ""),
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        self.assertEqual(structured["workflow"]["stage"], "finalized")
        self.assertTrue(structured["workflow"]["aiReviewTrusted"])
        qualification_text = "\n".join(
            row["content"] for row in structured["fieldGroups"]["qualificationRequirements"]
        )
        self.assertIn("AI 已接收的资格要求", qualification_text)



    def test_business_parse_manifest_does_not_include_script_ai_review_config(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：AI 审查配置注入测试项目",
                "第一章 招标公告",
                "3. 投标人资格要求",
                "3.1 投标人须为境内合法注册的独立法人。",
            ]
        ).encode("utf-8")
        captured_manifest: dict[str, Any] = {}

        def fake_run_parse_skill(skill_manifest_path: Path, **_kwargs: Any):
            captured_manifest.update(json.loads(skill_manifest_path.read_text(encoding="utf-8")))
            return _kwargs["local_result"], "unit-test stops before opencode"

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.system_settings.system_settings_service.get_opencode_model_config_sync",
            return_value={
                "enabled": True,
                "baseUrl": "https://llm.example.com/v1",
                "apiKey": "llm-secret",
                "model": "deepseek-v4-pro",
                "modelId": "deepseek-v4-pro",
                "timeoutMs": 45000,
                "maxTokens": 12000,
            },
        ), patch("app.services.parsing._run_parse_skill", side_effect=fake_run_parse_skill):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("aiReviewMode", captured_manifest)
        self.assertNotIn("aiReviewBaseUrl", captured_manifest)
        self.assertNotIn("aiReviewApiKey", captured_manifest)
        self.assertNotIn("aiReviewModel", captured_manifest)
        self.assertNotIn("aiReviewTimeoutSec", captured_manifest)
        self.assertNotIn("aiReviewMaxTokens", captured_manifest)



    def test_business_skill_failure_fails_parse_without_local_fallback_result(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# Business tender",
                "Project name: local fallback must not become completed result",
                "Bid deadline: 2026-03-18 09:30",
            ]
        ).encode("utf-8")

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=RuntimeError("unit-test skill failure"),
        ):
            client = TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
            try:
                response = client.post(
                    self.parse_results_url(project_id, "/upload-and-run"),
                    files=[("tenderFiles", ("business-tender.md", tender, "text/markdown"))],
                )
            finally:
                client.close()

        self.assertGreaterEqual(response.status_code, 500)
        progress = self.client.get(self.parse_results_url(project_id, "/progress")).json()
        self.assertEqual(progress["status"], "failed")
        self.assertIn("unit-test skill failure", progress["summary"])



    def test_business_agentic_prepared_workflow_triggers_backend_finalize_guard(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# Business tender",
                "Project name: prepared workflow guard project",
                "Qualification: bidder must be an independent legal person.",
            ]
        ).encode("utf-8")

        def fake_run_parse_skill(skill_manifest_path: Path, **kwargs):
            parse_dir = skill_manifest_path.parent
            prepared = json.loads(json.dumps(kwargs["local_result"], ensure_ascii=False))
            prepared["structured"]["mode"] = "opencode-skill"
            prepared["structured"]["workflow"] = {
                "stage": "prepared",
                "mode": "opencode-agentic-navigation",
                "navStorePath": str(parse_dir / "s1_nav.sqlite"),
                "documentMapPath": str(parse_dir / "document_map.json"),
                "submissionPath": str(parse_dir / "agentic_submissions.json"),
                "validationReportPath": str(parse_dir / "validation_report.json"),
                "submittedTargetCount": 0,
                "missingTargets": ["qualificationRequirements"],
                "validationErrors": [],
            }
            return prepared, ""

        def fake_finalize(skill_manifest_path: Path, structured_result: dict, profile):
            finalized = json.loads(json.dumps(structured_result, ensure_ascii=False))
            validation_report_path = skill_manifest_path.parent / "validation_report.json"
            validation_report_path.write_text(
                json.dumps({"schemaVersion": "bid-business-agentic-validation-v1", "status": "passed"}, ensure_ascii=False),
                encoding="utf-8",
            )
            finalized["structured"]["mode"] = "opencode-skill"
            finalized["structured"]["workflow"] = {
                "stage": "finalized",
                "mode": "opencode-agentic-navigation",
                "navStorePath": str(skill_manifest_path.parent / "s1_nav.sqlite"),
                "documentMapPath": str(skill_manifest_path.parent / "document_map.json"),
                "submissionPath": str(skill_manifest_path.parent / "agentic_submissions.json"),
                "validationReportPath": str(validation_report_path),
                "submittedTargetCount": 1,
                "missingTargets": [],
                "validationErrors": [],
            }
            finalized["structured"].setdefault("fieldGroups", {})["qualificationRequirements"] = [
                {"content": "finalize guard qualification", "evidenceIds": ["DOC-1:B000001"]}
            ]
            return finalized, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_run_parse_skill,
        ), patch("app.services.parsing._finalize_business_s1_result", side_effect=fake_finalize) as finalize_guard:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("business-tender.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(finalize_guard.call_count, 1)
        structured = response.json()["structured"]
        self.assertEqual(structured["workflow"]["stage"], "finalized")
        self.assertEqual(structured["workflow"]["mode"], "opencode-agentic-navigation")
        qualification_text = "\n".join(row["content"] for row in structured["fieldGroups"]["qualificationRequirements"])
        self.assertIn("finalize guard qualification", qualification_text)



    def test_business_finalized_agentic_workflow_without_validation_report_triggers_finalize_guard(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# Business tender",
                "Project name: validation report guard project",
                "Qualification: bidder must be an independent legal person.",
            ]
        ).encode("utf-8")

        def fake_run_parse_skill(skill_manifest_path: Path, **kwargs):
            parse_dir = skill_manifest_path.parent
            validation_report_path = parse_dir / "validation_report.json"
            validation_report_path.unlink(missing_ok=True)
            finalized = json.loads(json.dumps(kwargs["local_result"], ensure_ascii=False))
            finalized["structured"]["mode"] = "opencode-skill"
            finalized["structured"]["workflow"] = {
                "stage": "finalized",
                "mode": "opencode-agentic-navigation",
                "navStorePath": str(parse_dir / "s1_nav.sqlite"),
                "documentMapPath": str(parse_dir / "document_map.json"),
                "submissionPath": str(parse_dir / "agentic_submissions.json"),
                "validationReportPath": str(validation_report_path),
                "submittedTargetCount": 5,
                "missingTargets": [],
                "validationErrors": [],
            }
            return finalized, ""

        def fake_finalize(skill_manifest_path: Path, structured_result: dict, profile):
            finalized = json.loads(json.dumps(structured_result, ensure_ascii=False))
            validation_report_path = skill_manifest_path.parent / "validation_report.json"
            validation_report_path.write_text(
                json.dumps({"schemaVersion": "bid-business-agentic-validation-v1", "status": "passed"}, ensure_ascii=False),
                encoding="utf-8",
            )
            finalized["structured"]["workflow"]["validationReportPath"] = str(validation_report_path)
            return finalized, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_run_parse_skill,
        ), patch("app.services.parsing._finalize_business_s1_result", side_effect=fake_finalize) as finalize_guard:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("business-tender.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(finalize_guard.call_count, 1)
        workflow = response.json()["structured"]["workflow"]
        self.assertEqual(workflow["stage"], "finalized")
        self.assertEqual(workflow["mode"], "opencode-agentic-navigation")
        self.assertTrue(Path(workflow["validationReportPath"]).is_file())



    def test_business_finalize_guard_preserves_opencode_trace_and_separates_backend_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parse_dir = Path(tmp)
            structured_path = parse_dir / "s1_structured_result.json"
            manifest_path = parse_dir / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps({"structuredResultPath": str(structured_path)}, ensure_ascii=False),
                encoding="utf-8",
            )
            original_trace = {
                "status": "received",
                "sessionId": "ses-prj0017",
                "parts": [{"type": "tool", "text": "read /data/parsed/PRJ-0017/document_map.json running"}],
            }
            prepared_result = {
                "items": [],
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "targetSkill": "bid-business-tender-structured-parser",
                    "mode": "opencode-skill",
                    "workflow": {
                        "stage": "prepared",
                        "mode": "opencode-agentic-navigation",
                        "navStorePath": str(parse_dir / "s1_nav.sqlite"),
                        "documentMapPath": str(parse_dir / "document_map.json"),
                        "submissionPath": str(parse_dir / "agentic_submissions.json"),
                        "validationReportPath": str(parse_dir / "validation_report.json"),
                    },
                    "sourceDocuments": [],
                    "fieldGroups": {},
                    "scoringCriteria": {"business": []},
                    "coverage": [],
                    "projectDates": {"startDate": "", "endDate": ""},
                    "appendices": [],
                    "opencodeOutput": original_trace,
                },
            }
            finalized_result = json.loads(json.dumps(prepared_result, ensure_ascii=False))
            finalized_result["structured"]["workflow"]["stage"] = "finalized"
            finalized_result["structured"]["workflow"]["submittedTargetCount"] = 0
            structured_path.write_text(json.dumps(finalized_result, ensure_ascii=False), encoding="utf-8")

            class Completed:
                returncode = 0
                stdout = '{"summary":{"workflowStage":"finalized","submittedTargetCount":0}}'
                stderr = ""

            with patch("app.services.parsing.subprocess.run", return_value=Completed()):
                result, warning = parsing_service._finalize_business_s1_result(
                    manifest_path,
                    prepared_result,
                    parsing_service.BUSINESS_PARSE_PROFILE,
                )

        self.assertEqual(warning, "")
        structured = result["structured"]
        self.assertEqual(structured["opencodeOutput"], original_trace)
        self.assertEqual(
            structured["backendFinalizeOutput"]["stdout"],
            '{"summary":{"workflowStage":"finalized","submittedTargetCount":0}}',
        )
        self.assertTrue(structured["workflow"]["backendFinalizeGuardApplied"])



    def test_business_run_parse_skill_raises_when_opencode_never_produces_skill_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "s1_parse_manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            local_result = {
                "items": [{"id": "LOCAL-1", "title": "local fallback should not be returned"}],
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "targetSkill": "bid-business-tender-structured-parser",
                    "mode": "local-structured-parser",
                    "sourceDocuments": [],
                    "fieldGroups": {},
                    "scoringCriteria": {},
                    "coverage": [],
                    "projectDates": {"startDate": "", "endDate": ""},
                },
            }
            error = RuntimeError("unit-test opencode failed before finalize")
            error.opencode_trace = {
                "status": "stalled",
                "sessionId": "ses-business-no-finalize",
                "agentStatus": "stalled",
                "lastTool": "bash",
                "lastToolStatus": "running",
                "failureReason": "s1parse finalize did not complete",
            }

            with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
                "app.services.parsing.OpencodeEngine.generate_tender_parse_with_trace",
                side_effect=error,
            ):
                with self.assertRaisesRegex(RuntimeError, "S1 商务解析 Skill 调用失败"):
                    parsing_service._run_parse_skill(
                        manifest_path,
                        local_result=local_result,
                        profile=parsing_service.BUSINESS_PARSE_PROFILE,
                    )



    def test_technical_run_parse_skill_preserves_stalled_opencode_trace_on_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "s1_parse_manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            local_result = {
                "items": [],
                "structured": {
                    "schemaVersion": "bid-tender-structured-v1",
                    "targetSkill": "bid-tech-tender-structured-parser",
                    "mode": "local-structured-parser",
                    "sourceDocuments": [],
                    "fieldGroups": {},
                    "scoringCriteria": {},
                    "coverage": [],
                    "projectDates": {"startDate": "", "endDate": ""},
                },
            }
            error = RuntimeError("opencode incomplete/stalled: sessionId=ses-prj0017")
            error.opencode_trace = {
                "status": "stalled",
                "sessionId": "ses-prj0017",
                "agentStatus": "stalled",
                "lastTool": "read",
                "lastToolStatus": "running",
                "lastToolInput": {"filePath": "/data/parsed/PRJ-0017/document_map.json"},
                "failureReason": "read document_map.json running",
            }

            with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
                "app.services.parse_s1_skill._run_technical_sharded_parse_skill",
                side_effect=RuntimeError("unit-test sharded parse failed"),
            ), patch(
                "app.services.parsing.OpencodeEngine.generate_tender_parse_with_trace",
                side_effect=error,
            ):
                progress_events = []
                result, warning = parsing_service._run_parse_skill(
                    manifest_path,
                    local_result=local_result,
                    profile=parsing_service.TECHNICAL_PARSE_PROFILE,
                    progress_callback=lambda event, details: progress_events.append((event, details)),
                )

        structured = result["structured"]
        self.assertIn("Skill", warning)
        self.assertIn("opencode incomplete/stalled", warning)
        self.assertEqual(structured["opencodeOutput"]["sessionId"], "ses-prj0017")
        self.assertEqual(structured["workflow"]["opencodeSessionId"], "ses-prj0017")
        self.assertEqual(structured["workflow"]["opencodeAgentStatus"], "stalled")
        self.assertEqual(structured["workflow"]["opencodeLastTool"], "read")
        self.assertEqual(structured["workflow"]["opencodeLastToolStatus"], "running")
        self.assertIn("document_map.json", json.dumps(structured["opencodeOutput"]["lastToolInput"], ensure_ascii=False))
        self.assertEqual(progress_events[-1][0], "opencode_delta")
        self.assertEqual(progress_events[-1][1]["sessionId"], "ses-prj0017")



    def test_run_parse_skill_retries_once_after_incomplete_opencode_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "s1_parse_manifest.json"
            structured_path = Path(tmp) / "s1_structured_result.json"
            manifest_path.write_text(json.dumps({"structuredResultPath": str(structured_path)}), encoding="utf-8")
            local_result = {
                "items": [],
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "targetSkill": "bid-business-tender-structured-parser",
                    "mode": "local-structured-parser",
                    "sourceDocuments": [],
                    "fieldGroups": {},
                    "scoringCriteria": {},
                    "coverage": [],
                    "projectDates": {"startDate": "", "endDate": ""},
                },
            }
            final_result = {
                "items": [],
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "targetSkill": "bid-business-tender-structured-parser",
                    "mode": "opencode-skill",
                    "workflow": {
                        "stage": "finalized",
                        "mode": "opencode-agentic-navigation",
                    },
                    "fieldGroups": {"qualificationRequirements": [{"content": "retry success"}]},
                    "scoringCriteria": {"business": []},
                    "coverage": [],
                    "projectDates": {},
                },
            }
            structured_path.write_text(json.dumps(final_result, ensure_ascii=False), encoding="utf-8")
            error = RuntimeError("opencode incomplete/stalled: sessionId=ses-first")
            error.opencode_trace = {
                "status": "stalled",
                "sessionId": "ses-first",
                "agentStatus": "stalled",
                "lastTool": "bash",
                "lastToolStatus": "completed",
                "failureReason": "did not complete s1parse finalize",
            }

            calls: list[str] = []

            def fake_generate(prompt: str, **_kwargs: Any) -> dict[str, Any]:
                calls.append(prompt)
                if len(calls) == 1:
                    raise error
                return {"outputFile": str(structured_path)}

            with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
                "app.services.parsing.OpencodeEngine.generate_tender_parse_with_trace",
                side_effect=fake_generate,
            ):
                result, warning = parsing_service._run_parse_skill(
                    manifest_path,
                    local_result=local_result,
                    profile=parsing_service.BUSINESS_PARSE_PROFILE,
                )

        self.assertEqual(warning, "")
        self.assertEqual(len(calls), 2)
        self.assertIn("s1parse status", calls[1])
        self.assertIn("s1parse finalize", calls[1])
        structured = result["structured"]
        self.assertEqual(structured["mode"], "opencode-skill")
        self.assertEqual(structured["fieldGroups"]["qualificationRequirements"][0]["content"], "retry success")
        attempts = structured["workflow"]["opencodeAttempts"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["sessionId"], "ses-first")
        self.assertEqual(attempts[0]["status"], "stalled")
        self.assertEqual(attempts[1]["status"], "succeeded")
        self.assertEqual(attempts[1]["attempt"], 2)
