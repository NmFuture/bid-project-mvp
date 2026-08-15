from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch
from docx import Document
from app.core.config import settings
from app.services.store import store

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    complete_parse_for_tests,
    field_by_key,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_business_parse_results_refreshes_finalized_structured_file_before_returning(self) -> None:
        project_id = self.create_business_project()
        structured_path = settings.parsed_dir / project_id / "s1_structured_result.json"
        structured_path.parent.mkdir(parents=True, exist_ok=True)
        structured_path.write_text(
            json.dumps(
                {
                    "items": [],
                    "structured": {
                        "schemaVersion": "bid-business-tender-structured-v1",
                        "workflow": {"stage": "finalized", "mode": "opencode-agentic-navigation"},
                        "fieldGroups": {
                            "qualificationRequirements": [
                                {
                                    "content": "供应商须为入围供应商。",
                                    "evidenceIds": ["TEN-1:B000089"],
                                }
                            ],
                            "bidderInstructions": [],
                            "commercialRejectionClauses": [],
                            "projectBasics": [],
                        },
                        "scoringCriteria": {"business": []},
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        complete_parse_for_tests(
            project_id,
            [{"id": "TEN-1", "name": "商务招标文件.docx", "size_label": "1.0 MB"}],
            [],
            summary={"fileCount": 1, "extractedCount": 0, "textLength": 0, "warnings": []},
            parse_storage={
                "items": [],
                "structuredResultPath": str(structured_path),
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "workflow": {"stage": "finalized", "mode": "opencode-agentic-navigation"},
                    "fieldGroups": {
                        "qualificationRequirements": [
                            {
                                "content": "供应商须为入围供应商。",
                                "__evidenceIds": ["TEN-1:B000089"],
                            }
                        ],
                        "bidderInstructions": [],
                        "commercialRejectionClauses": [],
                        "projectBasics": [],
                    },
                    "scoringCriteria": {"business": []},
                },
            },
        )

        response = self.client.get(self.parse_results_url(project_id))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("__evidenceIds", text)
        qualification = payload["structured"]["fieldGroups"]["qualificationRequirements"][0]
        self.assertEqual(qualification["evidenceIds"], ["TEN-1:B000089"])

        project = store._require(project_id)
        persisted_text = json.dumps(project["parse_result"], ensure_ascii=False)
        self.assertNotIn("__evidenceIds", persisted_text)
        self.assertEqual(
            project["parse_storage"]["structured"]["fieldGroups"]["qualificationRequirements"][0]["evidenceIds"],
            ["TEN-1:B000089"],
        )



    def test_business_parse_results_hydrates_template_appendices_when_structured_file_omits_them(self) -> None:
        project_id = self.create_business_project()
        parse_dir = settings.parsed_dir / project_id
        structured_path = parse_dir / "s1_structured_result.json"
        extraction_path = parse_dir / "business_template_extraction" / "business_template_extraction.json"
        template_docx = extraction_path.parent / "templates" / "TPL-0001.docx"
        template_docx.parent.mkdir(parents=True, exist_ok=True)
        Document().save(str(template_docx))
        structured_path.parent.mkdir(parents=True, exist_ok=True)
        structured_path.write_text(
            json.dumps(
                {
                    "items": [],
                    "structured": {
                        "schemaVersion": "bid-business-tender-structured-v1",
                        "workflow": {"stage": "finalized", "mode": "opencode-agentic-navigation"},
                        "fieldGroups": {"projectBasics": []},
                        "scoringCriteria": {"business": []},
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        extraction_path.parent.mkdir(parents=True, exist_ok=True)
        extraction_path.write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-v1",
                    "skillName": "bid-business-template-extractor",
                    "summary": {"templateCount": 1},
                    "appendices": [
                        {
                            "id": "APPX-0001",
                            "title": "Bid Letter Template",
                            "evidence": "Bid Letter Template",
                            "artifactType": "business_attachment_template",
                            "templateType": "bid_letter",
                            "status": "generated",
                            "docxPath": str(template_docx),
                            "sourceDocumentId": "TEN-1",
                            "sourceDocumentName": "business-tender.docx",
                            "extractionMode": "business_template_extractor_skill",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        complete_parse_for_tests(
            project_id,
            [{"id": "TEN-1", "name": "business-tender.docx", "size_label": "1.0 MB"}],
            [],
            summary={"fileCount": 1, "extractedCount": 0, "textLength": 0, "warnings": [], "appendixCount": 1},
            parse_storage={
                "items": [],
                "structuredResultPath": str(structured_path),
                "businessTemplateExtractionPath": str(extraction_path),
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "workflow": {"stage": "finalized", "mode": "opencode-agentic-navigation"},
                    "fieldGroups": {"projectBasics": []},
                    "scoringCriteria": {"business": []},
                    "appendices": [
                        {
                            "id": "APPX-0001",
                            "title": "Bid Letter Template",
                            "status": "generated",
                            "docxPath": str(template_docx),
                            "extractionMode": "business_template_extractor_skill",
                        }
                    ],
                },
            },
        )

        response = self.client.get(self.parse_results_url(project_id))

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["title"], "Bid Letter Template")
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")
        project = store._require(project_id)
        self.assertEqual(len(project["parse_result"]["structured"]["appendices"]), 1)
        self.assertEqual(len(project["parse_storage"]["structured"]["appendices"]), 1)



    def test_business_parse_results_materializes_evidence_ids_to_readable_sources(self) -> None:
        project_id = self.create_business_project()
        parse_dir = settings.parsed_dir / project_id
        parse_dir.mkdir(parents=True, exist_ok=True)
        nav_path = parse_dir / "s1_nav.sqlite"
        conn = sqlite3.connect(nav_path)
        try:
            conn.executescript(
                """
                CREATE TABLE evidence (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    body_index INTEGER NOT NULL,
                    table_id TEXT NOT NULL DEFAULT '',
                    row_index INTEGER,
                    col_index INTEGER,
                    text TEXT NOT NULL
                );
                CREATE TABLE blocks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    body_index INTEGER NOT NULL,
                    block_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    heading_path TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE tables (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    body_index INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    heading_path TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.execute(
                "INSERT INTO tables(id, document_id, body_index, title, heading_path) VALUES (?, ?, ?, ?, ?)",
                ("TEN-1:T0003", "TEN-1", 311, "投标人须知前附表", "第二章 投标人须知 > 投标人须知前附表"),
            )
            conn.execute(
                "INSERT INTO blocks(id, document_id, body_index, block_type, text, heading_path) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "TEN-1:B000214",
                    "TEN-1",
                    214,
                    "paragraph",
                    "3.1.1 投标人为中华人民共和国境内合法注册的独立法人或其他组织。",
                    "第一章 招标公告 > 3.1 通用资格条件 > 3.1.1 投标人为中华人民共和国境内合法注册的独立法人或其他组织。",
                ),
            )
            conn.execute(
                "INSERT INTO blocks(id, document_id, body_index, block_type, text, heading_path) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "TEN-1:T0003",
                    "TEN-1",
                    311,
                    "table",
                    "投标人须知前附表",
                    "第二章 投标人须知 > 投标人须知前附表",
                ),
            )
            conn.execute(
                "INSERT INTO blocks(id, document_id, body_index, block_type, text, heading_path) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "TEN-1:B000224",
                    "TEN-1",
                    224,
                    "paragraph",
                    "标段一和标段二：投标人须提供近3年风电机组通过试运行业绩。",
                    "第一章 招标公告 > (6) 法定代表人或单位负责人为同一人的两个及两个以上法人，母公司、全资子公司及其控股公司，不得在同一标段同时投标。",
                ),
            )
            conn.execute(
                "INSERT INTO evidence(id, document_id, kind, body_index, table_id, row_index, col_index, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "TEN-1:B000214",
                    "TEN-1",
                    "paragraph",
                    214,
                    "",
                    None,
                    None,
                    "3.1.1 投标人为中华人民共和国境内合法注册的独立法人或其他组织。",
                ),
            )
            conn.execute(
                "INSERT INTO evidence(id, document_id, kind, body_index, table_id, row_index, col_index, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "TEN-1:T0003:R0004",
                    "TEN-1",
                    "table_row",
                    311,
                    "TEN-1:T0003",
                    4,
                    None,
                    "1.1.4 | 招标项目名称 | 华能赤峰风电项目",
                ),
            )
            conn.execute(
                "INSERT INTO evidence(id, document_id, kind, body_index, table_id, row_index, col_index, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "TEN-1:B000224",
                    "TEN-1",
                    "paragraph",
                    224,
                    "",
                    None,
                    None,
                    "标段一和标段二：投标人须提供近3年风电机组通过试运行业绩。",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        structured_path = parse_dir / "s1_structured_result.json"
        structured = {
            "schemaVersion": "bid-business-tender-structured-v1",
            "sourceDocuments": [
                {
                    "id": "TEN-1",
                    "name": "招标文件-华能赤峰风电项目招标文件.docx",
                    "sourcePath": "/data/uploads/PRJ/tender.docx",
                    "textPath": "/data/parsed/PRJ/TEN-1.txt",
                }
            ],
            "workflow": {
                "stage": "finalized",
                "mode": "opencode-agentic-navigation",
                "navStorePath": str(nav_path),
            },
            "fieldGroups": {
                "projectBasics": [
                    {
                        "key": "projectName",
                        "label": "项目名称",
                        "value": "华能赤峰风电项目",
                        "evidenceIds": ["TEN-1:T0003:R0004"],
                        "evidenceLocation": "表格第4行",
                        "sourceText": "招标文件-华能赤峰风电项目招标文件.docx / 第二章 投标人须知 > 投标人须知前附表 / 表格第4行",
                    }
                ],
                "qualificationRequirements": [
                    {
                        "content": "投标人为中华人民共和国境内合法注册的独立法人或其他组织。",
                        "evidenceIds": ["TEN-1:B000214"],
                        "evidenceLocation": "正文第214段",
                        "sourceText": "招标文件-华能赤峰风电项目招标文件.docx / 第一章 招标公告 > 3.1 通用资格条件 / 正文第214段",
                    },
                    {
                        "content": "标段一和标段二：投标人须提供近3年风电机组通过试运行业绩。",
                        "evidenceIds": ["TEN-1:B000224"],
                    }
                ],
                "bidderInstructions": [],
                "commercialRejectionClauses": [],
            },
            "scoringCriteria": {"business": []},
        }
        structured_path.write_text(
            json.dumps({"items": [], "structured": structured}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        complete_parse_for_tests(
            project_id,
            [{"id": "TEN-1", "name": "招标文件-华能赤峰风电项目招标文件.docx", "size_label": "1.0 MB"}],
            [],
            summary={"fileCount": 1, "extractedCount": 0, "textLength": 0, "warnings": []},
            parse_storage={
                "items": [],
                "structuredResultPath": str(structured_path),
                "structured": structured,
            },
        )

        response = self.client.get(self.parse_results_url(project_id))

        self.assertEqual(response.status_code, 200)
        field_groups = response.json()["structured"]["fieldGroups"]
        project_name = field_by_key(field_groups["projectBasics"], "projectName")
        self.assertEqual(project_name["sourceFile"], "招标文件-华能赤峰风电项目招标文件.docx")
        self.assertEqual(project_name["section"], "第二章 投标人须知 > 投标人须知前附表")
        self.assertEqual(project_name["evidenceLocation"], "1.1.4 招标项目名称")
        self.assertEqual(
            project_name["sourceText"],
            "招标文件-华能赤峰风电项目招标文件.docx / 第二章 投标人须知 > 投标人须知前附表 / 1.1.4 招标项目名称",
        )
        self.assertIn("招标项目名称", project_name["evidence"])
        self.assertNotIn("TEN-1:", project_name["evidenceLocation"])
        self.assertNotIn("表格第", project_name["sourceText"])

        qualification = field_groups["qualificationRequirements"][0]
        self.assertEqual(qualification["sourceFile"], "招标文件-华能赤峰风电项目招标文件.docx")
        self.assertEqual(qualification["section"], "第一章 招标公告 > 3.1 通用资格条件")
        self.assertEqual(qualification["evidenceLocation"], "3.1.1 投标人为中华人民共和国境内合法注册的独立法人或其他组织")
        self.assertIn("合法注册", qualification["evidence"])
        self.assertIn("招标文件-华能赤峰风电项目招标文件.docx", qualification["sourceText"])
        self.assertNotIn("TEN-1:", qualification["sourceText"])
        self.assertNotIn("正文第", qualification["sourceText"])
        self.assertEqual(qualification["evidenceIds"], ["TEN-1:B000214"])

        noisy_heading_qualification = field_groups["qualificationRequirements"][1]
        self.assertEqual(noisy_heading_qualification["section"], "第一章 招标公告")
        self.assertNotIn("法定代表人", noisy_heading_qualification["sourceText"])



    def test_business_upload_and_parse_returns_readable_sources_after_auto_redirect(self) -> None:
        project_id = self.create_business_project()
        parse_dir = settings.parsed_dir / project_id
        parse_dir.mkdir(parents=True, exist_ok=True)
        nav_path = parse_dir / "s1_nav.sqlite"
        conn = sqlite3.connect(nav_path)
        try:
            conn.executescript(
                """
                CREATE TABLE evidence (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    body_index INTEGER NOT NULL,
                    table_id TEXT NOT NULL DEFAULT '',
                    row_index INTEGER,
                    col_index INTEGER,
                    text TEXT NOT NULL
                );
                CREATE TABLE blocks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    body_index INTEGER NOT NULL,
                    block_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    heading_path TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE tables (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    body_index INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    heading_path TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.execute(
                "INSERT INTO tables(id, document_id, body_index, title, heading_path) VALUES (?, ?, ?, ?, ?)",
                ("TEN-1:T0001", "TEN-1", 10, "Bidder Instructions Table", "Chapter 2 > Bidder Instructions"),
            )
            conn.execute(
                "INSERT INTO blocks(id, document_id, body_index, block_type, text, heading_path) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "TEN-1:B0002",
                    "TEN-1",
                    20,
                    "paragraph",
                    "3.1.1 Bidder must be a legal entity registered in China.",
                    "Chapter 1 > 3.1 Qualification > 3.1.1 Bidder must be a legal entity registered in China.",
                ),
            )
            conn.execute(
                "INSERT INTO evidence(id, document_id, kind, body_index, table_id, row_index, col_index, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("TEN-1:T0001:R0004", "TEN-1", "table_row", 10, "TEN-1:T0001", 4, None, "1.1.4 | Project name | Liangshan wind project"),
            )
            conn.execute(
                "INSERT INTO evidence(id, document_id, kind, body_index, table_id, row_index, col_index, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("TEN-1:B0002", "TEN-1", "paragraph", 20, "", None, None, "3.1.1 Bidder must be a legal entity registered in China."),
            )
            conn.execute(
                "INSERT INTO evidence(id, document_id, kind, body_index, table_id, row_index, col_index, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("TEN-1:B0003", "TEN-1", "paragraph", 30, "", None, None, "Other bidder instruction."),
            )
            conn.commit()
        finally:
            conn.close()

        structured_path = parse_dir / "s1_structured_result.json"
        structured = {
            "schemaVersion": "bid-business-tender-structured-v1",
            "sourceDocuments": [{"id": "TEN-1", "name": "tender.md"}],
            "workflow": {"stage": "finalized", "mode": "opencode-agentic-navigation", "navStorePath": str(nav_path)},
            "fieldGroups": {
                "projectBasics": [
                    {
                        "key": "projectName",
                        "label": "Project name",
                        "value": "Liangshan wind project",
                        "evidenceIds": ["TEN-1:T0001:R0004"],
                    }
                ],
                "qualificationRequirements": [
                    {
                        "content": "Bidder must be a legal entity registered in China.",
                        "evidenceIds": ["TEN-1:B0002"],
                    }
                ],
                "bidderInstructions": [
                    {
                        "content": "Other bidder instruction.",
                        "evidenceIds": ["TEN-1:B0003"],
                    }
                ],
            },
            "scoringCriteria": {"business": []},
            "appendices": [],
        }
        structured_path.write_text(
            json.dumps({"items": [], "structured": structured}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def fake_parse(
            project_id,
            tender_files,
            *,
            bid_type,
            progress_callback=None,
            cancel_check=None,
            require_preparsed_pdf=False,
        ):
            return (
                {"fileCount": 1, "extractedCount": 0, "textLength": 10, "textPreview": "", "warnings": []},
                {
                    "documents": [{"name": "tender.md", "pageCount": 1, "textLength": 10}],
                    "items": [],
                    "structured": structured,
                    "structuredResultPath": str(structured_path),
                    "projectUpdates": {},
                },
            )

        with patch("app.services.bid_parse_service.parse_tender_documents", side_effect=fake_parse):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("tender.md", b"business source test", "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        field_groups = response.json()["structured"]["fieldGroups"]
        project_name = field_groups["projectBasics"][0]
        self.assertEqual(project_name["sourceFile"], "tender.md")
        self.assertEqual(project_name["section"], "Chapter 2 > Bidder Instructions")
        self.assertEqual(project_name["evidenceLocation"], "1.1.4 Project name")
        self.assertEqual(project_name["sourceText"], "tender.md / Chapter 2 > Bidder Instructions / 1.1.4 Project name")

        qualification = field_groups["qualificationRequirements"][0]
        self.assertEqual(qualification["sourceFile"], "tender.md")
        self.assertEqual(qualification["section"], "Chapter 1 > 3.1 Qualification")
        self.assertEqual(qualification["evidenceLocation"], "3.1.1 Bidder must be a legal entity registered in China.")
        self.assertIn("tender.md / Chapter 1 > 3.1 Qualification", qualification["sourceText"])
        self.assertNotIn("TEN-1:", qualification["sourceText"])

        self.assertNotIn("sourceText", field_groups["bidderInstructions"][0])
