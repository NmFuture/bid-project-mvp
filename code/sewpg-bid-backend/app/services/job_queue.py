from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.redis import RedisError, get_redis_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "bid:jobs"
MATERIAL_QUEUE_KEY = os.getenv("REDIS_MATERIAL_QUEUE_KEY", "bid:jobs:material").strip() or "bid:jobs:material"
DOCLING_QUEUE_KEY = os.getenv("REDIS_DOCLING_QUEUE_KEY", "bid:jobs:docling").strip() or "bid:jobs:docling"
PROCESSING_QUEUE_SUFFIX = ":processing"
JOB_KEY_PREFIX = "bid:job:"
LOCK_KEY_PREFIX = "bid:lock:"
S1_WORKFLOW_LOCK_KEY = f"{LOCK_KEY_PREFIX}s1_parse:workflow"
INFLIGHT_KEY = "bid:jobs:inflight"
CANCEL_KEY_PREFIX = "bid:job:cancel:"
INTERNAL_JOB_TYPES = {
    "s1_docling_batch",
    "s1_parse_continue",
}
KNOWN_JOB_TYPES = {
    "directory_generation",
    "fact_curate",
    "fill_generation",
    "material_cleaning",
    "material_deep_parse",
    "material_wiki_generation",
    "s1_parse",
    "technical_body_fill",
    *INTERNAL_JOB_TYPES,
}

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
_ACQUIRE_OR_RENEW_IF_OWNER_SCRIPT = (
    "local owner = redis.call('get', KEYS[1]) "
    "if owner == ARGV[1] then redis.call('expire', KEYS[1], ARGV[2]); return 1 end "
    "if not owner then redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2]); return 1 end "
    "return 0"
)
_ENQUEUE_INTERNAL_JOB_SCRIPT = (
    "if redis.call('exists', KEYS[1]) == 1 then return 0 end "
    "if ARGV[8] ~= '' then "
    "redis.call('hset', KEYS[3], 'status', ARGV[8], 'updatedAt', ARGV[5]) "
    "redis.call('expire', KEYS[3], ARGV[6]) end "
    "redis.call('hset', KEYS[1], "
    "'id', ARGV[1], 'type', ARGV[2], 'projectId', ARGV[3], "
    "'parentJobId', ARGV[4], 'status', 'queued', "
    "'createdAt', ARGV[5], 'updatedAt', ARGV[5]) "
    "redis.call('expire', KEYS[1], ARGV[6]) "
    "redis.call('rpush', KEYS[2], ARGV[7]) return 1"
)
_RECOVER_PROCESSING_JOB_SCRIPT = (
    "local payload = redis.call('rpop', KEYS[1]) "
    "if not payload then return nil end "
    "redis.call('lpush', KEYS[2], payload) "
    "local ok, job = pcall(cjson.decode, payload) "
    "if ok and job['id'] then "
    "local job_id = tostring(job['id']) "
    "redis.call('hdel', KEYS[3], job_id) "
    "local job_key = ARGV[1] .. job_id "
    "redis.call('hset', job_key, 'status', 'queued', 'updatedAt', ARGV[2]) "
    "redis.call('expire', job_key, ARGV[3]) end "
    "return payload"
)
_REQUEUE_PROCESSING_JOB_SCRIPT = (
    "local removed = redis.call('lrem', KEYS[2], 1, ARGV[1]) "
    "if removed == 0 then return 0 end "
    "redis.call('hdel', KEYS[3], ARGV[2]) "
    "redis.call('hset', KEYS[4], 'status', 'queued', 'updatedAt', ARGV[4], 'message', ARGV[6]) "
    "redis.call('expire', KEYS[4], ARGV[5]) "
    "redis.call('rpush', KEYS[1], ARGV[3]) "
    "return 1"
)


@dataclass(frozen=True)
class EnqueueResult:
    queued: bool
    job_id: str = ""
    locked: bool = False
    unavailable: bool = False

    @property
    def accepted(self) -> bool:
        """Whether the internal stage is queued now or already exists."""

        return self.queued or (bool(self.job_id) and not self.locked and not self.unavailable)


