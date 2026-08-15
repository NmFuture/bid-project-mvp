from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.core.config import settings
from app.services import parsing as parsing_service
from app.services.store import store

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    build_docx_bytes,
    field_by_key,
    sample_evaluation_docx_bytes,
    sample_technical_spec_docx_bytes,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_long_running_parse_step_emits_progress_heartbeats_until_done(self) -> None:
        heartbeats = []

        def slow_step() -> str:
            time.sleep(0.05)
            return "done"

        result = parsing_service._run_with_progress_heartbeat(
            slow_step,
            heartbeat=lambda metadata: heartbeats.append(metadata),
            interval_seconds=0.01,
        )

        self.assertEqual(result, "done")
        self.assertGreaterEqual(len(heartbeats), 1)
        self.assertTrue(heartbeats[0]["heartbeat"])
        self.assertEqual(heartbeats[0]["heartbeatIndex"], 1)
        self.assertIn("elapsedSeconds", heartbeats[0])



    def test_long_running_parse_step_checks_cancel_before_heartbeat(self) -> None:
        heartbeats = []

        def slow_step() -> str:
            time.sleep(0.05)
            return "done"

        with self.assertRaises(parsing_service.ParseCancelledError):
            parsing_service._run_with_progress_heartbeat(
                slow_step,
                heartbeat=lambda metadata: heartbeats.append(metadata),
                interval_seconds=0.01,
                cancel_check=lambda: True,
            )

        self.assertEqual(heartbeats, [])



    def test_upload_and_parse_docx_extracts_text_and_preview(self) -> None:
        project_id = self.create_project()
        file_bytes = build_docx_bytes(
            "上海电气风电项目招标文件",
            "第一章 项目概况",
            "本项目建设地点位于江苏。",
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", file_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["summary"]["fileCount"], 1)
        self.assertGreater(payload["summary"]["textLength"], 10)
        self.assertIn("上海电气风电项目招标文件", payload["summary"]["textPreview"])



    def test_upload_and_parse_markdown_extracts_text_and_preview(self) -> None:
        project_id = self.create_project()
        file_bytes = "# Markdown 招标说明\n\n本项目允许使用 Markdown 素材文件。".encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标说明.md", file_bytes, "text/markdown"),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["sourceFiles"][0]["type"], "MD")
        self.assertIn("Markdown 招标说明", payload["summary"]["textPreview"])



    def test_business_pdf_uses_docling_document_nav_without_lightweight_fallback(self) -> None:
        project_id = self.create_business_project()
        pdf_path = settings.uploads_dir / project_id / "business.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")
        nav_payload = {
            "schemaVersion": "business-document-nav-v1",
            "sourceEngine": "docling",
            "documents": [{"id": "DOC-1", "sourcePath": str(pdf_path)}],
            "pages": [{"pageNo": 1, "textDensity": 0.8}],
            "blocks": [
                {
                    "id": "DOC-1:B000001",
                    "type": "heading",
                    "text": "第六章 投标文件格式",
                    "sourceEngine": "docling",
                },
                {
                    "id": "DOC-1:B000002",
                    "type": "paragraph",
                    "text": "本章包含商务偏差表，请投标人填写。",
                    "sourceEngine": "docling",
                }
            ],
            "tables": [],
            "images": [],
            "evidence": [],
            "quality": {"engine": "docling", "status": "completed", "fallbackUsed": False},
        }

        def fake_parse_pdf(self, *, project_id: str, document: dict, output_dir: Path):
            nav_path = output_dir / "document_nav.json"
            quality_path = output_dir / "parse_quality.json"
            nav_path.write_text(json.dumps(nav_payload, ensure_ascii=False), encoding="utf-8")
            quality_path.write_text(
                json.dumps(
                    {
                        "engine": "docling",
                        "status": "completed",
                        "fallbackUsed": False,
                        "doclingMode": "local-text-layer",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return {
                "documentParseEngine": "docling",
                "status": "completed",
                "documentNavPath": str(nav_path),
                "parseQualityPath": str(quality_path),
                "doclingMode": "local-text-layer",
            }

        def fake_structured_parser(skill_manifest_path: Path, **kwargs):
            manifest = json.loads(skill_manifest_path.read_text(encoding="utf-8"))
            document = manifest["documents"][0]
            self.assertEqual(document["documentParseEngine"], "docling")
            self.assertEqual(document["doclingMode"], "local-text-layer")
            self.assertTrue(Path(document["documentNavPath"]).is_file())
            self.assertTrue(Path(document["parseQualityPath"]).is_file())
            text_path = Path(document["textPath"])
            self.assertIn("第六章 投标文件格式", text_path.read_text(encoding="utf-8"))
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
            "app.services.parsing.settings.business_pdf_parse_engine",
            "docling",
            create=True,
        ), patch(
            "app.services.parsing.settings.business_pdf_engine_fallback",
            "none",
            create=True,
        ), patch(
            "app.services.parsing.DoclingParseEngine.parse_pdf",
            new=fake_parse_pdf,
        ), patch(
            "app.services.parsing.extract_pdf_text",
            side_effect=AssertionError("Docling business PDF path must not call lightweight extract_pdf_text fallback"),
        ), patch(
            "app.services.parsing.run_business_template_extractor",
            return_value=([], {"schemaVersion": "bid-business-template-extractor-v1", "summary": {"templateCount": 0}}, ""),
        ), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_structured_parser,
        ), patch(
            "app.services.parsing._needs_business_s1_finalize_guard",
            return_value=False,
        ):
            summary, storage = parsing_service.parse_tender_documents(
                project_id,
                [
                    {
                        "id": "DOC-1",
                        "name": "business.pdf",
                        "path": str(pdf_path),
                        "content_type": "application/pdf",
                    }
                ],
                bid_type="商务标",
            )

        self.assertIn("第六章 投标文件格式", summary["textPreview"])
        self.assertEqual(storage["documents"][0]["documentParseEngine"], "docling")
        self.assertEqual(storage["documents"][0]["textLength"], len("第六章 投标文件格式\n\n本章包含商务偏差表，请投标人填写。"))
        self.assertTrue(Path(storage["documents"][0]["documentNavPath"]).is_file())
        self.assertIn("第六章 投标文件格式", Path(storage["documents"][0]["textPath"]).read_text(encoding="utf-8"))
        quality = json.loads(Path(storage["documents"][0]["parseQualityPath"]).read_text(encoding="utf-8"))
        self.assertEqual(quality["engine"], "docling")
        self.assertEqual(quality["sourceEngine"], "docling")
        self.assertEqual(quality["status"], "completed")
        self.assertEqual(quality["qualityStatus"], "needs_review")
        self.assertEqual(quality["doclingMode"], "local-text-layer")
        self.assertFalse(quality["fallbackUsed"])
        self.assertTrue(quality["reviewRequired"])



    def test_business_pdf_low_quality_pages_append_ocr_blocks(self) -> None:
        project_id = self.create_business_project()
        pdf_path = settings.uploads_dir / project_id / "business-low-quality.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")
        nav_payload = {
            "schemaVersion": "business-document-nav-v1",
            "sourceEngine": "docling",
            "documents": [{"id": "DOC-1", "sourcePath": str(pdf_path)}],
            "pages": [{"pageNo": 1, "textDensity": 0.01}],
            "blocks": [{"id": "DOC-1:B000001", "type": "paragraph", "text": "Docling 原始文本", "pageNo": 1}],
            "tables": [],
            "images": [],
            "evidence": [],
            "quality": {"engine": "docling", "status": "completed", "fallbackUsed": False},
        }

        def fake_parse_pdf(self, *, project_id: str, document: dict, output_dir: Path):
            nav_path = output_dir / "document_nav.json"
            quality_path = output_dir / "parse_quality.json"
            nav_path.write_text(json.dumps(nav_payload, ensure_ascii=False), encoding="utf-8")
            quality_path.write_text(
                json.dumps({"engine": "docling", "status": "completed", "fallbackUsed": False}, ensure_ascii=False),
                encoding="utf-8",
            )
            return {
                "documentParseEngine": "docling",
                "status": "completed",
                "documentNavPath": str(nav_path),
                "parseQualityPath": str(quality_path),
            }

        def fake_ocr_pages(*, project_id: str, document: dict, file_path: Path, page_numbers: list[int]):
            self.assertEqual(page_numbers, [1])
            return {1: {"text": "OCR 补充文本", "meta": {"status": "completed", "pageCount": 1}}}

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing.settings.business_pdf_parse_engine",
            "docling",
            create=True,
        ), patch(
            "app.services.parsing.DoclingParseEngine.parse_pdf",
            new=fake_parse_pdf,
        ), patch(
            "app.services.parse_extract._ocr_business_pdf_pages",
            side_effect=fake_ocr_pages,
        ), patch(
            "app.services.parsing.run_business_template_extractor",
            return_value=([], {"schemaVersion": "bid-business-template-extractor-v1", "summary": {"templateCount": 0}}, ""),
        ), patch(
            "app.services.parsing._run_parse_skill",
            return_value=(
                {
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
                },
                "",
            ),
        ), patch(
            "app.services.parsing._needs_business_s1_finalize_guard",
            return_value=False,
        ):
            _, storage = parsing_service.parse_tender_documents(
                project_id,
                [
                    {
                        "id": "DOC-1",
                        "name": "business-low-quality.pdf",
                        "path": str(pdf_path),
                        "content_type": "application/pdf",
                    }
                ],
                bid_type="商务标",
            )

        document = storage["documents"][0]
        nav = json.loads(Path(document["documentNavPath"]).read_text(encoding="utf-8"))
        texts = [block["text"] for block in nav["blocks"]]
        quality = json.loads(Path(document["parseQualityPath"]).read_text(encoding="utf-8"))
        self.assertIn("Docling 原始文本", texts)
        self.assertIn("OCR 补充文本", texts)
        self.assertTrue(any(block["type"] == "ocr_text" for block in nav["blocks"]))
        self.assertEqual(document["pageOcr"]["appliedPages"], [1])
        self.assertEqual(quality["engine"], "docling")
        self.assertFalse(quality["fallbackUsed"])
        self.assertEqual(quality["ocrAppliedPages"], [1])



    def test_parse_tender_documents_stops_when_cancel_requested_before_extracting(self) -> None:
        project_id = self.create_project()
        tender_path = settings.uploads_dir / project_id / "cancel-source.md"
        tender_path.parent.mkdir(parents=True, exist_ok=True)
        tender_path.write_text("取消测试文件", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "解析已取消"):
            parsing_service.parse_tender_documents(
                project_id,
                [
                    {
                        "id": "DOC-1",
                        "name": "cancel-source.md",
                        "path": str(tender_path),
                        "content_type": "text/markdown",
                    }
                ],
                bid_type="技术标",
                cancel_check=lambda: True,
            )



    def test_parse_tender_documents_isolates_single_file_failure(self) -> None:
        """单文件解析抛异常时记为失败条目并继续整批：结果/进度中显式可见，不静默吞掉。"""
        project_id = self.create_project()
        good_path = settings.uploads_dir / project_id / "tender-good.md"
        bad_path = settings.uploads_dir / project_id / "tender-bad.docx"
        good_path.parent.mkdir(parents=True, exist_ok=True)
        good_path.write_text("第一章 总则\n本项目为风力发电机组采购。", encoding="utf-8")
        bad_path.write_bytes(b"not-a-real-docx")

        progress_events: list[tuple[str, dict]] = []
        summary, storage = parsing_service.parse_tender_documents(
            project_id,
            [
                {
                    "id": "DOC-1",
                    "name": "tender-good.md",
                    "path": str(good_path),
                    "content_type": "text/markdown",
                },
                {
                    "id": "DOC-2",
                    "name": "tender-bad.docx",
                    "path": str(bad_path),
                    "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                },
            ],
            bid_type="技术标",
            progress_callback=lambda event, payload: progress_events.append((event, payload or {})),
        )

        # 失败条目在整批结果中显式可见
        self.assertEqual(summary["failedFileCount"], 1)
        self.assertEqual(len(summary["failedDocuments"]), 1)
        self.assertEqual(summary["failedDocuments"][0]["name"], "tender-bad.docx")
        self.assertTrue(summary["failedDocuments"][0]["error"])
        self.assertTrue(any("文件解析失败" in warning for warning in summary["warnings"]))

        # 成功文件正常解析，失败文件带 status/parseError 占位
        documents = {doc["name"]: doc for doc in storage["documents"]}
        self.assertEqual(documents["tender-good.md"]["status"], "completed")
        self.assertGreater(documents["tender-good.md"]["textLength"], 0)
        self.assertEqual(documents["tender-bad.docx"]["status"], "failed")
        self.assertTrue(documents["tender-bad.docx"]["parseError"])
        self.assertIn("本项目为风力发电机组采购", summary["textPreview"])

        # 进度事件中失败显式可见（failed 标记 + 错误信息）
        failed_events = [
            payload for event, payload in progress_events if event == "file_extracted" and payload.get("failed")
        ]
        self.assertEqual(len(failed_events), 1)
        self.assertEqual(failed_events[0]["fileName"], "tender-bad.docx")



    def test_upload_and_parse_image_uses_visual_recognition_without_manual_ocr_flow(self) -> None:
        project_id = self.create_project()
        recognized_text = "项目名称：图片型招标文件\n招标编号：IMG-2026-001\n投标截止日期：2026年8月20日"

        with patch(
            "app.services.parsing.ocr_service.recognize_text_for_parse",
            new=AsyncMock(return_value=(recognized_text, {"pageCount": 1})),
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[
                    (
                        "tenderFiles",
                        ("图片型招标文件.png", b"\x89PNG\r\n\x1a\nfake", "image/png"),
                    )
                ],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("图片型招标文件", payload["summary"]["textPreview"])
        self.assertIn("图片文件已通过 OCR/视觉模型转为可解析文本。", payload["summary"]["warnings"])
        self.assertNotIn("ocrConfirmedFields", payload["structured"])
        self.assertEqual(payload["structured"]["projectDates"]["endDate"], "2026-08-20")



    def test_upload_and_parse_multiple_tenders_extracts_structured_requirements_and_dates(self) -> None:
        project_id = self.create_project()
        main_tender = "\n".join(
            [
                "# 总发包招标文件",
                "项目名称：华能甘肃100MW风电项目",
                "招标编号：HN-2026-001",
                "招标人：华能集团",
                "招标文件获取时间：2026年6月1日至2026年6月10日",
                "投标截止日期：2026年9月30日",
                "评分细则：技术方案30分，供货保障10分。",
                "交货周期：2026年10月1日至2027年3月31日",
            ]
        ).encode("utf-8")
        child_tender = "\n".join(
            [
                "# 子项目招标文件",
                "单机容量：6.25MW",
                "叶轮直径：200m",
                "轮毂高度：120m",
                "可利用率：97%",
                "功率曲线保证率：95%",
                "环境适应性要求：低温-30℃、覆冰、防雷暴。",
                "专题方案要求：叶片专题方案、变桨系统专题方案。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                ("tenderFiles", ("总发包招标文件.md", main_tender, "text/markdown")),
                ("tenderFiles", ("子项目招标文件.md", child_tender, "text/markdown")),
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["fileCount"], 2)
        self.assertGreaterEqual(payload["summary"]["extractedCount"], 10)

        category_labels = {category["label"] for category in payload["structured"]["categories"]}
        self.assertIn("评分细则", category_labels)
        self.assertIn("项目基础信息", category_labels)
        self.assertIn("风机核心参数", category_labels)
        self.assertIn("性能保证指标", category_labels)
        self.assertIn("环境适应性要求", category_labels)
        self.assertIn("专题方案要求", category_labels)

        item_types = {item["type"] for item in payload["items"]}
        self.assertIn("评分细则", item_types)
        self.assertIn("项目基础信息", item_types)
        self.assertIn("风机核心参数", item_types)
        self.assertIn("性能保证指标", item_types)
        self.assertIn("环境适应性要求", item_types)
        self.assertIn("专题方案要求", item_types)

        source_files = {item["sourceFile"] for item in payload["items"]}
        self.assertIn("总发包招标文件.md", source_files)
        self.assertIn("子项目招标文件.md", source_files)
        self.assertTrue(all(item.get("evidence") for item in payload["items"]))
        self.assertTrue(all(item.get("evidenceLocation") for item in payload["items"]))

        parsed_dates = payload["structured"]["projectDates"]
        self.assertEqual(parsed_dates["startDate"], "2026-06-01")
        self.assertEqual(parsed_dates["endDate"], "2026-09-30")

        project = store._require(project_id)
        self.assertEqual(project["startDate"], "2026-06-01")
        self.assertEqual(project["endDate"], "2026-09-30")
        self.assertEqual(project["deadline"], "2026-09-30")



    def test_bid_dates_ignore_supply_delivery_ranges(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "# 招标文件",
                "项目名称：供货日期不应污染投标日期",
                "供货范围及交货进度",
                "主机设备2026年4月10日前开始供货，截止2026年8月30日前完成全部供货。",
                "安装调试服务期：2026年9月1日至2026年10月30日。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        parsed_dates = response.json()["structured"]["projectDates"]
        self.assertEqual(parsed_dates["startDate"], "")
        self.assertEqual(parsed_dates["endDate"], "")

        project = store._require(project_id)
        self.assertEqual(project["startDate"], "")
        self.assertEqual(project["endDate"], "")
        self.assertEqual(project["deadline"], "")



    def test_bid_dates_parse_bid_submission_and_opening_dates(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "# 招标公告",
                "招标文件获取时间：2026年5月8日至2026年5月15日。",
                "投标文件递交截止时间：2026年6月20日09时30分。",
                "开标时间：2026年6月20日09时30分。",
                "交货周期：2026年10月1日至2027年3月31日。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        parsed_dates = response.json()["structured"]["projectDates"]
        self.assertEqual(parsed_dates["startDate"], "2026-05-08")
        self.assertEqual(parsed_dates["endDate"], "2026-06-20")

        project = store._require(project_id)
        self.assertEqual(project["startDate"], "2026-05-08")
        self.assertEqual(project["endDate"], "2026-06-20")
        self.assertEqual(project["deadline"], "2026-06-20")



    def test_upload_and_parse_multifile_docx_tables_builds_structured_contract(self) -> None:
        project_id = self.create_project()

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "评标办法.docx",
                        sample_evaluation_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
                (
                    "tenderFiles",
                    (
                        "技术规范书.docx",
                        sample_technical_spec_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]

        source_documents = structured["sourceDocuments"]
        self.assertEqual(len(source_documents), 2)
        self.assertEqual(source_documents[0]["role"], "evaluation")
        self.assertEqual(source_documents[1]["role"], "technical_spec")

        scoring = structured["scoringCriteria"]
        self.assertEqual(len(scoring["technical"]), 2)
        self.assertEqual(len(scoring["business"]), 2)
        self.assertEqual(len(scoring["price"]), 1)
        self.assertEqual(len(scoring["lcoe"]), 1)
        self.assertEqual(len(scoring["compliance"]), 1)
        self.assertEqual(scoring["technical"][0]["scoringItem"], "技术方案")
        self.assertEqual(scoring["technical"][0]["score"], "30分")
        self.assertIn("技术承诺函", scoring["technical"][0]["proofRequirement"])
        self.assertEqual(scoring["business"][0]["scoringItem"], "企业业绩")
        self.assertIn("合同", scoring["business"][0]["proofRequirement"])

        for bucket in scoring.values():
            for row in bucket:
                self.assertTrue(row["sourceFile"])
                self.assertTrue(row["sourceDocumentId"])
                self.assertTrue(row["section"])
                self.assertTrue(row["evidence"])
                self.assertTrue(row["evidenceLocation"])

        field_groups = structured["fieldGroups"]
        project_basics = field_groups["projectBasics"]
        self.assertEqual(
            [field["key"] for field in project_basics],
            ["projectName", "tenderNo", "projectUnit", "tenderer", "tenderAgency", "bidDeadline"],
        )
        self.assertTrue(all(field["value"] == "" for field in project_basics))
        self.assertEqual(field_by_key(field_groups["turbineCoreParameters"], "singleCapacity")["value"], "6.25MW")
        self.assertEqual(field_by_key(field_groups["turbineCoreParameters"], "bladeTipClearance")["value"], "20m")
        self.assertIn("认证功率曲线", field_by_key(field_groups["performanceGuarantees"], "powerCurve")["value"])
        self.assertIn("防凝露", field_by_key(field_groups["environmentAdaptation"], "icingCondensation")["value"])

        for group in field_groups.values():
            if isinstance(group, list):
                for field in group:
                    if field["status"] == "found":
                        self.assertTrue(field["sourceFile"])
                        self.assertTrue(field["sourceDocumentId"])
                        self.assertTrue(field["evidence"])
                        self.assertTrue(field["evidenceLocation"])

        presence = structured["requirementPresence"]
        self.assertEqual(presence["topicPlans"]["status"], "present")
        self.assertEqual(presence["supplyScope"]["status"], "present")
        self.assertEqual(presence["assessmentTerms"]["status"], "present")



    def test_s1parse_skill_script_outputs_same_multifile_structured_contract(self) -> None:
        project_dir = Path(self.temp_dir.name) / "skill-script"
        project_dir.mkdir()
        evaluation_path = project_dir / "评标办法.docx"
        technical_path = project_dir / "技术规范书.docx"
        evaluation_path.write_bytes(sample_evaluation_docx_bytes())
        technical_path.write_bytes(sample_technical_spec_docx_bytes())
        evaluation_text = project_dir / "evaluation.txt"
        technical_text = project_dir / "technical.txt"
        evaluation_text.write_text("第三章 评标办法（综合评估法）\n附表2：技术评分标准表\n", encoding="utf-8")
        technical_text.write_text(
            "第二卷 技术规范书\n专题方案：应提供叶片专题、变桨系统专题、主轴专题、齿轮箱专题。\n",
            encoding="utf-8",
        )
        output_path = project_dir / "s1_structured_result.json"
        manifest_path = project_dir / "s1_parse_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "projectId": "PRJ-SKILL",
                    "structuredResultPath": str(output_path),
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "评标办法.docx",
                            "sourcePath": str(evaluation_path),
                            "textPath": str(evaluation_text),
                        },
                        {
                            "id": "DOC-2",
                            "name": "技术规范书.docx",
                            "sourcePath": str(technical_path),
                            "textPath": str(technical_text),
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        script_path = (
            Path(__file__).resolve().parents[1]
            / "opencode"
            / "skills"
            / "bid-tech-tender-structured-parser"
            / "scripts"
            / "run_from_manifest.py"
        )

        completed = subprocess.run(
            [sys.executable, str(script_path), str(manifest_path)],
            check=True,
            capture_output=True,
            text=True,
        )

        summary = json.loads(completed.stdout)
        self.assertEqual(summary["schemaVersion"], "bid-tender-structured-v1")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["structured"]["scoringCriteria"]["technical"]), 2)
        self.assertEqual(len(payload["structured"]["scoringCriteria"]["business"]), 2)
        project_basics = payload["structured"]["fieldGroups"]["projectBasics"]
        self.assertEqual(
            [field["key"] for field in project_basics],
            ["projectName", "tenderNo", "projectUnit", "tenderer", "tenderAgency", "bidDeadline"],
        )
        self.assertTrue(all(field["value"] == "" for field in project_basics))



    def test_project_create_and_update_support_start_and_end_dates(self) -> None:
        response = self.client.post(
            "/api/technical/projects",
            json={
                "name": "日期测试项目",
                "customerName": "测试业主",
                "startDate": "2026-05-10",
                "endDate": "2026-08-20",
                "deadline": "2026-08-20",
            },
        )
        self.assertEqual(response.status_code, 200)
        created = response.json()
        self.assertEqual(created["startDate"], "2026-05-10")
        self.assertEqual(created["endDate"], "2026-08-20")
        self.assertEqual(created["deadline"], "2026-08-20")

        update_response = self.client.put(
            f"/api/technical/projects/{created['id']}",
            json={
                "startDate": "2026-05-15",
                "endDate": "2026-09-01",
                "deadline": "2026-09-01",
            },
        )
        self.assertEqual(update_response.status_code, 200)
        updated = update_response.json()
        self.assertEqual(updated["startDate"], "2026-05-15")
        self.assertEqual(updated["endDate"], "2026-09-01")
        self.assertEqual(updated["deadline"], "2026-09-01")

        list_response = self.client.get("/api/technical/projects")
        self.assertEqual(list_response.status_code, 200)
        listed = list_response.json()["items"][0]
        self.assertEqual(listed["startDate"], "2026-05-15")
        self.assertEqual(listed["endDate"], "2026-09-01")



    def test_upload_and_parse_persists_text_to_disk_artifact(self) -> None:
        project_id = self.create_project()
        file_bytes = build_docx_bytes(
            "招标文件正文",
            "第二章 技术方案",
            "这里是一段比较长的测试内容，用于验证解析结果不会直接塞进项目状态数据库，而是落到磁盘文件。",
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", file_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        project = store._require(project_id)
        parse_storage = project["parse_storage"]
        combined_text_path = Path(parse_storage["combinedTextPath"])
        self.assertTrue(combined_text_path.exists())
        content = combined_text_path.read_text(encoding="utf-8")
        self.assertIn("第二章 技术方案", content)
        self.assertGreater(parse_storage["documents"][0]["textLength"], 10)
