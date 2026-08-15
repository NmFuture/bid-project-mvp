from __future__ import annotations

import json
from unittest.mock import patch
from docx import Document
from app.core.config import settings
from app.services import parsing as parsing_service
from app.services.store import store

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    build_business_attachment_templates_docx_bytes,
    build_business_multilevel_template_cluster_docx_bytes,
    complete_parse_for_tests,
    field_by_key,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_business_template_extractor_appendices_are_kept_when_structured_parser_returns_empty(self) -> None:
        project_id = self.create_business_project()
        template_docx = settings.parsed_dir / project_id / "business_template_extraction" / "templates" / "TPL-0001.docx"

        def fake_template_extractor(
            *,
            project_id: str,
            documents: list[dict],
            project_dir: Path,
            progress_callback=None,
            cancel_check=None,
        ):
            template_docx.parent.mkdir(parents=True, exist_ok=True)
            Document().save(str(template_docx))
            payload = {
                "schemaVersion": "bid-business-template-extractor-v1",
                "skillName": "bid-business-template-extractor",
                "summary": {"templateCount": 1},
                "appendices": [
                    {
                        "id": "APPX-0001",
                        "title": "Single Block Placeholder",
                        "artifactType": "business_attachment_template",
                        "templateType": "attachment_placeholder",
                        "status": "generated",
                        "docxPath": str(template_docx),
                        "sourceDocumentId": documents[0]["id"],
                        "sourceDocumentName": documents[0]["name"],
                        "extractionMode": "business_template_extractor_skill",
                    }
                ],
            }
            output_path = project_dir / "business_template_extraction" / "business_template_extraction.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return payload["appendices"], payload, ""

        def fake_structured_parser(skill_manifest_path: Path, **kwargs):
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
                            "business-tender.docx",
                            build_business_attachment_templates_docx_bytes(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ),
                    )
                ],
            )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["title"], "Single Block Placeholder")
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")



    def test_business_skill_result_is_authoritative_without_local_semantic_backfill(self) -> None:
        project_id = self.create_business_project()
        validation_report_path = settings.parsed_dir / project_id / "agentic_validation_report.json"
        validation_report_path.parent.mkdir(parents=True, exist_ok=True)
        validation_report_path.write_text(
            json.dumps({"schemaVersion": "bid-business-agentic-validation-v1", "status": "passed"}, ensure_ascii=False),
            encoding="utf-8",
        )
        tender = "\n".join(
            [
                "# Business tender",
                "Project name: backend must not backfill this",
                "Bid deadline: 2026-03-18 09:30",
                "Qualification: bidder must be an independent legal person.",
            ]
        ).encode("utf-8")
        skill_payload = {
            "items": [],
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
                "scoringCriteria": {},
                "fieldGroups": {},
                "coverage": [],
                "projectDates": {},
                "projectFactFields": [],
            },
        }

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._run_parse_skill",
            return_value=(skill_payload, ""),
        ), patch(
            "app.services.parsing._transform_to_business_contract",
            wraps=parsing_service._transform_to_business_contract,
        ) as local_transform:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("business-tender.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(local_transform.call_count, 0)
        structured = response.json()["structured"]
        self.assertEqual(structured["fieldGroups"], {})
        self.assertEqual(structured["projectDates"], {})



    def test_technical_skill_result_does_not_backfill_project_basics_from_local_parser(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "华能蒙东新能源公司赤峰市200万千瓦自建调峰能力风光储多能互补一体化+荒漠治理基地项目（翁牛特旗120万千瓦风电项目区）",
                "风力发电机组（不含塔架）及附属设备采购",
                "招 标 文 件",
                "招标编号：HNZB2025-12-1-382-01",
                "招标人：华能内蒙古东部能源有限公司",
                "项目单位：华能翁牛特旗新能源有限公司",
                "招标代理机构：中国华能集团有限公司北京睿采数动科技分公司",
                "投标文件递交截止时间：2026年01月26日15时00分",
                "本项目招标范围为整套风力发电机组及塔筒内所有必要设备。",
            ]
        ).encode("utf-8")

        def fake_run_parse_skill(_skill_manifest_path: Path, **kwargs):
            skill_result = json.loads(json.dumps(kwargs["local_result"], ensure_ascii=False))
            project_basics = skill_result["structured"].setdefault("fieldGroups", {}).setdefault("projectBasics", [])
            for row in project_basics:
                row["value"] = ""
                row["status"] = "missing"
                row["sourceFile"] = ""
                row["sourceDocumentId"] = ""
                row["section"] = ""
                row["evidence"] = ""
                row["evidenceLocation"] = ""
            skill_result["structured"].pop("projectDates", None)
            skill_result["structured"]["projectFactFields"] = project_basics
            skill_result["structured"]["workflow"] = {
                "stage": "finalized",
                "mode": "opencode-agentic-navigation",
                "submittedTargetCount": 2,
                "missingTargets": [],
                "validationErrors": [],
            }
            return skill_result, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_run_parse_skill,
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("招标文件-技术规范.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        project_basics = structured["fieldGroups"]["projectBasics"]
        self.assertEqual(field_by_key(project_basics, "projectName")["value"], "")
        self.assertEqual(field_by_key(project_basics, "tenderNo")["value"], "")
        self.assertEqual(field_by_key(project_basics, "projectUnit")["value"], "")
        self.assertEqual(field_by_key(project_basics, "tenderer")["value"], "")
        self.assertEqual(field_by_key(project_basics, "tenderAgency")["value"], "")
        self.assertEqual(field_by_key(project_basics, "bidDeadline")["value"], "")
        self.assertNotIn("projectDates", structured)
        self.assertEqual(structured["projectFactFields"], project_basics)
        self.assertNotIn("localProjectBasicsMerged", structured["workflow"])



    def test_technical_skill_result_updates_project_deadline_from_project_basics_without_project_dates(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "都匀市盛黔风电场风力发电机组及附属设备采购项目",
                "招标编号：PC-0307-26J1-FG0002",
                "招标人：都匀盛黔新能源有限公司",
                "投标文件递交截止时间：2026年05月06日10时00分",
                "本项目招标范围为整套风力发电机组及塔筒内所有必要设备。",
            ]
        ).encode("utf-8")

        def fake_run_parse_skill(_skill_manifest_path: Path, **kwargs):
            skill_result = json.loads(json.dumps(kwargs["local_result"], ensure_ascii=False))
            project_basics = [
                {"key": "projectName", "fieldKey": "projectName", "label": "项目名称", "value": "都匀市盛黔风电场风力发电机组及附属设备采购项目"},
                {"key": "tenderNo", "fieldKey": "tenderNo", "label": "招标编号", "value": "PC-0307-26J1-FG0002"},
                {"key": "projectUnit", "fieldKey": "projectUnit", "label": "项目单位", "value": ""},
                {"key": "tenderer", "fieldKey": "tenderer", "label": "招标人", "value": "都匀盛黔新能源有限公司"},
                {"key": "tenderAgency", "fieldKey": "tenderAgency", "label": "招标代理机构", "value": ""},
                {"key": "bidDeadline", "fieldKey": "bidDeadline", "label": "递交截止时间", "status": "found", "value": "2026-05-06 10:00"},
            ]
            structured = skill_result.setdefault("structured", {})
            structured.setdefault("fieldGroups", {})["projectBasics"] = project_basics
            structured.pop("projectDates", None)
            structured["projectFactFields"] = project_basics
            structured["workflow"] = {
                "stage": "finalized",
                "mode": "opencode-agentic-navigation",
                "submittedTargetCount": 2,
                "missingTargets": [],
                "validationErrors": [],
            }
            return skill_result, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_run_parse_skill,
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("招标文件-技术规范.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        project_basics = structured["fieldGroups"]["projectBasics"]
        self.assertEqual(field_by_key(project_basics, "bidDeadline")["value"], "2026-05-06 10:00")
        self.assertNotIn("projectDates", structured)
        self.assertNotIn("projectDates", payload["summary"])

        project = store._require(project_id)
        self.assertEqual(project["endDate"], "2026-05-06 10:00")
        self.assertEqual(project["deadline"], "2026-05-06 10:00")



    def test_technical_parse_results_preserves_agentic_project_basics_without_text_repair(self) -> None:
        project_id = self.create_project()
        parse_dir = settings.parsed_dir / project_id
        parse_dir.mkdir(parents=True, exist_ok=True)
        text_path = parse_dir / "TEN-1.txt"
        text_path.write_text(
            "\n".join(
                [
                    "华能蒙东新能源公司赤峰市200万千瓦自建调峰能力风光储多能互补一体化+荒漠治理基地项目（翁牛特旗120万千瓦风电项目区）",
                    "风力发电机组（不含塔架）及附属设备采购",
                    "招 标 文 件",
                    "招标编号：HNZB2025-12-1-382-01",
                    "招标人",
                    "：",
                    "华能内蒙古东部能源有限公司",
                    "管理单位",
                    "：",
                    "华能翁牛特旗新能源有限公司",
                    "招标代理机构",
                    "：",
                    "中国华能集团有限公司北京睿采数动科技分公司",
                ]
            ),
            encoding="utf-8",
        )
        structured_path = parse_dir / "s1_structured_result.json"
        empty_basics = [
            {"key": key, "label": label, "value": "", "status": "missing", "fieldKey": key}
            for key, label in (
                ("projectName", "项目名称"),
                ("tenderNo", "招标编号"),
                ("projectUnit", "项目单位"),
                ("tenderer", "招标人"),
                ("tenderAgency", "招标代理机构"),
                ("bidDeadline", "递交截止时间"),
            )
        ]
        structured_path.write_text(
            json.dumps(
                {
                    "items": [],
                    "structured": {
                        "schemaVersion": "bid-tender-structured-v1",
                        "workflow": {"stage": "finalized", "mode": "opencode-agentic-navigation"},
                        "fieldGroups": {"projectBasics": empty_basics},
                        "projectDates": {"startDate": "", "endDate": ""},
                        "projectFactFields": empty_basics,
                        "technicalInterpretation": {"items": [], "summary": {"total": 0}},
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        complete_parse_for_tests(
            project_id,
            [{"id": "TEN-1", "name": "招标文件-技术规范.md", "size_label": "1 KB"}],
            [],
            summary={"fileCount": 1, "extractedCount": 0, "textLength": 0, "warnings": []},
            parse_storage={
                "structuredResultPath": str(structured_path),
                "documents": [
                    {
                        "id": "TEN-1",
                        "name": "招标文件-技术规范.md",
                        "textPath": str(text_path),
                    }
                ],
                "items": [],
                "structured": {
                    "schemaVersion": "bid-tender-structured-v1",
                    "workflow": {"stage": "finalized", "mode": "opencode-agentic-navigation"},
                    "fieldGroups": {"projectBasics": empty_basics},
                    "projectDates": {"startDate": "", "endDate": ""},
                    "projectFactFields": empty_basics,
                    "technicalInterpretation": {"items": [], "summary": {"total": 0}},
                },
            },
        )

        response = self.client.get(self.parse_results_url(project_id))

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        project_basics = structured["fieldGroups"]["projectBasics"]
        self.assertEqual(field_by_key(project_basics, "projectName")["value"], "")
        self.assertEqual(field_by_key(project_basics, "tenderer")["value"], "")
        self.assertEqual(field_by_key(project_basics, "projectUnit")["value"], "")
        self.assertNotIn("localProjectBasicsMerged", structured["workflow"])
        persisted = json.loads(structured_path.read_text(encoding="utf-8"))
        self.assertEqual(
            field_by_key(persisted["structured"]["fieldGroups"]["projectBasics"], "tenderAgency")["value"],
            "",
        )



    def test_business_template_extractor_appendices_survive_skill_result_merge(self) -> None:
        project_id = self.create_business_project()
        template_docx = settings.parsed_dir / project_id / "business_template_extraction" / "templates" / "TPL-0001.docx"

        def fake_template_extractor(
            *,
            project_id: str,
            documents: list[dict],
            project_dir: Path,
            progress_callback=None,
            cancel_check=None,
        ):
            template_docx.parent.mkdir(parents=True, exist_ok=True)
            Document().save(str(template_docx))
            appendix = {
                "id": "APPX-0001",
                "title": "A投标价格总表",
                "artifactType": "business_attachment_template",
                "templateType": "price_table",
                "status": "generated",
                "docxPath": str(template_docx),
                "sourceDocumentId": documents[0]["id"],
                "sourceDocumentName": documents[0]["name"],
                "extractionMode": "business_template_extractor_skill",
            }
            payload = {
                "schemaVersion": "bid-business-template-extractor-v1",
                "skillName": "bid-business-template-extractor",
                "summary": {"templateCount": 1},
                "appendices": [appendix],
            }
            output_path = project_dir / "business_template_extraction" / "business_template_extraction.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return [appendix], payload, ""

        with patch("app.services.parsing.run_business_template_extractor", side_effect=fake_template_extractor):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[
                    (
                        "tenderFiles",
                        (
                            "商务招标文件.docx",
                            build_business_multilevel_template_cluster_docx_bytes(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ),
                    )
                ],
            )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertTrue(all(item["extractionMode"] == "business_template_extractor_skill" for item in appendices))
        self.assertTrue(any("A投标价格总表" in item["title"] for item in appendices))



    def test_business_template_extractor_empty_result_does_not_fallback_to_legacy(self) -> None:
        project_id = self.create_business_project()
        with patch(
            "app.services.parsing.run_business_template_extractor",
            return_value=([], {"summary": {"templateCount": 0}, "appendices": []}, "template skill empty"),
        ), patch(
            "app.services.parsing._extract_docx_appendices",
            wraps=parsing_service._extract_docx_appendices,
        ) as docx_appendix_extractor, patch(
            "app.services.parsing._extract_markdown_appendices",
            wraps=parsing_service._extract_markdown_appendices,
        ) as markdown_appendix_extractor, patch(
            "app.services.parsing._extract_text_business_appendices",
            wraps=parsing_service._extract_text_business_appendices,
        ) as text_appendix_extractor:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[
                    (
                        "tenderFiles",
                        (
                            "商务招标文件.docx",
                            build_business_attachment_templates_docx_bytes(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ),
                    )
                ],
            )
        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(appendices, [])
        self.assertEqual(docx_appendix_extractor.call_count, 0)
        self.assertEqual(markdown_appendix_extractor.call_count, 0)
        self.assertEqual(text_appendix_extractor.call_count, 0)



    def test_business_template_agent_failure_warning_does_not_allow_preview_fallback(self) -> None:
        warning = "商务模板提取 Agent 未完成，未启用脚本兜底：opencode incomplete/stalled"

        self.assertFalse(parsing_service._business_template_extractor_allows_preview_fallback(warning))



    def test_business_template_missing_agent_decision_warning_does_not_allow_preview_fallback(self) -> None:
        warning = "模板边界 Agent 裁决未完成，未启用脚本兜底：缺少 Agent 裁决文件：llm_boundary_decisions.json"

        self.assertFalse(parsing_service._business_template_extractor_allows_preview_fallback(warning))



    def test_business_template_empty_skill_result_does_not_allow_preview_fallback(self) -> None:
        warning = "商务模板提取 skill 未识别到模板。"

        self.assertFalse(parsing_service._business_template_extractor_allows_preview_fallback(warning))