class JobStatusUnavailable(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _queue_key_for_job_type(job_type: str) -> str:
    if job_type == "s1_docling_batch":
        return DOCLING_QUEUE_KEY
    if job_type in {"material_cleaning", "material_deep_parse", "material_wiki_generation"}:
        return MATERIAL_QUEUE_KEY
    return QUEUE_KEY


def processing_queue_key(queue_key: str) -> str:
    return f"{queue_key}{PROCESSING_QUEUE_SUFFIX}"


def generation_lock_key(job_type: str, project_id: str) -> str:
    if job_type not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")
    return f"{LOCK_KEY_PREFIX}{job_type}:{project_id}"


def claim_s1_workflow_lock(parent_job: dict[str, Any], ttl_sec: int | None = None) -> bool | None:
    """Acquire or renew the single-machine S1 workflow slot for its parent run."""

    client = get_redis_client()
    if client is None:
        return None
    job_id = str(parent_job.get("id") or "")
    job_type = str(parent_job.get("type") or "")
    project_id = str(parent_job.get("projectId") or "")
    if job_type != "s1_parse" or not job_id or not project_id:
        return False
    resolved_ttl = max(1, int(ttl_sec if ttl_sec is not None else settings.redis_job_lock_ttl_sec))
    try:
        return bool(
            client.eval(
                _ACQUIRE_OR_RENEW_IF_OWNER_SCRIPT,
                1,
                S1_WORKFLOW_LOCK_KEY,
                job_id,
                resolved_ttl,
            )
        )
    except RedisError as exc:
        logger.warning("Failed to claim S1 workflow lock: %s", exc)
        return None


def release_s1_workflow_lock(parent_job: dict[str, Any]) -> None:
    """Release the workflow slot only when the parent run still owns it."""

    client = get_redis_client()
    if client is None:
        return
    job_id = str(parent_job.get("id") or "")
    if str(parent_job.get("type") or "") != "s1_parse" or not job_id:
        return
    try:
        client.eval(_DELETE_IF_OWNER_SCRIPT, 1, S1_WORKFLOW_LOCK_KEY, job_id)
    except RedisError as exc:
        logger.warning("Failed to release S1 workflow lock: %s", exc)


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
        pipe.rpush(_queue_key_for_job_type(job_type), payload)
        pipe.execute()
        return EnqueueResult(queued=True, job_id=job_id)
    except RedisError as exc:
        logger.warning("Failed to enqueue Redis job, falling back to local execution: %s", exc)
        try:
            client.eval(_DELETE_IF_OWNER_SCRIPT, 1, lock_key, job_id)
        except RedisError:
            pass
        return EnqueueResult(queued=False, unavailable=True)


def enqueue_internal_job(
    job_type: str,
    project_id: str,
    data: dict[str, Any],
    *,
    job_id: str,
    parent_job_id: str,
    parent_status: str = "",
) -> EnqueueResult:
    """幂等投递 S1 内部阶段任务，不额外占用项目级生成锁。"""

    if job_type not in INTERNAL_JOB_TYPES:
        raise ValueError(f"Unknown internal job type: {job_type}")
    resolved_job_id = str(job_id or "").strip()
    if not resolved_job_id:
        raise ValueError("Internal job id is required")

    client = get_redis_client()
    if client is None:
        return EnqueueResult(queued=False, unavailable=True)

    created_at = _now_iso()
    payload_data = dict(data or {})
    job_user = payload_data.pop("__auditUser", None)
    job = {
        "id": resolved_job_id,
        "type": job_type,
        "projectId": project_id,
        "parentJobId": str(parent_job_id or ""),
        "data": payload_data,
        "createdAt": created_at,
    }
    if isinstance(job_user, dict):
        job["user"] = {
            "id": str(job_user.get("id") or ""),
            "name": str(job_user.get("name") or job_user.get("email") or ""),
            "email": str(job_user.get("email") or ""),
        }

    queue_key = _queue_key_for_job_type(job_type)
    payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
    try:
        # job hash 与队列写入在同一个 Lua 脚本内完成，重复 job_id 不会重复入队。
        queued = bool(client.eval(
            _ENQUEUE_INTERNAL_JOB_SCRIPT,
            3,
            _job_key(resolved_job_id),
            queue_key,
            _job_key(str(parent_job_id or "")),
            resolved_job_id,
            job_type,
            project_id,
            str(parent_job_id or ""),
            created_at,
            settings.redis_job_result_ttl_sec,
            payload,
            str(parent_status or ""),
        ))
        return EnqueueResult(queued=queued, job_id=resolved_job_id)
    except RedisError as exc:
        logger.warning("Failed to enqueue internal Redis job: %s", exc)
        return EnqueueResult(queued=False, unavailable=True)


def dequeue_generation_job(
    timeout_sec: int | None = None,
    *,
    queue_key: str = QUEUE_KEY,
) -> dict[str, Any] | None:
    client = get_redis_client()
    if client is None:
        return None

    timeout = settings.redis_worker_poll_timeout_sec if timeout_sec is None else timeout_sec
    processing_key = processing_queue_key(queue_key)
    try:
        raw_payload = client.blmove(queue_key, processing_key, timeout, src="LEFT", dest="RIGHT")
    except RedisError as exc:
        logger.warning("Failed to dequeue Redis job: %s", exc)
        return None
    if not raw_payload:
        return None

    try:
        payload = json.loads(str(raw_payload))
    except ValueError:
        logger.warning("Discarding malformed Redis job payload: %s", raw_payload)
        try:
            client.lrem(processing_key, 1, raw_payload)
        except RedisError:
            pass
        return None
    if not isinstance(payload, dict):
        try:
            client.lrem(processing_key, 1, raw_payload)
        except RedisError:
            pass
        return None
    payload["__queueKey"] = queue_key
    payload["__processingPayload"] = str(raw_payload)
    return payload


def requeue_processing_job(job: dict[str, Any], message: str = "") -> bool | None:
    """Atomically move a claimed job to the queue tail without duplicating it."""

    client = get_redis_client()
    if client is None:
        return None
    job_id = str(job.get("id") or "")
    queue_key = str(job.get("__queueKey") or "")
    processing_payload = str(job.get("__processingPayload") or "")
    if not job_id or not queue_key or not processing_payload:
        return False

    queued_job = {
        key: value
        for key, value in job.items()
        if key not in {"__queueKey", "__processingPayload"}
    }
    payload = json.dumps(queued_job, ensure_ascii=False, separators=(",", ":"))
    try:
        return bool(
            client.eval(
                _REQUEUE_PROCESSING_JOB_SCRIPT,
                4,
                queue_key,
                processing_queue_key(queue_key),
                INFLIGHT_KEY,
                _job_key(job_id),
                processing_payload,
                job_id,
                payload,
                _now_iso(),
                settings.redis_job_result_ttl_sec,
                str(message or ""),
            )
        )
    except RedisError as exc:
        logger.warning("Failed to requeue Redis job %s: %s", job_id, exc)
        return None


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


def mark_job_progress(job: dict[str, Any], progress: dict[str, Any]) -> None:
    client = get_redis_client()
    job_id = str(job.get("id") or "")
    if client is None or not job_id:
        return
    try:
        pipe = client.pipeline()
        pipe.hset(
            _job_key(job_id),
            mapping={
                "progress": json.dumps(progress or {}, ensure_ascii=False, separators=(",", ":")),
                "updatedAt": _now_iso(),
            },
        )
        pipe.expire(_job_key(job_id), settings.redis_job_result_ttl_sec)
        pipe.execute()
    except RedisError as exc:
        logger.warning("Failed to update Redis job progress: %s", exc)


def get_job_status(job_id: str) -> dict[str, Any] | None:
    resolved_job_id = str(job_id or "").strip()
    if not resolved_job_id:
        return None
    client = get_redis_client()
    if client is None:
        raise JobStatusUnavailable("Redis job status is unavailable")
    try:
        payload = client.hgetall(_job_key(resolved_job_id))
    except RedisError as exc:
        logger.warning("Failed to read Redis job status: %s", exc)
        raise JobStatusUnavailable("Redis job status is unavailable") from exc
    if not payload:
        return None
    result = dict(payload)
    raw_progress = result.get("progress")
    if isinstance(raw_progress, str):
        try:
            progress = json.loads(raw_progress)
        except ValueError:
            progress = {}
        result["progress"] = progress if isinstance(progress, dict) else {}
    return result


def request_job_cancel(job_id: str) -> None:
    client = get_redis_client()
    resolved_job_id = str(job_id or "").strip()
    if client is None or not resolved_job_id:
        return
    try:
        client.set(f"{CANCEL_KEY_PREFIX}{resolved_job_id}", "1", ex=settings.redis_job_result_ttl_sec)
    except RedisError as exc:
        logger.warning("Failed to mark Redis job cancelled: %s", exc)


def is_job_cancel_requested(job_id: str) -> bool:
    client = get_redis_client()
    resolved_job_id = str(job_id or "").strip()
    if client is None or not resolved_job_id:
        return False
    try:
        return bool(client.exists(f"{CANCEL_KEY_PREFIX}{resolved_job_id}"))
    except RedisError as exc:
        logger.warning("Failed to inspect Redis job cancellation: %s", exc)
        return False


def renew_generation_lock(job: dict[str, Any], ttl_sec: int | None = None) -> bool | None:
    """Extend only the lock still owned by this job."""

    client = get_redis_client()
    if client is None:
        return None
    job_type = str(job.get("type") or "")
    project_id = str(job.get("projectId") or "")
    job_id = str(job.get("id") or "")
    if job_type not in KNOWN_JOB_TYPES or not project_id or not job_id:
        return False
    lock_key = generation_lock_key(job_type, project_id)
    resolved_ttl = max(1, int(ttl_sec if ttl_sec is not None else settings.redis_job_lock_ttl_sec))
    try:
        return bool(
            client.eval(_RENEW_IF_OWNER_SCRIPT, 1, lock_key, job_id, resolved_ttl)
        )
    except RedisError as exc:
        logger.warning("Failed to renew Redis job lock: %s", exc)
        return None


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
        "parentJobId": str(job.get("parentJobId") or ""),
        "createdAt": str(job.get("createdAt") or ""),
        "startedAt": _now_iso(),
        # data 一并登记：全局互斥提示需要展示正在处理的任务信息（如解析文件名）。
        "data": job.get("data") if isinstance(job.get("data"), dict) else {},
    }
    if isinstance(job.get("user"), dict):
        entry["user"] = job["user"]
    if job.get("__queueKey") and job.get("__processingPayload"):
        entry["queueKey"] = str(job["__queueKey"])
        entry["processingPayload"] = str(job["__processingPayload"])
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
        pipe = client.pipeline()
        pipe.hdel(INFLIGHT_KEY, job_id)
        queue_key = str(job.get("__queueKey") or "")
        processing_payload = str(job.get("__processingPayload") or "")
        if queue_key and processing_payload:
            pipe.lrem(processing_queue_key(queue_key), 1, processing_payload)
        pipe.execute()
    except RedisError as exc:
        logger.warning("Failed to clear in-flight job: %s", exc)


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def recover_processing_jobs(queue_key: str) -> int:
    """把 BLMOVE 留在 processing 列表中的任务原子放回原队列。"""

    client = get_redis_client()
    if client is None:
        return 0
    recovered = 0
    while True:
        try:
            payload = client.eval(
                _RECOVER_PROCESSING_JOB_SCRIPT,
                3,
                processing_queue_key(queue_key),
                queue_key,
                INFLIGHT_KEY,
                JOB_KEY_PREFIX,
                _now_iso(),
                settings.redis_job_result_ttl_sec,
            )
        except RedisError as exc:
            logger.warning("Failed to recover processing jobs from %s: %s", queue_key, exc)
            break
        if not payload:
            break
        recovered += 1
    if recovered:
        logger.warning("Recovered %s processing job(s) to %s.", recovered, queue_key)
    return recovered


