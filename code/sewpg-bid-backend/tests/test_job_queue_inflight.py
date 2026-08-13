from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services import job_queue


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_mark_and_clear_job_inflight() -> None:
    client = MagicMock()
    raw_payload = '{"id":"job-1"}'
    job = {
        "id": "job-1",
        "type": "fill_generation",
        "projectId": "project-1",
        "parentJobId": "parent-1",
        "createdAt": "2026-07-22T00:00:00Z",
        "__queueKey": job_queue.QUEUE_KEY,
        "__processingPayload": raw_payload,
    }

    with patch.object(job_queue, "get_redis_client", return_value=client):
        job_queue.mark_job_inflight(job)
        job_queue.clear_job_inflight(job)

    field, raw = client.hset.call_args.args[1], client.hset.call_args.args[2]
    assert field == "job-1"
    entry = json.loads(raw)
    assert entry["type"] == "fill_generation"
    assert entry["projectId"] == "project-1"
    assert entry["parentJobId"] == "parent-1"
    assert entry["createdAt"] == "2026-07-22T00:00:00Z"
    assert entry["startedAt"]
    assert entry["queueKey"] == job_queue.QUEUE_KEY
    assert entry["processingPayload"] == raw_payload
    pipe = client.pipeline.return_value
    pipe.hdel.assert_called_once_with(job_queue.INFLIGHT_KEY, "job-1")
    pipe.lrem.assert_called_once_with(job_queue.processing_queue_key(job_queue.QUEUE_KEY), 1, raw_payload)
    pipe.execute.assert_called_once_with()


def test_recover_processing_job_moves_payload_back_atomically() -> None:
    client = MagicMock()
    raw_payload = json.dumps({"id": "run-1:continue", "type": "s1_parse_continue"})
    client.eval.side_effect = [["requeued", raw_payload], None]

    with patch.object(job_queue, "get_redis_client", return_value=client):
        recovered = job_queue.recover_processing_jobs(job_queue.QUEUE_KEY)

    assert recovered == 1
    first_call = client.eval.call_args_list[0]
    assert first_call.args[:6] == (
        job_queue._RECOVER_PROCESSING_JOB_SCRIPT,
        3,
        job_queue.processing_queue_key(job_queue.QUEUE_KEY),
        job_queue.QUEUE_KEY,
        job_queue.INFLIGHT_KEY,
        job_queue.JOB_KEY_PREFIX,
    )
    # 重试上限必须真的传给脚本，否则死循环没有出口
    assert first_call.args[8] == max(1, settings.redis_job_max_recover_attempts)


def test_recover_processing_job_abandoned_is_not_counted_as_recovered() -> None:
    """反复崩溃的任务由脚本判死后，恢复计数不能把它算成"又放回队列了"。"""
    client = MagicMock()
    client.eval.side_effect = [["abandoned", "job-poison"], None]

    with patch.object(job_queue, "get_redis_client", return_value=client):
        recovered = job_queue.recover_processing_jobs(job_queue.QUEUE_KEY)

    assert recovered == 0
    assert client.eval.call_count == 2


def test_recover_inflight_job_marked_failed_after_attempt_cap() -> None:
    client = MagicMock()
    client.hgetall.return_value = {
        "run-1:continue": json.dumps(
            {"id": "run-1:continue", "type": "s1_parse_continue", "projectId": "project-1"},
            ensure_ascii=False,
        )
    }
    client.hincrby.return_value = settings.redis_job_max_recover_attempts + 1
    pipe = client.pipeline.return_value

    with patch.object(job_queue, "get_redis_client", return_value=client):
        recovered = job_queue.recover_inflight_jobs("s1_parse_continue", job_queue.QUEUE_KEY)

    assert recovered == 0
    pipe.rpush.assert_not_called()
    mapping = pipe.hset.call_args.kwargs["mapping"]
    assert mapping["status"] == "failed"
    assert "不再自动重试" in mapping["message"]


def test_recover_inflight_docling_job_requeues_original_payload() -> None:
    client = MagicMock()
    client.hgetall.return_value = {
        "run-1:docling": json.dumps(
            {
                "id": "run-1:docling",
                "type": "s1_docling_batch",
                "projectId": "project-1",
                "parentJobId": "run-1",
                "createdAt": "2026-07-22T00:00:00Z",
                "startedAt": "2026-07-22T00:01:00Z",
                "data": {"runId": "run-1", "documents": [{"id": "TEN-1"}]},
            },
            ensure_ascii=False,
        )
    }
    client.hincrby.return_value = 1
    pipe = client.pipeline.return_value

    with patch.object(job_queue, "get_redis_client", return_value=client):
        recovered = job_queue.recover_inflight_jobs("s1_docling_batch", job_queue.DOCLING_QUEUE_KEY)

    assert recovered == 1
    queue_key, raw_payload = pipe.rpush.call_args.args
    assert queue_key == job_queue.DOCLING_QUEUE_KEY
    payload = json.loads(raw_payload)
    assert payload == {
        "id": "run-1:docling",
        "type": "s1_docling_batch",
        "projectId": "project-1",
        "parentJobId": "run-1",
        "data": {"runId": "run-1", "documents": [{"id": "TEN-1"}]},
        "createdAt": "2026-07-22T00:00:00Z",
    }
    pipe.hdel.assert_called_once_with(job_queue.INFLIGHT_KEY, "run-1:docling")
    pipe.execute.assert_called_once_with()


