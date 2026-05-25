from __future__ import annotations

import logging
import signal
import time
from typing import Any

from app.core.config import settings
from app.core.redis import redis_is_available
from app.services.job_queue import (
    dequeue_generation_job,
    mark_job_status,
    release_generation_lock,
)
from app.services.workspace_project_access import get_any_workspace_project_runtime_state

logger = logging.getLogger(__name__)
_stop_requested = False


def _request_stop(signum: int, _: Any) -> None:
    global _stop_requested
    logger.info("Received signal %s, stopping worker after current job.", signum)
    _stop_requested = True


def _runtime_state(project_id: str) -> dict[str, Any]:
    return get_any_workspace_project_runtime_state(project_id, not_found_error=KeyError)


def _run_job(job: dict[str, Any]) -> None:
    job_type = str(job.get("type") or "")
    project_id = str(job.get("projectId") or "")
    data = job.get("data") if isinstance(job.get("data"), dict) else {}
    user = job.get("user") if isinstance(job.get("user"), dict) else None
    final_state: dict[str, Any] = {}

    mark_job_status(job, "running")
    try:
        if job_type == "directory_generation":
            from app.services.bid_directory_flow import _run_directory_generation_job

            _run_directory_generation_job(project_id, data)
            project_state = _runtime_state(project_id)
            final_state = project_state.get("directory_state") if isinstance(project_state.get("directory_state"), dict) else {}
        elif job_type == "fill_generation":
            from app.services.bid_generation_flow import _run_fill_generation_job
            from app.services.bid_type import require_bid_type

            project_state = _runtime_state(project_id)
            bid_type = require_bid_type(
                data.get("__bidType") or project_state.get("bidType"),
                error_message="生成任务必须显式绑定技术标或商务标。",
            )
            _run_fill_generation_job(project_id, data, user, bid_type=bid_type)
            project_state = _runtime_state(project_id)
            final_state = project_state.get("fill_state") if isinstance(project_state.get("fill_state"), dict) else {}
        elif job_type == "material_cleaning":
            from app.services.material_cleaning import clean_material_file_sync

            result = clean_material_file_sync(project_id, data)
            final_state = {
                "status": "failed" if result.get("cleanStatus") == "failed" else "success",
                "summary": result.get("cleanMessage") or "",
            }
        else:
            raise RuntimeError(f"Unknown job type: {job_type}")
    except Exception as exc:  # pragma: no cover - route job functions handle expected failures
        logger.exception("Background job failed: %s", job)
        mark_job_status(job, "failed", str(exc))
        raise
    else:
        if final_state.get("status") == "failed":
            mark_job_status(job, "failed", str(final_state.get("summary") or "Job failed"))
        else:
            mark_job_status(job, "succeeded")
    finally:
        release_generation_lock(job)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    if not settings.redis_url:
        logger.error("REDIS_URL is not configured; worker cannot start.")
        return

    logger.info("Redis worker started. Queue polling timeout=%ss", settings.redis_worker_poll_timeout_sec)
    while not _stop_requested:
        if not redis_is_available():
            time.sleep(2)
            continue

        job = dequeue_generation_job()
        if not job:
            continue

        try:
            _run_job(job)
        except Exception:
            continue

    logger.info("Redis worker stopped.")


if __name__ == "__main__":
    main()
