from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.bid_generation_flow import _record_generation_audit, _record_generation_audit_sync
from app.services.background_task_cancel import (
    BackgroundTaskCancelled,
    cancel_task_state,
    raise_if_task_cancel_requested,
    request_task_cancel,
)
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.job_queue import enqueue_generation_job, force_release_generation_lock, is_generation_locked, request_job_cancel
from app.services.job_timing import current_locked_job_id
from app.services.local_job_executor import submit_local_job
from app.services.tech_assembly import regenerate_score_index_xref_for_project
from app.services.technical_score_index_state import (
    finish_score_index_state,
    score_index_state,
    start_score_index_state,
    update_score_index_state,
)
from app.services.workspace_project_access import (
    get_workspace_project_runtime_state,
    persist_workspace_project_fields,
    require_workspace_project_for_update,
)

SCORE_INDEX_JOB_TYPE = "score_index_xref"
SCORE_INDEX_STALE_AFTER_SEC = 30 * 60

_NOT_FOUND = lambda _project_id: HTTPException(  # noqa: E731 - 与同层服务的错误工厂写法保持一致
    status_code=404,
    detail="技术标项目不存在。",
)
_WRONG_TYPE = lambda _project_id: HTTPException(  # noqa: E731
    status_code=400,
    detail="该项目不是技术标项目。",
)


def _project_for_update(project_id: str) -> dict[str, Any]:
    return require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=_NOT_FOUND,
        wrong_type_error=_WRONG_TYPE,
    )


def _current_state(project_id: str) -> dict[str, Any]:
    project = get_workspace_project_runtime_state(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=_NOT_FOUND,
        wrong_type_error=_WRONG_TYPE,
    )
    return score_index_state(project)


def _write_state(project_id: str, **kwargs: Any) -> dict[str, Any]:
    project = _project_for_update(project_id)
    payload = update_score_index_state(project, **kwargs)
    persist_workspace_project_fields(project, "score_index_state")
    return payload


def _finish_state(project_id: str, **kwargs: Any) -> dict[str, Any]:
    project = _project_for_update(project_id)
    payload = finish_score_index_state(project, **kwargs)
    persist_workspace_project_fields(project, "score_index_state")
    return payload


def _cancel_state(project_id: str) -> dict[str, Any]:
    project = _project_for_update(project_id)
    payload = cancel_task_state(score_index_state(project), "索引生成已停止。")
    project["score_index_state"] = payload
    persist_workspace_project_fields(project, "score_index_state")
    return payload


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_stale(current: dict[str, Any]) -> bool:
    """长时间没有任何心跳就判定卡死，避免进程被杀后按钮永远禁用。"""
    if current.get("status") != "running":
        return False
    timestamps: list[datetime] = []
    for event in current.get("events") or []:
        if isinstance(event, dict):
            parsed = _parse_iso_datetime(event.get("at"))
            if parsed:
                timestamps.append(parsed)
    progress = current.get("indexProgress") if isinstance(current.get("indexProgress"), dict) else {}
    parsed_progress = _parse_iso_datetime(progress.get("updatedAt"))
    if parsed_progress:
        timestamps.append(parsed_progress)
    parsed_started = _parse_iso_datetime(current.get("startedAt"))
    if parsed_started:
        timestamps.append(parsed_started)
    if not timestamps:
        return False
    return (datetime.now(UTC) - max(timestamps)).total_seconds() > SCORE_INDEX_STALE_AFTER_SEC


def _recover_stale(project_id: str) -> dict[str, Any]:
    force_release_generation_lock(SCORE_INDEX_JOB_TYPE, project_id)
    return _finish_state(
        project_id,
        status="failed",
        summary="章节索引任务长时间无进展，系统已自动收口并释放任务锁，可重新点击重新生成索引。",
        run_duration_sec=0,
        error="score_index_stale",
        event_step="failed",
        event_level="error",
    )


def _index_summary_text(done: int, total: int) -> str:
    return f"已建立章节索引 {done}/{total} 项" if total > 0 else "正在建立章节索引"