def test_reclaim_marks_stale_inflight_job_failed_and_releases_lock() -> None:
    stale_started = _iso(datetime.now(UTC) - timedelta(hours=3))
    fresh_started = _iso(datetime.now(UTC))
    client = MagicMock()
    client.hgetall.return_value = {
        "job-stale": json.dumps(
            {"id": "job-stale", "type": "fill_generation", "projectId": "project-1", "startedAt": stale_started}
        ),
        "job-fresh": json.dumps(
            {"id": "job-fresh", "type": "directory_generation", "projectId": "project-2", "startedAt": fresh_started}
        ),
    }

    with patch.object(job_queue, "get_redis_client", return_value=client):
        reclaimed = job_queue.reclaim_stale_inflight_jobs(job_queue.settings.redis_job_lock_ttl_sec)

    assert reclaimed == 1
    # 仅超时的 job-stale 被回收：置失败、删 in-flight、释放其锁；job-fresh 不受影响
    pipe = client.pipeline.return_value
    pipe.hdel.assert_called_once_with(job_queue.INFLIGHT_KEY, "job-stale")
    # mark_job_status 通过 pipeline 对 job-stale 的 job hash 写入 failed 状态
    status_targets = [call.args[0] for call in pipe.hset.call_args_list]
    assert job_queue._job_key("job-stale") in status_targets
    # 释放锁必须带 owner 校验：只删仍归 job-stale 所有的锁，不碰同项目新任务的锁
    client.eval.assert_called_once_with(
        job_queue._DELETE_IF_OWNER_SCRIPT,
        1,
        job_queue.generation_lock_key("fill_generation", "project-1"),
        "job-stale",
    )
    client.delete.assert_not_called()


def test_reclaim_no_client_returns_zero() -> None:
    with patch.object(job_queue, "get_redis_client", return_value=None):
        assert job_queue.reclaim_stale_inflight_jobs(60) == 0


