from __future__ import annotations

import json
from pathlib import Path
from docx import Document
from app.core.config import settings
from app.services import parsing as parsing_service
from app.services.store import store

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    build_business_attachment_templates_docx_bytes,
    build_business_attachment_templates_with_toc_docx_bytes,
    build_business_commitment_template_alignment_docx_bytes,
    build_business_fingerprint_only_tables_docx_bytes,
    build_business_multilevel_template_cluster_docx_bytes,
    build_docx_blocks_bytes,
    field_by_key,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_business_bid_parse_returns_business_contract_without_technical_groups(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：华能甘肃100MW风电项目",
                "招标编号：HN-BUS-2026-001",
                "招标人：华能集团",
                "交货周期：2026年10月1日至2027年3月31日",
                "质保期：5年",
                "附表3：商务评分标准表",
                "| 序号 | 评分项 | 分值 | 得分点 | 证明材料要求 |",
                "| --- | --- | --- | --- | --- |",
                "| 1 | 企业业绩 | 20分 | 近三年同类项目业绩满足要求得满分。 | 提供合同或中标通知书。 |",
                "投标函：按招标文件格式填写并签字盖章。",
                "法定代表人授权委托书：须加盖公章。",
                "商务偏差表：投标人应逐项响应。",
                "投标保证金：须提供电汇回单或保函。",
                "投标人证明其是合格投标人并有资格履行合同的证明文件。",
                "投标人不得存在下列情形之一。",
                "投标人需要说明的其他内容。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        self.assertEqual(structured["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(payload["summary"]["targetSkill"], "bid-business-tender-structured-parser")
        self.assertIn("commitmentLetterCount", payload["summary"])
        fact_by_key = {field["fieldKey"]: field for field in structured["projectFactFields"]}
        self.assertEqual(fact_by_key["projectName"]["value"], "华能甘肃100MW风电项目")
        self.assertEqual(fact_by_key["tenderNo"]["value"], "HN-BUS-2026-001")
        self.assertEqual(fact_by_key["tenderer"]["value"], "华能集团")

        field_groups = structured["fieldGroups"]
        self.assertIn("projectBasics", field_groups)
        self.assertIn("businessResponse", field_groups)
        self.assertIn("qualificationSupport", field_groups)
        self.assertIn("qualificationRequirements", field_groups)
        self.assertIn("bidderInstructions", field_groups)
        self.assertIn("commercialRejectionClauses", field_groups)
        self.assertIn("commitmentRequirements", field_groups)
        self.assertIn("tenderAgency", {field["key"] for field in field_groups["projectBasics"]})
        self.assertIn("bidDeadline", {field["key"] for field in field_groups["projectBasics"]})
        self.assertNotIn("turbineCoreParameters", field_groups)
        self.assertNotIn("performanceGuarantees", field_groups)
        self.assertNotIn("environmentAdaptation", field_groups)

        scoring = structured["scoringCriteria"]
        self.assertEqual(set(scoring.keys()), {"business", "price", "compliance"})
        self.assertGreaterEqual(len(scoring["business"]), 1)
        self.assertEqual(scoring["business"][0]["scoringItem"], "企业业绩")

        self.assertEqual(structured["requirementPresence"]["bidSecurity"]["status"], "present")
        self.assertEqual(structured["requirementPresence"]["qualificationDocuments"]["status"], "present")
        self.assertEqual(structured["requirementPresence"]["disqualificationClauses"]["status"], "present")

        commitment_fields = field_groups["commitmentRequirements"]
        self.assertEqual(field_by_key(commitment_fields, "generalCommitmentCount")["value"], "1")
        self.assertEqual(field_by_key(commitment_fields, "generatedCommitmentCount")["value"], "1")
        self.assertEqual(field_by_key(commitment_fields, "pendingCommitmentCount")["value"], "0")
        self.assertEqual(field_by_key(commitment_fields, "disqualificationCommitmentRequired")["status"], "found")

        letters = structured["commitmentLetters"]
        self.assertEqual(len(letters), 1)
        self.assertEqual(letters[0]["title"], "投标人不存在下列情形之一承诺函")
        self.assertEqual(letters[0]["commitmentType"], "disqualification")
        self.assertEqual(letters[0]["status"], "generated")
        self.assertTrue(letters[0]["docxPath"])
        self.assertTrue(Path(letters[0]["docxPath"]).exists())

        preview = self.client.get(
            self.parse_results_url(project_id, f"/commitment-letters/{letters[0]['id']}/preview")
        )
        self.assertEqual(preview.status_code, 200)
        preview_payload = preview.json()
        self.assertEqual(preview_payload["id"], letters[0]["id"])
        self.assertIn("/parse-results/commitment-letters/", preview_payload["onlyoffice"]["browserFileUrl"])

        approved = self.client.post(
            self.parse_results_url(project_id, f"/commitment-letters/{letters[0]['id']}/approve"),
            json={"approved": True},
        )
        self.assertEqual(approved.status_code, 200)
        approved_letter = approved.json()["letter"]
        self.assertEqual(approved_letter["assetReviewStatus"], "approved")
        self.assertEqual(approved_letter["assetMaterialFolder"], "资格审查与商务响应成册")



    def test_business_bid_deadline_preserves_minutes_and_ignores_opening_time(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：京能风电设备采购项目",
                "招标编号：ZBA272600801",
                "招标人：山西漳山发电有限责任公司",
                "投标文件的递交",
                "投标截止时间",
                "递交截止时间：2026年03月18日 09时30分",
                "开标时间及地点",
                "开标时间：2026年03月18日 10时30分",
                "交货周期：2026年10月1日至2027年3月31日。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        project_basics = payload["structured"]["fieldGroups"]["projectBasics"]
        bid_deadline = field_by_key(project_basics, "bidDeadline")
        self.assertEqual(bid_deadline["value"], "2026-03-18 09:30")
        self.assertIn("递交截止时间", bid_deadline["evidence"])
        self.assertNotIn("开标时间", bid_deadline["evidence"])
        self.assertEqual(payload["structured"]["projectDates"]["endDate"], "2026-03-18 09:30")
        fact_by_key = {field["fieldKey"]: field for field in payload["structured"]["projectFactFields"]}
        self.assertEqual(fact_by_key["bidDeadline"]["value"], "2026-03-18 09:30")

        project = store._require(project_id)
        self.assertEqual(project["endDate"], "2026-03-18 09:30")
        self.assertEqual(project["deadline"], "2026-03-18 09:30")



    def test_business_bid_deadline_normalizer_prefers_datetime_candidate(self) -> None:
        self.assertEqual(
            parsing_service._normalize_bid_deadline(
                "2026-03-18 4.2.1 | 投标截止时间 | 2026年03月18日 09时30分"
            ),
            "2026-03-18 09:30",
        )



    def test_business_bid_deadline_requires_real_date_candidate(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：华能风电项目",
                "招标编号：HNZB2025-12-1-382",
                "投标保证金到账截止时间为投标截止时间；请投标人确保投标截止时间前到账。",
                "5.1 递交截止时间：2026年1月26日15时00分",
                "开标时间：2026年1月26日16时00分",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        project_basics = response.json()["structured"]["fieldGroups"]["projectBasics"]
        bid_deadline = field_by_key(project_basics, "bidDeadline")
        self.assertEqual(bid_deadline["value"], "2026-01-26 15:00")
        self.assertIn("递交截止时间", bid_deadline["evidence"])
        self.assertNotIn("投标保证金到账截止时间", bid_deadline["evidence"])



    def test_business_local_transform_discards_preface_reference_project_basics(self) -> None:
        payload = {
            "items": [
                {
                    "fieldKey": "projectName",
                    "title": "招标项目名称",
                    "keyEntity": "招标项目名称",
                    "value": "见招标公告",
                    "sourceFile": "商务招标文件.md",
                    "sourceDocumentId": "DOC-1",
                    "section": "投标人须知前附表",
                    "evidence": "1.1.4 | 招标项目名称 | 见招标公告",
                    "evidenceLocation": "L12",
                    "confidence": 0.9,
                },
                {
                    "fieldKey": "projectName",
                    "title": "招标项目名称",
                    "keyEntity": "招标项目名称",
                    "value": "公告真实项目",
                    "sourceFile": "商务招标文件.md",
                    "sourceDocumentId": "DOC-1",
                    "section": "第一章 招标公告",
                    "evidence": "招标项目名称：公告真实项目",
                    "evidenceLocation": "L4",
                    "confidence": 0.86,
                },
                {
                    "fieldKey": "tenderer",
                    "title": "招标人",
                    "keyEntity": "招标人",
                    "value": "见招标公告",
                    "sourceFile": "商务招标文件.md",
                    "sourceDocumentId": "DOC-1",
                    "section": "投标人须知前附表",
                    "evidence": "1.1.2 | 招标人 | 见招标公告",
                    "evidenceLocation": "L10",
                    "confidence": 0.9,
                },
                {
                    "fieldKey": "tenderer",
                    "title": "招标人",
                    "keyEntity": "招标人",
                    "value": "公告真实招标单位",
                    "sourceFile": "商务招标文件.md",
                    "sourceDocumentId": "DOC-1",
                    "section": "第一章 招标公告",
                    "evidence": "招标人：公告真实招标单位",
                    "evidenceLocation": "L5",
                    "confidence": 0.86,
                },
            ],
            "structured": {"projectDates": {"startDate": "", "endDate": ""}, "appendices": []},
        }
        result = parsing_service._transform_to_business_contract(
            "PRJ-LOCAL-REFERENCE",
            payload,
            profile=parsing_service.BUSINESS_PARSE_PROFILE,
            documents=[],
            texts_by_id={},
            run_semantic_review=False,
        )

        project_basics = result["structured"]["fieldGroups"]["projectBasics"]
        self.assertEqual(field_by_key(project_basics, "projectName")["value"], "公告真实项目")
        self.assertEqual(field_by_key(project_basics, "tenderer")["value"], "公告真实招标单位")
        self.assertNotEqual(field_by_key(project_basics, "projectName")["value"], "见招标公告")
        self.assertNotEqual(field_by_key(project_basics, "tenderer")["value"], "见招标公告")



    def test_business_parse_results_recovers_completed_structured_file_after_idle_state(self) -> None:
        project_id = self.create_business_project()
        parse_dir = settings.parsed_dir / project_id
        parse_dir.mkdir(parents=True, exist_ok=True)
        structured_payload = {
            "items": [
                {
                    "id": "REQ-1",
                    "fieldKey": "projectName",
                    "title": "项目名称",
                    "value": "后台\x00恢复测试项目",
                    "sourceFile": "商务招标文件.pdf",
                }
            ],
            "structured": {
                "schemaVersion": "bid-business-tender-structured-v1",
                "fieldGroups": {
                    "projectBasics": [
                        {
                            "key": "projectName",
                            "label": "项目名称",
                            "value": "后台\x00恢复测试项目",
                        }
                    ]
                },
                "appendices": [],
                "commitmentLetters": [],
                "workflow": {
                    "documentParseEngine": "docling",
                    "documentParseStatus": "completed",
                    "fallbackUsed": False,
                },
            },
            "summary": {
                "fileCount": 1,
                "extractedCount": 1,
                "textLength": 12,
                "textPreview": "后台\x00恢复测试项目",
                "warnings": [],
            },
        }
        (parse_dir / "s1_structured_result.json").write_text(
            json.dumps(structured_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        (parse_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "id": "TEN-1",
                            "name": "商务招标文件.pdf",
                            "documentParseEngine": "docling",
                            "documentParseStatus": "completed",
                            "fallbackUsed": False,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (parse_dir / "combined.txt").write_text("后台\x00恢复测试项目", encoding="utf-8")

        project = store._require(project_id)
        project["parse_result"] = {
            "status": "idle",
            "parsedAt": "",
            "sourceFiles": [],
            "items": [],
            "structured": {},
            "summary": {"fileCount": 0, "extractedCount": 0, "textLength": 0, "textPreview": "", "warnings": []},
        }
        project["parse_storage"] = {
            "projectDir": "",
            "parseDir": "",
            "combinedTextPath": "",
            "manifestPath": "",
            "documents": [],
        }
        project["parse_progress"] = {
            "status": "completed",
            "percentage": 100,
            "summary": "解析完成",
            "startedAt": "",
            "completedAt": "",
            "events": [],
        }
        store.persist_project_state(project)

        response = self.client.get(self.parse_results_url(project_id))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["value"], "后台恢复测试项目")
        self.assertNotIn("\x00", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(payload["structured"]["workflow"]["documentParseEngine"], "docling")
        self.assertFalse(payload["structured"]["workflow"]["fallbackUsed"])

        project = store._require(project_id)
        self.assertEqual(project["parse_result"]["status"], "completed")
        self.assertEqual(len(project["parse_result"]["items"]), 1)
        self.assertNotIn("\x00", json.dumps(project["parse_result"], ensure_ascii=False))
        self.assertNotIn("\x00", json.dumps(project["parse_storage"], ensure_ascii=False))
        self.assertEqual(Path(project["parse_storage"]["structuredResultPath"]), parse_dir / "s1_structured_result.json")
        self.assertEqual(Path(project["parse_storage"]["combinedTextPath"]), parse_dir / "combined.txt")



    def test_business_complete_parse_strips_nul_chars_before_persisting(self) -> None:
        project_id = self.create_business_project()
        parse_dir = settings.parsed_dir / project_id
        parse_dir.mkdir(parents=True, exist_ok=True)
        structured_path = parse_dir / "s1_structured_result.json"
        structured_path.write_text("{}", encoding="utf-8")

        from app.services.bid_parse_service import business_parse_service

        parse_result = business_parse_service.complete_parse(
            project_id,
            [
                {
                    "id": "TEN-1",
                    "name": "商务招标文件.pdf",
                    "size_label": "1 MB",
                    "path": str(settings.uploads_dir / project_id / "商务招标文件.pdf"),
                }
            ],
            [],
            summary={
                "fileCount": 1,
                "extractedCount": 1,
                "textLength": 10,
                "textPreview": "预览\x00文本",
                "warnings": ["警告\x00内容"],
            },
            parse_storage={
                "projectDir": str(parse_dir),
                "combinedTextPath": str(parse_dir / "combined.txt"),
                "manifestPath": str(parse_dir / "manifest.json"),
                "structuredResultPath": str(structured_path),
                "documents": [{"id": "TEN-1", "name": "商务\x00招标文件.pdf"}],
                "items": [{"id": "REQ-1", "value": "字段\x00值"}],
                "structured": {"fieldGroups": {"projectBasics": [{"key": "projectName", "value": "项目\x00名称"}]}},
            },
        )

        self.assertEqual(parse_result["items"][0]["value"], "字段值")
        self.assertEqual(parse_result["structured"]["fieldGroups"]["projectBasics"][0]["value"], "项目名称")
        project = store._require(project_id)
        self.assertNotIn("\x00", json.dumps(project["parse_result"], ensure_ascii=False))
        self.assertNotIn("\x00", json.dumps(project["parse_storage"], ensure_ascii=False))



    def test_business_bid_text_attachment_template_docx_keeps_template_body(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "第一章 投标文件格式",
                "附件1 投标函",
                "致：华能集团",
                "我方已仔细研究招标文件的全部内容，愿意按招标文件要求参加投标。",
                "投标人（盖章）：____________",
                "二、法定代表人授权书",
                "本人授权以下代表作为我方合法代理人参加本项目投标。",
                "授权代表签字：____________",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertGreaterEqual(len(appendices), 2)
        bid_letter = next(item for item in appendices if "投标函" in item["title"])
        self.assertEqual(bid_letter["rowCount"], 0)
        doc = Document(str(Path(bid_letter["docxPath"])))
        paragraph_texts = [paragraph.text for paragraph in doc.paragraphs]
        self.assertIn("致：华能集团", paragraph_texts)
        self.assertTrue(any("愿意按招标文件要求参加投标" in text for text in paragraph_texts))



    def test_business_bid_extracts_sixth_chapter_attachment_templates(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "第二章 投标人须知",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
                "第六章 投标文件格式",
                "附件1 投标函",
                "致：华能集团",
                "投标人（盖章）：____________",
                "附件2 法定代表人（单位负责人）身份证明",
                "姓名：____________ 身份证号：____________",
                "附件3 业绩情况表",
                "| 序号 | 项目名称 | 合同容量 | 投运时间 |",
                "| --- | --- | --- | --- |",
                "| 1 |  |  |  |",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        appendices = structured["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertTrue(any("附件1 投标函" in title for title in titles))
        self.assertTrue(any("法定代表人" in title and "身份证明" in title for title in titles))
        self.assertTrue(any("业绩情况表" in title for title in titles))
        bid_letter = next(item for item in appendices if "投标函" in item["title"])
        doc = Document(str(Path(bid_letter["docxPath"])))
        self.assertIn("致：华能集团", [paragraph.text for paragraph in doc.paragraphs])
        self.assertNotIn("投标人须无条件承诺", "".join(titles))



    def test_business_bid_docx_attachment_templates_do_not_use_legacy_slice_when_agent_missing(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务附件模板招标文件.docx",
                        build_business_attachment_templates_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["structured"]["appendices"], [])
        self.assertEqual(payload["summary"]["appendixCount"], 0)
        self.assertTrue(payload["summary"].get("warnings"))



    def test_business_bid_uses_template_extractor_and_keeps_header_cluster(self) -> None:
        project_id = self.create_business_project()
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
        payload = response.json()
        structured = payload["structured"]
        appendices = structured["appendices"]
        self.assertEqual(appendices, [])
        parse_dir = settings.parsed_dir / project_id
        extraction_path = parse_dir / "business_template_extraction" / "business_template_extraction.json"
        self.assertTrue(extraction_path.is_file())
        extraction_payload = json.loads(extraction_path.read_text(encoding="utf-8"))
        self.assertEqual(extraction_payload["summary"]["templateCount"], 0)
        self.assertEqual(extraction_payload.get("schemaVersion"), "bid-business-template-extractor-v1")
        self.assertFalse((extraction_path.parent / "DOC-1" / "candidate_templates.json").exists())
        self.assertFalse((extraction_path.parent / "DOC-1" / "llm_boundary_decisions.json").exists())
        skill_manifest = json.loads((parse_dir / "s1_parse_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(skill_manifest["businessTemplateExtractionPath"], str(extraction_path))
        self.assertEqual(skill_manifest["businessTemplateExtractionSummary"]["templateCount"], 0)



    def test_business_bid_docx_attachment_templates_with_toc_do_not_use_legacy_slice_when_agent_missing(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务附件模板含目录招标文件.docx",
                        build_business_attachment_templates_with_toc_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["structured"]["appendices"], [])
        self.assertEqual(payload["summary"]["appendixCount"], 0)
        self.assertTrue(payload["summary"].get("warnings"))



    def test_business_bid_docx_table_fingerprint_does_not_use_legacy_slice_when_agent_missing(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务表格指纹招标文件.docx",
                        build_business_fingerprint_only_tables_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["structured"]["appendices"], [])
        self.assertEqual(payload["summary"]["appendixCount"], 0)
        self.assertTrue(payload["summary"].get("warnings"))



    def test_business_bid_title_only_attachment_template_is_not_materialized(self) -> None:
        project_id = self.create_business_project()
        tender = build_docx_blocks_bytes(
            "第六章 投标文件格式",
            "附件1 投标函",
            "附件2 开标价格表",
            [
                ["序号", "项目名称", "投标报价"],
                ["1", "", ""],
            ],
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务招标文件.docx",
                        tender,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertNotIn("附件1 投标函", titles)
        self.assertEqual(titles, [])



    def test_business_bid_probably_incomplete_attachment_template_is_not_materialized(self) -> None:
        project_id = self.create_business_project()
        tender = build_docx_blocks_bytes(
            "第六章 投标文件格式",
            "附件1 其他说明",
            "本附件用于说明投标人认为需要说明的其他事项，具体内容由投标人结合项目实际情况自行说明",
            "附件2 开标价格表",
            [
                ["序号", "项目名称", "投标报价"],
                ["1", "", ""],
            ],
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务招标文件.docx",
                        tender,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertNotIn("附件1 其他说明", titles)
        self.assertEqual(titles, [])



    def test_business_bid_existing_commitment_template_suppresses_generated_duplicate(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务承诺模板招标文件.docx",
                        build_business_commitment_template_alignment_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        appendices = structured["appendices"]
        self.assertEqual(appendices, [])
        self.assertEqual([item["title"] for item in structured["commitmentLetters"]], ["材料取得承诺书"])
        self.assertEqual(structured["commitmentTemplateAlignments"], [])



    def test_business_bid_unrelated_commitment_template_does_not_suppress_required_letter(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "投标人不得存在下列情形之一。",
                "# 第六章 投标文件格式",
                "附件6 履约保证函格式",
                "我方承诺按招标文件要求提交履约保证函。",
                "投标人（盖章）：____________",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        self.assertEqual([item["title"] for item in structured["appendices"]], ["附件6 履约保证函格式"])
        titles = [item["title"] for item in structured["commitmentLetters"]]
        self.assertIn("投标人不存在下列情形之一承诺函", titles)
        self.assertEqual(structured["commitmentTemplateAlignments"], [])
