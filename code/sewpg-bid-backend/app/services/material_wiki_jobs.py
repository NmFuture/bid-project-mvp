from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.redis import RedisError, get_redis_client
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE, require_bid_type
from app.services.job_queue import (
    JobStatusUnavailable,
    enqueue_generation_job,
    find_active_jobs_of_type,
    get_job_status,
)
from app.services.peripheral import PeripheralError

MATERIAL_WIKI_JOB_TYPE = "material_wiki_generation"
LATEST_WIKI_JOB_KEY_PREFIX = "bid:jobs:material-wiki:latest"
logger = logging.getLogger(__name__)
_WIKI_SCOPE = {
    TECHNICAL_BID_TYPE: "wiki:technical",
    BUSINESS_BID_TYPE: "wiki:business",
}


def _latest_job_key(bid_type: str) -> str:
    return f"{LATEST_WIKI_JOB_KEY_PREFIX}:{bid_type}"


def _remember_latest_job(bid_type: str, job_id: str) -> None:
    client = get_redis_client()
    if client is None or not job_id:
        return
    try:
        client.set(_latest_job_key(bid_type), job_id, ex=settings.redis_job_result_ttl_sec)
    except RedisError as exc:
        logger.warning("Failed to remember latest material Wiki job: %s", exc)


def enqueue_material_wiki_generation(
    bid_type: str,
    *,
    mode: str,
    reference_path: str = "",
    fallback_to_deterministic: bool = False,
) -> dict[str, Any]:
    try:
        resolved_bid_type = require_bid_type(bid_type)
    except ValueError as exc:
        raise PeripheralError(400, str(exc), "WIKI_BID_TYPE_REQUIRED") from exc

    scope = _WIKI_SCOPE[resolved_bid_type]
    result = enqueue_generation_job(
        MATERIAL_WIKI_JOB_TYPE,
        scope,
        {
            "bidType": resolved_bid_type,
            "mode": str(mode or "create"),
            "referencePath": str(reference_path or ""),
            "fallbackToDeterministic": bool(fallback_to_deterministic),
        },
    )
    if result.queued:
        _remember_latest_job(resolved_bid_type, result.job_id)
        return {"jobId": result.job_id, "status": "queued", "reused": False}
    if result.locked:
        active = next(
            (
                job
                for job in find_active_jobs_of_type(MATERIAL_WIKI_JOB_TYPE)
                if str(job.get("projectId") or "") == scope
            ),
            None,
        )
        if active and active.get("id"):
            _remember_latest_job(resolved_bid_type, str(active["id"]))
            return {"jobId": str(active["id"]), "status": "queued", "reused": True}
        raise PeripheralError(409, "Wiki 生成任务正在执行，请稍后重试。", "WIKI_JOB_LOCKED")
    raise PeripheralError(503, "素材任务队列暂不可用，请稍后重试。", "MATERIAL_QUEUE_UNAVAILABLE")


def material_wiki_job_status(job_id: str, bid_type: str) -> dict[str, Any]:
    try:
        resolved_bid_type = require_bid_type(bid_type)
    except ValueError as exc:
        raise PeripheralError(400, str(exc), "WIKI_BID_TYPE_REQUIRED") from exc
    try:
        payload = get_job_status(job_id)
    except JobStatusUnavailable as exc:
        raise PeripheralError(
            503,
            "素材任务状态暂不可用，请稍后重试。",
            "MATERIAL_QUEUE_UNAVAILABLE",
        ) from exc
    if (
        not payload
        or str(payload.get("type") or "") != MATERIAL_WIKI_JOB_TYPE
        or str(payload.get("projectId") or "") != _WIKI_SCOPE[resolved_bid_type]
    ):
        raise PeripheralError(404, "Wiki 生成任务不存在。", "WIKI_JOB_NOT_FOUND")
    return payload


def latest_material_wiki_job_status(bid_type: str) -> dict[str, Any]:
    resolved_bid_type = require_bid_type(bid_type)
    client = get_redis_client()
    if client is None:
        raise PeripheralError(503, "素材任务状态暂不可用，请稍后重试。", "MATERIAL_QUEUE_UNAVAILABLE")
    try:
        job_id = str(client.get(_latest_job_key(resolved_bid_type)) or "")
    except RedisError as exc:
        raise PeripheralError(
            503,
            "素材任务状态暂不可用，请稍后重试。",
            "MATERIAL_QUEUE_UNAVAILABLE",
        ) from exc
    if not job_id:
        return {"status": "idle"}
    try:
        payload = material_wiki_job_status(job_id, resolved_bid_type)
    except PeripheralError as exc:
        if exc.status_code == 404:
            return {"status": "idle"}
        raise
    state = str(payload.get("status") or "").lower()
    compatible_state = "running" if state in {"queued", "running"} else state
    result = {
        "jobId": job_id,
        "status": compatible_state,
        "progress": payload.get("progress") if isinstance(payload.get("progress"), dict) else {},
        "message": str(payload.get("message") or ""),
    }
    if compatible_state in {"failed", "cancelled"}:
        result["error"] = result["message"]
    return result


def execute_material_wiki_generation(
    data: dict[str, Any],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    bid_type = require_bid_type(data.get("bidType"))
    kwargs = {
        "mode": str(data.get("mode") or "create"),
        "reference_path": str(data.get("referencePath") or ""),
        "fallback_to_deterministic": bool(data.get("fallbackToDeterministic")),
    }
    if bid_type == BUSINESS_BID_TYPE:
        from app.services.business_wiki_generation import generate_business_wiki

        result = asyncio.run(generate_business_wiki(**kwargs))
    else:
        from app.services.technical_wiki_generation import generate_technical_wiki

        result = asyncio.run(generate_technical_wiki(**kwargs, on_progress=progress_callback))
    generation = result.get("generation") if isinstance(result.get("generation"), dict) else {}
    return {
        "status": "success",
        "summary": str(generation.get("summary") or f"{bid_type} Wiki 已生成。"),
    }
