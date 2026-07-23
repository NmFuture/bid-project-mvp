from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import bid_parse_service
from app.services.bid_parse_cancel import ParseCancelledError
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

    def test_upload_and_run_returns_409_with_file_name_when_another_parse_active(self) -> None:
        project_id = self.create_project()
        active_job = {
            "id": "job-other-1",
            "projectId": "PRJ-OTHER",
            "data": {"tenderFiles": [{"name": "其他项目招标文件.docx"}]},
        }
        with patch(
            "app.services.bid_parse_service.find_active_jobs_of_type",
            return_value=[active_job],
        ):
            response = self.post_upload(project_id)
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertIn("其他项目招标文件.docx", detail)
        self.assertIn("每次只能解析一个任务", detail)

    def test_upload_and_run_ignores_active_job_of_same_project(self) -> None:
        project_id = self.create_project()
        same_project_job = {
            "id": "job-same-1",
            "projectId": project_id,
            "data": {"tenderFiles": [{"name": "本项目的文件.docx"}]},
        }
        # 同项目的活跃任务不触发全局互斥（由项目锁负责）；调度成功即放行。
        with patch(
            "app.services.bid_parse_service.find_active_jobs_of_type",
            return_value=[same_project_job],
        ), patch(
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

    def test_execute_s1_parse_job_skips_parse_when_cancelled_while_queued(self) -> None:
        project_id = self.create_project()
        service = bid_parse_service.technical_parse_service
        service._mark_parse_queued(project_id, "解析任务已提交，排队等待中。", file_names=["招标文件.docx"])
        service.cancel_parse(project_id)
        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            return_value=fake_parse_payload(),
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
        # 排队期间已取消：worker 消费时不得执行解析，进度保持 cancelled。
        parse_mock.assert_not_called()
        progress = self.client.get(f"/api/technical/projects/{project_id}/parse-results/progress").json()
        self.assertEqual(progress["status"], "cancelled")
        self.assertTrue(progress["cancelRequested"])

    def test_execute_s1_parse_job_marks_failed_when_post_processing_fails(self) -> None:
        project_id = self.create_project()
        summary, storage = fake_parse_payload()
        settings.s1_parse_job_max_attempts = 3
        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            return_value=(summary, storage),
        ) as parse_mock, patch(
            "app.services.bid_parse_service.materialize_parse_appendix_docx_assets",
            side_effect=RuntimeError("appendix docx 502 unavailable"),
        ):
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
        # 后处理失败不做整链重试：解析只跑一次，进度落为 failed 并带真实异常信息。
        self.assertEqual(parse_mock.call_count, 1)
        progress = self.client.get(f"/api/technical/projects/{project_id}/parse-results/progress").json()
        self.assertEqual(progress["status"], "failed")
        self.assertIn("appendix docx 502 unavailable", progress["summary"])

    def test_execute_s1_parse_job_post_processing_cancel_stays_cancelled(self) -> None:
        project_id = self.create_project()
        summary, storage = fake_parse_payload()
        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            return_value=(summary, storage),
        ), patch(
            "app.services.bid_parse_service.materialize_parse_appendix_docx_assets",
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
        # 后处理阶段的取消语义不得被兜底改成 failed。
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
        with patch("app.services.bid_parse_service._run_s1_parse_job") as job_mock:
            redis_worker._run_job(
                {"id": "job-dispatch-1", "type": "s1_parse", "projectId": project_id, "data": {"__bidType": "技术标"}}
            )
        job_mock.assert_called_once_with(project_id, {"__bidType": "技术标"})


if __name__ == "__main__":
    unittest.main()
