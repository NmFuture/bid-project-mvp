from __future__ import annotations

import itertools
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.store import now_iso, store


class GapReviewFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.sqlite_path = base / "sqlite" / "app.db"
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store._projects = {}
        store._counter = itertools.count(1)
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


if __name__ == "__main__":
    unittest.main()
