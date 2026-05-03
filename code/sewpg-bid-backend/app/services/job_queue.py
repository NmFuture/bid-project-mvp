from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.redis import RedisError, get_redis_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "bid:jobs"
JOB_KEY_PREFIX = "bid:job:"
LOCK_KEY_PREFIX = "bid:lock:"
KNOWN_JOB_TYPES = {"directory_generation", "fill_generation", "material_cleaning"}


@dataclass(frozen=True)
class EnqueueResult:
    queued: bool
    job_id: str = ""
    locked: bool = False
    unavailable: bool = False


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def generation_lock_key(job_type: str, project_id: str) -> str:
    if job_type not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")
    return f"{LOCK_KEY_PREFIX}{job_type}:{project_id}"


def is_generation_locked(job_type: str, project_id: str) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.exists(generation_lock_key(job_type, project_id)))
    except RedisError as exc:
        logger.warning("Failed to inspect Redis job lock: %s", exc)
        return False


def enqueue_generation_job(job_type: str, project_id: str, data: dict[str, Any]) -> EnqueueResult:
    if job_type not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")

    client = get_redis_client()
    if client is None:
        return EnqueueResult(queued=False, unavailable=True)

    job_id = uuid4().hex
    lock_key = generation_lock_key(job_type, project_id)
    created_at = _now_iso()
    payload_data = dict(data or {})
    job_user = payload_data.pop("__auditUser", None)
    job = {
        "id": job_id,
        "type": job_type,
        "projectId": project_id,
        "data": payload_data,
        "createdAt": created_at,
    }
    if isinstance(job_user, dict):
        job["user"] = {
            "id": str(job_user.get("id") or ""),
            "name": str(job_user.get("name") or job_user.get("email") or ""),
            "email": str(job_user.get("email") or ""),
        }

    try:
        lock_acquired = client.set(
            lock_key,
            job_id,
            nx=True,
            ex=settings.redis_job_lock_ttl_sec,
        )
        if not lock_acquired:
            return EnqueueResult(queued=False, locked=True)

        payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
        pipe = client.pipeline()
        pipe.hset(
            _job_key(job_id),
            mapping={
                "id": job_id,
                "type": job_type,
                "projectId": project_id,
                "status": "queued",
                "createdAt": created_at,
                "updatedAt": created_at,
            },
        )
        pipe.expire(_job_key(job_id), settings.redis_job_result_ttl_sec)
        pipe.rpush(QUEUE_KEY, payload)
        pipe.execute()
        return EnqueueResult(queued=True, job_id=job_id)
    except RedisError as exc:
        logger.warning("Failed to enqueue Redis job, falling back to local execution: %s", exc)
        try:
            client.delete(lock_key)
        except RedisError:
            pass
        return EnqueueResult(queued=False, unavailable=True)


def dequeue_generation_job(timeout_sec: int | None = None) -> dict[str, Any] | None:
    client = get_redis_client()
    if client is None:
        return None

    timeout = settings.redis_worker_poll_timeout_sec if timeout_sec is None else timeout_sec
    try:
        item = client.blpop(QUEUE_KEY, timeout=timeout)
    except RedisError as exc:
        logger.warning("Failed to dequeue Redis job: %s", exc)
        return None
    if not item:
        return None

    _, raw_payload = item
    try:
        payload = json.loads(str(raw_payload))
    except ValueError:
        logger.warning("Discarding malformed Redis job payload: %s", raw_payload)
        return None
    return payload if isinstance(payload, dict) else None


def mark_job_status(job: dict[str, Any], status: str, message: str = "") -> None:
    client = get_redis_client()
    if client is None:
        return

    job_id = str(job.get("id") or "")
    if not job_id:
        return

    updated_at = _now_iso()
    mapping = {
        "status": status,
        "updatedAt": updated_at,
    }
    if message:
        mapping["message"] = message

    try:
        pipe = client.pipeline()
        pipe.hset(_job_key(job_id), mapping=mapping)
        pipe.expire(_job_key(job_id), settings.redis_job_result_ttl_sec)
        pipe.execute()
    except RedisError as exc:
        logger.warning("Failed to update Redis job status: %s", exc)


def release_generation_lock(job: dict[str, Any]) -> None:
    client = get_redis_client()
    if client is None:
        return

    job_type = str(job.get("type") or "")
    project_id = str(job.get("projectId") or "")
    job_id = str(job.get("id") or "")
    if job_type not in KNOWN_JOB_TYPES or not project_id:
        return

    lock_key = generation_lock_key(job_type, project_id)
    try:
        if not job_id or client.get(lock_key) == job_id:
            client.delete(lock_key)
    except RedisError as exc:
        logger.warning("Failed to release Redis job lock: %s", exc)
