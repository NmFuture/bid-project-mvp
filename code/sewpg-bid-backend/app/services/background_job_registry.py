from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger(__name__)

# 进程内后台任务注册表：按任务名单例运行，状态仅存内存。
# 后端重启后状态回到 idle；接入的任务必须可安全重跑（断点续跑），
# 由调用方保证幂等，重启后重新触发即可续上。
_JOBS: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_status(name: str) -> dict[str, Any]:
    job = _JOBS.get(name)
    if job is None:
        return {"name": name, "status": "idle"}
    return {
        "name": name,
        "status": job["status"],
        "startedAt": job.get("startedAt") or "",
        "finishedAt": job.get("finishedAt") or "",
        "progress": job.get("progress") or {},
        "result": job.get("result"),
        "error": job.get("error") or "",
    }


def start_job(name: str, coro_factory: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """启动命名的后台任务；同名任务运行中时直接返回当前状态（幂等重入）。"""

    existing = _JOBS.get(name)
    if existing and existing["status"] == "running":
        return _public_status(name)
    job: dict[str, Any] = {
        "status": "running",
        "startedAt": _now_iso(),
        "finishedAt": "",
        "progress": {},
        "result": None,
        "error": "",
    }
    _JOBS[name] = job

    async def _runner() -> None:
        try:
            result = await coro_factory()
        except Exception as exc:  # noqa: BLE001 - 后台任务失败必须显式落状态，不静默吞掉
            logger.exception("Background job %s failed", name)
            job["status"] = "failed"
            job["error"] = str(exc)
        else:
            job["status"] = "succeeded"
            job["result"] = result
        finally:
            job["finishedAt"] = _now_iso()

    job["task"] = asyncio.ensure_future(_runner())
    return _public_status(name)


def get_job_status(name: str) -> dict[str, Any]:
    return _public_status(name)


def update_job_progress(name: str, progress: dict[str, Any]) -> None:
    job = _JOBS.get(name)
    if job is not None and job["status"] == "running":
        job["progress"] = dict(progress)
