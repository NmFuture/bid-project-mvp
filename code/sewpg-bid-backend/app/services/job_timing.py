from __future__ import annotations

import json
import logging
import queue
import threading
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.core.redis import RedisError, get_redis_client
from app.services.bid_project_repository import ProjectStateRepository
from app.services.job_queue import INFLIGHT_KEY, JOB_KEY_PREFIX, generation_lock_key
from app.services.job_timing_events import (
    JOB_TIMING_FINALIZE_PROCESSING_KEY,
    JOB_TIMING_FINALIZE_QUEUE_KEY,
    decode_job_timing_event,
    timing_now_iso,
)

logger = logging.getLogger(__name__)

TIMING_KEY_PREFIX = "bid:timing:"

_JOB_TIMINGS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS job_timings (
        id BIGSERIAL PRIMARY KEY,
        job_id VARCHAR(80) NOT NULL,
        run_id VARCHAR(80),
        job_type VARCHAR(40) NOT NULL,
        bid_type VARCHAR(20),
        project_id VARCHAR(50),
        project_name VARCHAR(300),
        triggered_by VARCHAR(100),
        status VARCHAR(20),
        queued_at TIMESTAMPTZ,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        queue_wait_ms BIGINT,
        duration_ms BIGINT,
        error_message TEXT,
        phases JSONB DEFAULT '[]'::jsonb,
        meta JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_timings_job_id ON job_timings(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_job_timings_type_created ON job_timings(job_type, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_job_timings_project ON job_timings(project_id)",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return timing_now_iso()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _db_text(value: Any, max_length: int) -> str:
    return str(value or "")[:max_length]


def _timing_key(run_id: str, suffix: str) -> str:
    return f"{TIMING_KEY_PREFIX}{run_id}:{suffix}"


def record_phase(run_id: str, step: str, label: str, at: str | None = None) -> None:
    """记录阶段首达时间：同一 step 只记首次（HSETNX），重复事件不覆盖。

    跨 redis_worker/docling_worker/API 三进程共享同一个 Redis key；
    无 Redis 时静默跳过，埋点绝不影响主链路。
    """

    resolved_run_id = str(run_id or "").strip()
    resolved_step = str(step or "").strip()
    if not resolved_run_id or not resolved_step:
        return
    client = get_redis_client()
    if client is None:
        return
    first_seen_key = _timing_key(resolved_run_id, "phases")
    labels_key = _timing_key(resolved_run_id, "labels")
    try:
        first_seen = client.hsetnx(first_seen_key, resolved_step, str(at or _now_iso()))
        if first_seen:
            client.hset(labels_key, resolved_step, str(label or resolved_step))
            client.expire(first_seen_key, settings.redis_job_result_ttl_sec)
            client.expire(labels_key, settings.redis_job_result_ttl_sec)
    except RedisError as exc:
        logger.warning("记录阶段耗时失败 run_id=%s step=%s: %s", resolved_run_id, resolved_step, exc)


def record_timing_meta(run_id: str, **values: Any) -> None:
    """附加任务级元数据（如上传耗时），finalize 时并入 job_timings.meta。"""

    resolved_run_id = str(run_id or "").strip()
    if not resolved_run_id or not values:
        return
    client = get_redis_client()
    if client is None:
        return
    meta_key = _timing_key(resolved_run_id, "meta")
    try:
        client.hset(
            meta_key,
            mapping={str(key): json.dumps(value, ensure_ascii=False) for key, value in values.items()},
        )
        client.expire(meta_key, settings.redis_job_result_ttl_sec)
    except RedisError as exc:
        logger.warning("记录任务耗时元数据失败 run_id=%s: %s", resolved_run_id, exc)


def current_locked_job_id(job_type: str, project_id: str) -> str:
    """目录生成等 state 中没有 runId 的场景：用项目级任务锁反查当前 job_id。"""

    client = get_redis_client()
    if client is None:
        return ""
    try:
        return str(client.get(generation_lock_key(job_type, project_id)) or "")
    except (RedisError, ValueError) as exc:
        logger.warning("反查任务锁失败 job_type=%s project_id=%s: %s", job_type, project_id, exc)
        return ""


class JobTimingTables:
    def __init__(self) -> None:
        self._ready = False

    async def ensure(self, session: Any) -> None:
        if self._ready:
            return
        from sqlalchemy import text  # docling-worker 镜像无 sqlalchemy，API 侧才走到这里

        for ddl in _JOB_TIMINGS_DDL:
            await session.execute(text(ddl))
        # 调用方多是只读会话，不 commit 会连建表一起回滚；置位必须晚于提交
        await session.commit()
        self._ready = True


_job_timing_tables = JobTimingTables()


async def ensure_job_timing_tables(session: Any) -> None:
    await _job_timing_tables.ensure(session)


# worker 进程内是同步上下文，走 psycopg 直连（与 ProjectStateRepository 同一套 DSN）。
_sync_ready = False


def _ensure_sync(connection: Any) -> None:
    global _sync_ready
    if _sync_ready:
        return
    for ddl in _JOB_TIMINGS_DDL:
        connection.execute(ddl)
    # 单独提交建表：否则后面的 INSERT 一旦超时回滚，会把建表一起丢掉
    connection.commit()
    _sync_ready = True


def _project_name(project_id: str) -> str:
    if not project_id:
        return ""
    try:
        from app.services.store import store

        return str(store.get_project(project_id).get("name") or "")
    except Exception:
        return ""


def _build_phases(
    first_seen: dict[str, Any],
    labels: dict[str, Any],
    finished_at: datetime,
) -> list[dict[str, Any]]:
    """按首达时间排序，阶段耗时 = 下一阶段首达时间 - 本阶段首达时间，末阶段到 finished_at。"""

    entries: list[tuple[datetime, str, str]] = []
    for step, raw_at in first_seen.items():
        at = _parse_iso(str(raw_at))
        if at is None:
            continue
        entries.append((at, str(step), str(labels.get(step) or step)))
    entries.sort(key=lambda item: item[0])
    phases: list[dict[str, Any]] = []
    for index, (at, step, label) in enumerate(entries):
        end = entries[index + 1][0] if index + 1 < len(entries) else finished_at
        phases.append(
            {
                "step": step,
                "label": label,
                "startedAt": at.isoformat().replace("+00:00", "Z"),
                "durationMs": max(0, int((end - at).total_seconds() * 1000)),
            }
        )
    return phases


def finalize_job_timing(
    job: dict[str, Any],
    status: str,
    error_message: str = "",
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """任务终态汇总写入 job_timings；任何失败只记 warning，绝不影响主链路。"""

    try:
        _finalize_job_timing(job, status, error_message=error_message, extra_meta=extra_meta)
    except Exception as exc:
        logger.warning("写入任务耗时汇总失败 job_id=%s: %s", (job or {}).get("id"), exc)


def _finalize_job_timing(
    job: dict[str, Any],
    status: str,
    *,
    finished_at_iso: str = "",
    error_message: str = "",
    extra_meta: dict[str, Any] | None = None,
) -> None:
    job_id = _db_text(job.get("id"), 80).strip()
    job_type = _db_text(job.get("type"), 40).strip()
    if not job_id or not job_type:
        return
    project_id = _db_text(job.get("projectId"), 50)
    data = job.get("data") if isinstance(job.get("data"), dict) else {}
    # S1 工作流（s1_parse/docling_batch/s1_parse_continue）共享父任务 runId，
    # 阶段数据都挂在 runId 下；目录生成 runId 即 job_id。
    run_id = _db_text(job.get("parentJobId"), 80) or job_id

    client = get_redis_client()
    job_fields: dict[str, Any] = {}
    first_seen: dict[str, Any] = {}
    labels: dict[str, Any] = {}
    redis_meta: dict[str, Any] = {}
    started_at = _parse_iso(str(job.get("__timingStartedAt") or ""))
    if client is not None:
        try:
            job_fields = client.hgetall(f"{JOB_KEY_PREFIX}{job_id}") or {}
            first_seen = client.hgetall(_timing_key(run_id, "phases")) or {}
            labels = client.hgetall(_timing_key(run_id, "labels")) or {}
            redis_meta = client.hgetall(_timing_key(run_id, "meta")) or {}
            if started_at is None:
                inflight_raw = client.hget(INFLIGHT_KEY, job_id)
                if inflight_raw:
                    started_at = _parse_iso(str(json.loads(str(inflight_raw)).get("startedAt") or ""))
        except (RedisError, ValueError) as exc:
            logger.warning("读取任务耗时上下文失败 job_id=%s: %s", job_id, exc)

    queued_at = _parse_iso(str(job_fields.get("createdAt") or job.get("createdAt") or ""))
    finished_at = _parse_iso(finished_at_iso) or _utcnow()
    queue_wait_ms = _elapsed_ms(queued_at, started_at)
    duration_ms = _elapsed_ms(started_at, finished_at)
    phases = _build_phases(first_seen, labels, finished_at)

    meta: dict[str, Any] = {}
    for key, raw in redis_meta.items():
        try:
            meta[str(key)] = json.loads(str(raw))
        except ValueError:
            meta[str(key)] = raw
    if extra_meta:
        meta.update(extra_meta)

    user = job.get("user") if isinstance(job.get("user"), dict) else {}
    triggered_by = _db_text(user.get("name") or user.get("email"), 100)

    connection_options = (
        f"-c statement_timeout={max(1, settings.job_timing_db_statement_timeout_ms)} "
        f"-c lock_timeout={max(1, settings.job_timing_db_lock_timeout_ms)}"
    )
    with closing(
        psycopg.connect(
            ProjectStateRepository._postgres_dsn(),
            connect_timeout=max(1, settings.job_timing_db_connect_timeout_sec),
            options=connection_options,
        )
    ) as connection:
        _ensure_sync(connection)
        connection.execute(
            """
            INSERT INTO job_timings (
                job_id, run_id, job_type, bid_type, project_id, project_name, triggered_by,
                status, queued_at, started_at, finished_at, queue_wait_ms, duration_ms,
                error_message, phases, meta
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id) DO UPDATE SET
                run_id = excluded.run_id,
                job_type = excluded.job_type,
                bid_type = excluded.bid_type,
                project_id = excluded.project_id,
                project_name = excluded.project_name,
                triggered_by = excluded.triggered_by,
                status = excluded.status,
                queued_at = excluded.queued_at,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                queue_wait_ms = excluded.queue_wait_ms,
                duration_ms = excluded.duration_ms,
                error_message = excluded.error_message,
                phases = excluded.phases,
                meta = excluded.meta,
                updated_at = NOW()
            """,
            (
                job_id,
                run_id,
                job_type,
                _db_text(data.get("__bidType"), 20) or None,
                project_id or None,
                _db_text(_project_name(project_id), 300) or None,
                triggered_by or None,
                _db_text(status, 20),
                queued_at,
                started_at,
                finished_at,
                queue_wait_ms,
                duration_ms,
                str(error_message or ""),
                Jsonb(phases),
                Jsonb(meta),
            ),
        )
        connection.commit()

    logger.info(
        "任务耗时汇总 job_id=%s job_type=%s status=%s duration_ms=%s queue_wait_ms=%s phases=%d",
        job_id,
        job_type,
        status,
        duration_ms if duration_ms is not None else -1,
        queue_wait_ms if queue_wait_ms is not None else -1,
        len(phases),
    )


def _ack_job_timing_event(client: Any, raw_payload: str) -> None:
    client.lrem(JOB_TIMING_FINALIZE_PROCESSING_KEY, 1, raw_payload)


def _requeue_job_timing_event(client: Any, raw_payload: str) -> None:
    pipe = client.pipeline()
    pipe.lrem(JOB_TIMING_FINALIZE_PROCESSING_KEY, 1, raw_payload)
    pipe.rpush(JOB_TIMING_FINALIZE_QUEUE_KEY, raw_payload)
    pipe.execute()


def _recover_job_timing_events(client: Any) -> int:
    recovered = 0
    while client.lmove(
        JOB_TIMING_FINALIZE_PROCESSING_KEY,
        JOB_TIMING_FINALIZE_QUEUE_KEY,
        src="RIGHT",
        dest="LEFT",
    ):
        recovered += 1
    return recovered


def run_job_timing_writer(stop_event: threading.Event) -> None:
    """Consume timing events in a dedicated thread so PostgreSQL never blocks job execution."""

    client = get_redis_client()
    if client is None:
        logger.warning("任务耗时写入线程未启动：Redis 不可用。")
        return
    try:
        recovered = _recover_job_timing_events(client)
        if recovered:
            logger.info("已恢复 %d 条未完成的任务耗时事件。", recovered)
    except RedisError as exc:
        logger.warning("恢复任务耗时事件失败: %s", exc)

    while not stop_event.is_set():
        try:
            raw_payload = client.blmove(
                JOB_TIMING_FINALIZE_QUEUE_KEY,
                JOB_TIMING_FINALIZE_PROCESSING_KEY,
                timeout=1,
                src="LEFT",
                dest="RIGHT",
            )
        except RedisError as exc:
            logger.warning("读取任务耗时事件失败: %s", exc)
            stop_event.wait(2)
            continue
        if not raw_payload:
            continue
        try:
            event = decode_job_timing_event(str(raw_payload))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("丢弃无效任务耗时事件: %s", exc)
            try:
                _ack_job_timing_event(client, str(raw_payload))
            except RedisError as ack_exc:
                logger.warning("删除无效任务耗时事件失败: %s", ack_exc)
            continue
        try:
            _finalize_job_timing(
                event["job"],
                event["status"],
                finished_at_iso=event["finishedAt"],
                error_message=event["errorMessage"],
                extra_meta=event["extraMeta"],
            )
        except Exception as exc:
            logger.warning("异步写入任务耗时失败 job_id=%s: %s", event["job"].get("id"), exc)
            try:
                _requeue_job_timing_event(client, str(raw_payload))
            except RedisError as requeue_exc:
                logger.warning("重新排队任务耗时事件失败: %s", requeue_exc)
            stop_event.wait(2)
            continue
        try:
            _ack_job_timing_event(client, str(raw_payload))
        except RedisError as exc:
            logger.warning("确认任务耗时事件失败 job_id=%s: %s", event["job"].get("id"), exc)


_IN_PROCESS_TIMING_WRITES: queue.Queue[
    tuple[dict[str, Any], str, str, dict[str, Any] | None, str]
] = queue.Queue()


def _run_in_process_timing_writer() -> None:
    while True:
        job, status, error_message, extra_meta, finished_at_iso = _IN_PROCESS_TIMING_WRITES.get()
        try:
            _finalize_job_timing(
                job,
                status,
                finished_at_iso=finished_at_iso,
                error_message=error_message,
                extra_meta=extra_meta,
            )
        except Exception as exc:
            logger.warning("异步写入本地任务耗时失败 job_id=%s: %s", job.get("id"), exc)
        finally:
            _IN_PROCESS_TIMING_WRITES.task_done()


_IN_PROCESS_TIMING_THREAD = threading.Thread(
    target=_run_in_process_timing_writer,
    daemon=True,
    name="job-timing-writer",
)
_IN_PROCESS_TIMING_THREAD.start()


def submit_job_timing_write(
    job: dict[str, Any],
    status: str,
    error_message: str = "",
    extra_meta: dict[str, Any] | None = None,
) -> None:
    _IN_PROCESS_TIMING_WRITES.put((job, status, error_message, extra_meta, timing_now_iso()))


def _row_to_item(row: Any) -> dict[str, Any]:
    def _iso(value: Any) -> str:
        return value.isoformat() if isinstance(value, datetime) else (str(value) if value else "")

    return {
        "id": row["id"],
        "jobId": str(row["job_id"] or ""),
        "runId": str(row["run_id"] or ""),
        "jobType": str(row["job_type"] or ""),
        "bidType": str(row["bid_type"] or ""),
        "projectId": str(row["project_id"] or ""),
        "projectName": str(row["project_name"] or ""),
        "triggeredBy": str(row["triggered_by"] or ""),
        "status": str(row["status"] or ""),
        "queuedAt": _iso(row["queued_at"]),
        "startedAt": _iso(row["started_at"]),
        "finishedAt": _iso(row["finished_at"]),
        "queueWaitMs": row["queue_wait_ms"],
        "durationMs": row["duration_ms"],
        "errorMessage": str(row["error_message"] or ""),
        "phases": row["phases"] if isinstance(row["phases"], list) else [],
        "meta": row["meta"] if isinstance(row["meta"], dict) else {},
    }


async def list_job_timings(
    *,
    job_type: str = "",
    bid_type: str = "",
    project_id: str = "",
    status: str = "",
    days: int = 7,
    limit: int = 50,
) -> dict[str, Any]:
    from app.models import async_session
    from sqlalchemy import text

    conditions = ["created_at >= NOW() - make_interval(days => :days)"]
    params: dict[str, Any] = {"days": int(days), "limit": int(limit)}
    if job_type:
        conditions.append("job_type = :job_type")
        params["job_type"] = job_type
    if bid_type:
        conditions.append("bid_type = :bid_type")
        params["bid_type"] = bid_type
    if project_id:
        conditions.append("project_id = :project_id")
        params["project_id"] = project_id
    if status:
        conditions.append("status = :status")
        params["status"] = status
    where_sql = " AND ".join(conditions)

    async with async_session() as session:
        await ensure_job_timing_tables(session)
        total = int(
            (
                await session.execute(
                    text(f"SELECT COUNT(*) AS total FROM job_timings WHERE {where_sql}"),
                    params,
                )
            ).scalar()
            or 0
        )
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                        SELECT * FROM job_timings
                        WHERE {where_sql}
                        ORDER BY created_at DESC, id DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
    return {"items": [_row_to_item(row) for row in rows], "total": total}


async def get_job_timing(timing_id: int) -> dict[str, Any] | None:
    from app.models import async_session
    from sqlalchemy import text

    async with async_session() as session:
        await ensure_job_timing_tables(session)
        row = (
            (
                await session.execute(
                    text("SELECT * FROM job_timings WHERE id = :timing_id"),
                    {"timing_id": int(timing_id)},
                )
            )
            .mappings()
            .first()
        )
    return _row_to_item(row) if row is not None else None


def _ms(value: Any) -> int | None:
    return None if value is None else int(round(float(value)))


async def summarize_job_timings(*, days: int = 7) -> dict[str, Any]:
    from app.models import async_session
    from sqlalchemy import text

    params = {"days": int(days)}
    async with async_session() as session:
        await ensure_job_timing_tables(session)
        type_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT
                            job_type,
                            COUNT(*) AS count,
                            COUNT(*) FILTER (WHERE status = 'succeeded') AS success_count,
                            AVG(duration_ms) AS avg_duration_ms,
                            percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_duration_ms,
                            percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_duration_ms,
                            MAX(duration_ms) AS max_duration_ms,
                            AVG(queue_wait_ms) AS avg_queue_wait_ms
                        FROM job_timings
                        WHERE created_at >= NOW() - make_interval(days => :days)
                        GROUP BY job_type
                        ORDER BY job_type
                        """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        phase_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT
                            job_type,
                            phase->>'step' AS step,
                            phase->>'label' AS label,
                            AVG((phase->>'durationMs')::bigint) AS avg_duration_ms,
                            MAX((phase->>'durationMs')::bigint) AS max_duration_ms,
                            COUNT(*) AS count
                        FROM job_timings, jsonb_array_elements(phases) AS phase
                        WHERE created_at >= NOW() - make_interval(days => :days)
                        GROUP BY job_type, phase->>'step', phase->>'label'
                        ORDER BY job_type, phase->>'step'
                        """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

    by_type = []
    for row in type_rows:
        count = int(row["count"] or 0)
        success_count = int(row["success_count"] or 0)
        by_type.append(
            {
                "jobType": str(row["job_type"] or ""),
                "count": count,
                "successCount": success_count,
                "successRate": round(success_count / count, 4) if count else 0,
                "avgDurationMs": _ms(row["avg_duration_ms"]),
                "p50DurationMs": _ms(row["p50_duration_ms"]),
                "p95DurationMs": _ms(row["p95_duration_ms"]),
                "maxDurationMs": _ms(row["max_duration_ms"]),
                "avgQueueWaitMs": _ms(row["avg_queue_wait_ms"]),
            }
        )
    by_phase = [
        {
            "jobType": str(row["job_type"] or ""),
            "step": str(row["step"] or ""),
            "label": str(row["label"] or ""),
            "avgDurationMs": _ms(row["avg_duration_ms"]),
            "maxDurationMs": _ms(row["max_duration_ms"]),
            "count": int(row["count"] or 0),
        }
        for row in phase_rows
    ]
    return {"days": int(days), "byType": by_type, "byPhase": by_phase}
