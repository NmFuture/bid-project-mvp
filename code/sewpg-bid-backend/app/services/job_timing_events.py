from __future__ import annotations

import functools
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.redis import RedisError, get_redis_client
from app.services.job_queue import JOB_KEY_PREFIX

logger = logging.getLogger(__name__)

JOB_TIMING_FINALIZE_QUEUE_KEY = "bid:timing:finalize"
JOB_TIMING_FINALIZE_PROCESSING_KEY = f"{JOB_TIMING_FINALIZE_QUEUE_KEY}:processing"
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def timing_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _event_job(job: dict[str, Any], job_type_override: str = "") -> dict[str, Any]:
    data = job.get("data") if isinstance(job.get("data"), dict) else {}
    user = job.get("user") if isinstance(job.get("user"), dict) else {}
    return {
        "id": str(job.get("id") or ""),
        "type": str(job_type_override or job.get("type") or ""),
        "projectId": str(job.get("projectId") or ""),
        "parentJobId": str(job.get("parentJobId") or ""),
        "createdAt": str(job.get("createdAt") or ""),
        "__timingStartedAt": str(job.get("__timingStartedAt") or ""),
        "data": {"__bidType": str(data.get("__bidType") or "")},
        "user": {
            "id": str(user.get("id") or ""),
            "name": str(user.get("name") or ""),
            "email": str(user.get("email") or ""),
        },
    }


def enqueue_job_timing_finalization(
    job: dict[str, Any],
    status: str,
    error_message: str = "",
    *,
    job_type_override: str = "",
    extra_meta: dict[str, Any] | None = None,
) -> bool:
    """Emit a small terminal event; PostgreSQL work is handled by another thread/process."""

    timed_job = _event_job(job, job_type_override)
    if not timed_job["id"] or not timed_job["type"]:
        return False
    client = get_redis_client()
    if client is None:
        return False
    payload = {
        "job": timed_job,
        "status": str(status or ""),
        "finishedAt": timing_now_iso(),
        "errorMessage": str(error_message or ""),
        "extraMeta": extra_meta if isinstance(extra_meta, dict) else {},
    }
    try:
        client.rpush(JOB_TIMING_FINALIZE_QUEUE_KEY, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return True
    except (RedisError, TypeError, ValueError) as exc:
        logger.warning("投递任务耗时事件失败 job_id=%s: %s", timed_job["id"], exc)
        return False


def decode_job_timing_event(raw_payload: str) -> dict[str, Any]:
    payload = json.loads(str(raw_payload))
    job = payload.get("job") if isinstance(payload, dict) else None
    if not isinstance(job, dict) or not str(job.get("id") or "") or not str(job.get("type") or ""):
        raise ValueError("任务耗时事件缺少 job.id 或 job.type")
    return {
        "job": job,
        "status": str(payload.get("status") or ""),
        "finishedAt": str(payload.get("finishedAt") or ""),
        "errorMessage": str(payload.get("errorMessage") or ""),
        "extraMeta": payload.get("extraMeta") if isinstance(payload.get("extraMeta"), dict) else {},
    }


def finalize_tracked_redis_job(
    job: dict[str, Any],
    *,
    tracked_types: set[str] | None = None,
    job_type_override: str = "",
) -> None:
    """Queue terminal timing work without importing or connecting to PostgreSQL."""

    try:
        job_type = str(job.get("type") or "")
        job_id = str(job.get("id") or "")
        if tracked_types is not None and job_type not in tracked_types:
            return
        client = get_redis_client()
        if client is None or not job_id:
            return
        fields = client.hgetall(f"{JOB_KEY_PREFIX}{job_id}") or {}
        status = str(fields.get("status") or "")
        if status not in TERMINAL_JOB_STATUSES:
            return
        enqueue_job_timing_finalization(
            job,
            status,
            str(fields.get("message") or ""),
            job_type_override=job_type_override,
        )
    except Exception as exc:
        logger.warning("任务耗时收口失败 job_id=%s: %s", job.get("id"), exc)


def track_job_timing(
    *,
    tracked_types: set[str] | None = None,
    job_type_override: str = "",
) -> Any:
    """Record execution start and enqueue terminal timing work after the worker returns."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(job: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            job["__timingStartedAt"] = timing_now_iso()
            try:
                return func(job, *args, **kwargs)
            finally:
                finalize_tracked_redis_job(
                    job,
                    tracked_types=tracked_types,
                    job_type_override=job_type_override,
                )

        return wrapper

    return decorator
