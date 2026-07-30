from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import job_timing
from app.services.auth_service import current_user


class FakeRedis:
    """最小可用的 Redis 替身：只实现耗时埋点用到的命令。"""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}
        self.values: dict[str, str] = {}

    def hsetnx(self, name, key, value):
        bucket = self.hashes.setdefault(name, {})
        if key in bucket:
            return 0
        bucket[key] = value
        return 1

    def hset(self, name, key=None, value=None, mapping=None):
        bucket = self.hashes.setdefault(name, {})
        if mapping:
            for map_key, map_value in mapping.items():
                bucket[map_key] = map_value
        else:
            bucket[key] = value

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def expire(self, name, ttl):
        self.expires[name] = ttl

    def get(self, name):
        return self.values.get(name)


class FakeConnection:
    """psycopg 连接替身：记录 SQL 与参数，不真正连库。"""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self.committed = False
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _jsonb_value(wrapper):
    return getattr(wrapper, "obj", wrapper)


def test_record_phase_keeps_first_seen(monkeypatch) -> None:
    client = FakeRedis()
    monkeypatch.setattr(job_timing, "get_redis_client", lambda: client)

    job_timing.record_phase("run-1", "docling", "PDF 解析", at="2026-07-30T00:01:00Z")
    job_timing.record_phase("run-1", "docling", "PDF 解析", at="2026-07-30T00:02:00Z")

    # 幂等：重复 step 不覆盖首达时间与标签
    assert client.hashes["bid:timing:run-1:phases"]["docling"] == "2026-07-30T00:01:00Z"
    assert client.hashes["bid:timing:run-1:labels"]["docling"] == "PDF 解析"
    assert client.expires["bid:timing:run-1:phases"] == settings.redis_job_result_ttl_sec
    assert client.expires["bid:timing:run-1:labels"] == settings.redis_job_result_ttl_sec


def test_record_phase_skips_without_run_id_or_redis(monkeypatch) -> None:
    monkeypatch.setattr(job_timing, "get_redis_client", lambda: None)
    # 无 Redis / 空 runId 都静默跳过，不影响主链路
    job_timing.record_phase("run-1", "docling", "PDF 解析")
    job_timing.record_phase("", "docling", "PDF 解析")


