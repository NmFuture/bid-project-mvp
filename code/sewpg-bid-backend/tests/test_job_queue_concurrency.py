from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch

from app.services import job_queue, local_job_executor
from app.workers import docling_worker


class _InternalJobRedis:
    def __init__(self) -> None:
        self.job_keys: set[str] = set()
        self.queues: dict[str, list[str]] = {}
        self.parent_statuses: dict[str, str] = {}

    def eval(self, script: str, numkeys: int, *args):
        assert script == job_queue._ENQUEUE_INTERNAL_JOB_SCRIPT
        assert numkeys == 3
        job_key, queue_key, parent_key = str(args[0]), str(args[1]), str(args[2])
        if job_key in self.job_keys:
            return 0
        self.job_keys.add(job_key)
        self.queues.setdefault(queue_key, []).append(str(args[9]))
        if args[10]:
            self.parent_statuses[parent_key] = str(args[10])
        return 1


def test_queued_job_lock_uses_finite_queue_ttl() -> None:
    client = MagicMock()
    client.set.return_value = True
    pipeline = client.pipeline.return_value
    pipeline.execute.return_value = []

    with patch.object(job_queue, "get_redis_client", return_value=client):
        result = job_queue.enqueue_generation_job("fill_generation", "project-1", {})

    assert result.queued is True
    _, job_id = client.set.call_args.args
    assert job_id == result.job_id
    # 排队锁必须带有限 TTL 兜底，防止 payload 丢失后锁永久残留
    assert client.set.call_args.kwargs == {
        "nx": True,
        "ex": job_queue.settings.redis_job_queue_lock_ttl_sec,
    }


def test_enqueue_failure_releases_lock_with_owner_check() -> None:
    client = MagicMock()
    client.set.return_value = True
    client.pipeline.return_value.execute.side_effect = job_queue.RedisError("boom")

    with patch.object(job_queue, "get_redis_client", return_value=client):
        result = job_queue.enqueue_generation_job("fill_generation", "project-1", {})

    assert result.unavailable is True
    script, numkeys, lock_key, owner = client.eval.call_args.args
    assert script == job_queue._DELETE_IF_OWNER_SCRIPT
    assert numkeys == 1
    assert lock_key == job_queue.generation_lock_key("fill_generation", "project-1")
    assert owner


