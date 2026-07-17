from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from app.services import job_queue, local_job_executor


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


def test_renew_returns_false_when_lock_owned_by_other_job() -> None:
    client = MagicMock()
    client.eval.return_value = 0
    job = {"id": "job-1", "type": "fill_generation", "projectId": "project-1"}

    with patch.object(job_queue, "get_redis_client", return_value=client):
        assert job_queue.renew_generation_lock(job) is False


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
