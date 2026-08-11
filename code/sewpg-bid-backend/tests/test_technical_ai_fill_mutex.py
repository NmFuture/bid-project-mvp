"""单条填写与一键填写互斥（#229）：409、(project, gap) 锁、失败/完成后释放可重试。"""
from __future__ import annotations

import threading
import unittest
from unittest import mock

from fastapi import HTTPException

from app.services import job_queue
from app.services import technical_gap_service as service_module
from app.services.technical_gap_service import TechnicalGapService

TABLE_SKILL = "bid-tech-table-filler"


class _FakeRedis:
    """最小 Redis 替身：只实现锁用到的 set NX EX 与 owner 校验删除脚本。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def eval(self, script, numkeys, key, owner):
        if self.store.get(key) == owner:
            del self.store[key]
            return 1
        return 0


def _project_with_gap() -> dict:
    return {
        "id": "PRJ-MUTEX",
        "gap_state": {
            "recognitionStatus": "completed",
            "projectFactTable": {"status": "confirmed"},
            "plan": {
                "items": [
                    {
                        "id": "G1",
                        "title": "目录项G1",
                        "decision": "fill_required",
                        "fillTasks": [{"id": "T1", "skill": TABLE_SKILL, "status": "pending"}],
                        "appendixTasks": [],
                    }
                ]
            },
        },
    }


def _fill_payload() -> dict:
    return {
        "artifact": {"id": "ART-G1-T1", "fillTaskId": "T1", "fileName": "G1_AI填写.docx"},
        "artifacts": [],
        "item": {},
        "gapPlan": {},
    }


class BodyFillRunningBlocksAiFillTests(unittest.TestCase):
    """一键填写运行中（状态或队列锁任一成立）时，单条 ai_fill 返回 409。"""

    def setUp(self) -> None:
        self.project = _project_with_gap()
        patches = [
            mock.patch.object(
                service_module, "require_technical_gap_project_for_update", return_value=self.project
            ),
            mock.patch.object(
                service_module, "ensure_technical_gap_state", side_effect=lambda project: project["gap_state"]
            ),
            mock.patch.object(service_module, "repair_technical_gap_state_fill_task_skills", return_value=False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.service = TechnicalGapService()

    def test_queue_lock_held_returns_409(self) -> None:
        with mock.patch.object(service_module, "body_fill_locked", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                self.service.ai_fill("PRJ-MUTEX", "G1", object(), {})
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("一键填写", str(ctx.exception.detail))

    def test_running_state_returns_409(self) -> None:
        self.project["gap_state"]["bodyFillState"] = {"status": "running"}
        with (
            mock.patch.object(service_module, "body_fill_locked", return_value=False),
            mock.patch.object(service_module, "body_fill_stale", return_value=False),
        ):
            with self.assertRaises(HTTPException) as ctx:
                self.service.ai_fill("PRJ-MUTEX", "G1", object(), {})
        self.assertEqual(ctx.exception.status_code, 409)

    def test_ai_fill_all_also_blocked(self) -> None:
        with mock.patch.object(service_module, "body_fill_locked", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                self.service.ai_fill_all("PRJ-MUTEX", object(), {})
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("一键填写", str(ctx.exception.detail))


class AiFillSlotTests(unittest.TestCase):
    """(project, gap) 互斥位：并发冲突、释放后重试、Redis 缺席时进程内兜底。"""

    def tearDown(self) -> None:
        # 测试间清理进程内兜底锁，避免串用例
        with service_module._LOCAL_AI_FILL_SLOTS_GUARD:
            service_module._LOCAL_AI_FILL_SLOTS.clear()

    def test_local_fallback_mutex_and_release(self) -> None:
        with mock.patch.object(job_queue, "get_redis_client", return_value=None):
            first = service_module._acquire_ai_fill_slot("PRJ-MUTEX", "G1")
            self.assertIsNotNone(first)
            # 同 gap 冲突，不同 gap 不受影响
            self.assertIsNone(service_module._acquire_ai_fill_slot("PRJ-MUTEX", "G1"))
            other = service_module._acquire_ai_fill_slot("PRJ-MUTEX", "G2")
            self.assertIsNotNone(other)
            service_module._release_ai_fill_slot("PRJ-MUTEX", "G1", first)
            retry = service_module._acquire_ai_fill_slot("PRJ-MUTEX", "G1")
            self.assertIsNotNone(retry)
            service_module._release_ai_fill_slot("PRJ-MUTEX", "G1", retry)
            service_module._release_ai_fill_slot("PRJ-MUTEX", "G2", other)

    def test_redis_lock_mutex_and_owner_checked_release(self) -> None:
        fake = _FakeRedis()
        with mock.patch.object(job_queue, "get_redis_client", return_value=fake):
            self.assertTrue(job_queue.acquire_ai_fill_lock("PRJ-MUTEX", "G1", "owner-1"))
            self.assertFalse(job_queue.acquire_ai_fill_lock("PRJ-MUTEX", "G1", "owner-2"))
            # 非 owner 释放不掉，owner 释放后可重试
            job_queue.release_ai_fill_lock("PRJ-MUTEX", "G1", "owner-2")
            self.assertFalse(job_queue.acquire_ai_fill_lock("PRJ-MUTEX", "G1", "owner-3"))
            job_queue.release_ai_fill_lock("PRJ-MUTEX", "G1", "owner-1")
            self.assertTrue(job_queue.acquire_ai_fill_lock("PRJ-MUTEX", "G1", "owner-3"))


class AiFillConcurrencyTests(unittest.TestCase):
    """同 gap 并发单条填写：一个执行、一个 409；失败/完成后锁释放可重试。"""

    def setUp(self) -> None:
        self.project = _project_with_gap()
        patches = [
            mock.patch.object(
                service_module, "require_technical_gap_project_for_update", return_value=self.project
            ),
            mock.patch.object(
                service_module, "ensure_technical_gap_state", side_effect=lambda project: project["gap_state"]
            ),
            mock.patch.object(service_module, "body_fill_locked", return_value=False),
            mock.patch.object(service_module, "repair_technical_gap_state_fill_task_skills", return_value=False),
            mock.patch.object(job_queue, "get_redis_client", return_value=None),
            mock.patch.object(
                service_module,
                "mutate_technical_gap_project",
                side_effect=lambda project_id, mutate, **kwargs: mutate(self.project),
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.service = TechnicalGapService()
        patcher = mock.patch.object(self.service, "_refresh_gap_integrity", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        url_patcher = mock.patch.object(
            self.service, "_url_scope", return_value={"browser_base_url": "", "onlyoffice_base_url": ""}
        )
        url_patcher.start()
        self.addCleanup(url_patcher.stop)

    def tearDown(self) -> None:
        with service_module._LOCAL_AI_FILL_SLOTS_GUARD:
            service_module._LOCAL_AI_FILL_SLOTS.clear()

    def test_concurrent_same_gap_one_wins_one_409(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def slow_fill(project, gap_id, data, **kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=30))
            return _fill_payload()

        outcomes: dict[str, object] = {}

        def run(key: str) -> None:
            try:
                outcomes[key] = self.service.ai_fill("PRJ-MUTEX", "G1", object(), {"fillTaskId": "T1"})
            except HTTPException as exc:
                outcomes[key] = exc

        with mock.patch.object(service_module, "run_technical_ai_fill_for_gap", side_effect=slow_fill):
            first = threading.Thread(target=run, args=("first",))
            first.start()
            self.assertTrue(started.wait(timeout=30))
            second = threading.Thread(target=run, args=("second",))
            second.start()
            second.join(timeout=30)
            release.set()
            first.join(timeout=30)

        self.assertIsInstance(outcomes["second"], HTTPException)
        self.assertEqual(outcomes["second"].status_code, 409)
        self.assertIn("正在 AI 填写中", str(outcomes["second"].detail))
        self.assertEqual(outcomes["first"]["artifact"]["id"], "ART-G1-T1")

        # 完成后锁已释放，可立即重试
        with mock.patch.object(
            service_module, "run_technical_ai_fill_for_gap", return_value=_fill_payload()
        ):
            retry = self.service.ai_fill("PRJ-MUTEX", "G1", object(), {"fillTaskId": "T1"})
        self.assertEqual(retry["artifact"]["id"], "ART-G1-T1")

    def test_failed_fill_releases_slot_for_retry(self) -> None:
        with mock.patch.object(
            service_module,
            "run_technical_ai_fill_for_gap",
            side_effect=RuntimeError("填写失败"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                self.service.ai_fill("PRJ-MUTEX", "G1", object(), {"fillTaskId": "T1"})
        self.assertEqual(ctx.exception.status_code, 400)

        # 失败后锁已释放，重试可成功
        with mock.patch.object(
            service_module, "run_technical_ai_fill_for_gap", return_value=_fill_payload()
        ):
            retry = self.service.ai_fill("PRJ-MUTEX", "G1", object(), {"fillTaskId": "T1"})
        self.assertEqual(retry["artifact"]["id"], "ART-G1-T1")


if __name__ == "__main__":
    unittest.main()
