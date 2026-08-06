from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Any

from app.core.config import settings
from app.core.redis import redis_is_available
from app.services.job_queue import (
    QUEUE_KEY,
    claim_s1_workflow_lock,
    clear_job_inflight,
    dequeue_generation_job,
    mark_job_inflight,
    mark_job_progress,
    mark_job_status,
    reclaim_stale_inflight_jobs,
    recover_inflight_jobs,
    recover_processing_jobs,
    release_s1_workflow_lock,
    release_generation_lock,
    requeue_processing_job,
    renew_generation_lock,
)
from app.services.job_timing import run_job_timing_writer
from app.services.job_timing_events import track_job_timing
from app.services.workspace_project_access import get_any_workspace_project_runtime_state

logger = logging.getLogger(__name__)
_stop_requested = False

# 周期回收残留 in-flight job：不能只在启动时做一次，否则本 worker 存活期间
# 其他 worker 崩溃留下的任务会一直卡在 running。
RECLAIM_INTERVAL_SEC = 300


def _material_cleaning_final_state(result: dict[str, Any]) -> dict[str, str]:
    clean_status = str(result.get("cleanStatus") or "")
    status = "failed" if clean_status == "failed" else "cancelled" if clean_status == "stale" else "success"
    return {"status": status, "summary": str(result.get("cleanMessage") or "")}


def _request_stop(signum: int, _: Any) -> None:
    global _stop_requested
    logger.info("Received signal %s, stopping worker after current job.", signum)
    _stop_requested = True


def _runtime_state(project_id: str) -> dict[str, Any]:
    return get_any_workspace_project_runtime_state(project_id, not_found_error=KeyError)


def _workflow_parent_job(job: dict[str, Any]) -> dict[str, Any] | None:
    parent_job_id = str(job.get("parentJobId") or "")
    if not parent_job_id:
        return None
    return {
        "id": parent_job_id,
        "type": "s1_parse",
        "projectId": str(job.get("projectId") or ""),
    }


def _s1_parse_service(data: dict[str, Any]) -> Any:
    from app.services.bid_parse_service import business_parse_service, technical_parse_service
    from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type

    return business_parse_service if require_bid_type(data.get("__bidType")) == BUSINESS_BID_TYPE else technical_parse_service


def _terminal_parse_progress(service: Any, project_id: str, run_id: str) -> dict[str, Any] | None:
    progress = service.parse_progress(project_id)
    if str(progress.get("runId") or "") != run_id:
        return None
    return progress if str(progress.get("status") or "").lower() in {"completed", "failed", "cancelled"} else None


def _finish_expired_s1_job(
    job: dict[str, Any],
    data: dict[str, Any],
    workflow_parent: dict[str, Any] | None,
) -> bool:
    if str(job.get("type") or "") not in {"s1_parse", "s1_parse_continue"}:
        return False
    project_id = str(job.get("projectId") or "")
    run_id = str((workflow_parent or job).get("id") or "")
    service = _s1_parse_service(data)
    if not service.is_current_parse_run(project_id, run_id):
        return False

    progress = _terminal_parse_progress(service, project_id, run_id)
    if progress is None:
        message = str(data.get("__doclingError") or "解析任务在服务停机期间超时，请重新发起解析。")
        service.update_parse_progress(
            project_id,
            status="failed",
            percentage=100,
            summary=message,
            event_step="failed",
            event_level="error",
            event_message=message,
            phase_key="failed",
            phase_label="解析失败",
            phase_percent=100,
        )
        final_status = "failed"
        final_message = message
    else:
        parse_status = str(progress.get("status") or "").lower()
        final_status = "succeeded" if parse_status == "completed" else parse_status
        final_message = str(progress.get("summary") or "")

    mark_job_status(job, final_status, final_message)
    if workflow_parent:
        mark_job_status(workflow_parent, final_status, final_message)
    return True


