from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.redis import redis_is_available
from app.services.docling_engine import prewarm_docling_converters
from app.services.docling_jobs import DOCLING_BATCH_JOB_TYPE, enqueue_docling_failure, execute_docling_batch
from app.services.job_queue import (
    DOCLING_QUEUE_KEY,
    claim_s1_workflow_lock,
    clear_job_inflight,
    dequeue_generation_job,
    mark_job_inflight,
    mark_job_status,
    recover_inflight_jobs,
    recover_processing_jobs,
    release_s1_workflow_lock,
    release_generation_lock,
    renew_generation_lock,
)
from app.services.job_timing_events import track_job_timing


logger = logging.getLogger(__name__)
READY_PATH = Path("/tmp/docling-worker-ready")
_stop_requested = False


def _request_stop(signum: int, _: Any) -> None:
    global _stop_requested
    logger.info("Received signal %s, stopping Docling worker after current job.", signum)
    _stop_requested = True


def _parent_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(job.get("parentJobId") or ""),
        "type": "s1_parse",
        "projectId": str(job.get("projectId") or ""),
    }


# 耗时监控：docling 批次统一记为 docling_batch，runId 继承 S1 父任务。
@track_job_timing(tracked_types={DOCLING_BATCH_JOB_TYPE}, job_type_override="docling_batch")
def _run_job(job: dict[str, Any]) -> None:
    if str(job.get("type") or "") != DOCLING_BATCH_JOB_TYPE:
        raise RuntimeError(f"Docling worker received unsupported job: {job.get('type')}")
    parent = _parent_job(job)
    if not parent["id"]:
        raise RuntimeError("Docling job is missing parentJobId")

    mark_job_status(job, "running")
    mark_job_inflight(job)
    lock_renewed = renew_generation_lock(parent)
    if lock_renewed is None:
        raise RuntimeError("Redis 暂不可用，无法确认 S1 父任务锁。")
    if not lock_renewed:
        message = "Docling 任务恢复时父任务锁已过期，请重新发起解析。"
        handoff = enqueue_docling_failure(job, message)
        if not handoff.accepted:
            raise RuntimeError(message)
        mark_job_status(job, "failed", message)
        clear_job_inflight(job)
        release_s1_workflow_lock(parent)
        return
    workflow_lock = claim_s1_workflow_lock(parent)
    if workflow_lock is None:
        raise RuntimeError("Redis 暂不可用，无法确认 S1 全局工作流锁。")
    if not workflow_lock:
        message = "Docling 父任务已失去 S1 全局工作流锁。"
        handoff = enqueue_docling_failure(job, message)
        if not handoff.accepted:
            raise RuntimeError(message)
        mark_job_status(job, "failed", message)
        clear_job_inflight(job)
        return
    mark_job_status(parent, "running_docling")
    heartbeat_stop = threading.Event()

    def renew_parent_lock() -> None:
        interval = max(1, settings.redis_job_lock_ttl_sec // 3)
        while not heartbeat_stop.wait(interval):
            renew_generation_lock(parent)
            claim_s1_workflow_lock(parent)

    heartbeat = threading.Thread(target=renew_parent_lock, daemon=True, name=f"docling-lock-{parent['id']}")
    heartbeat.start()
    release_parent = False
    handoff_complete = False
    try:
        outcome = execute_docling_batch(job)
        handoff_complete = True
        status = str(outcome.get("status") or "")
        if status == "cancelled":
            mark_job_status(job, "cancelled")
            mark_job_status(parent, "cancelled")
            release_parent = True
        elif status == "failed":
            mark_job_status(job, "failed", str(outcome.get("message") or "Docling 解析失败"))
        else:
            mark_job_status(job, "succeeded")
    except Exception as exc:
        logger.exception("Docling background job failed: %s", job)
        # 保留 processing 记录并让容器退出；重启后恢复任务，避免 Redis
        # 短暂不可用导致解析完成后丢失 continuation。
        mark_job_status(job, "retrying", str(exc))
        mark_job_status(parent, "waiting_docling", "Docling Worker 将在重启后重试。")
        raise
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=1)
        if handoff_complete:
            clear_job_inflight(job)
            if release_parent:
                release_generation_lock(parent)
                release_s1_workflow_lock(parent)


def _mark_ready() -> None:
    READY_PATH.unlink(missing_ok=True)
    temp_path = READY_PATH.with_suffix(".tmp")
    temp_path.write_text("ready\n", encoding="ascii")
    temp_path.replace(READY_PATH)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    READY_PATH.unlink(missing_ok=True)

    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not configured; Docling worker cannot start.")

    logger.info("Prewarming CPU Docling pipelines.")
    prewarm_docling_converters()
    recover_processing_jobs(DOCLING_QUEUE_KEY)
    recover_inflight_jobs(DOCLING_BATCH_JOB_TYPE, DOCLING_QUEUE_KEY)
    _mark_ready()
    logger.info("Docling worker started. Queue=%s", DOCLING_QUEUE_KEY)

    try:
        while not _stop_requested:
            if not redis_is_available():
                time.sleep(2)
                continue
            job = dequeue_generation_job(queue_key=DOCLING_QUEUE_KEY)
            if not job:
                continue
            _run_job(job)
    finally:
        READY_PATH.unlink(missing_ok=True)
    logger.info("Docling worker stopped.")


if __name__ == "__main__":
    main()
