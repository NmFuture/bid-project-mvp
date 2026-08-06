"""素材流水线自动衔接（上传→清洗→Wiki 增量，产品裁决 2026-08-04）单测。"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services import material_wiki_auto
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
from app.workers import redis_worker


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
        _ = ex
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def incrby(self, key: str, amount: int) -> int:
        value = int(self.store.get(key) or 0) + int(amount)
        self.store[key] = str(value)
        return value

    def expire(self, key: str, seconds: int) -> bool:
        _ = seconds
        return key in self.store

    def eval(self, script: str, key_count: int, key: str, value: str) -> int:
        _ = script, key_count
        if self.store.get(key) != value:
            return 0
        self.store.pop(key, None)
        return 1


class MaterialWikiAutoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_redis = _FakeRedis()
        self.redis_patcher = patch(
            "app.services.material_wiki_auto.get_redis_client",
            return_value=self.fake_redis,
        )
        self.redis_patcher.start()
        self.flag_patcher = patch.object(settings, "material_wiki_auto_refresh", True)
        self.flag_patcher.start()

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        self.redis_patcher.stop()

    def test_cleaning_finished_triggers_refresh_when_queue_empty(self) -> None:
        with (
            patch(
                "app.services.job_queue.find_active_jobs_of_type",
                return_value=[{"id": "JOB-SELF"}],
            ),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                return_value={"jobId": "WIKI-1", "status": "queued", "reused": False},
            ) as enqueue,
        ):
            material_wiki_auto.on_material_cleaning_job_finished(current_job_id="JOB-SELF")
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs.get("mode"), "refresh")

    def test_cleaning_finished_skips_when_other_jobs_active(self) -> None:
        with (
            patch(
                "app.services.job_queue.find_active_jobs_of_type",
                return_value=[{"id": "JOB-SELF"}, {"id": "JOB-OTHER"}],
            ),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
            ) as enqueue,
        ):
            material_wiki_auto.on_material_cleaning_job_finished(current_job_id="JOB-SELF")
        enqueue.assert_not_called()

    def test_reused_wiki_job_marks_pending_for_rerun(self) -> None:
        with patch(
            "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
            return_value={"jobId": "WIKI-RUNNING", "status": "queued", "reused": True},
        ):
            material_wiki_auto.request_technical_wiki_auto_refresh("测试")
        self.assertIn(material_wiki_auto._AUTO_REFRESH_PENDING_KEY, self.fake_redis.store)

    def test_wiki_finished_acknowledges_pending_and_reruns(self) -> None:
        self.fake_redis.store[material_wiki_auto._AUTO_REFRESH_PENDING_KEY] = "pending-1"
        with (
            patch("app.services.job_queue.find_active_jobs_of_type", return_value=[]),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                return_value={"jobId": "WIKI-2", "status": "queued", "reused": False},
            ) as enqueue,
        ):
            material_wiki_auto.on_material_wiki_job_finished(TECHNICAL_BID_TYPE)
        enqueue.assert_called_once()
        self.assertNotIn(material_wiki_auto._AUTO_REFRESH_PENDING_KEY, self.fake_redis.store)

    def test_wiki_finished_without_pending_is_noop(self) -> None:
        with patch(
            "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
        ) as enqueue:
            material_wiki_auto.on_material_wiki_job_finished(TECHNICAL_BID_TYPE)
        enqueue.assert_not_called()

    def test_wiki_finished_keeps_pending_when_enqueue_fails(self) -> None:
        from app.services.peripheral import PeripheralError

        pending_key = material_wiki_auto._AUTO_REFRESH_PENDING_KEY
        self.fake_redis.store[pending_key] = "pending-1"
        with (
            patch("app.services.job_queue.find_active_jobs_of_type", return_value=[]),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                side_effect=PeripheralError(503, "队列不可用", "MATERIAL_QUEUE_UNAVAILABLE"),
            ),
        ):
            material_wiki_auto.on_material_wiki_job_finished(TECHNICAL_BID_TYPE)
        self.assertEqual(self.fake_redis.store.get(pending_key), "pending-1")

    def test_wiki_finished_does_not_ack_newer_pending_token(self) -> None:
        pending_key = material_wiki_auto._AUTO_REFRESH_PENDING_KEY
        self.fake_redis.store[pending_key] = "pending-old"

        def enqueue_with_concurrent_change(*_args, **_kwargs):
            self.fake_redis.store[pending_key] = "pending-new"
            return {"jobId": "WIKI-2", "status": "queued", "reused": False}

        with (
            patch("app.services.job_queue.find_active_jobs_of_type", return_value=[]),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                side_effect=enqueue_with_concurrent_change,
            ),
        ):
            material_wiki_auto.on_material_wiki_job_finished(TECHNICAL_BID_TYPE)
        self.assertEqual(self.fake_redis.store.get(pending_key), "pending-new")

    def test_business_wiki_finished_does_not_consume_technical_pending(self) -> None:
        pending_key = material_wiki_auto._AUTO_REFRESH_PENDING_KEY
        self.fake_redis.store[pending_key] = "pending-technical"
        with patch("app.services.material_wiki_jobs.enqueue_material_wiki_generation") as enqueue:
            material_wiki_auto.on_material_wiki_job_finished(BUSINESS_BID_TYPE)
        enqueue.assert_not_called()
        self.assertEqual(self.fake_redis.store.get(pending_key), "pending-technical")

    def test_wiki_finished_waits_for_cleaning_without_consuming_pending(self) -> None:
        pending_key = material_wiki_auto._AUTO_REFRESH_PENDING_KEY
        self.fake_redis.store[pending_key] = "pending-1"
        with (
            patch(
                "app.services.job_queue.find_active_jobs_of_type",
                return_value=[{"id": "CLEANING-1"}],
            ),
            patch("app.services.material_wiki_jobs.enqueue_material_wiki_generation") as enqueue,
        ):
            material_wiki_auto.on_material_wiki_job_finished(TECHNICAL_BID_TYPE)
        enqueue.assert_not_called()
        self.assertEqual(self.fake_redis.store.get(pending_key), "pending-1")

    def test_idle_retry_claim_throttles_repeated_queue_failures(self) -> None:
        from app.services.peripheral import PeripheralError

        pending_key = material_wiki_auto._AUTO_REFRESH_PENDING_KEY
        self.fake_redis.store[pending_key] = "pending-1"
        with (
            patch("app.services.job_queue.find_active_jobs_of_type", return_value=[]),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                side_effect=PeripheralError(503, "队列不可用", "MATERIAL_QUEUE_UNAVAILABLE"),
            ) as enqueue,
        ):
            material_wiki_auto.retry_pending_technical_wiki_auto_refresh(claim_retry=True)
            material_wiki_auto.retry_pending_technical_wiki_auto_refresh(claim_retry=True)
        enqueue.assert_called_once()
        self.assertEqual(self.fake_redis.store.get(pending_key), "pending-1")

    def test_worker_releases_wiki_lock_before_followup_hook(self) -> None:
        events: list[str] = []
        queued_job_ids: list[str] = []
        pending_key = material_wiki_auto._AUTO_REFRESH_PENDING_KEY
        self.fake_redis.store[pending_key] = "pending-1"
        job = {
            "id": "WIKI-1",
            "type": "material_wiki_generation",
            "projectId": "wiki:technical",
            "data": {"bidType": TECHNICAL_BID_TYPE, "mode": "refresh"},
        }

        def enqueue_followup(*_args, **_kwargs):
            events.append("enqueue")
            queued_job_ids.append("WIKI-2")
            return {"jobId": "WIKI-2", "status": "queued", "reused": False}

        with (
            patch("app.workers.redis_worker.mark_job_status"),
            patch("app.workers.redis_worker.mark_job_inflight"),
            patch("app.workers.redis_worker.clear_job_inflight"),
            patch("app.workers.redis_worker.renew_generation_lock", return_value=True),
            patch(
                "app.workers.redis_worker.release_generation_lock",
                side_effect=lambda _job: events.append("release"),
            ),
            patch("app.services.job_queue.find_active_jobs_of_type", return_value=[]),
            patch(
                "app.services.material_wiki_jobs.execute_material_wiki_generation",
                return_value={"status": "success", "summary": "done"},
            ),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                side_effect=enqueue_followup,
            ) as enqueue,
        ):
            completed = redis_worker._run_job(job)
        self.assertTrue(completed)
        self.assertEqual(events, ["release", "enqueue"])
        self.assertEqual(enqueue.call_args.args[0], TECHNICAL_BID_TYPE)
        self.assertEqual(queued_job_ids, ["WIKI-2"])
        self.assertNotEqual(queued_job_ids[0], job["id"])
        self.assertNotIn(pending_key, self.fake_redis.store)

    def test_upload_hook_only_fires_for_non_cleaning_batches(self) -> None:
        with (
            patch("app.services.job_queue.find_active_jobs_of_type", return_value=[]),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                return_value={"jobId": "WIKI-3", "status": "queued", "reused": False},
            ) as enqueue,
        ):
            material_wiki_auto.on_material_upload_completed(clean_job_count=3)
            enqueue.assert_not_called()
            material_wiki_auto.on_material_upload_completed(clean_job_count=0)
            enqueue.assert_called_once()

    @staticmethod
    def _queues(deep_parse: list[dict[str, str]], cleaning: list[dict[str, str]]):
        """按任务类型分别应答队列查询：深度解析钩子会同时查两个队列。"""

        def _side_effect(job_type: str) -> list[dict[str, str]]:
            return deep_parse if job_type == material_wiki_auto.MATERIAL_DEEP_PARSE_JOB_TYPE else cleaning

        return _side_effect

    def test_deep_parse_finished_triggers_refresh_when_queues_empty(self) -> None:
        with (
            patch(
                "app.services.job_queue.find_active_jobs_of_type",
                side_effect=self._queues([{"id": "JOB-SELF"}], []),
            ),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                return_value={"jobId": "WIKI-4", "status": "queued", "reused": False},
            ) as enqueue,
        ):
            material_wiki_auto.on_material_deep_parse_job_finished(
                "RAW-2297", current_job_id="JOB-SELF"
            )
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs.get("mode"), "refresh")

    def test_deep_parse_finished_skips_when_batch_still_running(self) -> None:
        with (
            patch(
                "app.services.job_queue.find_active_jobs_of_type",
                return_value=[{"id": "JOB-SELF"}, {"id": "JOB-OTHER"}],
            ),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
            ) as enqueue,
        ):
            material_wiki_auto.on_material_deep_parse_job_finished(
                "RAW-2297", current_job_id="JOB-SELF"
            )
        enqueue.assert_not_called()

    def test_deep_parse_refresh_claimed_once_per_file(self) -> None:
        with (
            patch(
                "app.services.job_queue.find_active_jobs_of_type",
                side_effect=self._queues([{"id": "JOB-SELF"}], []),
            ),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                return_value={"jobId": "WIKI-5", "status": "queued", "reused": False},
            ) as enqueue,
        ):
            material_wiki_auto.on_material_deep_parse_job_finished(
                "RAW-2297", current_job_id="JOB-SELF"
            )
            material_wiki_auto.on_material_deep_parse_job_finished(
                "RAW-2297", current_job_id="JOB-SELF"
            )
        # 循环刹车：同一素材只补跑一次，避免 refresh↔深度解析 无限转圈。
        enqueue.assert_called_once()

    def test_cleaning_batch_total_accumulates_and_resets(self) -> None:
        with patch("app.services.material_wiki_jobs.enqueue_material_wiki_generation"):
            material_wiki_auto.on_material_upload_completed(clean_job_count=3)
            material_wiki_auto.on_material_upload_completed(clean_job_count=2)
        # 跨批次累加：前一批没跑完又传一批，进度条显示合并后的一条。
        self.assertEqual(material_wiki_auto._cleaning_batch_total(), 5)

        with (
            patch("app.services.job_queue.find_active_jobs_of_type", return_value=[{"id": "JOB-SELF"}]),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
                return_value={"jobId": "WIKI-7", "status": "queued", "reused": False},
            ),
        ):
            material_wiki_auto.on_material_cleaning_job_finished(current_job_id="JOB-SELF")
        # 队列排空即归零，进度条不再显示清洗段计数。
        self.assertEqual(material_wiki_auto._cleaning_batch_total(), 0)

    def test_tree_change_hook_triggers_refresh(self) -> None:
        with patch(
            "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
            return_value={"jobId": "WIKI-6", "status": "queued", "reused": False},
        ) as enqueue:
            material_wiki_auto.on_material_tree_changed("删除素材目录")
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs.get("mode"), "refresh")
        self.assertNotIn(material_wiki_auto._AUTO_REFRESH_PENDING_KEY, self.fake_redis.store)

    def test_tree_change_during_running_wiki_marks_pending(self) -> None:
        from app.services.peripheral import PeripheralError

        with patch(
            "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
            side_effect=PeripheralError(409, "任务运行中", "WIKI_JOB_RUNNING"),
        ):
            material_wiki_auto.on_material_tree_changed("批量删除素材")
        # 连续删除撞上运行中的任务：落补跑标记，由 Wiki 结束钩子补一轮。
        self.assertIn(material_wiki_auto._AUTO_REFRESH_PENDING_KEY, self.fake_redis.store)

    def test_disabled_flag_disables_all_hooks(self) -> None:
        with (
            patch.object(settings, "material_wiki_auto_refresh", False),
            patch(
                "app.services.material_wiki_jobs.enqueue_material_wiki_generation",
            ) as enqueue,
        ):
            material_wiki_auto.on_material_cleaning_job_finished(current_job_id="X")
            material_wiki_auto.on_material_upload_completed(clean_job_count=0)
            material_wiki_auto.on_material_wiki_job_finished(TECHNICAL_BID_TYPE)
            material_wiki_auto.on_material_deep_parse_job_finished("RAW-1", current_job_id="X")
            material_wiki_auto.on_material_tree_changed("删除素材文件")
        enqueue.assert_not_called()


class PipelineProgressTerminalTests(unittest.TestCase):
    """进度聚合必须带出各阶段最近终态（R10-B07-05）：失败/取消的任务离开 active 后仍可展示。"""

    @staticmethod
    def _run_progress(*, cleaning_terminal=None, deep_parse_terminal=None, active_by_type=None):
        terminal_by_type = {
            material_wiki_auto.MATERIAL_CLEANING_JOB_TYPE: cleaning_terminal,
            material_wiki_auto.MATERIAL_DEEP_PARSE_JOB_TYPE: deep_parse_terminal,
        }
        active_by_type = active_by_type or {}

        with (
            patch(
                "app.services.job_queue.find_active_jobs_of_type",
                side_effect=lambda job_type: active_by_type.get(job_type, []),
            ),
            patch(
                "app.services.job_queue.latest_terminal_job_of_type",
                side_effect=lambda job_type, bid_type: terminal_by_type.get(job_type),
            ),
            patch(
                "app.services.material_wiki_jobs.latest_material_wiki_job_status",
                return_value={"status": "idle"},
            ),
            patch.object(
                material_wiki_auto,
                "_pending_preview_count",
                new=AsyncMock(return_value=0),
            ),
        ):
            return asyncio.run(material_wiki_auto.technical_pipeline_progress())

    def test_progress_includes_last_terminal_per_stage(self) -> None:
        payload = self._run_progress(
            cleaning_terminal={
                "jobId": "clean-1",
                "status": "failed",
                "message": "清洗失败：未生成 Word 文件。",
                "finishedAt": "2026-08-06T01:00:00Z",
            },
            deep_parse_terminal={
                "jobId": "dp-1",
                "status": "cancelled",
                "message": "任务锁已失效或已被新任务替代。",
                "finishedAt": "2026-08-06T01:05:00Z",
            },
        )
        self.assertEqual(payload["cleaning"]["active"], 0)
        self.assertEqual(payload["cleaning"]["lastTerminal"]["jobId"], "clean-1")
        self.assertEqual(payload["cleaning"]["lastTerminal"]["status"], "failed")
        self.assertEqual(payload["cleaning"]["lastTerminal"]["finishedAt"], "2026-08-06T01:00:00Z")
        self.assertEqual(payload["deepParse"]["lastTerminal"]["status"], "cancelled")

    def test_progress_last_terminal_defaults_to_none(self) -> None:
        payload = self._run_progress()
        self.assertIsNone(payload["cleaning"]["lastTerminal"])
        self.assertIsNone(payload["deepParse"]["lastTerminal"])

    def test_progress_filters_business_active_jobs_but_keeps_legacy_technical_jobs(self) -> None:
        payload = self._run_progress(
            active_by_type={
                material_wiki_auto.MATERIAL_CLEANING_JOB_TYPE: [
                    {"id": "legacy-tech", "data": {}},
                    {"id": "business-1", "data": {"bidType": "商务标"}},
                    {"id": "invalid-1", "data": {"bidType": "unknown"}},
                ],
            },
        )

        self.assertEqual(payload["cleaning"]["active"], 1)


if __name__ == "__main__":
    unittest.main()