# 耗时监控：仅对跟踪的任务类型在终态时汇总写 job_timings，中间态（等待/重试）跳过。
@track_job_timing(tracked_types={"s1_parse", "s1_parse_continue", "directory_generation"})
def _run_job(job: dict[str, Any]) -> bool:
    job_type = str(job.get("type") or "")
    project_id = str(job.get("projectId") or "")
    data = job.get("data") if isinstance(job.get("data"), dict) else {}
    user = job.get("user") if isinstance(job.get("user"), dict) else None
    final_state: dict[str, Any] = {}
    workflow_parent = _workflow_parent_job(job)
    lock_job = workflow_parent or job
    deferred = False
    workflow_terminal = False

    mark_job_status(job, "running")
    mark_job_inflight(job)
    lock_renewed = renew_generation_lock(lock_job)
    if lock_renewed is None:
        raise RuntimeError("Redis 暂不可用，无法确认任务锁。")
    if not lock_renewed:
        if not _finish_expired_s1_job(job, data, workflow_parent):
            mark_job_status(job, "cancelled", "任务锁已失效或已被新任务替代。")
        clear_job_inflight(job)
        release_s1_workflow_lock(lock_job)
        return True

    if job_type == "s1_parse":
        workflow_lock = claim_s1_workflow_lock(lock_job)
        if workflow_lock is None:
            raise RuntimeError("Redis 暂不可用，无法确认 S1 全局工作流锁。")
        if not workflow_lock:
            renew_generation_lock(lock_job, settings.redis_job_queue_lock_ttl_sec)
            requeued = requeue_processing_job(job, "等待当前 S1 解析工作流完成。")
            if requeued is None:
                raise RuntimeError("Redis 暂不可用，无法将等待中的 S1 任务放回队列。")
            if not requeued:
                raise RuntimeError("等待中的 S1 任务未能安全放回队列。")
            return False
    elif workflow_parent:
        workflow_lock = claim_s1_workflow_lock(workflow_parent)
        if workflow_lock is None:
            raise RuntimeError("Redis 暂不可用，无法确认 S1 全局工作流锁。")
        if not workflow_lock:
            if not _finish_expired_s1_job(job, data, workflow_parent):
                mark_job_status(job, "cancelled", "S1 全局工作流锁已失效。")
            clear_job_inflight(job)
            release_generation_lock(workflow_parent)
            release_s1_workflow_lock(workflow_parent)
            return True
    heartbeat_stop = threading.Event()

    def renew_lock_until_done() -> None:
        interval = max(1, settings.redis_job_lock_ttl_sec // 3)
        while not heartbeat_stop.wait(interval):
            renew_generation_lock(lock_job)
            if str(lock_job.get("type") or "") == "s1_parse":
                claim_s1_workflow_lock(lock_job)

    heartbeat = threading.Thread(
        target=renew_lock_until_done,
        daemon=True,
        name=f"job-lock-{job.get('id', '')}",
    )
    heartbeat.start()
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
            from app.services.material_wiki_auto import on_material_cleaning_job_finished

            result = clean_material_file_sync(str(data.get("fileId") or project_id), data)
            final_state = _material_cleaning_final_state(result)
            try:
                # 素材流水线自动衔接：本任务是清洗队列最后一个时，触发 Wiki 增量构建。
                on_material_cleaning_job_finished(current_job_id=str(job.get("id") or ""))
            except Exception as auto_exc:
                logger.warning("素材流水线自动衔接失败（清洗钩子）：%s", auto_exc)
        elif job_type == "material_deep_parse":
            from app.services.material_deep_parse import deep_parse_material_file_sync
            from app.services.material_wiki_auto import on_material_deep_parse_job_finished

            result = deep_parse_material_file_sync(project_id, data)
            final_state = {
                "status": "failed" if result.get("deepParseStatus") == "failed" else "success",
                "summary": result.get("deepParseMessage") or "",
            }
            try:
                # 素材流水线自动衔接：解析产物就绪后补跑 Wiki，把兜底卡片升级为正式预览。
                on_material_deep_parse_job_finished(
                    str(data.get("fileId") or project_id),
                    current_job_id=str(job.get("id") or ""),
                )
            except Exception as auto_exc:
                logger.warning("素材流水线自动衔接失败（深度解析钩子）：%s", auto_exc)
        elif job_type == "material_wiki_generation":
            from app.services.material_wiki_auto import on_material_wiki_job_finished
            from app.services.material_wiki_jobs import execute_material_wiki_generation

            final_state = execute_material_wiki_generation(
                data,
                progress_callback=lambda progress: mark_job_progress(job, progress),
            )
            try:
                # 素材流水线自动衔接：消费补跑标记，收录 Wiki 运行期间到达的新批次。
                on_material_wiki_job_finished()
            except Exception as auto_exc:
                logger.warning("素材流水线自动衔接失败（Wiki 钩子）：%s", auto_exc)
        elif job_type == "s1_parse":
            from app.services.bid_parse_service import business_parse_service, technical_parse_service
            from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type
            from app.services.docling_jobs import enqueue_docling_batch

            run_id = str(job.get("id") or "")
            bid_type = require_bid_type(data.get("__bidType"))
            service = business_parse_service if bid_type == BUSINESS_BID_TYPE else technical_parse_service
            if not service.is_current_parse_run(project_id, run_id):
                final_state = {"status": "cancelled", "summary": "解析任务已被更新任务替代。"}
                workflow_terminal = True
            else:
                prepared_data = dict(data)
                prepared_data["__runId"] = run_id
                service.update_parse_progress(
                    project_id,
                    status="running",
                    percentage=10,
                    summary="Docling 任务已进入专用解析队列。",
                    event_step="docling_queued",
                    event_message="PDF 已提交至 Docling Worker。",
                    phase_key="docling_queue",
                    phase_label="等待 PDF 解析",
                    phase_percent=0,
                    stale_after_seconds=settings.redis_job_queue_lock_ttl_sec,
                )
                mark_job_status(job, "waiting_docling")
                enqueue_result = enqueue_docling_batch(project_id, prepared_data, run_id)
                if not enqueue_result.accepted:
                    service.update_parse_progress(
                        project_id,
                        status="failed",
                        percentage=100,
                        summary="Docling 专用队列暂不可用。",
                        event_step="failed",
                        event_level="error",
                        event_message="Docling 专用队列暂不可用。",
                        phase_key="failed",
                        phase_label="解析失败",
                        phase_percent=100,
                    )
                    raise RuntimeError("Docling 专用队列暂不可用")
                renew_generation_lock(lock_job, settings.redis_job_queue_lock_ttl_sec)
                claim_s1_workflow_lock(lock_job, settings.redis_job_queue_lock_ttl_sec)
                deferred = True
                final_state = {"status": "waiting_docling", "summary": "等待 Docling Worker。"}
        elif job_type == "s1_parse_continue":
            from app.services.bid_parse_service import _run_s1_parse_job

            workflow_terminal = True
            service = _s1_parse_service(data)
            terminal_progress = _terminal_parse_progress(service, project_id, str(workflow_parent["id"]))
            if terminal_progress is not None:
                final_state = {
                    "status": str(terminal_progress.get("status") or ""),
                    "summary": str(terminal_progress.get("summary") or ""),
                }
            else:
                docling_error = str(data.get("__doclingError") or "")
                if docling_error:
                    service.update_parse_progress(
                        project_id,
                        status="failed",
                        percentage=100,
                        summary=f"Docling 解析失败：{docling_error}",
                        event_step="failed",
                        event_level="error",
                        event_message=f"Docling 解析失败：{docling_error}",
                        phase_key="failed",
                        phase_label="解析失败",
                        phase_percent=100,
                    )
                    raise RuntimeError(docling_error)
                _run_s1_parse_job(project_id, data)
                project_state = _runtime_state(project_id)
                parse_progress = (
                    project_state.get("parse_progress") if isinstance(project_state.get("parse_progress"), dict) else {}
                )
                final_state = {
                    "status": str(parse_progress.get("status") or ""),
                    "summary": str(parse_progress.get("summary") or ""),
                }
        else:
            raise RuntimeError(f"Unknown job type: {job_type}")
    except Exception as exc:  # pragma: no cover - route job functions handle expected failures
        logger.exception("Background job failed: %s", job)
        mark_job_status(job, "failed", str(exc))
        if workflow_parent:
            mark_job_status(workflow_parent, "failed", str(exc))
            workflow_terminal = True
        raise
    else:
        final_status = str(final_state.get("status") or "")
        if not deferred:
            if final_status == "failed":
                mark_job_status(job, "failed", str(final_state.get("summary") or "Job failed"))
            elif final_status == "cancelled":
                mark_job_status(job, "cancelled", str(final_state.get("summary") or "任务已取消。"))
            else:
                mark_job_status(job, "succeeded", str(final_state.get("summary") or ""))
        if workflow_parent and workflow_terminal:
            if final_status == "failed":
                mark_job_status(workflow_parent, "failed", str(final_state.get("summary") or "Job failed"))
            elif final_status == "cancelled":
                mark_job_status(workflow_parent, "cancelled", str(final_state.get("summary") or "任务已取消。"))
            else:
                mark_job_status(workflow_parent, "succeeded")
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=1)
        clear_job_inflight(job)
        if workflow_parent:
            if workflow_terminal:
                release_generation_lock(workflow_parent)
                release_s1_workflow_lock(workflow_parent)
        elif not deferred:
            release_generation_lock(job)
            if job_type == "s1_parse":
                release_s1_workflow_lock(job)
    return True


