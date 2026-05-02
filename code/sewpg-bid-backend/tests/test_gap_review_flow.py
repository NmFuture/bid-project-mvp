from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.store import now_iso, store


class GapReviewFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def _create_project_with_confirmed_outline(self) -> str:
        response = self.client.post(
            "/api/projects",
            json={
                "name": "S4-S6联调项目",
                "customerName": "测试业主",
            },
        )
        response.raise_for_status()
        project_id = response.json()["id"]

        store.save_generated_outline(
            project_id=project_id,
            nodes=[
                {
                    "id": "OL-1",
                    "title": "第1章 标前概述",
                    "children": [
                        {"id": "OL-1-1", "title": "技术评分标准索引表", "children": []},
                        {"id": "OL-1-2", "title": "投标方案优势说明", "children": []},
                    ],
                },
                {
                    "id": "OL-2",
                    "title": "第2章 技术标准",
                    "children": [
                        {"id": "OL-2-1", "title": "性能保证", "children": []},
                    ],
                },
                {
                    "id": "OL-3",
                    "title": "第3章 风资源评估与机位排布方案",
                    "children": [],
                },
            ],
            generated_at=now_iso(),
            summary="目录已生成。",
        )
        store.confirm_outline(project_id)
        return project_id

    def _create_project_with_confirmed_directory_json(self) -> str:
        project_id = self._create_project_with_confirmed_outline()
        project_dir = settings.parsed_dir / project_id
        work_dir = project_dir / "s2_toc_workdir"
        work_dir.mkdir(parents=True, exist_ok=True)
        toc_json = work_dir / "投标文件-总目录.json"
        toc_json.write_text(
            json.dumps(
                {
                    "schema_version": "bid-toc-json-v1",
                    "document_title": "S4-S6联调项目投标文件总目录",
                    "project": {
                        "owner": "测试业主",
                        "name": "S4-S6联调项目",
                        "code": project_id,
                    },
                    "items": [
                        {
                            "order": 1,
                            "number": "1",
                            "title": "标前概述",
                            "level": 1,
                            "annotation": "保留",
                            "source": "template",
                            "reason": "",
                            "material_refs": [],
                        },
                        {
                            "order": 2,
                            "number": "1.1",
                            "title": "技术评分标准索引表",
                            "level": 2,
                            "annotation": "适配",
                            "source": "wiki",
                            "reason": "匹配素材库：评分索引",
                            "material_refs": [
                                {
                                    "id": "RAW-0001",
                                    "docx": "通用素材/技术标/技术评分标准索引表.docx",
                                    "usage": "both",
                                }
                            ],
                        },
                        {
                            "order": 3,
                            "number": "2.1",
                            "title": "性能保证",
                            "level": 2,
                            "annotation": "新增-招标要求",
                            "source": "tender_special",
                            "reason": "招标文件要求填写性能保证附表",
                            "material_refs": [],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        parse_storage = store.get_parse_storage(project_id)
        parse_storage["projectDir"] = str(project_dir)
        project = store._require(project_id)
        project["parse_storage"] = parse_storage
        project["parse_result"]["structured"] = {
            "appendices": [
                {
                    "id": "APP-PERF",
                    "title": "性能保证附表",
                    "sourceFile": "招标文件.docx",
                    "blankTable": True,
                }
            ],
            "projectDates": {"startDate": "2026-06-01", "endDate": "2026-09-30"},
        }
        store._persist_project(project)
        return project_id

    def test_gap_detection_creates_real_gap_plan_from_directory_material_refs_and_parse_appendices(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()

        response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("gapPlan", payload)
        self.assertEqual(payload["gapPlan"]["schemaVersion"], "bid-tech-gap-plan-v1")
        self.assertEqual(payload["summary"]["totalTocItems"], 3)
        self.assertEqual(payload["summary"]["matchedCount"], 1)
        self.assertEqual(payload["summary"]["missingCount"], 1)
        self.assertGreaterEqual(payload["summary"]["fillableTaskCount"], 1)
        matched = next(item for item in payload["gapPlan"]["items"] if item["status"] == "matched")
        self.assertEqual(matched["matchedMaterials"][0]["id"], "RAW-0001")
        missing = next(item for item in payload["gapPlan"]["items"] if item["status"] == "needs_input")
        self.assertEqual(missing["number"], "2.1")
        self.assertEqual(missing["fillTasks"][0]["skill"], "bid-tech-table-filler")
        self.assertTrue(payload["gapPlan"]["planFile"].endswith("gap_plan.json"))

    def test_gap_ai_fill_calls_opencode_skill_and_registers_resolved_artifact(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        gap_plan = detection_response.json()["gapPlan"]
        fill_item = next(item for item in gap_plan["items"] if item["fillTasks"])
        gap_id = fill_item["id"]
        fill_task_id = fill_item["fillTasks"][0]["id"]

        def fake_run_table_filler(manifest_path, progress_callback=None):
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            output_file = Path(manifest["outputFile"])
            output_file.parent.mkdir(parents=True, exist_ok=True)
            doc = Document()
            doc.add_paragraph("性能保证附表")
            doc.add_paragraph("已根据参考素材和解析字段填写。")
            doc.save(output_file)
            return {
                "schema_version": "bid-tech-table-fill-v1",
                "outputFile": str(output_file),
                "unfilledFields": ["保证值来源页码"],
                "evidenceRefs": [{"source": "招标文件.docx", "field": "性能保证"}],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": str(manifest_path),
                    "providerId": "local-skill",
                    "modelId": "bid-tech-table-filler",
                    "receivedAt": "2026-05-02T00:00:00Z",
                    "parts": [{"type": "text", "text": "{\"schema_version\":\"bid-tech-table-fill-v1\"}"}],
                },
            }

        with patch(
            "app.services.gap_planning.run_table_filler_skill",
            side_effect=fake_run_table_filler,
        ):
            response = self.client.post(
                f"/api/projects/{project_id}/gaps/{gap_id}/ai-fill",
                json={
                    "fillTaskId": fill_task_id,
                    "referenceMaterialIds": ["RAW-0001"],
                    "parseFieldIds": ["APP-PERF"],
                    "operator": "测试用户",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["item"]["status"], "resolved")
        self.assertEqual(payload["artifact"]["source"], "ai_fill")
        self.assertEqual(payload["artifact"]["skill"], "bid-tech-table-filler")
        self.assertTrue(Path(payload["artifact"]["path"]).exists())
        self.assertIn("onlyoffice", payload["artifact"])
        updated_gap = self.client.get(f"/api/projects/{project_id}/gaps").json()["gapPlan"]
        updated_item = next(item for item in updated_gap["items"] if item["id"] == gap_id)
        self.assertEqual(updated_item["resolvedArtifacts"][0]["source"], "ai_fill")
        self.assertEqual(updated_item["fillTasks"][0]["status"], "completed")

    def test_gap_review_mock_flow_runs_from_s4_to_s6(self) -> None:
        project_id = self._create_project_with_confirmed_outline()

        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        detection_payload = detection_response.json()
        self.assertEqual(detection_payload["status"], "completed")
        self.assertGreater(len(detection_payload["items"]), 0)

        gaps_response = self.client.get(f"/api/projects/{project_id}/gaps")
        self.assertEqual(gaps_response.status_code, 200)
        gaps_payload = gaps_response.json()
        self.assertEqual(gaps_payload["status"], "ready")
        items = gaps_payload["items"]
        self.assertGreater(len(items), 0)

        for index, item in enumerate(items):
            submission_response = self.client.post(
                f"/api/projects/{project_id}/materials/submissions",
                json={
                    "missingId": item["id"],
                    "bidType": item.get("bidType") or "技术标",
                    "files": [
                        {
                            "name": f"{item['id']}.docx",
                            "size": 1024,
                            "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        }
                    ],
                },
            )
            self.assertEqual(submission_response.status_code, 200)

            if index % 2 == 0:
                update_response = self.client.put(
                    f"/api/projects/{project_id}/gaps/{item['id']}",
                    json={"action": "resolve", "source": {"name": f"{item['id']}.docx"}},
                )
            else:
                update_response = self.client.patch(
                    f"/api/projects/{project_id}/materials/missing/{item['id']}",
                    json={"status": "skipped", "reason": "MVP阶段先跳过"},
                )
            self.assertEqual(update_response.status_code, 200)

        submit_review_response = self.client.post(f"/api/projects/{project_id}/gaps/submit-review")
        self.assertEqual(submit_review_response.status_code, 200)

        review_items_response = self.client.get(f"/api/projects/{project_id}/review-items")
        self.assertEqual(review_items_response.status_code, 200)
        self.assertEqual(review_items_response.json()["status"], "ready")

        prepare_response = self.client.post(f"/api/projects/{project_id}/review-items/prepare")
        self.assertEqual(prepare_response.status_code, 200)

        review_document_response = self.client.get(f"/api/projects/{project_id}/review-items/document")
        self.assertEqual(review_document_response.status_code, 200)
        review_document = review_document_response.json()
        self.assertEqual(review_document["status"], "ready")
        self.assertIn("onlyoffice", review_document)
        self.assertIn("fileUrl", review_document["onlyoffice"])

        confirm_response = self.client.post(f"/api/projects/{project_id}/review-items/confirm")
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.json()["reviewStatus"], "confirmed")

    def test_submit_review_blocks_until_gap_plan_is_resolved(self) -> None:
        project_id = self._create_project_with_confirmed_outline()

        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)

        submit_review_response = self.client.post(f"/api/projects/{project_id}/gaps/submit-review")
        self.assertEqual(submit_review_response.status_code, 400)
        self.assertIn("缺口未解决", submit_review_response.json()["detail"])

        gaps_payload = self.client.get(f"/api/projects/{project_id}/gaps").json()
        for item in gaps_payload["items"]:
            update_response = self.client.patch(
                f"/api/projects/{project_id}/materials/missing/{item['id']}",
                json={"status": "skipped", "reason": "测试中人工确认忽略"},
            )
            self.assertEqual(update_response.status_code, 200)

        recheck_response = self.client.post(f"/api/projects/{project_id}/gaps/recheck")
        self.assertEqual(recheck_response.status_code, 200)
        self.assertEqual(recheck_response.json()["integrity"]["status"], "passed")

        submit_review_response = self.client.post(f"/api/projects/{project_id}/gaps/submit-review")
        self.assertEqual(submit_review_response.status_code, 200)
        submit_payload = submit_review_response.json()["payload"]
        self.assertTrue(submit_payload["submittedForReview"])
        self.assertGreater(len(submit_payload["items"]), 0)
        self.assertTrue(all(item["status"] == "skipped" for item in submit_payload["items"]))

        prepare_response = self.client.post(f"/api/projects/{project_id}/review-items/prepare")
        self.assertEqual(prepare_response.status_code, 200)
        review_items_response = self.client.get(f"/api/projects/{project_id}/review-items")
        self.assertEqual(review_items_response.status_code, 200)
        self.assertEqual(review_items_response.json()["summary"]["pendingCount"], 0)


if __name__ == "__main__":
    unittest.main()
