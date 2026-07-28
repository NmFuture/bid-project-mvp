from __future__ import annotations

import asyncio
import unittest

from app.services.background_job_registry import (
    _JOBS,
    get_job_status,
    start_job,
    update_job_progress,
)


class BackgroundJobRegistryTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        _JOBS.clear()

    async def test_idle_status_for_unknown_job(self) -> None:
        self.assertEqual(get_job_status("missing"), {"name": "missing", "status": "idle"})

    async def test_job_runs_to_succeeded_with_progress_and_result(self) -> None:
        async def work() -> dict:
            update_job_progress("cert", {"processed": 1, "total": 2})
            await asyncio.sleep(0)
            return {"message": "done"}

        status = start_job("cert", work)
        self.assertEqual(status["status"], "running")
        # 让后台 task 跑完
        await asyncio.gather(*[job["task"] for job in _JOBS.values() if job.get("task")])
        final = get_job_status("cert")
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["result"], {"message": "done"})
        self.assertEqual(final["progress"], {"processed": 1, "total": 2})
        self.assertTrue(final["startedAt"])
        self.assertTrue(final["finishedAt"])

    async def test_start_is_idempotent_while_running(self) -> None:
        gate = asyncio.Event()
        starts = 0

        async def work() -> dict:
            nonlocal starts
            starts += 1
            await gate.wait()
            return {"ok": True}

        first = start_job("wiki", work)
        second = start_job("wiki", work)
        self.assertEqual(first["status"], "running")
        self.assertEqual(second["status"], "running")
        gate.set()
        await asyncio.gather(*[job["task"] for job in _JOBS.values() if job.get("task")])
        self.assertEqual(starts, 1)
        self.assertEqual(get_job_status("wiki")["status"], "succeeded")

    async def test_failure_is_recorded_not_swallowed(self) -> None:
        async def work() -> dict:
            raise RuntimeError("boom")

        start_job("broken", work)
        await asyncio.gather(*[job["task"] for job in _JOBS.values() if job.get("task")])
        final = get_job_status("broken")
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["error"], "boom")
        self.assertIsNone(final["result"])

    async def test_restart_after_terminal_state(self) -> None:
        async def work() -> dict:
            return {"ok": True}

        start_job("rerun", work)
        await asyncio.gather(*[job["task"] for job in _JOBS.values() if job.get("task")])
        again = start_job("rerun", work)
        self.assertEqual(again["status"], "running")
        await asyncio.gather(*[job["task"] for job in _JOBS.values() if job.get("task")])
        self.assertEqual(get_job_status("rerun")["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
