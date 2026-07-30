from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.materials import OcrTask
from app.services.ocr_service import OcrService


class _FakeResult:
    def __init__(self, task: OcrTask | None) -> None:
        self.task = task

    def scalar_one_or_none(self) -> OcrTask | None:
        return self.task


class _FakeSession:
    def __init__(self, task: OcrTask | None = None, events: list[str] | None = None) -> None:
        self.task = task
        self.events = events
        self.added: list[Any] = []
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self.task)

    async def flush(self) -> None:
        return None

    async def refresh(self, _instance: Any) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def commit(self) -> None:
        if self.events is not None:
            self.events.append("commit")

    def add(self, instance: Any) -> None:
        self.added.append(instance)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, *_args: Any) -> None:
        return None


class OcrAuditResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_task_stays_completed_when_audit_record_fails(self) -> None:
        service = OcrService()
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = Path(temp_dir) / "OCR-success"
            task_dir.mkdir()
            input_path = task_dir / "source.png"
            input_path.write_bytes(b"fake png")
            task = OcrTask(
                id="OCR-success",
                project_id="PRJ-001",
                source_file_name="source.png",
                mime_type="image/png",
                status="pending",
                retry_count=0,
                max_retries=2,
                input_path=str(input_path),
                audit_meta={},
            )
            session = _FakeSession(task)
            audit_record = AsyncMock(side_effect=RuntimeError("audit unavailable"))

            with (
                patch(
                    "app.services.ocr_service.async_session",
                    return_value=_FakeSessionContext(session),
                ),
                patch(
                    "app.services.ocr_service.system_settings_service.get_model_secret_config",
                    new=AsyncMock(return_value={"enabled": True, "baseUrl": "http://ocr"}),
                ),
                patch.object(
                    service,
                    "_ocr_image",
                    new=AsyncMock(return_value=("项目：示例风场", {"requestId": "req-1"})),
                ),
                patch("app.services.ocr_service.audit_service.record", new=audit_record),
                self.assertLogs("app.services.ocr_service", level="ERROR") as logs,
            ):
                await service._process_task(task.id, "worker-test", 1)

            input_deleted = not input_path.exists()

        finalize_stmt = session.statements[1]
        finalize_params = finalize_stmt.compile().params
        self.assertEqual(finalize_params["status"], "completed")
        self.assertEqual(finalize_params["error_message"], "")
        self.assertEqual(finalize_params["page_count"], 1)
        self.assertTrue(input_deleted)
        self.assertEqual(len(session.added), 1)
        audit_record.assert_awaited_once()
        self.assertIn("OCR 审计记录失败：执行任务 OCR-success", "\n".join(logs.output))

    async def test_final_failure_is_committed_before_best_effort_audit(self) -> None:
        service = OcrService()
        events: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "source.png"
            input_path.write_bytes(b"fake png")
            task = OcrTask(
                id="OCR-failed",
                project_id="PRJ-001",
                source_file_name="source.png",
                mime_type="image/png",
                status="pending",
                retry_count=2,
                max_retries=2,
                input_path=str(input_path),
                audit_meta={},
            )
            session = _FakeSession(task, events)

            async def fail_audit(**_kwargs: Any) -> None:
                events.append("audit")
                raise RuntimeError("audit unavailable")

            with (
                patch(
                    "app.services.ocr_service.async_session",
                    return_value=_FakeSessionContext(session),
                ),
                patch(
                    "app.services.ocr_service.system_settings_service.get_model_secret_config",
                    new=AsyncMock(return_value={"enabled": True, "baseUrl": "http://ocr"}),
                ),
                patch.object(
                    service,
                    "_ocr_image",
                    new=AsyncMock(side_effect=RuntimeError("model unavailable")),
                ),
                patch("app.services.ocr_service.audit_service.record", new=fail_audit),
                self.assertLogs("app.services.ocr_service", level="ERROR"),
            ):
                await service._process_task(task.id, "worker-test", 1)

        self.assertEqual(events, ["commit", "audit"])
        finalize_stmt = session.statements[1]
        finalize_params = finalize_stmt.compile().params
        self.assertEqual(finalize_params["status"], "failed")
        self.assertEqual(finalize_params["error_message"], "model unavailable")

    async def test_enqueued_task_is_returned_when_submission_audit_fails(self) -> None:
        service = OcrService()
        session = _FakeSession()
        audit_record = AsyncMock(side_effect=RuntimeError("audit unavailable"))

        with (
            patch.object(service, "_ensure_tables", new=AsyncMock()),
            patch(
                "app.services.ocr_service.system_settings_service.get_model_secret_config",
                new=AsyncMock(return_value={"enabled": True, "baseUrl": "http://ocr"}),
            ),
            patch(
                "app.services.ocr_service.async_session",
                return_value=_FakeSessionContext(session),
            ),
            patch.object(
                service,
                "_persist_task_input",
                new=MagicMock(return_value=Path("/tmp/OCR-created/source.png")),
            ),
            patch.object(service, "start_worker", new=AsyncMock()),
            patch("app.services.ocr_service.audit_service.record", new=audit_record),
            patch("app.services.ocr_service.uuid4", return_value=MagicMock(hex="created")),
            self.assertLogs("app.services.ocr_service", level="ERROR") as logs,
        ):
            result = await service.run_ocr(
                project_id="PRJ-001",
                file_name="source.png",
                content=b"fake png",
            )

        self.assertEqual(result["id"], "OCR-created")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].status, "pending")
        audit_record.assert_awaited_once()
        self.assertIn("OCR 审计记录失败：提交任务 OCR-created", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
