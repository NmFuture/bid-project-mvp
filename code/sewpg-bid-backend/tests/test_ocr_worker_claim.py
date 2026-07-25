from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.sql.dml import Update

from app.services.ocr_service import _OCR_MAX_CONCURRENT, OcrService


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class _ClaimSession:
    """按调用顺序返回预设 scalar 结果：第一次 execute 是候选 SELECT，第二次是原子 claim UPDATE。"""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> _ScalarResult:
        self.statements.append(statement)
        value = self._results.pop(0) if self._results else None
        return _ScalarResult(value)

    async def commit(self) -> None:
        self.commits += 1


class _SessionContext:
    def __init__(self, session: _ClaimSession) -> None:
        self.session = session

    async def __aenter__(self) -> _ClaimSession:
        return self.session

    async def __aexit__(self, *_args: Any) -> None:
        return None


class OcrAtomicClaimTests(unittest.IsolatedAsyncioTestCase):
    def _patch_session(self, session: _ClaimSession):
        return patch(
            "app.services.ocr_service.async_session",
            return_value=_SessionContext(session),
        )

    async def test_claim_won_marks_processing_and_runs_task(self) -> None:
        service = OcrService()
        session = _ClaimSession(["OCR-1", "OCR-1"])
        process_task = AsyncMock()

        with self._patch_session(session), patch.object(service, "_process_task", new=process_task):
            processed = await service._process_one_pending_task()

        self.assertTrue(processed)
        process_task.assert_awaited_once_with("OCR-1")
        self.assertEqual(session.commits, 1)
        self.assertEqual(len(session.statements), 2)
        claim_stmt = session.statements[1]
        self.assertIsInstance(claim_stmt, Update)
        claim_params = claim_stmt.compile().params
        self.assertEqual(claim_params["status"], "processing")
        self.assertIn("locked_at", claim_params)

    async def test_claim_lost_returns_true_without_processing(self) -> None:
        """候选任务被其他 worker 抢先 claim：UPDATE 条件不满足返回空，不处理但继续抢下一条。"""
        service = OcrService()
        session = _ClaimSession(["OCR-1", None])
        process_task = AsyncMock()

        with self._patch_session(session), patch.object(service, "_process_task", new=process_task):
            processed = await service._process_one_pending_task()

        self.assertTrue(processed)
        process_task.assert_not_awaited()
        self.assertEqual(session.commits, 1)

    async def test_claim_condition_covers_pending_and_stale_processing(self) -> None:
        """claim 条件同时覆盖未锁定 pending 与锁超时的 processing 回收。"""
        service = OcrService()
        session = _ClaimSession(["OCR-1", "OCR-1"])

        with self._patch_session(session), patch.object(service, "_process_task", new=AsyncMock()):
            await service._process_one_pending_task()

        claim_sql = str(session.statements[1])
        claim_params = session.statements[1].compile().params
        self.assertIn("locked_at IS NULL", claim_sql)
        self.assertIn("locked_at <", claim_sql)
        self.assertEqual(claim_params["status_1"], "pending")
        self.assertEqual(claim_params["status_2"], "processing")

    async def test_no_claimable_task_returns_false(self) -> None:
        service = OcrService()
        session = _ClaimSession([None])
        process_task = AsyncMock()

        with self._patch_session(session), patch.object(service, "_process_task", new=process_task):
            processed = await service._process_one_pending_task()

        self.assertFalse(processed)
        process_task.assert_not_awaited()
        self.assertEqual(len(session.statements), 1)


class OcrWorkerConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_worker_spawns_max_concurrent_loops(self) -> None:
        service = OcrService()
        loop_mock = MagicMock(side_effect=lambda: service._shutdown_event.wait())

        with patch.object(service, "_ocr_worker_loop", new=loop_mock):
            await service.start_worker()
            self.assertEqual(len(service._worker_tasks), _OCR_MAX_CONCURRENT)
            self.assertEqual(loop_mock.call_count, _OCR_MAX_CONCURRENT)

            # 幂等：重复启动不增加 worker
            await service.start_worker()
            self.assertEqual(len(service._worker_tasks), _OCR_MAX_CONCURRENT)
            self.assertEqual(loop_mock.call_count, _OCR_MAX_CONCURRENT)

            await service.stop_worker()

        self.assertEqual(service._worker_tasks, [])
        self.assertTrue(service._shutdown_event.is_set())

    async def test_workers_process_tasks_concurrently(self) -> None:
        """多个 worker loop 并行时，不同任务可真正并发执行（不串行等待）。"""
        service = OcrService()
        release = asyncio.Event()
        in_flight = 0
        max_in_flight = 0

        async def fake_process() -> bool:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await release.wait()
            in_flight -= 1
            service._shutdown_event.set()
            return True

        with patch.object(service, "_process_one_pending_task", side_effect=fake_process):
            await service.start_worker()
            await asyncio.sleep(0.1)
            self.assertGreaterEqual(max_in_flight, 2)
            release.set()
            await service.stop_worker()

        self.assertEqual(service._worker_tasks, [])


if __name__ == "__main__":
    unittest.main()