def handle_score_index_progress(project_id: str, stage: str, details: dict[str, Any] | None = None) -> None:
    raise_if_task_cancel_requested(_current_state(project_id))
    meta = details or {}

    if stage == "calling_score_index_xref":
        _write_state(
            project_id,
            percentage=5,
            summary="正在定位成稿中的技术评分标准索引表。",
            event_message="开始重新生成章节索引。",
            event_step="score_index_start",
        )
        return

    if stage == "score_index_xref_probed":
        row_count = int(meta.get("rowCount") or 0)
        pending = int(meta.get("pendingRowCount") or 0)
        done = max(0, row_count - pending)
        if not meta.get("tableFound"):
            _write_state(
                project_id,
                percentage=15,
                summary="成稿中未找到技术评分标准索引表。",
                event_message="未找到技术评分标准索引表，本次不改动成稿。",
                event_level="warning",
                event_step="score_index_table_missing",
            )
            return
        _write_state(
            project_id,
            percentage=15,
            summary=f"已定位评分索引表，共 {row_count} 项评审因素待建立索引。",
            index_progress={"done": done, "total": row_count, "phase": "probed"},
            event_message=f"评分索引表体检完成：{row_count} 行，待判断 {pending} 行。",
            event_step="score_index_probed",
        )
        return

    if stage == "score_index_xref_mapping_requested":
        pending = int(meta.get("pendingRowCount") or 0)
        _write_state(
            project_id,
            percentage=25,
            summary=f"正在判断 {pending} 项评审因素应索引的章节，请稍候。",
            event_message=f"已提交章节判断，待判断 {pending} 行。",
            event_step="score_index_mapping",
        )
        return

    if stage in {"score_index_xref_completed", "score_index_xref_skipped"}:
        summary = meta.get("summary") if isinstance(meta.get("summary"), dict) else {}
        row_count = int(summary.get("rowCount") or 0)
        filled = int(summary.get("filledRowCount") or 0)
        _write_state(
            project_id,
            percentage=90,
            summary=_index_summary_text(filled, row_count) + "，正在写回成稿。",
            index_progress={"done": filled, "total": row_count, "phase": "built"},
            event_message=f"章节索引已建立：填写 {filled} 行，链接条目 {int(summary.get('linkedCount') or 0)} 条。",
            event_step="score_index_built",
        )
        return

    if stage == "score_index_xref_failed":
        _write_state(
            project_id,
            percentage=90,
            summary="章节索引生成失败，成稿未被改动。",
            event_message=f"章节索引生成失败：{meta.get('error') or '未知错误'}",
            event_level="error",
            event_step="score_index_failed",
        )
        return


def run_score_index_job(project_id: str, data: dict[str, Any] | None = None, user: dict[str, Any] | None = None) -> None:
    request_data = dict(data or {})
    try:
        raise_if_task_cancel_requested(_current_state(project_id))
        result = regenerate_score_index_xref_for_project(
            project_id,
            progress_callback=lambda stage, details=None: handle_score_index_progress(project_id, stage, details),
        )
    except BackgroundTaskCancelled:
        _cancel_state(project_id)
        _record_generation_audit_sync(
            project_id=project_id,
            action="停止重新生成章节索引",
            status="已停止",
            user=user,
            bid_type=TECHNICAL_BID_TYPE,
            data=request_data,
            diff={"before": {}, "after": {"status": "cancelled"}},
            metadata={},
        )
        return
    except ValueError as exc:
        _finish_state(
            project_id,
            status="failed",
            summary=str(exc),
            run_duration_sec=0,
            error=str(exc),
            event_step="failed",
            event_level="error",
        )
        _record_generation_audit_sync(
            project_id=project_id,
            action="重新生成章节索引失败",
            status="失败",
            user=user,
            bid_type=TECHNICAL_BID_TYPE,
            data=request_data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__},
        )
        return
    except Exception as exc:  # noqa: BLE001 - 失败要显式落到状态里，不能静默吞掉
        message = f"重新生成章节索引异常：{exc}"
        _finish_state(
            project_id,
            status="failed",
            summary=message,
            run_duration_sec=0,
            error=str(exc),
            event_step="failed",
            event_level="error",
        )
        _record_generation_audit_sync(
            project_id=project_id,
            action="重新生成章节索引失败",
            status="失败",
            user=user,
            bid_type=TECHNICAL_BID_TYPE,
            data=request_data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__},
        )
        return

    xref_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    row_count = int(xref_summary.get("rowCount") or 0)
    filled = int(xref_summary.get("filledRowCount") or 0)
    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    applied = bool(result.get("applied"))
    status = result.get("status")

    if status == "failed":
        _finish_state(
            project_id,
            status="failed",
            summary="章节索引生成失败，成稿未被改动。",
            run_duration_sec=int(result.get("runDurationSec") or 0),
            warnings=warnings,
            error=str(result.get("error") or ""),
            event_step="failed",
            event_level="error",
        )
        return

    if not applied:
        # skipped：文档里没有评分索引表。不是失败，但也没改任何东西，如实说明。
        _finish_state(
            project_id,
            status="completed",
            summary="成稿中未找到技术评分标准索引表，本次未改动成稿。",
            run_duration_sec=int(result.get("runDurationSec") or 0),
            output={"applied": False, "rowCount": row_count, "filledRowCount": filled},
            warnings=warnings,
            event_step="skipped",
            event_level="warning",
        )
        return

    page_pending = xref_summary.get("pageNumbersResolved") is False
    _finish_state(
        project_id,
        status="completed",
        summary=f"章节索引已重新生成，{_index_summary_text(filled, row_count)}。",
        run_duration_sec=int(result.get("runDurationSec") or 0),
        output={
            "applied": True,
            "rowCount": row_count,
            "filledRowCount": filled,
            "linkedCount": int(xref_summary.get("linkedCount") or 0),
            "unresolvedCount": int(xref_summary.get("unresolvedCount") or 0),
            "pageNumbersResolved": not page_pending,
        },
        warnings=warnings,
    )
    _record_generation_audit_sync(
        project_id=project_id,
        action="重新生成章节索引",
        user=user,
        bid_type=TECHNICAL_BID_TYPE,
        data=request_data,
        diff={"before": {}, "after": {"filledRowCount": filled, "rowCount": row_count}},
        metadata={"warningCount": len(warnings)},
    )


