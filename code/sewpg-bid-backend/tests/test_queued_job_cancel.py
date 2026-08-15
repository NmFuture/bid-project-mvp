from __future__ import annotations

import json

import pytest

from app.services import job_queue


class _FakeRedis:
    """够用的假 Redis：只实现队列取消这条路用到的命令。"""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str, **kwargs) -> bool:  # noqa: ANN003, ARG002
        self.values[key] = value
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.values else 0

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def lrem(self, key: str, count: int, value: str) -> int:  # noqa: ARG002
        items = self.lists.get(key, [])
        if value not in items:
            return 0
        items.remove(value)
        return 1

    def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs) -> int:  # noqa: ANN003, ARG002
        self.hashes.setdefault(key, {}).update(mapping or {})
        return 1

    def hget(self, key: str, field: str):
        return self.hashes.get(key, {}).get(field)

    def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        return 1 if existed else 0

    def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002
        return True

    def pipeline(self) -> "_FakePipeline":
        return _FakePipeline(self)


class _FakePipeline:
    """mark_job_status 走 pipeline：按顺序记下来，execute 时一次性落到假 Redis 上。"""

    def __init__(self, client: "_FakeRedis") -> None:
        self._client = client
        self._ops: list = []

    def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs):  # noqa: ANN003, ARG002
        self._ops.append(lambda: self._client.hset(key, mapping=mapping))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(lambda: self._client.expire(key, ttl))
        return self

    def lrem(self, key: str, count: int, value: str):
        self._ops.append(lambda: self._client.lrem(key, count, value))
        return self

    def set(self, key: str, value: str, **kwargs):  # noqa: ANN003, ARG002
        self._ops.append(lambda: self._client.set(key, value))
        return self

    def execute(self) -> list:
        results = [op() for op in self._ops]
        self._ops = []
        return results


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(job_queue, "get_redis_client", lambda: client)
    return client


def _queue_job(client: _FakeRedis, job_id: str, job_type: str, project_id: str) -> str:
    raw = json.dumps({"id": job_id, "type": job_type, "projectId": project_id, "data": {}})
    client.lists.setdefault(job_queue.QUEUE_KEY, []).append(raw)
    return raw


def test_cancel_reports_running_only_when_the_worker_actually_started_it(fake_redis: _FakeRedis) -> None:
    fake_redis.values[job_queue.generation_lock_key("score_index_xref", "PRJ-1")] = "job-running"
    fake_redis.hashes[f"{job_queue.JOB_KEY_PREFIX}job-running"] = {"status": "running"}

    assert job_queue.cancel_generation_job("score_index_xref", "PRJ-1") == "running"
    # 正在执行的任务只能置取消标记，等它自己到安全停止点
    assert fake_redis.exists(f"{job_queue.CANCEL_KEY_PREFIX}job-running")
    assert fake_redis.values.get(job_queue.generation_lock_key("score_index_xref", "PRJ-1")), "在跑就不能放锁"


def test_holding_the_lock_does_not_mean_the_job_started(fake_redis: _FakeRedis) -> None:
    """项目锁是入队时就拿的，不是开跑时才拿。

    照锁判断「在不在跑」会把排队中的任务误判成执行中，于是只置一个取消标记就返回，
    任务继续躺在队列里——界面就一直停在「停止中」。这正是实测复现出来的那一幕。
    """
    fake_redis.values[job_queue.generation_lock_key("score_index_xref", "PRJ-1")] = "job-waiting"
    fake_redis.hashes[f"{job_queue.JOB_KEY_PREFIX}job-waiting"] = {"status": "queued"}
    _queue_job(fake_redis, "job-waiting", "score_index_xref", "PRJ-1")

    assert job_queue.cancel_generation_job("score_index_xref", "PRJ-1") == "queued"
    assert fake_redis.lists[job_queue.QUEUE_KEY] == []
    assert not fake_redis.values.get(job_queue.generation_lock_key("score_index_xref", "PRJ-1")),         "排队任务被摘掉后要放锁，否则这个项目要等锁过期才能再发起"


def test_cancel_drops_a_job_that_is_still_waiting_in_the_queue(fake_redis: _FakeRedis) -> None:
    """实测里索引重新生成卡在「停止中」，就是因为它还排着队没开跑。

    worker 正忙着别的活，队列里的任务谁也不会去动它，用户只能一直等。
    """
    _queue_job(fake_redis, "job-queued", "score_index_xref", "PRJ-1")

    assert job_queue.cancel_generation_job("score_index_xref", "PRJ-1") == "queued"
    assert fake_redis.lists[job_queue.QUEUE_KEY] == [], "任务必须从队列里摘掉"
    assert fake_redis.exists(f"{job_queue.CANCEL_KEY_PREFIX}job-queued")
    assert fake_redis.hashes[f"{job_queue.JOB_KEY_PREFIX}job-queued"]["status"] == "cancelled"


def test_cancel_only_drops_the_matching_project_and_type(fake_redis: _FakeRedis) -> None:
    _queue_job(fake_redis, "other-project", "score_index_xref", "PRJ-2")
    _queue_job(fake_redis, "other-type", "fill_generation", "PRJ-1")
    _queue_job(fake_redis, "target", "score_index_xref", "PRJ-1")

    assert job_queue.cancel_generation_job("score_index_xref", "PRJ-1") == "queued"
    remaining = [json.loads(raw)["id"] for raw in fake_redis.lists[job_queue.QUEUE_KEY]]
    assert remaining == ["other-project", "other-type"], "只能摘掉目标任务"


def test_cancel_reports_none_when_nothing_is_running_or_queued(fake_redis: _FakeRedis) -> None:
    # Redis 正常但既没锁也没排队：这个任务已经不存在了，调用方可以直接收成终态
    assert job_queue.cancel_generation_job("score_index_xref", "PRJ-1") == "none"


def test_cancel_reports_unknown_when_redis_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_queue, "get_redis_client", lambda: None)

    # 判断不了就别谎报已停止，交给调用方按「请求停止」处理
    assert job_queue.cancel_generation_job("score_index_xref", "PRJ-1") == "unknown"


def test_cancel_treats_a_job_taken_by_the_worker_as_running(fake_redis: _FakeRedis) -> None:
    """摘的瞬间任务刚被 worker 取走：不能谎报已停止。"""
    raw = _queue_job(fake_redis, "job-racing", "score_index_xref", "PRJ-1")

    original_lrem = fake_redis.lrem

    def racing_lrem(key: str, count: int, value: str) -> int:
        original_lrem(key, count, value)
        return 0  # 模拟摘的时候已经不在队列里了

    fake_redis.lrem = racing_lrem  # type: ignore[method-assign]

    assert job_queue.cancel_generation_job("score_index_xref", "PRJ-1") == "running"
    assert fake_redis.exists(f"{job_queue.CANCEL_KEY_PREFIX}job-racing"), "仍要打上取消标记，让 worker 取到后跳过"
    assert raw is not None
