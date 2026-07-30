from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from app.services.job_timing import _now_iso, finalize_job_timing


logger = logging.getLogger(__name__)
_JOBS: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = queue.Queue()

# 本地兜底执行时同样写任务耗时：函数名 → 任务类型（无 Redis 时阶段数据为空也接受）。
_LOCAL_JOB_TYPES = {
    "_run_s1_parse_job": "s1_parse",
    "_run_directory_generation_job": "directory_generation",
}


def _local_job_status(job_type: str, project_id: str) -> str:
    """本地执行无任务状态哈希，按项目运行态推断终态。"""

    try:
        from app.services.workspace_project_access import get_any_workspace_project_runtime_state

        state = get_any_workspace_project_runtime_state(project_id, not_found_error=KeyError)
        if job_type == "directory_generation":
            raw = str((state.get("directory_state") or {}).get("status") or "")
            return {"completed": "succeeded", "failed": "failed"}.get(raw, "succeeded")
        raw = str((state.get("parse_progress") or {}).get("status") or "")
        return {"completed": "succeeded", "failed": "failed", "cancelled": "cancelled"}.get(raw, "succeeded")
    except Exception:
        return "succeeded"


def _finalize_local_job_timing(
    function: Callable[..., Any],
    args: tuple[Any, ...],
    started_at: str,
    error_message: str,
) -> None:
    try:
        job_type = _LOCAL_JOB_TYPES.get(getattr(function, "__name__", ""))
        if not job_type or not args:
            return
        project_id = str(args[0] or "")
        data = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
        status = "failed" if error_message else _local_job_status(job_type, project_id)
        job = {
            "id": str(data.get("__runId") or f"local-{job_type}-{project_id}"),
            "type": job_type,
            "projectId": project_id,
            "data": data,
            "createdAt": started_at,
            "__timingStartedAt": started_at,
        }
        finalize_job_timing(job, status, error_message)
    except Exception as exc:
        logger.warning("本地任务耗时汇总失败（已忽略）: %s", exc)


def _run_jobs() -> None:
    while True:
        function, args, kwargs = _JOBS.get()
        started_at = _now_iso()
        error_message = ""
        try:
            function(*args, **kwargs)
        except Exception as exc:
            error_message = str(exc)
            logger.exception("Local background job failed")
        finally:
            _finalize_local_job_timing(function, args, started_at, error_message)
            _JOBS.task_done()


_WORKER = threading.Thread(target=_run_jobs, daemon=True, name="local-background-job")
_WORKER.start()


def submit_local_job(function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Serialize background jobs when Redis is unavailable."""

    _JOBS.put((function, args, kwargs))