def _schedule_score_index_job(project_id: str, data: dict[str, Any], user: dict[str, Any] | None = None) -> None:
    enqueue_data = dict(data or {})
    if user:
        enqueue_data["__auditUser"] = {
            "id": str(user.get("id") or ""),
            "name": str(user.get("name") or user.get("email") or ""),
            "email": str(user.get("email") or ""),
        }
    queue_result = enqueue_generation_job(SCORE_INDEX_JOB_TYPE, project_id, enqueue_data)
    if queue_result.queued or queue_result.locked:
        return
    submit_local_job(run_score_index_job, project_id, data, user)


class TechnicalScoreIndexService:
    async def status(self, project_id: str) -> dict[str, Any]:
        current = _current_state(project_id)
        if _is_stale(current):
            current = _recover_stale(project_id)
        return copy.deepcopy(current)

    async def cancel(self, project_id: str) -> dict[str, Any]:
        project = _project_for_update(project_id)
        current = score_index_state(project)
        payload = request_task_cancel(current, "已请求停止索引生成，正在等待安全停止点。")
        project["score_index_state"] = payload
        persist_workspace_project_fields(project, "score_index_state")
        request_job_cancel(current_locked_job_id(SCORE_INDEX_JOB_TYPE, project_id))
        return payload

    async def run(
        self,
        project_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
        user: dict[str, Any] | None = None,
    ) -> JSONResponse:
        current = _current_state(project_id)
        if _is_stale(current):
            current = _recover_stale(project_id)
        if current.get("status") == "running" or is_generation_locked(SCORE_INDEX_JOB_TYPE, project_id):
            return JSONResponse(
                status_code=202,
                content={**current, "message": "章节索引正在生成中，请稍候。"},
            )

        project = _project_for_update(project_id)
        fill_state = project.get("fill_state") if isinstance(project.get("fill_state"), dict) else {}
        if fill_state.get("status") == "running":
            raise HTTPException(status_code=409, detail="正文正在重新生成，请等待完成后再重新生成索引。")

        payload = start_score_index_state(project)
        persist_workspace_project_fields(project, "score_index_state")

        request_data = data or {}
        await _record_generation_audit(
            project_id=project_id,
            action="开始重新生成章节索引",
            user=user,
            bid_type=TECHNICAL_BID_TYPE,
            data=request_data,
            diff={"before": current, "after": {"status": payload.get("status")}},
            metadata={},
            request=request,
        )
        _schedule_score_index_job(project_id, request_data, user)
        return JSONResponse(
            status_code=202,
            content={**payload, "message": "已开始重新生成章节索引，请稍候。"},
        )


technical_score_index_service = TechnicalScoreIndexService()