def recover_inflight_jobs(job_type: str, queue_key: str) -> int:
    """单实例 worker 启动时把指定类型的遗留执行中任务原样放回队列。"""

    if job_type not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")
    client = get_redis_client()
    if client is None:
        return 0
    try:
        entries = client.hgetall(INFLIGHT_KEY)
    except RedisError as exc:
        logger.warning("Failed to scan in-flight jobs for recovery: %s", exc)
        return 0

    recovered = 0
    for job_id, raw in (entries or {}).items():
        try:
            entry = json.loads(str(raw))
        except ValueError:
            continue
        if not isinstance(entry, dict) or str(entry.get("type") or "") != job_type:
            continue

        resolved_job_id = str(entry.get("id") or job_id)
        created_at = str(entry.get("createdAt") or _now_iso())
        job = {
            "id": resolved_job_id,
            "type": job_type,
            "projectId": str(entry.get("projectId") or ""),
            "data": entry.get("data") if isinstance(entry.get("data"), dict) else {},
            "createdAt": created_at,
        }
        parent_job_id = str(entry.get("parentJobId") or "")
        if parent_job_id:
            job["parentJobId"] = parent_job_id
        if isinstance(entry.get("user"), dict):
            job["user"] = entry["user"]

        updated_at = _now_iso()
        try:
            pipe = client.pipeline()
            pipe.rpush(queue_key, json.dumps(job, ensure_ascii=False, separators=(",", ":")))
            pipe.hdel(INFLIGHT_KEY, job_id)
            pipe.hset(
                _job_key(resolved_job_id),
                mapping={"status": "queued", "updatedAt": updated_at},
            )
            pipe.expire(_job_key(resolved_job_id), settings.redis_job_result_ttl_sec)
            pipe.execute()
        except RedisError as exc:
            logger.warning("Failed to recover in-flight job %s: %s", resolved_job_id, exc)
            continue
        recovered += 1

    if recovered:
        logger.warning("Recovered %s in-flight %s job(s).", recovered, job_type)
    return recovered


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

    active_ids = {job["id"] for job in active if job["id"]}
    queue_keys = (
        QUEUE_KEY,
        processing_queue_key(QUEUE_KEY),
        MATERIAL_QUEUE_KEY,
        processing_queue_key(MATERIAL_QUEUE_KEY),
        DOCLING_QUEUE_KEY,
        processing_queue_key(DOCLING_QUEUE_KEY),
    )
    for queue_key in dict.fromkeys(queue_keys):
        try:
            queued_items = client.lrange(queue_key, 0, -1)
        except RedisError as exc:
            logger.warning("Failed to scan queued jobs in %s: %s", queue_key, exc)
            continue
        for raw in queued_items or []:
            try:
                payload = json.loads(str(raw))
            except ValueError:
                continue
            if str(payload.get("type") or "") != job_type:
                continue
            job_id = str(payload.get("id") or "")
            if job_id and job_id in active_ids:
                continue
            active.append(
                {
                    "id": job_id,
                    "projectId": str(payload.get("projectId") or ""),
                    "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
                }
            )
            if job_id:
                active_ids.add(job_id)
    return active


