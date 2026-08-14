from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.bid_outline_state import confirm_outline_state, save_generated_outline_state
from app.services.bid_runtime_state import now_iso
from app.services.store import store


class TechnicalGapDetectionJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()
        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

        response = self.client.post(
            "/api/technical/projects",
            json={"name": "素材匹配后台任务项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        self.project_id = response.json()["id"]

        project = store.require_project_for_update(self.project_id)
        save_generated_outline_state(
            project,
            nodes=[{"id": "OL-1", "title": "技术方案", "children": []}],
            generated_at=now_iso(),
            summary="目录已生成。",
        )
        confirm_outline_state(project)
        store.persist_project_state(project)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_run_returns_202_without_running_planner_in_request(self) -> None:
        with patch("app.services.technical_gap_service._schedule_gap_detection_job") as schedule, patch(
            "app.services.technical_gap_service.build_technical_gap_plan_for_project",
            side_effect=AssertionError("planner must run in background"),
        ):
            response = self.client.post(
                f"/api/technical/projects/{self.project_id}/gaps-detection/run"
            )

        self.assertEqual(response.status_code, 202)
        self.assertIn(response.json()["status"], {"queued", "running"})
        self.assertGreaterEqual(response.json()["percentage"], 1)
        schedule.assert_called_once_with(self.project_id)

    def test_repeated_run_does_not_schedule_duplicate_job(self) -> None:
        with patch("app.services.technical_gap_service._schedule_gap_detection_job") as schedule:
            first = self.client.post(
                f"/api/technical/projects/{self.project_id}/gaps-detection/run"
            )
            second = self.client.post(
                f"/api/technical/projects/{self.project_id}/gaps-detection/run"
            )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        schedule.assert_called_once_with(self.project_id)

    def test_cancel_is_idempotent_and_cancelled_worker_skips_planner(self) -> None:
        from app.services.technical_gap_service import run_technical_gap_detection_job

        with patch("app.services.technical_gap_service._schedule_gap_detection_job"):
            self.client.post(
                f"/api/technical/projects/{self.project_id}/gaps-detection/run"
            )

        first = self.client.post(
            f"/api/technical/projects/{self.project_id}/gaps-detection/cancel"
        )
        second = self.client.post(
            f"/api/technical/projects/{self.project_id}/gaps-detection/cancel"
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["status"], "cancel_requested")
        self.assertEqual(
            first.json()["cancelRequestedAt"],
            second.json()["cancelRequestedAt"],
        )

        with patch(
            "app.services.technical_gap_service.build_technical_gap_plan_for_project"
        ) as planner:
            run_technical_gap_detection_job(self.project_id)

        planner.assert_not_called()
        status = self.client.get(
            f"/api/technical/projects/{self.project_id}/gaps-detection"
        )
        self.assertEqual(status.json()["status"], "cancelled")

    def test_worker_publishes_completed_status(self) -> None:
        from app.services.technical_gap_service import run_technical_gap_detection_job

        plan = {
            "schemaVersion": "bid-tech-gap-plan-v1",
            "projectId": self.project_id,
            "status": "ready",
            "summary": {"totalTocItems": 1, "missingCount": 1},
            "items": [
                {
                    "id": "GAP-0001",
                    "number": "1",
                    "title": "技术方案",
                    "status": "missing",
                    "decision": "material_required",
                    "matchedMaterials": [],
                    "candidateMaterials": [],
                    "fillTasks": [],
                    "resolvedArtifacts": [],
                }
            ],
        }
        with patch("app.services.technical_gap_service._schedule_gap_detection_job"):
            self.client.post(
                f"/api/technical/projects/{self.project_id}/gaps-detection/run"
            )
        with patch(
            "app.services.technical_gap_service.build_technical_gap_plan_for_project",
            return_value=plan,
        ), patch.object(
            __import__(
                "app.services.technical_gap_service",
                fromlist=["technical_gap_service"],
            ).technical_gap_service,
            "_autobuild_facts_after_detection",
        ):
            run_technical_gap_detection_job(self.project_id)

        status = self.client.get(
            f"/api/technical/projects/{self.project_id}/gaps-detection"
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")
        self.assertEqual(status.json()["percentage"], 100)


if __name__ == "__main__":
    unittest.main()