def run_worker(queue_key: str = QUEUE_KEY, *, worker_name: str = "Redis") -> None:
    global _stop_requested
    _stop_requested = False
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    if not settings.redis_url:
        logger.error("REDIS_URL is not configured; worker cannot start.")
        return

    logger.info(
        "%s worker started. Queue=%s polling timeout=%ss",
        worker_name,
        queue_key,
        settings.redis_worker_poll_timeout_sec,
    )
    timing_stop: threading.Event | None = None
    timing_writer: threading.Thread | None = None
    if queue_key == QUEUE_KEY:
        timing_stop = threading.Event()
        timing_writer = threading.Thread(
            target=run_job_timing_writer,
            args=(timing_stop,),
            daemon=True,
            name="job-timing-redis-writer",
        )
        timing_writer.start()
    next_reclaim_at = 0.0
    recovery_done = False
    try:
        while not _stop_requested:
            if not redis_is_available():
                time.sleep(2)
                continue

            if not recovery_done:
                recover_processing_jobs(queue_key)
                if queue_key == QUEUE_KEY:
                    # 兼容升级前已登记、但尚未使用 processing 列表的 continuation。
                    recover_inflight_jobs("s1_parse_continue", QUEUE_KEY)
                recovery_done = True

            if time.monotonic() >= next_reclaim_at:
                reclaim_stale_inflight_jobs(settings.redis_job_lock_ttl_sec, queue_key)
                next_reclaim_at = time.monotonic() + RECLAIM_INTERVAL_SEC

            job = dequeue_generation_job(queue_key=queue_key)
            if not job:
                continue

            try:
                completed_or_deferred = _run_job(job)
                if not completed_or_deferred:
                    time.sleep(1)
            except Exception:
                recovery_done = False
                continue
    finally:
        if timing_stop is not None and timing_writer is not None:
            timing_stop.set()
            timing_writer.join(
                timeout=max(
                    2,
                    settings.job_timing_db_connect_timeout_sec
                    + settings.job_timing_db_statement_timeout_ms / 1000
                    + settings.job_timing_db_lock_timeout_ms / 1000
                    + 1,
                )
            )

    logger.info("%s worker stopped.", worker_name)


def main() -> None:
    run_worker()


if __name__ == "__main__":
    main()