def test_finalize_job_timing_computes_durations_phases_and_meta(monkeypatch) -> None:
    client = FakeRedis()
    client.hset("bid:job:job-1", mapping={"createdAt": "2026-07-30T00:00:00Z", "status": "succeeded"})
    client.hset(
        "bid:timing:job-1:phases",
        mapping={
            "upload": "2026-07-30T00:00:30Z",
            "docling": "2026-07-30T00:01:00Z",
        },
    )
    client.hset(
        "bid:timing:job-1:labels",
        mapping={"upload": "文件上传落盘", "docling": "PDF 解析"},
    )
    client.hset("bid:timing:job-1:meta", mapping={"uploadMs": json.dumps(30000)})
    connection = FakeConnection()

    monkeypatch.setattr(job_timing, "get_redis_client", lambda: client)
    monkeypatch.setattr(job_timing.psycopg, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(job_timing, "_utcnow", lambda: datetime(2026, 7, 30, 0, 5, tzinfo=UTC))
    monkeypatch.setattr(job_timing, "_sync_ready", False)
    monkeypatch.setattr(job_timing, "_project_name", lambda project_id: "测试项目")

    job = {
        "id": "job-1",
        "type": "s1_parse",
        "projectId": "PRJ-0001",
        "createdAt": "2026-07-30T00:00:00Z",
        "data": {"__bidType": "技术标"},
        "user": {"name": "张三"},
        "__timingStartedAt": "2026-07-30T00:00:10Z",
    }
    job_timing.finalize_job_timing(job, "succeeded", extra_meta={"origin": "upload"})

    assert connection.committed
    upsert_sql, params = connection.executed[-1]
    assert "ON CONFLICT (job_id)" in upsert_sql
    (
        job_id,
        run_id,
        job_type,
        bid_type,
        project_id,
        project_name,
        triggered_by,
        status,
        queued_at,
        started_at,
        finished_at,
        queue_wait_ms,
        duration_ms,
        error_message,
        phases_jsonb,
        meta_jsonb,
    ) = params
    assert job_id == "job-1"
    assert run_id == "job-1"
    assert job_type == "s1_parse"
    assert bid_type == "技术标"
    assert project_id == "PRJ-0001"
    assert project_name == "测试项目"
    assert triggered_by == "张三"
    assert status == "succeeded"
    # 排队 10s（00:00:00 → 00:00:10），执行 290s（00:00:10 → 00:05:00）
    assert queue_wait_ms == 10_000
    assert duration_ms == 290_000
    assert finished_at == datetime(2026, 7, 30, 0, 5, tzinfo=UTC)

    phases = _jsonb_value(phases_jsonb)
    assert phases == [
        {
            "step": "upload",
            "label": "文件上传落盘",
            "startedAt": "2026-07-30T00:00:30Z",
            "durationMs": 30_000,
        },
        {
            "step": "docling",
            "label": "PDF 解析",
            "startedAt": "2026-07-30T00:01:00Z",
            "durationMs": 240_000,
        },
    ]
    # Redis 元数据与 extra_meta 合并
    assert _jsonb_value(meta_jsonb) == {"uploadMs": 30000, "origin": "upload"}


def test_finalize_job_timing_uses_parent_run_id(monkeypatch) -> None:
    client = FakeRedis()
    connection = FakeConnection()
    monkeypatch.setattr(job_timing, "get_redis_client", lambda: client)
    monkeypatch.setattr(job_timing.psycopg, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(job_timing, "_project_name", lambda project_id: "")

    job = {
        "id": "run-1:continue",
        "type": "s1_parse_continue",
        "projectId": "PRJ-0001",
        "parentJobId": "run-1",
        "data": {},
    }
    job_timing.finalize_job_timing(job, "succeeded")

    _, params = connection.executed[-1]
    assert params[0] == "run-1:continue"
    assert params[1] == "run-1"


def test_finalize_job_timing_degrades_on_db_error(monkeypatch, caplog) -> None:
    monkeypatch.setattr(job_timing, "get_redis_client", lambda: None)

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(job_timing.psycopg, "connect", _boom)

    with caplog.at_level(logging.WARNING, logger="app.services.job_timing"):
        job_timing.finalize_job_timing({"id": "job-x", "type": "s1_parse"}, "failed", "炸了")

    assert any("写入任务耗时汇总失败" in record.message for record in caplog.records)


def test_track_job_timing_finalizes_only_on_terminal_status(monkeypatch) -> None:
    client = FakeRedis()
    monkeypatch.setattr(job_timing, "get_redis_client", lambda: client)
    calls: list[tuple] = []
    monkeypatch.setattr(
        job_timing,
        "finalize_job_timing",
        lambda job, status, message="": calls.append((job["type"], status, message)),
    )

    @job_timing.track_job_timing(tracked_types={"s1_parse"})
    def _run(job):
        raise RuntimeError("炸了")

    # 终态 failed → 收口
    client.hset("bid:job:job-9", mapping={"status": "failed", "message": "炸了"})
    job = {"id": "job-9", "type": "s1_parse"}
    with pytest.raises(RuntimeError):
        _run(job)
    assert calls == [("s1_parse", "failed", "炸了")]
    assert job["__timingStartedAt"]

    # 中间态 waiting_docling → 跳过
    calls.clear()
    client.hset("bid:job:job-10", mapping={"status": "waiting_docling"})
    with pytest.raises(RuntimeError):
        _run({"id": "job-10", "type": "s1_parse"})
    assert calls == []

    # 未跟踪的任务类型 → 跳过
    calls.clear()
    client.hset("bid:job:job-11", mapping={"status": "succeeded"})
    _ = job_timing.finalize_tracked_redis_job(
        {"id": "job-11", "type": "fill_generation"},
        tracked_types={"s1_parse", "s1_parse_continue", "directory_generation"},
    )
    assert calls == []


def test_current_locked_job_id(monkeypatch) -> None:
    client = FakeRedis()
    client.values["bid:lock:directory_generation:PRJ-0001"] = "job-dir-1"
    monkeypatch.setattr(job_timing, "get_redis_client", lambda: client)
    assert job_timing.current_locked_job_id("directory_generation", "PRJ-0001") == "job-dir-1"

    monkeypatch.setattr(job_timing, "get_redis_client", lambda: None)
    assert job_timing.current_locked_job_id("directory_generation", "PRJ-0001") == ""


class TestMonitoringRoutes:
    def _client(self) -> TestClient:
        app.dependency_overrides[current_user] = lambda: {"id": "u-1", "name": "测试用户"}
        return TestClient(app, base_url="http://127.0.0.1:8000")

    def teardown_method(self) -> None:
        app.dependency_overrides.pop(current_user, None)

    def test_list_job_timings_maps_query_params(self, monkeypatch) -> None:
        list_mock = AsyncMock(return_value={"items": [], "total": 0})
        monkeypatch.setattr("app.api.routes.monitoring.list_job_timings", list_mock)

        client = self._client()
        response = client.get(
            "/api/monitoring/job-timings",
            params={
                "jobType": "s1_parse",
                "bidType": "技术标",
                "projectId": "PRJ-0001",
                "status": "succeeded",
                "days": 3,
                "limit": 20,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}
        list_mock.assert_awaited_once_with(
            job_type="s1_parse",
            bid_type="技术标",
            project_id="PRJ-0001",
            status="succeeded",
            days=3,
            limit=20,
        )

    def test_summary_route_not_swallowed_by_detail(self, monkeypatch) -> None:
        payload = {
            "days": 7,
            "byType": [
                {
                    "jobType": "s1_parse",
                    "count": 4,
                    "successCount": 3,
                    "successRate": 0.75,
                    "avgDurationMs": 60000,
                    "p50DurationMs": 55000,
                    "p95DurationMs": 90000,
                    "maxDurationMs": 95000,
                    "avgQueueWaitMs": 1200,
                }
            ],
            "byPhase": [
                {
                    "jobType": "s1_parse",
                    "step": "docling",
                    "label": "PDF 解析",
                    "avgDurationMs": 30000,
                    "maxDurationMs": 45000,
                    "count": 4,
                }
            ],
        }
        summary_mock = AsyncMock(return_value=payload)
        monkeypatch.setattr("app.api.routes.monitoring.summarize_job_timings", summary_mock)

        client = self._client()
        response = client.get("/api/monitoring/job-timings/summary", params={"days": 7})

        assert response.status_code == 200
        body = response.json()
        assert body["days"] == 7
        assert body["byType"][0]["successRate"] == 0.75
        assert body["byPhase"][0]["step"] == "docling"
        summary_mock.assert_awaited_once_with(days=7)

    def test_detail_returns_404_when_missing(self, monkeypatch) -> None:
        get_mock = AsyncMock(return_value=None)
        monkeypatch.setattr("app.api.routes.monitoring.get_job_timing", get_mock)

        client = self._client()
        response = client.get("/api/monitoring/job-timings/999")

        assert response.status_code == 404
        get_mock.assert_awaited_once_with(999)
