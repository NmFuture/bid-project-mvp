from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy.sql.dml import Update

from app.models.materials import OcrCandidate, OcrTask
from app.services.ocr_service import OcrService


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def first(self) -> Any:
        return self.value


class _LeaseSession:
    """按调用顺序返回预设 execute 结果，并记录语句/写入/提交用于断言。"""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        value = self._results.pop(0) if self._results else None
        return _FakeResult(value)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def add(self, instance: Any) -> None:
        self.added.append(instance)


class _SessionContext:
    def __init__(self, session: _LeaseSession) -> None:
        self.session = session

    async def __aenter__(self) -> _LeaseSession:
        return self.session

    async def __aexit__(self, *_args: Any) -> None:
        return None


def _patch_session(session: _LeaseSession):
    return patch(
        "app.services.ocr_service.async_session",
        return_value=_SessionContext(session),
    )


def _sample_candidates() -> list[dict[str, Any]]:
    return [
        {
            "fieldName": "项目名称",
            "fieldValue": "示例风场",
            "fieldType": "text",
            "confidence": 80,
            "sourceText": "项目名称：示例风场",
            "pageNumber": 1,
        }
    ]


class OcrLeaseRenewTests(unittest.IsolatedAsyncioTestCase):
    async def test_renew_lease_refreshes_locked_at_with_owner_guard(self) -> None:
        """续租以 (task_id, owner, fence_token) 为条件刷新 locked_at。"""
        service = OcrService()
        session = _LeaseSession(["OCR-1"])

        with _patch_session(session):
            renewed = await service._renew_lease("OCR-1", "worker-a", 3)

        self.assertTrue(renewed)
        self.assertEqual(session.commits, 1)
        stmt = session.statements[0]
        self.assertIsInstance(stmt, Update)
        params = stmt.compile().params
        self.assertIn("locked_at", params)
        self.assertEqual(params["locked_by_1"], "worker-a")
        self.assertEqual(params["fence_token_1"], 3)
        self.assertEqual(params["status_1"], "processing")

    async def test_renew_lease_returns_false_when_lease_lost(self) -> None:
        """任务已被其他 worker 接管（fence token 变化）时续租失败。"""
        service = OcrService()
        session = _LeaseSession([None])

        with _patch_session(session):
            renewed = await service._renew_lease("OCR-1", "worker-a", 1)

        self.assertFalse(renewed)


class OcrHeartbeatLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_keeps_long_task_lease_fresh(self) -> None:
        """长任务执行期间持续续租，locked_at 不会停在 claim 时刻而被超时回收。"""
        service = OcrService()
        lost_lease = asyncio.Event()
        renew = AsyncMock(return_value=True)

        with (
            patch("app.services.ocr_service._OCR_HEARTBEAT_INTERVAL_SECONDS", 0.01),
            patch.object(service, "_renew_lease", new=renew),
        ):
            heartbeat = asyncio.create_task(
                service._heartbeat_loop("OCR-1", "worker-a", 1, lost_lease, None)
            )
            await asyncio.sleep(0.05)
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

        self.assertGreaterEqual(renew.await_count, 2)
        self.assertFalse(lost_lease.is_set())

    async def test_heartbeat_failure_cancels_processing(self) -> None:
        """续租失败（worker 失联后任务被接管）时取消本地处理并置位 lost_lease。"""
        service = OcrService()
        lost_lease = asyncio.Event()
        renew = AsyncMock(side_effect=[True, False])
        victim = asyncio.create_task(asyncio.sleep(60))

        with (
            patch("app.services.ocr_service._OCR_HEARTBEAT_INTERVAL_SECONDS", 0.01),
            patch.object(service, "_renew_lease", new=renew),
        ):
            await service._heartbeat_loop("OCR-1", "worker-a", 1, lost_lease, victim)

        await asyncio.gather(victim, return_exceptions=True)
        self.assertTrue(lost_lease.is_set())
        self.assertTrue(victim.cancelled())
        self.assertEqual(renew.await_count, 2)


class OcrFencingFinalizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_worker_result_does_not_overwrite(self) -> None:
        """worker A 失联、任务被 worker B（fence token 更大）接管后，A 的迟到结果被丢弃。"""
        service = OcrService()
        # DB 中任务已是 owner-b/fence 2，owner-a/fence 1 的条件更新匹配不到行
        session = _LeaseSession([None])

        with _patch_session(session):
            finalized = await service._finalize_task_success(
                "OCR-1",
                "worker-a",
                1,
                project_id="PRJ-001",
                page_count=1,
                raw_response={"requestId": "req-a"},
                extracted_text="项目名称：示例风场",
                candidates=_sample_candidates(),
            )

        self.assertFalse(finalized)
        self.assertEqual(session.added, [])
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)
        stmt = session.statements[0]
        params = stmt.compile().params
        self.assertEqual(params["locked_by_1"], "worker-a")
        self.assertEqual(params["fence_token_1"], 1)
        self.assertEqual(params["status_1"], "processing")

    async def test_success_finalize_writes_candidates_once(self) -> None:
        """首次写入成功并落候选；任务已 completed 后重复提交被 fencing 拒绝（幂等）。"""
        service = OcrService()
        first_session = _LeaseSession(["OCR-1"])

        with _patch_session(first_session):
            finalized = await service._finalize_task_success(
                "OCR-1",
                "worker-a",
                1,
                project_id="PRJ-001",
                page_count=1,
                raw_response={},
                extracted_text="项目名称：示例风场",
                candidates=_sample_candidates(),
            )

        self.assertTrue(finalized)
        self.assertEqual(first_session.commits, 1)
        self.assertEqual(len(first_session.added), 1)
        self.assertIsInstance(first_session.added[0], OcrCandidate)
        self.assertEqual(first_session.added[0].task_id, "OCR-1")

        # 重复提交：任务已 completed，guard 不匹配，不再产生重复候选
        second_session = _LeaseSession([None])
        with _patch_session(second_session):
            again = await service._finalize_task_success(
                "OCR-1",
                "worker-a",
                1,
                project_id="PRJ-001",
                page_count=1,
                raw_response={},
                extracted_text="项目名称：示例风场",
                candidates=_sample_candidates(),
            )

        self.assertFalse(again)
        self.assertEqual(second_session.added, [])
        self.assertEqual(second_session.commits, 0)

    async def test_failure_finalize_releases_lock_for_retry(self) -> None:
        """可重试失败释放锁并递增 retry_count；最终失败置 failed 且不重复审计状态。"""
        service = OcrService()
        retry_session = _LeaseSession(["OCR-1"])

        with _patch_session(retry_session):
            finalized, is_final = await service._finalize_task_failure(
                "OCR-1",
                "worker-a",
                1,
                error_message="model unavailable",
                retry_count=0,
                max_retries=2,
                allow_retry=True,
            )

        self.assertTrue(finalized)
        self.assertFalse(is_final)
        params = retry_session.statements[0].compile().params
        self.assertEqual(params["status"], "pending")
        self.assertEqual(params["retry_count"], 1)
        self.assertIsNone(params["locked_at"])
        self.assertIsNone(params["locked_by"])

        final_session = _LeaseSession(["OCR-1"])
        with _patch_session(final_session):
            finalized, is_final = await service._finalize_task_failure(
                "OCR-1",
                "worker-a",
                1,
                error_message="model unavailable",
                retry_count=2,
                max_retries=2,
                allow_retry=True,
            )

        self.assertTrue(finalized)
        self.assertTrue(is_final)
        params = final_session.statements[0].compile().params
        self.assertEqual(params["status"], "failed")
        self.assertNotIn("retry_count", params)


class OcrRunClaimedTaskLeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_result_dropped_when_lease_lost_during_ocr(self) -> None:
        """OCR 执行期间租约易主：结果不落库、不记审计、不删输入文件。"""
        service = OcrService()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "source.png"
            input_path.write_bytes(b"fake png")
            task = OcrTask(
                id="OCR-lost",
                project_id="PRJ-001",
                source_file_name="source.png",
                mime_type="image/png",
                status="processing",
                retry_count=0,
                max_retries=2,
                input_path=str(input_path),
                audit_meta={},
            )
            session = _LeaseSession([task])
            lost_lease = asyncio.Event()
            audit_record = AsyncMock()

            async def fake_ocr_image(*_args: Any, **_kwargs: Any) -> tuple[str, dict[str, Any]]:
                # OCR 返回时租约已被其他 worker 接管
                lost_lease.set()
                return "项目名称：示例风场", {"requestId": "req-late"}

            with (
                _patch_session(session),
                patch(
                    "app.services.ocr_service.system_settings_service.get_model_secret_config",
                    new=AsyncMock(return_value={"enabled": True, "baseUrl": "http://ocr"}),
                ),
                patch.object(service, "_ocr_image", new=fake_ocr_image),
                patch("app.services.ocr_service.audit_service.record", new=audit_record),
            ):
                await service._run_claimed_task("OCR-lost", "worker-a", 1, lost_lease)

            input_kept = input_path.exists()

        # 只有加载任务的 SELECT，没有任何结果写入
        self.assertEqual(len(session.statements), 1)
        self.assertEqual(session.added, [])
        audit_record.assert_not_awaited()
        self.assertTrue(input_kept)


if __name__ == "__main__":
    unittest.main()
