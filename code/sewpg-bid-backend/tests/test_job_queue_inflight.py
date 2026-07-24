from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

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
    client.eval.side_effect = [raw_payload, None]

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