def test_running_job_lock_is_renewed_atomically_with_owner_check() -> None:
    client = MagicMock()
    client.eval.return_value = 1
    job = {"id": "job-1", "type": "fill_generation", "projectId": "project-1"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        renewed = job_queue.renew_generation_lock(job)

    assert renewed is True
    client.eval.assert_called_once_with(
        job_queue._RENEW_IF_OWNER_SCRIPT,
        1,
        job_queue.generation_lock_key("fill_generation", "project-1"),
        "job-1",
        job_queue.settings.redis_job_lock_ttl_sec,
    )


def test_running_job_lock_accepts_explicit_ttl() -> None:
    client = MagicMock()
    client.eval.return_value = 1
    job = {"id": "job-1", "type": "s1_parse", "projectId": "project-1"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        renewed = job_queue.renew_generation_lock(job, ttl_sec=4321)

    assert renewed is True
    client.eval.assert_called_once_with(
        job_queue._RENEW_IF_OWNER_SCRIPT,
        1,
        job_queue.generation_lock_key("s1_parse", "project-1"),
        "job-1",
        4321,
    )


def test_internal_docling_job_is_idempotent_and_uses_dedicated_queue() -> None:
    client = _InternalJobRedis()

    with patch.object(job_queue, "get_redis_client", return_value=client):
        first = job_queue.enqueue_internal_job(
            "s1_docling_batch",
            "project-1",
            {"runId": "run-1"},
            job_id="run-1:docling",
            parent_job_id="run-1",
        )
        duplicate = job_queue.enqueue_internal_job(
            "s1_docling_batch",
            "project-1",
            {"runId": "run-1"},
            job_id="run-1:docling",
            parent_job_id="run-1",
        )

    assert first.queued is True
    assert duplicate.queued is False
    assert first.accepted is True
    assert duplicate.accepted is True
    assert first.job_id == duplicate.job_id == "run-1:docling"
    queued = client.queues[job_queue.DOCLING_QUEUE_KEY]
    assert len(queued) == 1
    payload = json.loads(queued[0])
    assert payload["parentJobId"] == "run-1"
    assert payload["data"] == {"runId": "run-1"}


def test_internal_continuation_sets_parent_waiting_in_same_enqueue_script() -> None:
    client = _InternalJobRedis()

    with patch.object(job_queue, "get_redis_client", return_value=client):
        result = job_queue.enqueue_internal_job(
            "s1_parse_continue",
            "project-1",
            {"__runId": "run-1"},
            job_id="run-1:continue",
            parent_job_id="run-1",
            parent_status="waiting_continuation",
        )

    assert result.queued is True
    assert client.parent_statuses[job_queue._job_key("run-1")] == "waiting_continuation"
    assert len(client.queues[job_queue.QUEUE_KEY]) == 1


def test_s1_workflow_lock_is_global_and_owner_checked() -> None:
    client = MagicMock()
    client.eval.return_value = 1
    parent = {"id": "run-1", "type": "s1_parse", "projectId": "project-1"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        claimed = job_queue.claim_s1_workflow_lock(parent, ttl_sec=4321)
        job_queue.release_s1_workflow_lock(parent)

    assert claimed is True
    assert client.eval.call_args_list[0].args == (
        job_queue._ACQUIRE_OR_RENEW_IF_OWNER_SCRIPT,
        1,
        job_queue.S1_WORKFLOW_LOCK_KEY,
        "run-1",
        4321,
    )
    assert client.eval.call_args_list[1].args == (
        job_queue._DELETE_IF_OWNER_SCRIPT,
        1,
        job_queue.S1_WORKFLOW_LOCK_KEY,
        "run-1",
    )


def test_busy_s1_job_is_atomically_requeued_to_the_tail() -> None:
    client = MagicMock()
    client.eval.return_value = 1
    raw_payload = json.dumps({"id": "run-2", "type": "s1_parse", "projectId": "project-2", "data": {}})
    job = {
        "id": "run-2",
        "type": "s1_parse",
        "projectId": "project-2",
        "data": {},
        "__queueKey": job_queue.QUEUE_KEY,
        "__processingPayload": raw_payload,
    }

    with patch.object(job_queue, "get_redis_client", return_value=client):
        requeued = job_queue.requeue_processing_job(job, "waiting")

    assert requeued is True
    call = client.eval.call_args
    assert call.args[:6] == (
        job_queue._REQUEUE_PROCESSING_JOB_SCRIPT,
        4,
        job_queue.QUEUE_KEY,
        job_queue.processing_queue_key(job_queue.QUEUE_KEY),
        job_queue.INFLIGHT_KEY,
        job_queue._job_key("run-2"),
    )
    queued_payload = json.loads(call.args[8])
    assert "__queueKey" not in queued_payload
    assert "__processingPayload" not in queued_payload


def test_dequeue_can_use_docling_queue() -> None:
    client = MagicMock()
    payload = {"id": "run-1:docling", "type": "s1_docling_batch", "projectId": "project-1"}
    raw_payload = json.dumps(payload)
    client.blmove.return_value = raw_payload

    with patch.object(job_queue, "get_redis_client", return_value=client):
        result = job_queue.dequeue_generation_job(timeout_sec=1, queue_key=job_queue.DOCLING_QUEUE_KEY)

    assert result == {
        **payload,
        "__queueKey": job_queue.DOCLING_QUEUE_KEY,
        "__processingPayload": raw_payload,
    }
    client.blmove.assert_called_once_with(
        job_queue.DOCLING_QUEUE_KEY,
        job_queue.processing_queue_key(job_queue.DOCLING_QUEUE_KEY),
        1,
        src="LEFT",
        dest="RIGHT",
    )


def test_find_active_jobs_scans_default_and_docling_queues() -> None:
    client = MagicMock()
    client.hgetall.return_value = {}
    docling_payload = json.dumps(
        {"id": "run-1:docling", "type": "s1_docling_batch", "projectId": "project-1", "data": {}}
    )
    client.lrange.side_effect = lambda key, _start, _end: [docling_payload] if key == job_queue.DOCLING_QUEUE_KEY else []

    with patch.object(job_queue, "get_redis_client", return_value=client):
        active = job_queue.find_active_jobs_of_type("s1_docling_batch")

    assert active == [{"id": "run-1:docling", "projectId": "project-1", "data": {}}]
    assert [call.args[0] for call in client.lrange.call_args_list] == [
        job_queue.QUEUE_KEY,
        job_queue.processing_queue_key(job_queue.QUEUE_KEY),
        job_queue.DOCLING_QUEUE_KEY,
        job_queue.processing_queue_key(job_queue.DOCLING_QUEUE_KEY),
    ]


def test_renew_returns_false_when_lock_owned_by_other_job() -> None:
    client = MagicMock()
    client.eval.return_value = 0
    job = {"id": "job-1", "type": "fill_generation", "projectId": "project-1"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        assert job_queue.renew_generation_lock(job) is False


def test_renew_returns_none_when_redis_is_unavailable() -> None:
    job = {"id": "job-1", "type": "fill_generation", "projectId": "project-1"}

    with patch.object(job_queue, "get_redis_client", return_value=None):
        assert job_queue.renew_generation_lock(job) is None


def test_release_lock_deletes_only_when_owner_matches() -> None:
    client = MagicMock()
    job = {"id": "job-1", "type": "fill_generation", "projectId": "project-1"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        job_queue.release_generation_lock(job)

    client.eval.assert_called_once_with(
        job_queue._DELETE_IF_OWNER_SCRIPT,
        1,
        job_queue.generation_lock_key("fill_generation", "project-1"),
        "job-1",
    )
    client.delete.assert_not_called()


def test_cancelled_docling_job_releases_parent_workflow_locks() -> None:
    parent = {"id": "run-1", "type": "s1_parse", "projectId": "project-1"}
    job = {
        "id": "run-1:docling",
        "type": "s1_docling_batch",
        "projectId": "project-1",
        "parentJobId": "run-1",
        "data": {},
    }

    with patch.object(docling_worker, "mark_job_status"), patch.object(
        docling_worker,
        "mark_job_inflight",
    ), patch.object(
        docling_worker,
        "renew_generation_lock",
        return_value=True,
    ), patch.object(
        docling_worker,
        "claim_s1_workflow_lock",
        return_value=True,
    ), patch.object(
        docling_worker,
        "execute_docling_batch",
        return_value={"status": "cancelled", "runId": "run-1"},
    ), patch.object(
        docling_worker,
        "clear_job_inflight",
    ), patch.object(
        docling_worker,
        "release_generation_lock",
    ) as release_project_mock, patch.object(
        docling_worker,
        "release_s1_workflow_lock",
    ) as release_workflow_mock:
        docling_worker._run_job(job)

    release_project_mock.assert_called_once_with(parent)
    release_workflow_mock.assert_called_once_with(parent)


def test_local_job_executor_runs_jobs_serially() -> None:
    first_started = threading.Event()
    first_may_finish = threading.Event()
    order: list[str] = []

    def first_job() -> None:
        order.append("first-start")
        first_started.set()
        assert first_may_finish.wait(timeout=5)
        order.append("first-end")

    def second_job() -> None:
        order.append("second")

    local_job_executor.submit_local_job(first_job)
    local_job_executor.submit_local_job(second_job)

    assert first_started.wait(timeout=5)
    # 第一个任务未结束时，第二个任务不得开始执行
    assert "second" not in order
    first_may_finish.set()
    local_job_executor._JOBS.join()
    assert order == ["first-start", "first-end", "second"]


def test_local_job_executor_survives_job_failure() -> None:
    done = threading.Event()

    def failing_job() -> None:
        raise RuntimeError("boom")

    local_job_executor.submit_local_job(failing_job)
    local_job_executor.submit_local_job(done.set)

    assert done.wait(timeout=5)
