from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import bid_parse_service
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.job_queue import EnqueueResult
from app.services.store import store
from app.workers import redis_worker


def build_docx_bytes(*lines: str) -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(file_obj)
    return file_obj.getvalue()


def fake_parse_payload() -> tuple[dict, dict]:
    summary = {"fileCount": 1, "extractedCount": 1, "textLength": 1, "textPreview": "", "warnings": []}
    storage = {"documents": [], "items": [], "structured": {}, "projectUpdates": {}}
    return summary, storage


def fake_tender_record() -> dict:
    return {
        "id": "TEN-1",
        "name": "招标文件.md",
        "stored_name": "tender-1-fake.md",
        "size_bytes": 128,
        "size_label": "0.00 MB",
        "content_type": "text/markdown",
        "path": "/tmp/fake-tender.md",
    }


class ParseAsyncJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        store._ensure_db()
        self.technical_appendix_sync_patcher = patch(
            "app.services.bid_project_service.sync_technical_parse_appendices",
            new=AsyncMock(return_value={"status": "synced", "syncedCount": 0}),
        )
        self.technical_appendix_sync_patcher.start()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        self.technical_appendix_sync_patcher.stop()
        self.temp_dir.cleanup()

    def create_project(self) -> str:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": "异步解析测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def create_business_project(self) -> str:
        response = self.client.post(
            "/api/business/projects",
            json={"name": "商务异步解析测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def post_upload(self, project_id: str, *, prefix: str = "/api/technical/projects"):
        return self.client.post(
            f"{prefix}/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    (
                        "招标文件.docx",
                        build_docx_bytes("异步解析测试招标文件"),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

    def test_upload_and_run_returns_202_queued_when_job_scheduled(self) -> None:
        project_id = self.create_project()
        with patch(
            "app.services.bid_parse_service._schedule_s1_parse_job",
            return_value=("queued", "job-queued-1"),
        ):
            response = self.post_upload(project_id)
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["jobId"], "job-queued-1")
        self.assertIn("后台", payload["message"])

        progress = self.client.get(f"/api/technical/projects/{project_id}/parse-results/progress").json()
        self.assertEqual(progress["status"], "queued")
        self.assertEqual(progress["phaseKey"], "queue")
        # 目标文件名随进度常驻，供前端提醒用户当前解析对象
        self.assertEqual(progress["fileNames"], ["招标文件.docx"])

    def test_upload_and_run_allows_another_project_to_queue(self) -> None:
        project_id = self.create_project()
        with patch(
            "app.services.bid_parse_service._schedule_s1_parse_job",
            return_value=("queued", "job-second-project"),
        ):
            response = self.post_upload(project_id)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["jobId"], "job-second-project")

    def test_upload_and_run_ignores_active_job_of_same_project(self) -> None:
        project_id = self.create_project()
        # 同项目冲突由项目锁负责；调度成功即放行。
        with patch(
            "app.services.bid_parse_service._schedule_s1_parse_job",
            return_value=("queued", "job-same-queued"),
        ):
            response = self.post_upload(project_id)
        self.assertEqual(response.status_code, 202)

    def test_upload_and_run_returns_409_when_parse_locked(self) -> None:
        project_id = self.create_project()
        with patch("app.services.bid_parse_service.is_generation_locked", return_value=True):
            response = self.post_upload(project_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn("进行中", response.json()["detail"])

    def test_business_run_endpoint_returns_409_when_locked_and_400_without_files(self) -> None:
        project_id = self.create_business_project()
        # 先内联完成一次解析，让项目有可复用的招标文件。
        self.post_upload(project_id, prefix="/api/business/projects").raise_for_status()
        with patch("app.services.bid_parse_service.is_generation_locked", return_value=True):
            response = self.client.post(f"/api/business/projects/{project_id}/parse-results/run")
        self.assertEqual(response.status_code, 409)

        other_id = self.create_business_project()
        response = self.client.post(f"/api/business/projects/{other_id}/parse-results/run")
        self.assertEqual(response.status_code, 400)

    def test_run_endpoint_returns_202_queued_when_scheduled(self) -> None:
        project_id = self.create_project()
        # 先内联完成一次解析，让项目有可复用的招标文件。
        self.post_upload(project_id).raise_for_status()
        with patch(
            "app.services.bid_parse_service._schedule_s1_parse_job",
            return_value=("queued", "job-rerun-1"),
        ):
            response = self.client.post(f"/api/technical/projects/{project_id}/parse-results/run")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["jobId"], "job-rerun-1")

    def test_execute_s1_parse_job_success_completes_progress_and_result(self) -> None:
        project_id = self.create_project()
        summary, storage = fake_parse_payload()
        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            return_value=(summary, storage),
        ) as parse_mock:
            bid_parse_service._run_s1_parse_job(
                project_id,
                {
                    "__bidType": "技术标",
                    "origin": "upload",
                    "tenderFiles": [fake_tender_record()],
                    "templateFiles": [],
                },
            )
        self.assertEqual(parse_mock.call_count, 1)
        progress = self.client.get(f"/api/technical/projects/{project_id}/parse-results/progress").json()
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["percentage"], 100)
        steps = [event.get("step") for event in progress["events"]]
        self.assertIn("upload", steps)
        result = self.client.get(f"/api/technical/projects/{project_id}/parse-results").json()
        self.assertEqual(result["status"], "completed")

    def test_execute_s1_parse_job_retries_transient_error_then_succeeds(self) -> None:
        project_id = self.create_project()
        summary, storage = fake_parse_payload()
        settings.s1_parse_job_max_attempts = 3
        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            side_effect=[RuntimeError("opencode 502 bad gateway"), (summary, storage)],
        ) as parse_mock, patch(
            "app.services.bid_parse_service.time.sleep"
        ) as sleep_mock:
            bid_parse_service._run_s1_parse_job(
                project_id,
                {
                    "__bidType": "技术标",
                    "origin": "upload",
                    "tenderFiles": [fake_tender_record()],
                    "templateFiles": [],
                },
            )
        self.assertEqual(parse_mock.call_count, 2)
        sleep_mock.assert_called_once_with(30)
        progress = self.client.get(f"/api/technical/projects/{project_id}/parse-results/progress").json()
        self.assertEqual(progress["status"], "completed")
        retry_events = [event for event in progress["events"] if event.get("step") in {"retry", "retry_wait"}]
        self.assertTrue(retry_events)

    def test_execute_s1_parse_job_does_not_retry_deterministic_error(self) -> None:
        project_id = self.create_project()
        settings.s1_parse_job_max_attempts = 3
        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            side_effect=RuntimeError("appendix slicing broken"),
        ) as parse_mock:
            with self.assertRaises(RuntimeError):
                bid_parse_service._run_s1_parse_job(
                    project_id,
                    {
                        "__bidType": "技术标",
                        "origin": "upload",
                        "tenderFiles": [fake_tender_record()],
                        "templateFiles": [],
                    },
                )
        self.assertEqual(parse_mock.call_count, 1)
        progress = self.client.get(f"/api/technical/projects/{project_id}/parse-results/progress").json()
        self.assertEqual(progress["status"], "failed")
        self.assertIn("appendix slicing broken", progress["summary"])

    def test_execute_s1_parse_job_honours_cancel(self) -> None:
        project_id = self.create_project()
        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            side_effect=ParseCancelledError("解析已取消。"),
        ):
            bid_parse_service._run_s1_parse_job(
                project_id,
                {
                    "__bidType": "技术标",
                    "origin": "upload",
                    "tenderFiles": [fake_tender_record()],
                    "templateFiles": [],
                },
            )
        progress = self.client.get(f"/api/technical/projects/{project_id}/parse-results/progress").json()
        self.assertEqual(progress["status"], "cancelled")

    def test_execute_s1_parse_job_requires_bid_type(self) -> None:
        project_id = self.create_project()
        with self.assertRaises(ValueError):
            bid_parse_service._run_s1_parse_job(project_id, {"tenderFiles": [fake_tender_record()]})

    def test_update_parse_progress_throttles_persist(self) -> None:
        project_id = self.create_project()
        settings.parse_progress_persist_interval_sec = 60.0
        service = bid_parse_service.technical_parse_service
        service._progress_persist_guard.pop(project_id, None)
        with patch("app.services.bid_parse_service.persist_workspace_project_state") as persist_mock:
            service.start_parse_progress(project_id)
            service.update_parse_progress(project_id, phase_key="extract", percentage=10, summary="提取中")
            service.update_parse_progress(project_id, phase_key="extract", percentage=11, summary="提取中")
        # start 必写、跨阶段必写、同阶段间隔内跳过：共 2 次落库。
        self.assertEqual(persist_mock.call_count, 2)

    def test_worker_dispatches_s1_parse_job(self) -> None:
        project_id = self.create_project()
        with patch(
            "app.services.docling_jobs.enqueue_docling_batch",
            return_value=EnqueueResult(queued=True, job_id="job-dispatch-1:docling"),
        ) as enqueue_mock, patch(
            "app.workers.redis_worker.renew_generation_lock",
            return_value=True,
        ), patch(
            "app.workers.redis_worker.claim_s1_workflow_lock",
            return_value=True,
        ), patch(
            "app.workers.redis_worker.release_s1_workflow_lock",
        ) as release_workflow_mock:
            redis_worker._run_job(
                {"id": "job-dispatch-1", "type": "s1_parse", "projectId": project_id, "data": {"__bidType": "技术标"}}
            )
        enqueue_mock.assert_called_once()
        release_workflow_mock.assert_not_called()

    def test_worker_requeues_later_project_while_s1_workflow_is_busy(self) -> None:
        job = {
            "id": "job-waiting-2",
            "type": "s1_parse",
            "projectId": "project-2",
            "data": {"__bidType": "技术标"},
            "__queueKey": "bid:jobs",
            "__processingPayload": "payload",
        }
        with patch(
            "app.workers.redis_worker.renew_generation_lock",
            return_value=True,
        ), patch(
            "app.workers.redis_worker.claim_s1_workflow_lock",
            return_value=False,
        ), patch(
            "app.workers.redis_worker.requeue_processing_job",
            return_value=True,
        ) as requeue_mock, patch(
            "app.services.docling_jobs.enqueue_docling_batch",
        ) as enqueue_mock:
            completed = redis_worker._run_job(job)

        self.assertFalse(completed)
        requeue_mock.assert_called_once_with(job, "等待当前 S1 解析工作流完成。")
        enqueue_mock.assert_not_called()

    def test_continuation_releases_parent_project_and_workflow_locks(self) -> None:
        parent = {"id": "run-1", "type": "s1_parse", "projectId": "project-1"}
        job = {
            "id": "run-1:continue",
            "type": "s1_parse_continue",
            "projectId": "project-1",
            "parentJobId": "run-1",
            "data": {"__bidType": "技术标"},
        }
        service = MagicMock()
        with patch(
            "app.workers.redis_worker.renew_generation_lock",
            return_value=True,
        ), patch(
            "app.workers.redis_worker.claim_s1_workflow_lock",
            return_value=True,
        ), patch(
            "app.workers.redis_worker._s1_parse_service",
            return_value=service,
        ), patch(
            "app.workers.redis_worker._terminal_parse_progress",
            return_value={"status": "completed", "summary": "done"},
        ), patch(
            "app.workers.redis_worker.release_generation_lock",
        ) as release_project_mock, patch(
            "app.workers.redis_worker.release_s1_workflow_lock",
        ) as release_workflow_mock:
            completed = redis_worker._run_job(job)

        self.assertTrue(completed)
        release_project_mock.assert_called_once_with(parent)
        release_workflow_mock.assert_called_once_with(parent)


if __name__ == "__main__":
    unittest.main()
