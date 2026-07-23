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
INFLIGHT_KEY = "bid:jobs:inflight"
KNOWN_JOB_TYPES = {"directory_generation", "fill_generation", "material_cleaning", "material_deep_parse", "s1_parse"}

# 锁的续期/释放必须校验 owner 且原子执行：GET 之后再 EXPIRE/DEL 存在竞态，
# 可能把同一项目里后来任务刚拿到的锁误续期或误删。
_RENEW_IF_OWNER_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) end return 0"
)
_DELETE_IF_OWNER_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) end return 0"
)


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
        # 排队等待期用较长但有限的 TTL 兜底：若入队后 payload 丢失（Redis 清库、队列被删），
        # 锁不会永久残留；正常执行时 worker 会按执行 TTL 持续续期。
        lock_acquired = client.set(
            lock_key,
            job_id,
            nx=True,
            ex=settings.redis_job_queue_lock_ttl_sec,
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
            client.eval(_DELETE_IF_OWNER_SCRIPT, 1, lock_key, job_id)
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


def renew_generation_lock(job: dict[str, Any]) -> bool:
    """Extend only the lock still owned by this job."""

    client = get_redis_client()
    if client is None:
        return False
    job_type = str(job.get("type") or "")
    project_id = str(job.get("projectId") or "")
    job_id = str(job.get("id") or "")
    if job_type not in KNOWN_JOB_TYPES or not project_id or not job_id:
        return False
    lock_key = generation_lock_key(job_type, project_id)
    try:
        return bool(
            client.eval(_RENEW_IF_OWNER_SCRIPT, 1, lock_key, job_id, settings.redis_job_lock_ttl_sec)
        )
    except RedisError as exc:
        logger.warning("Failed to renew Redis job lock: %s", exc)
        return False


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
        if job_id:
            client.eval(_DELETE_IF_OWNER_SCRIPT, 1, lock_key, job_id)
        else:
            client.delete(lock_key)
    except RedisError as exc:
        logger.warning("Failed to release Redis job lock: %s", exc)


def force_release_generation_lock(job_type: str, project_id: str) -> None:
    if job_type not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")

    client = get_redis_client()
    if client is None:
        return

    try:
        client.delete(generation_lock_key(job_type, project_id))
    except RedisError as exc:
        logger.warning("Failed to force release Redis job lock: %s", exc)


def mark_job_inflight(job: dict[str, Any]) -> None:
    """记录 job 进入执行态：worker 崩溃后可据此把残留 job 显式置失败，而非永久卡 running。"""

    client = get_redis_client()
    if client is None:
        return
    job_id = str(job.get("id") or "")
    if not job_id:
        return
    entry = {
        "id": job_id,
        "type": str(job.get("type") or ""),
        "projectId": str(job.get("projectId") or ""),
        "startedAt": _now_iso(),
        # data 一并登记：全局互斥提示需要展示正在处理的任务信息（如解析文件名）。
        "data": job.get("data") if isinstance(job.get("data"), dict) else {},
    }
    try:
        client.hset(INFLIGHT_KEY, job_id, json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    except RedisError as exc:
        logger.warning("Failed to record in-flight job: %s", exc)


def clear_job_inflight(job: dict[str, Any]) -> None:
    client = get_redis_client()
    if client is None:
        return
    job_id = str(job.get("id") or "")
    if not job_id:
        return
    try:
        client.hdel(INFLIGHT_KEY, job_id)
    except RedisError as exc:
        logger.warning("Failed to clear in-flight job: %s", exc)


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def find_active_jobs_of_type(job_type: str) -> list[dict[str, Any]]:
    """扫描 in-flight 登记表与等待队列，返回指定类型、尚未进入终态的任务。

    用于全局互斥提示（如同一时间只允许一个 S1 解析）。Redis 不可用时返回空，
    调用方按「无全局冲突」降级处理（本地兜底执行本来就是串行的）。
    注意这是提示级检查，扫描与入队之间存在竞态窗口；同项目冲突仍由项目锁兜底。
    """

    if job_type not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")

    client = get_redis_client()
    if client is None:
        return []

    active: list[dict[str, Any]] = []
    try:
        entries = client.hgetall(INFLIGHT_KEY)
    except RedisError as exc:
        logger.warning("Failed to scan in-flight jobs: %s", exc)
        entries = {}
    for raw in (entries or {}).values():
        try:
            entry = json.loads(str(raw))
        except ValueError:
            continue
        if str(entry.get("type") or "") != job_type:
            continue
        active.append(
            {
                "id": str(entry.get("id") or ""),
                "projectId": str(entry.get("projectId") or ""),
                "data": entry.get("data") if isinstance(entry.get("data"), dict) else {},
            }
        )

    inflight_ids = {job["id"] for job in active if job["id"]}
    try:
        queued_items = client.lrange(QUEUE_KEY, 0, -1)
    except RedisError as exc:
        logger.warning("Failed to scan queued jobs: %s", exc)
        queued_items = []
    for raw in queued_items or []:
        try:
            payload = json.loads(str(raw))
        except ValueError:
            continue
        if str(payload.get("type") or "") != job_type:
            continue
        job_id = str(payload.get("id") or "")
        if job_id and job_id in inflight_ids:
            continue
        active.append(
            {
                "id": job_id,
                "projectId": str(payload.get("projectId") or ""),
                "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
            }
        )
    return active


def reclaim_stale_inflight_jobs(max_age_sec: int) -> int:
    """把执行时长超过 max_age_sec 的残留 in-flight job 显式置为 failed 并释放其锁。

    由 worker 在启动时和运行中周期调用：正常完成的 job 会在 finally 里清除 in-flight 标记，
    残留项说明某个 worker 在执行中崩溃/被杀，需显式失败而不是留在 running。
    释放锁走 owner 校验（锁值必须仍是该 job id），绝不误删同一项目后续任务的锁。
    返回回收的 job 数。
    """

    client = get_redis_client()
    if client is None:
        return 0
    try:
        entries = client.hgetall(INFLIGHT_KEY)
    except RedisError as exc:
        logger.warning("Failed to scan in-flight jobs: %s", exc)
        return 0

    now = datetime.now(UTC)
    reclaimed = 0
    for job_id, raw in (entries or {}).items():
        try:
            entry = json.loads(str(raw))
        except ValueError:
            entry = {}
        started_at = _parse_iso(str(entry.get("startedAt") or ""))
        if started_at is not None and (now - started_at).total_seconds() < max_age_sec:
            continue
        job_type = str(entry.get("type") or "")
        project_id = str(entry.get("projectId") or "")
        reclaim_job = {"id": str(job_id), "type": job_type, "projectId": project_id}
        mark_job_status(reclaim_job, "failed", "worker 执行中断，任务被判定为失败。")
        if job_type in KNOWN_JOB_TYPES and project_id:
            release_generation_lock(reclaim_job)
        try:
            client.hdel(INFLIGHT_KEY, job_id)
        except RedisError as exc:
            logger.warning("Failed to remove reclaimed in-flight job %s: %s", job_id, exc)
        reclaimed += 1
    if reclaimed:
        logger.warning("Reclaimed %s stale in-flight job(s) as failed.", reclaimed)
    return reclaimed