def reclaim_stale_inflight_jobs(max_age_sec: int, queue_key: str = QUEUE_KEY) -> int:
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
        # Docling 使用独立单实例 worker 启动恢复，普通 worker 不应误回收其长任务。
        if _queue_key_for_job_type(job_type) != queue_key:
            continue
        reclaim_job = {
            "id": str(job_id),
            "type": job_type,
            "projectId": project_id,
            "__queueKey": str(entry.get("queueKey") or ""),
            "__processingPayload": str(entry.get("processingPayload") or ""),
        }
        mark_job_status(reclaim_job, "failed", "worker 执行中断，任务被判定为失败。")
        parent_job_id = str(entry.get("parentJobId") or "")
        workflow_parent = (
            {"id": parent_job_id, "type": "s1_parse", "projectId": project_id}
            if job_type == "s1_parse_continue" and parent_job_id
            else reclaim_job if job_type == "s1_parse" else None
        )
        lock_job = workflow_parent or reclaim_job
        if str(lock_job.get("type") or "") in KNOWN_JOB_TYPES and project_id:
            release_generation_lock(lock_job)
        if workflow_parent:
            mark_job_status(workflow_parent, "failed", "worker 执行中断，任务被判定为失败。")
            release_s1_workflow_lock(workflow_parent)
        clear_job_inflight(reclaim_job)
        reclaimed += 1
    if reclaimed:
        logger.warning("Reclaimed %s stale in-flight job(s) as failed.", reclaimed)
    return reclaimed