def test_mark_job_status_records_last_terminal_snapshot() -> None:
    """终态任务离开 active 集合后，进度接口仍能凭该快照展示失败原因（R10-B07-05）。"""
    client = MagicMock()
    job = {"id": "clean-1", "type": "material_cleaning", "projectId": "p-1"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        job_queue.mark_job_status(job, "failed", "清洗失败：未生成 Word 文件。")

    key, raw = client.set.call_args.args[:2]
    assert key == f"{job_queue.LAST_TERMINAL_KEY_PREFIX}:material_cleaning:technical"
    assert client.set.call_args.kwargs.get("ex") == job_queue.settings.redis_job_result_ttl_sec
    snapshot = json.loads(raw)
    assert snapshot["jobId"] == "clean-1"
    assert snapshot["type"] == "material_cleaning"
    assert snapshot["bidType"] == "技术标"
    assert snapshot["status"] == "failed"
    assert snapshot["message"] == "清洗失败：未生成 Word 文件。"
    assert snapshot["finishedAt"]


def test_mark_job_status_truncates_long_terminal_message() -> None:
    client = MagicMock()
    job = {"id": "clean-2", "type": "material_cleaning"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        job_queue.mark_job_status(job, "failed", "x" * 600)

    snapshot = json.loads(client.set.call_args.args[1])
    assert len(snapshot["message"]) == job_queue.LAST_TERMINAL_MESSAGE_MAX


def test_mark_job_status_isolates_business_terminal_snapshot() -> None:
    client = MagicMock()
    job = {
        "id": "clean-business-1",
        "type": "material_cleaning",
        "data": {"bidType": "商务标"},
    }

    with patch.object(job_queue, "get_redis_client", return_value=client):
        job_queue.mark_job_status(job, "failed", "商务素材清洗失败")

    key, raw = client.set.call_args.args[:2]
    assert key == f"{job_queue.LAST_TERMINAL_KEY_PREFIX}:material_cleaning:business"
    assert json.loads(raw)["bidType"] == "商务标"


def test_mark_job_status_skips_snapshot_for_explicit_invalid_bid_type() -> None:
    for invalid_bid_type in ("", None, 0, "unknown", "非技术标", "技术资料", "商务资料"):
        client = MagicMock()
        job = {
            "id": f"clean-invalid-{invalid_bid_type}",
            "type": "material_cleaning",
            "data": {"bidType": invalid_bid_type},
        }

        with patch.object(job_queue, "get_redis_client", return_value=client):
            job_queue.mark_job_status(job, "failed", "bad type")

        client.set.assert_not_called()


def test_mark_job_status_skips_terminal_snapshot_for_intermediate_status() -> None:
    client = MagicMock()
    job = {"id": "clean-3", "type": "material_cleaning"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        job_queue.mark_job_status(job, "running")

    client.set.assert_not_called()


def test_latest_terminal_job_of_type_reads_snapshot() -> None:
    client = MagicMock()
    client.get.return_value = json.dumps(
        {"jobId": "dp-1", "bidType": "商务标", "status": "cancelled"}
    )

    with patch.object(job_queue, "get_redis_client", return_value=client):
        snapshot = job_queue.latest_terminal_job_of_type("material_deep_parse", "商务标")

    assert snapshot == {"jobId": "dp-1", "bidType": "商务标", "status": "cancelled"}
    client.get.assert_called_once_with(
        f"{job_queue.LAST_TERMINAL_KEY_PREFIX}:material_deep_parse:business"
    )


def test_latest_terminal_job_of_type_accepts_legacy_unscoped_snapshot_only_for_technical() -> None:
    legacy = json.dumps({"jobId": "legacy-1", "status": "failed", "message": "legacy"})
    client = MagicMock()
    client.get.side_effect = [None, legacy]

    with patch.object(job_queue, "get_redis_client", return_value=client):
        snapshot = job_queue.latest_terminal_job_of_type("material_cleaning", "技术标")

    assert snapshot == {"jobId": "legacy-1", "status": "failed", "message": "legacy"}
    assert [call.args[0] for call in client.get.call_args_list] == [
        f"{job_queue.LAST_TERMINAL_KEY_PREFIX}:material_cleaning:technical",
        f"{job_queue.LAST_TERMINAL_KEY_PREFIX}:material_cleaning",
    ]


def test_latest_terminal_job_of_type_rejects_cross_bid_and_invalid_legacy_snapshots() -> None:
    client = MagicMock()
    client.get.side_effect = [
        None,
        json.dumps({"jobId": "business-1", "bidType": "商务标", "status": "failed"}),
    ]
    with patch.object(job_queue, "get_redis_client", return_value=client):
        assert job_queue.latest_terminal_job_of_type("material_cleaning", "技术标") is None

    for invalid_bid_type in ("", None, 0, "unknown", "非技术标", "技术资料", "商务资料"):
        client = MagicMock()
        client.get.side_effect = [
            None,
            json.dumps(
                {"jobId": "invalid-1", "bidType": invalid_bid_type, "status": "failed"}
            ),
        ]
        with patch.object(job_queue, "get_redis_client", return_value=client):
            assert job_queue.latest_terminal_job_of_type("material_cleaning", "技术标") is None


def test_latest_terminal_job_of_type_returns_none_when_missing_or_broken() -> None:
    client = MagicMock()
    client.get.return_value = None
    with patch.object(job_queue, "get_redis_client", return_value=client):
        assert job_queue.latest_terminal_job_of_type("material_cleaning") is None

    client.get.return_value = "{not-json"
    with patch.object(job_queue, "get_redis_client", return_value=client):
        assert job_queue.latest_terminal_job_of_type("material_cleaning") is None

    with patch.object(job_queue, "get_redis_client", return_value=None):
        assert job_queue.latest_terminal_job_of_type("material_cleaning") is None


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("BID_RUN_INTEGRATION") != "1", reason="requires Redis")
def test_repeatedly_crashing_job_is_abandoned_by_recovery_script() -> None:
    """真 Redis 下验证恢复脚本的重试上限——这是"崩溃→重启→原样重跑"死循环的唯一出口。"""
    client = job_queue.get_redis_client()
    assert client is not None

    queue_key = "bid:jobs:test-recover"
    processing_key = job_queue.processing_queue_key(queue_key)
    job_id = "poison-job-1"
    job_key = job_queue.JOB_KEY_PREFIX + job_id
    payload = json.dumps({"id": job_id, "type": "fill_generation", "projectId": "PRJ-TEST"})
    max_attempts = max(1, settings.redis_job_max_recover_attempts)

    client.delete(queue_key, processing_key, job_key)
    try:
        # 前 max_attempts 轮：每轮模拟一次 worker 崩溃，任务应当被放回队列继续重试。
        for expected_attempt in range(1, max_attempts + 1):
            client.lpush(processing_key, payload)
            assert job_queue.recover_processing_jobs(queue_key) == 1
            assert client.lrange(queue_key, 0, -1) == [payload]
            assert client.hget(job_key, "status") == "queued"
            assert int(client.hget(job_key, "recoverAttempts")) == expected_attempt
            client.delete(queue_key)

        # 再崩一次就越过上限：不再放回队列，任务如实标失败。
        client.lpush(processing_key, payload)
        assert job_queue.recover_processing_jobs(queue_key) == 0
        assert client.lrange(queue_key, 0, -1) == []
        assert client.lrange(processing_key, 0, -1) == []
        assert client.hget(job_key, "status") == "failed"
        assert "不再自动重试" in client.hget(job_key, "message")
    finally:
        client.delete(queue_key, processing_key, job_key)
