from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch
from docx import Document


class BusinessGapPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = None

    def _setup_app_test(self) -> None:
        from fastapi.testclient import TestClient
        from app.core.config import settings
        from app.main import app
        from app.services.store import store

        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()
        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        if self.client is not None:
            self.client.close()
        self.temp_dir.cleanup()

    def test_businessgap_runner_generates_toc_based_plan_and_parser_artifacts(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script_path = backend_root / "opencode" / "skill" / "bid-business-gap-planner" / "scripts" / "run_from_manifest.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse_result.json"
            output_path = root / "business_gap_plan.json"
            letter_path = root / "保密承诺书.docx"
            letter_path.write_bytes(b"fake-docx")
            toc_path.write_text(
                json.dumps(
                    {
                        "schema_version": "bid-toc-json-v1",
                        "items": [
                            {"order": 1, "number": "一", "title": "投标函", "level": 1},
                            {"order": 2, "number": "九", "title": "投标人需要说明的其他内容", "level": 1},
                            {"order": 3, "number": "9.1", "title": "保密承诺书", "level": 2},
                            {"order": 4, "number": "七", "title": "机型认证证书", "level": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "structured": {
                            "schemaVersion": "bid-business-tender-structured-v1",
                            "commitmentLetters": [
                                {
                                    "id": "COMMIT-0001",
                                    "title": "保密承诺书",
                                    "docxPath": str(letter_path),
                                    "assetReviewStatus": "pending_review",
                                    "triggerText": "投标人须提供保密承诺书。",
                                }
                            ],
                            "appendices": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest_path = root / "business_gap_input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BG-001",
                        "projectName": "商务缺口测试",
                        "bidType": "商务标",
                        "workDir": str(root),
                        "tocJsonPath": str(toc_path),
                        "parseResultPath": str(parse_path),
                        "businessWikiDir": "",
                        "materialScope": {"bidType": "商务标", "readableScopes": []},
                        "materialIndex": [
                            {
                                "id": "RAW-0001",
                                "name": "EW6.25机型认证证书.pdf",
                                "folderPath": "商务标/通用素材/05-专题证书库/机型认证证书",
                                "materialTier": "standard",
                                "turbineModelLabel": "EW6.25",
                            }
                        ],
                        "selectedBusinessTurbineModel": {"model": "EW6.25"},
                        "outputFile": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(script_path), "--manifest", str(manifest_path), "--response", "summary"],
                check=True,
                capture_output=True,
                text=True,
            )
            summary = json.loads(completed.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["schemaVersion"], "bid-business-gap-plan-v1")
        self.assertEqual(summary["coverageStatus"], "complete")
        self.assertEqual(len(plan["tocRefs"]), 4)
        titles = [task["title"] for task in plan["tasks"]]
        self.assertIn("投标函", titles)
        commitment = next(task for task in plan["tasks"] if task["title"] == "保密承诺书")
        self.assertEqual(commitment["status"], "review_required")
        self.assertEqual(commitment["resolvedArtifacts"][0]["artifactId"], "COMMIT-0001")
        self.assertEqual(commitment["assemblyMode"], "template_fill_docx")
        self.assertEqual(commitment["fillPlan"]["mode"], "template_fill_docx")
        certificate = next(task for task in plan["tasks"] if "机型认证" in task["title"])
        self.assertTrue(certificate["candidateMaterials"])
        self.assertEqual(certificate["assemblyMode"], "embed_scan_or_image")
        self.assertEqual(certificate["materialUsage"], "embed_scan")

    def test_businessgap_runner_uses_business_wiki_index_for_candidates_and_risks(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script_path = backend_root / "opencode" / "skill" / "bid-business-gap-planner" / "scripts" / "run_from_manifest.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse_result.json"
            output_path = root / "business_gap_plan.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "schema_version": "bid-toc-json-v1",
                        "items": [
                            {"order": 1, "number": "七", "title": "机型认证证书", "level": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"status": "completed", "structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest_path = root / "business_gap_input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BG-WIKI",
                        "projectName": "商务 Wiki 候选测试",
                        "bidType": "商务标",
                        "workDir": str(root),
                        "tocJsonPath": str(toc_path),
                        "parseResultPath": str(parse_path),
                        "businessWikiDir": "",
                        "businessWikiIndex": {
                            "schemaVersion": "bid-business-wiki-index-v1",
                            "mappingRows": [
                                {
                                    "module_name": "08-资格证明文件模块（附件7）",
                                    "module_code": "BM-08",
                                    "candidate_card_ids": "biz-card-RAW-0007",
                                    "usage_mode": "attach_whole",
                                }
                            ],
                            "evidenceCards": [
                                {
                                    "card_id": "biz-card-RAW-0007",
                                    "material_id": "RAW-0007",
                                    "title": "EW6.25机型认证证书",
                                    "path": "商务标/通用素材/05-专题证书库/01-机型认证证书/EW6.25机型认证证书.pdf",
                                    "material_tier": "通用素材",
                                    "business_category": "专题证书",
                                    "usage_mode": "attach_whole",
                                    "validity_status": "pending_verify",
                                    "expiry_date": "待核验",
                                    "turbine_models": ["EW6.25"],
                                    "needs_human_confirm": "yes",
                                    "ocr_confidence": "0.60",
                                }
                            ],
                            "evidenceSegments": [
                                {
                                    "segment_id": "biz-seg-RAW-0007-cert",
                                    "card_id": "biz-card-RAW-0007",
                                    "material_id": "RAW-0007",
                                    "title": "EW6.25机型认证证书扫描件",
                                    "segment_type": "pdf_attachment",
                                    "segment_scope": "card_primary",
                                    "business_category": "专题证书",
                                    "document_type": "证书/资质文件",
                                    "usage_mode": "attach_whole",
                                    "path": "商务标/通用素材/05-专题证书库/01-机型认证证书/EW6.25机型认证证书.pdf",
                                    "source_pages": "第 1-2 页",
                                    "summary": "EW6.25 机型认证证书，需核验证书有效期。",
                                    "keywords": ["EW6.25", "机型认证", "证书"],
                                    "validity_status": "pending_verify",
                                    "expiry_date": "待核验",
                                    "turbine_models": ["EW6.25"],
                                    "needs_human_confirm": "yes",
                                    "ocr_confidence": "0.60",
                                }
                            ],
                        },
                        "materialScope": {"bidType": "商务标", "readableScopes": []},
                        "materialIndex": [
                            {
                                "id": "RAW-0007",
                                "name": "证书扫描件.pdf",
                                "folderPath": "商务标/通用素材/05-专题证书库/01-机型认证证书",
                                "materialTier": "standard",
                                "turbineModelLabel": "",
                            }
                        ],
                        "selectedBusinessTurbineModel": {"model": "EW6.25"},
                        "outputFile": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(script_path), "--manifest", str(manifest_path), "--response", "summary"],
                check=True,
                capture_output=True,
                text=True,
            )
            plan = json.loads(output_path.read_text(encoding="utf-8"))

        certificate = next(task for task in plan["tasks"] if "机型认证" in task["title"])
        candidate = certificate["candidateMaterials"][0]
        self.assertEqual(candidate["materialId"], "RAW-0007")
        self.assertEqual(candidate["wikiCardId"], "biz-card-RAW-0007")
        self.assertEqual(candidate["evidenceSegmentId"], "biz-seg-RAW-0007-cert")
        self.assertEqual(candidate["evidenceSegmentTitle"], "EW6.25机型认证证书扫描件")
        self.assertEqual(candidate["evidenceSourcePages"], "第 1-2 页")
        self.assertIn("Wiki", candidate["reason"])
        self.assertEqual(certificate["assemblyMode"], "attach_whole_file")
        self.assertEqual(certificate["materialUsage"], "attach_whole")
        self.assertEqual(certificate["selectedEvidenceSegments"][0]["segmentId"], "biz-seg-RAW-0007-cert")
        self.assertEqual(certificate["fillPlan"]["mode"], "attach_whole_file")
        self.assertIn("wiki_validity_pending_verify", certificate["riskFlags"])
        self.assertIn("wiki_ocr_low_confidence", certificate["riskFlags"])

    def test_businessgap_runner_prioritizes_manual_material_feedback(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script_path = backend_root / "opencode" / "skill" / "bid-business-gap-planner" / "scripts" / "run_from_manifest.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse_result.json"
            output_path = root / "business_gap_plan.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "schema_version": "bid-toc-json-v1",
                        "items": [
                            {"order": 1, "number": "7.1", "title": "机型认证证书", "level": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"status": "completed", "structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest_path = root / "business_gap_input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BG-FEEDBACK",
                        "projectName": "商务反馈候选测试",
                        "bidType": "商务标",
                        "workDir": str(root),
                        "tocJsonPath": str(toc_path),
                        "parseResultPath": str(parse_path),
                        "businessWikiDir": "",
                        "businessWikiIndex": {"schemaVersion": "bid-business-wiki-index-v1"},
                        "materialScope": {"bidType": "商务标", "readableScopes": []},
                        "materialIndex": [
                            {
                                "id": "RAW-FB-001",
                                "name": "人工指定过的EW6.25机型认证证书.pdf",
                                "folderPath": "商务标/通用素材/05-专题证书库/01-机型认证证书",
                                "materialTier": "standard",
                            }
                        ],
                        "materialFeedback": {
                            "schemaVersion": "bid-business-material-feedback-v1",
                            "items": [
                                {
                                    "feedbackKey": "biz-feedback-test",
                                    "taskTitle": "机型认证证书",
                                    "moduleKey": "qualification_compliance_certificates",
                                    "taskType": "certificate",
                                    "assemblyMode": "embed_scan_or_image",
                                    "materialUsage": "embed_scan",
                                    "materialId": "RAW-FB-001",
                                    "materialName": "人工指定过的EW6.25机型认证证书.pdf",
                                    "folderPath": "商务标/通用素材/05-专题证书库/01-机型认证证书",
                                    "evidenceSegmentId": "SEG-FB-001",
                                    "evidenceSegmentTitle": "EW6.25机型认证证书页",
                                    "evidenceSummary": "人工在商务 S3 中确认该材料支撑机型认证证书任务。",
                                }
                            ],
                        },
                        "selectedBusinessTurbineModel": {"model": "EW6.25"},
                        "outputFile": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(script_path), "--manifest", str(manifest_path), "--response", "summary"],
                check=True,
                capture_output=True,
                text=True,
            )
            plan = json.loads(output_path.read_text(encoding="utf-8"))

        certificate = next(task for task in plan["tasks"] if "机型认证" in task["title"])
        candidate = certificate["candidateMaterials"][0]
        self.assertEqual(candidate["materialId"], "RAW-FB-001")
        self.assertEqual(candidate["feedbackKey"], "biz-feedback-test")
        self.assertIn("人工指定反馈命中", candidate["reason"])
        self.assertIn("manual_feedback_candidate", certificate["riskFlags"])
        self.assertEqual(certificate["selectedEvidenceSegments"][0]["segmentId"], "SEG-FB-001")

    def test_businessgap_runner_attaches_scoring_asset_to_scoring_index_task(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script_path = backend_root / "opencode" / "skill" / "bid-business-gap-planner" / "scripts" / "run_from_manifest.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse_result.json"
            output_path = root / "business_gap_plan.json"
            scoring_path = root / "商务评分标准表.docx"
            scoring_path.write_bytes(b"fake-scoring-docx")
            toc_path.write_text(
                json.dumps(
                    {
                        "schema_version": "bid-toc-json-v1",
                        "items": [
                            {"order": 1, "number": "一", "title": "商务评分索引表", "level": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "structured": {
                            "businessScoringAsset": {
                                "id": "BIZ-SCORING-001",
                                "fileName": "商务评分标准表.docx",
                                "docxPath": str(scoring_path),
                                "reviewStatus": "approved",
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest_path = root / "business_gap_input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BG-SCORING",
                        "projectName": "商务评分索引测试",
                        "bidType": "商务标",
                        "workDir": str(root),
                        "tocJsonPath": str(toc_path),
                        "parseResultPath": str(parse_path),
                        "businessWikiDir": "",
                        "materialScope": {"bidType": "商务标", "readableScopes": []},
                        "materialIndex": [],
                        "selectedBusinessTurbineModel": {},
                        "outputFile": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(script_path), "--manifest", str(manifest_path), "--response", "summary"],
                check=True,
                capture_output=True,
                text=True,
            )
            plan = json.loads(output_path.read_text(encoding="utf-8"))

        scoring_task = next(task for task in plan["tasks"] if task["title"] == "商务评分索引表")
        self.assertEqual(scoring_task["status"], "ready")
        self.assertEqual(scoring_task["resolvedArtifacts"][0]["artifactId"], "BIZ-SCORING-001")
        self.assertEqual(scoring_task["resolvedArtifacts"][0]["sourceMode"], "parsed_business_scoring")

    def test_businessgap_runner_negative_rules_avoid_performance_material_for_bid_letter(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script_path = backend_root / "opencode" / "skill" / "bid-business-gap-planner" / "scripts" / "run_from_manifest.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse_result.json"
            output_path = root / "business_gap_plan.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "schema_version": "bid-toc-json-v1",
                        "items": [
                            {"order": 1, "number": "一", "title": "投标函", "level": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"status": "completed", "structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest_path = root / "business_gap_input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BG-NEGATIVE",
                        "projectName": "商务负面规则测试",
                        "bidType": "商务标",
                        "workDir": str(root),
                        "tocJsonPath": str(toc_path),
                        "parseResultPath": str(parse_path),
                        "businessWikiDir": "",
                        "materialScope": {"bidType": "商务标", "readableScopes": []},
                        "materialIndex": [
                            {
                                "id": "RAW-PERF-001",
                                "name": "投标项目业绩合同扫描件.pdf",
                                "folderPath": "商务标/通用素材/03-业绩资产池/合同扫描件",
                                "materialTier": "standard",
                            }
                        ],
                        "selectedBusinessTurbineModel": {},
                        "outputFile": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(script_path), "--manifest", str(manifest_path), "--response", "summary"],
                check=True,
                capture_output=True,
                text=True,
            )
            plan = json.loads(output_path.read_text(encoding="utf-8"))

        bid_letter = next(task for task in plan["tasks"] if task["title"] == "投标函")
        self.assertEqual(bid_letter["candidateMaterials"], [])
        self.assertEqual(bid_letter["status"], "needs_input")

    def test_businessgap_runner_emits_template_candidates_from_template_index(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script_path = backend_root / "opencode" / "skill" / "bid-business-gap-planner" / "scripts" / "run_from_manifest.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse_result.json"
            output_path = root / "business_gap_plan.json"
            template_path = root / "投标函格式模板.docx"
            doc = Document()
            doc.add_paragraph("投标函")
            doc.add_paragraph("项目名称：")
            doc.save(template_path)
            toc_path.write_text(
                json.dumps(
                    {
                        "schema_version": "bid-toc-json-v1",
                        "items": [
                            {"order": 1, "number": "一", "title": "投标函", "level": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"status": "completed", "structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest_path = root / "business_gap_input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BG-TEMPLATE",
                        "projectName": "商务模板候选测试",
                        "bidType": "商务标",
                        "workDir": str(root),
                        "tocJsonPath": str(toc_path),
                        "parseResultPath": str(parse_path),
                        "businessWikiDir": "",
                        "materialScope": {"bidType": "商务标", "readableScopes": []},
                        "materialIndex": [],
                        "templateIndex": [
                            {
                                "templateId": "TPL-PROJECT-001",
                                "templateName": "投标函格式模板.docx",
                                "fileName": template_path.name,
                                "filePath": str(template_path),
                                "sourceMode": "project_uploaded_bid_template",
                                "sourceLabel": "项目上传模板",
                                "templateScope": "project",
                                "score": 0.92,
                                "reason": "S1/S2 项目上传投标模板",
                            }
                        ],
                        "selectedBusinessTurbineModel": {},
                        "outputFile": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(script_path), "--manifest", str(manifest_path), "--response", "summary"],
                check=True,
                capture_output=True,
                text=True,
            )
            plan = json.loads(output_path.read_text(encoding="utf-8"))

        bid_letter = next(task for task in plan["tasks"] if task["title"] == "投标函")
        self.assertEqual(bid_letter["status"], "review_required")
        self.assertEqual(bid_letter["assemblyMode"], "template_fill_docx")
        self.assertEqual(bid_letter["materialUsage"], "fill_template")
        self.assertEqual(bid_letter["templateCandidates"][0]["templateId"], "TPL-PROJECT-001")
        self.assertEqual(bid_letter["templateCandidates"][0]["sourceMode"], "project_uploaded_bid_template")
        self.assertEqual(bid_letter["candidateMaterials"], [])
        self.assertIn("candidate_template_unconfirmed", bid_letter["riskFlags"])

    def test_business_gap_api_uses_business_workspace_and_keeps_technical_gap_state_empty(self) -> None:
        self._setup_app_test()
        from app.core.config import settings
        from app.services.store import now_iso, store
        from app.services.workspace_artifacts import business_workspace_dir, technical_workspace_dir

        project = store.create_project({"name": "商务S3项目", "customerName": "华能集团", "bidType": "商务标"})
        project_id = project["id"]
        business_workspace = business_workspace_dir(project_id)
        business_workspace.mkdir(parents=True, exist_ok=True)
        letter_path = business_workspace / "commitment-letters" / "保密承诺书.docx"
        letter_path.parent.mkdir(parents=True, exist_ok=True)
        letter_path.write_bytes(b"fake-docx")
        store.complete_parse(
            project_id,
            tender_files=[{"id": "TEN-1", "name": "商务招标文件.md", "path": str(settings.uploads_dir / "tender.md"), "size_label": "1 KB"}],
            template_files=[],
            summary={"fileCount": 1, "extractedCount": 1, "textLength": 20, "textPreview": "", "warnings": []},
            parse_storage={
                "projectDir": str(business_workspace),
                "combinedTextPath": str(business_workspace / "combined.txt"),
                "manifestPath": "",
            },
        )
        store.update_parse_result(
            project_id,
            {
                "status": "completed",
                "structured": {
                    "schemaVersion": "bid-business-tender-structured-v1",
                    "commitmentLetters": [
                        {
                            "id": "COMMIT-0001",
                            "title": "保密承诺书",
                            "docxPath": str(letter_path),
                            "assetReviewStatus": "pending_review",
                        }
                    ],
                    "appendices": [],
                    "projectFactFields": [
                        {
                            "fieldKey": "projectName",
                            "label": "项目名称",
                            "value": "商务S3项目",
                            "category": "项目基础信息",
                            "required": True,
                            "confidence": 0.95,
                        },
                        {
                            "fieldKey": "tenderNo",
                            "label": "招标编号",
                            "value": "BIZ-2026-001",
                            "category": "项目基础信息",
                            "required": True,
                            "confidence": 0.94,
                        },
                        {
                            "fieldKey": "tenderer",
                            "label": "招标人",
                            "value": "华能集团",
                            "category": "项目基础信息",
                            "required": True,
                            "confidence": 0.9,
                        },
                    ],
                },
            },
        )
        store.save_generated_outline(
            project_id=project_id,
            nodes=[
                {"id": "OL-1", "title": "投标函", "children": []},
                {"id": "OL-2", "title": "投标人需要说明的其他内容", "children": [
                    {"id": "OL-2-1", "title": "保密承诺书", "children": []},
                ]},
            ],
            generated_at=now_iso(),
            summary="商务目录已生成。",
        )
        store.confirm_outline(project_id)
        store.update_stage(project_id, 2, {"status": "completed"})

        with patch(
            "app.services.business_gap_planning.OpencodeClient.run_bid_business_gap_planner_with_trace",
            side_effect=RuntimeError("offline test fallback"),
        ):
            response = self.client.post(f"/api/projects/{project_id}/business-gaps/run")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(str(payload["plan"]["planFile"]).endswith("business_gap_plan.json"))
        self.assertIn("business-workspace/gaps", str(payload["plan"]["planFile"]))
        self.assertEqual(store._require(project_id)["gap_state"]["recognitionStatus"], "idle")
        self.assertTrue((business_workspace / "gaps" / "business_gap_input.json").exists())
        self.assertFalse((technical_workspace_dir(project_id) / "s4_gap_workdir" / "gap_plan.json").exists())

        get_response = self.client.get(f"/api/projects/{project_id}/business-gaps")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(len(get_response.json()["tocRefs"]), 3)
        empty_ref = next(item for item in get_response.json()["tocRefs"] if item["title"] == "投标人需要说明的其他内容")
        manual_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/toc/{empty_ref['nodeId']}/manual-task",
            json={"title": "本章节补充说明材料"},
        )
        self.assertEqual(manual_response.status_code, 200)
        manual_task = manual_response.json()["task"]
        self.assertEqual(manual_task["sourceType"], "manual_user")
        self.assertEqual(manual_task["tocTarget"]["nodeId"], empty_ref["nodeId"])
        self.assertEqual(manual_task["status"], "needs_input")
        manual_ref = next(item for item in manual_response.json()["plan"]["tocRefs"] if item["nodeId"] == empty_ref["nodeId"])
        self.assertIn(manual_task["id"], manual_ref["taskIds"])
        manual_upload_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/tasks/{manual_task['id']}/upload",
            json={
                "files": [
                    {
                        "name": "本章节补充说明.png",
                        "mimeType": "image/png",
                        "data": "data:image/png;base64," + b64encode(b"fake-image").decode("ascii"),
                    }
                ]
            },
        )
        self.assertEqual(manual_upload_response.status_code, 200)
        self.assertEqual(manual_upload_response.json()["task"]["status"], "ready")
        self.assertIn("business-workspace/gaps/uploads", manual_upload_response.json()["artifact"]["filePath"])
        manual_ref_after_upload = next(
            item
            for item in manual_upload_response.json()["plan"]["tocRefs"]
            if item["nodeId"] == empty_ref["nodeId"]
        )
        self.assertEqual(manual_ref_after_upload["status"], "ready")
        manual_artifact = manual_upload_response.json()["artifact"]
        remove_manual_response = self.client.delete(
            f"/api/projects/{project_id}/business-gaps/tasks/{manual_task['id']}/artifacts/{manual_artifact['artifactId']}"
        )
        self.assertEqual(remove_manual_response.status_code, 200)
        self.assertEqual(remove_manual_response.json()["task"]["status"], "needs_input")
        manual_ref_after_remove = next(
            item
            for item in remove_manual_response.json()["plan"]["tocRefs"]
            if item["nodeId"] == empty_ref["nodeId"]
        )
        self.assertEqual(manual_ref_after_remove["status"], "partial")
        self.assertFalse(Path(manual_artifact["filePath"]).exists())
        task = next(item for item in get_response.json()["tasks"] if item["title"] == "保密承诺书")
        confirm_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/tasks/{task['id']}/confirm-artifact",
            json={"artifactId": "COMMIT-0001", "confirmed": True},
        )
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.json()["task"]["status"], "ready")

        bid_letter_task = next(item for item in get_response.json()["tasks"] if item["title"] == "投标函")
        mode_response = self.client.patch(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}",
            json={"assemblyMode": "template_fill_docx"},
        )
        self.assertEqual(mode_response.status_code, 200)
        mode_task = mode_response.json()["task"]
        self.assertEqual(mode_task["status"], "review_required")
        self.assertEqual(mode_task["decision"], "review_required")
        self.assertEqual(mode_task["materialUsage"], "fill_template")
        self.assertIn("candidate_template_unconfirmed", mode_task["riskFlags"])
        self.assertTrue(mode_task["templateCandidates"])

        stored_plan = store._require(project_id)["business_gap_state"]["plan"]
        bid_letter_stored = next(item for item in stored_plan["tasks"] if item["id"] == bid_letter_task["id"])
        bid_letter_stored["candidateMaterials"] = [
            {
                "materialId": "RAW-TPL-001",
                "materialName": "投标函格式模板.docx",
                "folderPath": "商务标/通用素材/06-通用模板底稿库/投标函空白模板",
                "wikiUsageMode": "fill_template",
                "score": 0.86,
            }
        ]
        candidate_mode_response = self.client.patch(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}",
            json={"assemblyMode": "template_fill_docx"},
        )
        self.assertEqual(candidate_mode_response.status_code, 200)
        candidate_mode_task = candidate_mode_response.json()["task"]
        self.assertEqual(candidate_mode_task["status"], "review_required")
        self.assertEqual(candidate_mode_task["decision"], "review_required")
        self.assertIn("candidate_template_unconfirmed", candidate_mode_task["riskFlags"])
        template_source = business_workspace / "项目上传投标函模板.docx"
        doc = Document()
        doc.add_paragraph("投标函")
        doc.add_paragraph("项目名称：")
        doc.save(template_source)
        store.update_template_files(
            project_id,
            [
                {
                    "id": "TPL-PROJECT-001",
                    "name": "项目上传投标函模板.docx",
                    "stored_name": template_source.name,
                    "size_bytes": template_source.stat().st_size,
                    "size_label": "1 KB",
                    "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "path": str(template_source),
                }
            ],
        )
        stored_plan = store._require(project_id)["business_gap_state"]["plan"]
        bid_letter_stored = next(item for item in stored_plan["tasks"] if item["id"] == bid_letter_task["id"])
        bid_letter_stored["candidateMaterials"] = []
        bid_letter_stored["templateCandidates"] = []
        backfill_response = self.client.get(f"/api/projects/{project_id}/business-gaps")
        self.assertEqual(backfill_response.status_code, 200)
        backfilled_task = next(item for item in backfill_response.json()["tasks"] if item["id"] == bid_letter_task["id"])
        self.assertEqual(backfilled_task["status"], "review_required")
        self.assertEqual(backfilled_task["templateCandidates"][0]["templateId"], "TPL-PROJECT-001")
        self.assertEqual(backfilled_task["templateCandidates"][0]["sourceMode"], "project_uploaded_bid_template")
        select_template_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}/select-template",
            json={"template": {"templateId": "TPL-PROJECT-001"}},
        )
        self.assertEqual(select_template_response.status_code, 200)
        selected_template_task = select_template_response.json()["task"]
        self.assertEqual(selected_template_task["status"], "ready")
        self.assertEqual(selected_template_task["assemblyMode"], "template_fill_docx")
        self.assertEqual(select_template_response.json()["artifact"]["sourceMode"], "project_uploaded_bid_template")
        self.assertIn("business-workspace/gaps/selected-templates", select_template_response.json()["artifact"]["filePath"])

        upload_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}/upload",
            json={
                "files": [
                    {
                        "name": "补充授权材料.pdf",
                        "mimeType": "application/pdf",
                        "data": "data:application/pdf;base64," + b64encode(b"%PDF-business-gap").decode("ascii"),
                    }
                ]
            },
        )
        self.assertEqual(upload_response.status_code, 200)
        uploaded = upload_response.json()["artifact"]
        self.assertEqual(upload_response.json()["task"]["status"], "ready")
        self.assertEqual(uploaded["sourceMode"], "uploaded_in_business_s3")
        self.assertIn("business-workspace/gaps/uploads", uploaded["filePath"])
        self.assertTrue(Path(uploaded["filePath"]).exists())
        self.assertFalse((technical_workspace_dir(project_id) / "s4_gap_workdir" / "manual_upload").exists())
        self.assertEqual(uploaded["materialSyncStatus"], "not_synced")
        self.assertEqual(uploaded["materialSyncPolicy"], "manual_project_only")
        self.assertIn(f"商务标/项目素材/{project_id}/02-商务响应文件", uploaded["materialTargetPath"])

        multipart_upload_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}/upload-files",
            data={"operator": "测试用户"},
            files=[
                (
                    "files",
                    (
                        "S3补充模板.docx",
                        b"business-gap-docx-bytes",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        self.assertEqual(multipart_upload_response.status_code, 200)
        multipart_uploaded = multipart_upload_response.json()["artifact"]
        self.assertEqual(multipart_upload_response.json()["task"]["status"], "ready")
        self.assertEqual(multipart_uploaded["sourceMode"], "uploaded_in_business_s3")
        self.assertEqual(multipart_uploaded["operator"], "测试用户")
        self.assertEqual(Path(multipart_uploaded["filePath"]).read_bytes(), b"business-gap-docx-bytes")

        ai_mode_response = self.client.patch(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}",
            json={"assemblyMode": "ai_draft"},
        )
        self.assertEqual(ai_mode_response.status_code, 200)
        ai_mode_task = ai_mode_response.json()["task"]
        self.assertEqual(ai_mode_task["status"], "needs_input")
        self.assertEqual(ai_mode_task["decision"], "ai_draft_required")
        self.assertIn("ai_draft_required", ai_mode_task["riskFlags"])
        ai_draft_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}/ai-draft",
            json={"operator": "测试用户"},
        )
        self.assertEqual(ai_draft_response.status_code, 200)
        ai_draft_task = ai_draft_response.json()["task"]
        self.assertEqual(ai_draft_task["status"], "ready")
        self.assertEqual(ai_draft_task["decision"], "ready")
        self.assertNotIn("ai_draft_required", ai_draft_task["riskFlags"])

        sync_response = self.client.post(
            f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}/sync-artifact-material",
            json={"artifactId": uploaded["artifactId"]},
        )
        self.assertEqual(sync_response.status_code, 200)
        synced = sync_response.json()["artifact"]
        self.assertEqual(synced["materialSyncStatus"], "synced_to_project_material")
        self.assertEqual(synced["wikiSyncStatus"], "wiki_rebuild_required")
        self.assertIn(f"商务标/项目素材/{project_id}/02-商务响应文件", synced["materialTargetPath"])
        self.assertTrue(sync_response.json()["wikiRebuildRequired"])
        synced_material = sync_response.json()["material"]
        self.assertEqual(synced_material["bidType"], "商务标")
        self.assertEqual(synced_material["materialTier"], "project")
        self.assertEqual(synced_material["projectId"], project_id)
        self.assertIn("商务标/项目素材", synced_material["folderPath"])
        self.assertFalse(synced_material["folderPath"].startswith("技术标/"))

        async def fake_download_payload(material_id: str) -> tuple[dict[str, str], str]:
            return {
                "fileId": material_id,
                "fileName": "商务素材证书.pdf",
                "bucket": "mock-bucket",
                "key": "mock-key",
                "mimeType": "application/pdf",
            }, "raw"

        def fake_download_file(bucket: str, key: str, target_path: Path) -> Path:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"%PDF-selected-material")
            return target_path

        async def fake_raw_files(**kwargs):
            return {
                "items": [
                    {
                        "id": "RAW-9001",
                        "name": "商务素材证书.pdf",
                        "folderPath": "商务标/通用素材/05-专题证书库",
                        "materialTier": "standard",
                        "cleanStatus": "",
                        "hasCleanedWord": False,
                        "size": 128,
                    }
                ],
                "total": 1,
            }

        with patch.object(store, "_business_material_download_payload", side_effect=fake_download_payload), patch(
            "app.services.store.minio_client.download_file",
            side_effect=fake_download_file,
        ):
            with patch(
                "app.services.business_gap_planning.material_store.raw_files",
                side_effect=fake_raw_files,
            ):
                selectable_response = self.client.get(
                    f"/api/projects/{project_id}/business-gaps/selectable-materials?keyword=证书"
                )
            self.assertEqual(selectable_response.status_code, 200)
            selectable_payload = selectable_response.json()
            self.assertEqual(selectable_payload["bidType"], "商务标")
            self.assertEqual(selectable_payload["items"][0]["materialId"], "RAW-9001")
            self.assertEqual(selectable_payload["segments"][0]["materialId"], "RAW-9001")
            self.assertTrue(selectable_payload["segments"][0]["evidenceSegmentId"])

            select_response = self.client.post(
                f"/api/projects/{project_id}/business-gaps/tasks/{bid_letter_task['id']}/select-material",
                json={
                    "materials": [
                        {
                            "materialId": "RAW-9001",
                            "materialName": "商务素材证书.pdf",
                            "folderPath": "商务标/通用素材/05-专题证书库",
                            "materialTier": "standard",
                            "evidenceSegmentId": selectable_payload["segments"][0]["evidenceSegmentId"],
                            "evidenceSegmentTitle": selectable_payload["segments"][0]["evidenceSegmentTitle"],
                            "evidenceSourcePages": selectable_payload["segments"][0]["evidenceSourcePages"],
                            "evidenceSummary": selectable_payload["segments"][0]["evidenceSummary"],
                        }
                    ]
                },
            )
        self.assertEqual(select_response.status_code, 200)
        selected_task = select_response.json()["task"]
        self.assertEqual(selected_task["status"], "ready")
        self.assertEqual(selected_task["selectedMaterialRefs"][0]["materialId"], "RAW-9001")
        self.assertEqual(selected_task["selectedEvidenceSegments"][0]["segmentId"], selectable_payload["segments"][0]["evidenceSegmentId"])
        self.assertEqual(select_response.json()["artifact"]["sourceMode"], "selected_from_business_material_library")
        self.assertEqual(select_response.json()["artifact"]["evidenceSegmentId"], selectable_payload["segments"][0]["evidenceSegmentId"])
        self.assertIn("business-workspace/gaps/selected-materials", select_response.json()["artifact"]["filePath"])
        self.assertFalse((technical_workspace_dir(project_id) / "s4_gap_workdir" / "selected_material").exists())

        facts_response = self.client.post(f"/api/projects/{project_id}/business-gaps/facts/build")
        self.assertEqual(facts_response.status_code, 200)
        facts = facts_response.json()
        labels = {field["label"]: field for field in facts["fields"]}
        self.assertEqual(labels["项目名称"]["value"], "商务S3项目")
        self.assertEqual(labels["招标编号"]["value"], "BIZ-2026-001")
        self.assertIn("投标人", labels)
        confirm_facts_response = self.client.put(
            f"/api/projects/{project_id}/business-gaps/facts",
            json={"fields": facts["fields"], "confirm": True, "operator": "测试用户"},
        )
        self.assertEqual(confirm_facts_response.status_code, 200)
        self.assertEqual(confirm_facts_response.json()["status"], "confirmed")
        stored_project = store._require(project_id)
        self.assertEqual(stored_project["business_gap_state"]["projectFactTable"]["status"], "confirmed")
        self.assertEqual(stored_project["gap_state"]["projectFactTable"], {})


if __name__ == "__main__":
    unittest.main()
