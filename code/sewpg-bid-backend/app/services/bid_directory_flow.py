from __future__ import annotations

import asyncio
import copy
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.core.config import settings
from app.services.bid_outline_state import (
    confirm_outline_state,
    directory_state_with_rule_evidence,
    fail_directory_generation_state,
    regenerate_outline_state,
    save_outline_state,
    start_directory_generation_state,
    update_directory_generation_state,
)
from app.services.bid_project_state import project_parse_input_records
from app.services.bid_project_service import BidProjectService
from app.services.job_queue import enqueue_generation_job, is_generation_locked
from app.services.job_timing import current_locked_job_id, record_phase
from app.services.local_job_executor import submit_local_job
from app.services.onlyoffice_documents import build_editor_session_key
from app.services.outline_generation import generate_outline_for_project_with_progress
from app.services.url_utils import absolute_url, onlyoffice_backend_base_url
from app.services.workspace_project_access import (
    get_any_workspace_project_runtime_state,
    persist_workspace_project_state,
    require_any_workspace_project_for_update,
    require_workspace_project_for_update,
)


_OUTLINE_PREVIEW_EXTENSIONS = {".doc", ".docx", ".pdf"}

# 目录生成阶段 → 中文标签（耗时监控 phases 展示用）。
_DIRECTORY_STAGE_LABELS = {
    "inputs_ready": "准备目录输入",
    "outline_session_ready": "建立生成会话",
    "outline_delta": "LLM 生成目录",
    "normalizing_result": "整理保存结果",
    "outline_failed": "生成失败",
    "outline_fallback": "回退本地生成",
}

# 进度锚点按真实耗时占比分配：准备 0-5，判定 5-88（章节 5-78、附表 78-88），保存 88-100。
_DECISION_PHASE_PERCENT_RANGES = {
    "chapters": (5, 78),
    "serial": (5, 78),
    "appendix": (78, 88),
}


def _decision_progress_percentage(phase: str, decided: int, total: int) -> int | None:
    if total <= 0:
        return None
    low, high = _DECISION_PHASE_PERCENT_RANGES.get(phase, (5, 78))
    ratio = max(0.0, min(1.0, decided / total))
    return int(round(low + (high - low) * ratio))


def _directory_tasks(step1: str, step2: str, step3: str) -> list[dict[str, Any]]:
    return [
        {"id": "task-1", "label": "准备目录输入", "status": step1},
        {"id": "task-2", "label": "Opencode 生成目录", "status": step2},
        {"id": "task-3", "label": "保存目录结果", "status": step3},
    ]


def _project_not_found(project_id: str) -> KeyError:
    return KeyError(project_id)


def _any_project(project_id: str) -> dict[str, Any]:
    return get_any_workspace_project_runtime_state(
        project_id,
        not_found_error=_project_not_found,
    )


def _any_project_for_update(project_id: str) -> dict[str, Any]:
    return require_any_workspace_project_for_update(
        project_id,
        not_found_error=_project_not_found,
    )


def _directory_state(project_id: str) -> dict[str, Any]:
    return directory_state_with_rule_evidence(_any_project(project_id))


def _update_directory_state(project_id: str, **kwargs: Any) -> dict[str, Any]:
    project = _any_project_for_update(project_id)
    state = update_directory_generation_state(project, **kwargs)
    persist_workspace_project_state(project)
    return state


def _fail_directory_generation(project_id: str, message: str, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    project = _any_project_for_update(project_id)
    state = fail_directory_generation_state(project, message=message, tasks=tasks)
    persist_workspace_project_state(project)
    return state


def _handle_directory_progress(project_id: str, stage: str, details: dict[str, Any] | None = None) -> None:
    meta = details or {}
    if stage == "decision_progress":
        # 高频计数上报：不写事件、不进耗时埋点，只更新计数与百分比
        phase = str(meta.get("phase") or "chapters")
        decided = max(0, int(meta.get("decided") or 0))
        total = max(0, int(meta.get("total") or 0))
        decision_progress: dict[str, Any] = {"phase": phase, "decided": decided, "total": total}
        if meta.get("chaptersTotal") is not None:
            decision_progress["chaptersDone"] = max(0, int(meta.get("chaptersDone") or 0))
            decision_progress["chaptersTotal"] = max(0, int(meta.get("chaptersTotal") or 0))
        label = "技术附表" if phase == "appendix" else "目录条款"
        summary = (
            f"正在逐项判定{label}，已完成 {decided}/{total} 项。"
            if total > 0
            else f"正在逐项判定{label}。"
        )
        _update_directory_state(
            project_id,
            percentage=_decision_progress_percentage(phase, decided, total),
            summary=summary,
            tasks=_directory_tasks("done", "running", "pending"),
            decision_progress=decision_progress,
        )
        return

    # 耗时埋点：目录 state 无 runId，用项目级任务锁反查当前 directory_generation job_id。
    record_phase(
        current_locked_job_id("directory_generation", project_id),
        stage,
        _DIRECTORY_STAGE_LABELS.get(stage, stage),
    )
    if stage == "inputs_ready":
        tender_file_count = int(meta.get("tenderFileCount") or 0)
        template_file_count = int(meta.get("templateFileCount") or 0)
        _update_directory_state(
            project_id,
            percentage=5,
            summary=f"已准备目录生成输入（招标文件 {tender_file_count} 个，投标模板 {template_file_count} 个），准备调用 futurecode。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message=f"已完成目录输入准备：招标文件 {tender_file_count} 个，投标模板 {template_file_count} 个。",
            event_step="hint_ready",
        )
        return

    if stage == "outline_session_ready":
        _update_directory_state(
            project_id,
            percentage=8,
            summary="futurecode session 已建立，正在运行 S2 目录生成 Skill。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message="futurecode session 已建立，正在等待目录语义审核结果。",
            event_step="futurecode_session",
            opencode_output={
                "status": "waiting",
                "sessionId": str(meta.get("sessionId") or ""),
                "providerId": str(meta.get("providerId") or ""),
                "modelId": str(meta.get("modelId") or ""),
            },
        )
        return

    if stage == "outline_delta":
        previous_parts = list((_directory_state(project_id).get("opencodeOutput") or {}).get("parts") or [])
        meta = {key: value for key, value in meta.items() if key != "suppressPercentage"}
        parts = list(meta.get("parts") or [])
        first_delta = bool(parts) and not previous_parts
        # 技术标并行章节路径由 decision_progress 驱动百分比；未标记的路径（商务标/串行）沿用流式锚点
        suppress_percentage = bool((details or {}).get("suppressPercentage"))
        _update_directory_state(
            project_id,
            percentage=None if suppress_percentage else (65 if first_delta else 70),
            summary=None if suppress_percentage else "futurecode 正在执行目录生成和语义审核，请稍候。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message="futurecode 已返回 S2 流式片段。" if first_delta else None,
            event_step="futurecode_delta",
            opencode_output=meta,
        )
        return

    if stage == "outline_fallback":
        _update_directory_state(
            project_id,
            percentage=60,
            summary="futurecode 调用暂不可用，正在使用同一 S2 Skill 脚本生成目录。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message=f"futurecode 调用失败，已切换到本地 Skill 脚本：{meta.get('error') or ''}",
            event_level="error",
            event_step="futurecode_fallback",
        )
        return

    if stage == "outline_failed":
        _update_directory_state(
            project_id,
            percentage=60,
            summary="futurecode/opencode 目录生成失败，技术标目录生成不会回退到本地脚本决策。",
            tasks=_directory_tasks("done", "failed", "pending"),
            event_message=f"futurecode/opencode 目录生成失败：{meta.get('error') or ''}",
            event_level="error",
            event_step="futurecode_failed",
        )
        return

    if stage == "normalizing_result":
        chapter_count = int(meta.get("chapterCount") or 0)
        _update_directory_state(
            project_id,
            percentage=90,
            summary=f"futurecode 已生成目录结果，正在整理 {chapter_count} 个一级章节。",
            tasks=_directory_tasks("done", "done", "running"),
            event_message=f"futurecode 已返回目录结果，正在整理 {chapter_count} 个一级章节。",
            event_step="normalizing",
        )


def _run_directory_generation_job(project_id: str, data: dict[str, Any]) -> None:
    try:
        generate_outline_for_project_with_progress(
            project_id,
            data,
            progress_callback=lambda stage, details=None: _handle_directory_progress(project_id, stage, details),
        )
    except ValueError as exc:
        _fail_directory_generation(
            project_id,
            str(exc),
            tasks=_directory_tasks("failed", "pending", "pending"),
        )
    except RuntimeError as exc:
        _fail_directory_generation(
            project_id,
            str(exc),
            tasks=_directory_tasks("done", "failed", "pending"),
        )
    except Exception as exc:  # pragma: no cover
        _fail_directory_generation(
            project_id,
            f"目录生成异常：{exc}",
            tasks=_directory_tasks("done", "failed", "pending"),
        )


def _schedule_directory_generation_job(project_id: str, data: dict[str, Any]) -> None:
    queue_result = enqueue_generation_job("directory_generation", project_id, data)
    if queue_result.queued or queue_result.locked:
        return

    submit_local_job(_run_directory_generation_job, project_id, data)


def _add_callback_token(url: str) -> str:
    token = settings.onlyoffice_callback_token
    if not token:
        return url
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("oo_callback_token", token))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _document_type_by_suffix(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        return "pdf", "pdf"
    if suffix in {"xlsx", "xls"}:
        return suffix, "cell"
    if suffix in {"pptx", "ppt"}:
        return suffix, "slide"
    return suffix or "docx", "word"


def _resolve_outline_tender_file(file_records: list[dict[str, Any]], file_id: str) -> tuple[dict[str, Any], Path]:
    for item in file_records:
        if str(item.get("id") or "") != file_id:
            continue
        path = Path(str(item.get("path") or ""))
        if not path.exists():
            raise HTTPException(status_code=404, detail="招标文件不存在或已被删除。")
        return item, path
    raise HTTPException(status_code=404, detail="未找到对应的招标文件。")


def _build_tender_preview(
    project_id: str,
    request: Request,
    *,
    api_prefix: str,
    file_records: list[dict[str, Any]],
    file_id_hint: str = "",
) -> dict[str, Any]:
    source_files = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
        }
        for item in file_records
    ]

    if not source_files:
        return {
            "status": "empty",
            "message": "暂无招标文件可预览，请先在“审核”模块上传并解析。",
            "sourceFiles": [],
            "onlyoffice": None,
        }

    candidate = None
    candidate_path = None
    ordered_records = list(file_records)
    if file_id_hint:
        ordered_records = sorted(
            ordered_records,
            key=lambda item: 0 if str(item.get("id") or "") == file_id_hint else 1,
        )

    for item in ordered_records:
        path = Path(str(item.get("path") or ""))
        suffix = path.suffix.lower()
        if suffix not in _OUTLINE_PREVIEW_EXTENSIONS:
            continue
        if not path.exists():
            continue
        candidate = item
        candidate_path = path
        break

    if not candidate or not candidate_path:
        return {
            "status": "unsupported",
            "message": "当前招标文件类型暂不支持 OnlyOffice 预览（支持 .doc/.docx/.pdf）。",
            "sourceFiles": source_files,
            "onlyoffice": None,
        }

    file_id = str(candidate.get("id") or "")
    file_name = str(candidate.get("name") or candidate_path.name)
    file_type, document_type = _document_type_by_suffix(candidate_path)
    quoted_name = quote(file_name)

    browser_file_url = absolute_url(
        request,
        f"{api_prefix}/{project_id}/outline/tender-files/{file_id}/file/{quoted_name}",
    )
    browser_callback_url = _add_callback_token(
        absolute_url(request, f"{api_prefix}/{project_id}/outline/tender-files/callback"),
    )

    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = (
        f"{onlyoffice_base}{api_prefix}/{project_id}/outline/tender-files/{file_id}/file/{quoted_name}"
    )
    onlyoffice_callback_url = _add_callback_token(
        f"{onlyoffice_base}{api_prefix}/{project_id}/outline/tender-files/callback",
    )

    return {
        "status": "ready",
        "message": "",
        "sourceFiles": source_files,
        "activeFile": {
            "id": file_id,
            "name": file_name,
            "fileType": file_type,
            "documentType": document_type,
        },
        "onlyoffice": {
            "documentKey": build_editor_session_key(candidate_path),
            "title": file_name,
            "fileType": file_type,
            "documentType": document_type,
            "fileUrl": onlyoffice_file_url,
            "callbackUrl": onlyoffice_callback_url,
            "browserFileUrl": browser_file_url,
            "browserCallbackUrl": browser_callback_url,
            "user": {
                "id": "user-1",
                "name": "当前用户",
            },
        },
    }


class BidDirectoryService:
    def __init__(self, project_service: BidProjectService, api_prefix: str) -> None:
        self.project_service = project_service
        self.api_prefix = api_prefix.rstrip("/")

    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return self.project_service.ensure_project(project_id)

    def require_project_for_update(self, project_id: str) -> dict[str, Any]:
        return require_workspace_project_for_update(
            project_id,
            bid_type=self.project_service.bid_type,
            not_found_error=lambda _project_id: HTTPException(
                status_code=404,
                detail=self.project_service.not_found_message,
            ),
            wrong_type_error=lambda _project_id: HTTPException(
                status_code=400,
                detail=self.project_service.wrong_type_message,
            ),
        )

    def parse_inputs(
        self,
        project_id: str,
        *,
        include_fallback: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        project = self.ensure_project(project_id)
        return project_parse_input_records(project_id, project, include_fallback=include_fallback)

    def directory_state(self, project_id: str) -> dict[str, Any]:
        return directory_state_with_rule_evidence(self.ensure_project(project_id))

    def outline_state(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.ensure_project(project_id)["outline_state"])

    def start_directory_generation(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = start_directory_generation_state(project)
        persist_workspace_project_state(project)
        return payload

    async def generation_status(self, project_id: str) -> dict[str, Any]:
        return self.directory_state(project_id)

    async def generation_stream(self, project_id: str, request: Request) -> StreamingResponse:
        self.directory_state(project_id)

        async def event_stream():
            last_payload: str | None = None
            last_keepalive_at = time.monotonic()

            while True:
                if await request.is_disconnected():
                    break

                payload = self.directory_state(project_id)
                serialized = json.dumps(payload, ensure_ascii=False)
                if serialized != last_payload:
                    yield f"data: {serialized}\n\n"
                    last_payload = serialized
                    last_keepalive_at = time.monotonic()
                    if payload.get("status") in {"completed", "failed"}:
                        break
                elif time.monotonic() - last_keepalive_at >= 15:
                    yield ": keepalive\n\n"
                    last_keepalive_at = time.monotonic()

                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def run_generation(self, project_id: str, data: dict[str, Any] | None = None) -> JSONResponse:
        current = self.directory_state(project_id)
        if current.get("status") == "running" or is_generation_locked("directory_generation", project_id):
            return JSONResponse(
                status_code=202,
                content={**current, "message": "目录生成任务正在执行中，请稍候。"},
            )

        try:
            payload = self.start_directory_generation(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        _schedule_directory_generation_job(project_id, data or {})
        return JSONResponse(
            status_code=202,
            content={**payload, "message": "已开始生成目录，请稍候。"},
        )

    async def outline(self, project_id: str, request: Request, *, file_id: str = "") -> dict[str, Any]:
        file_records, _ = self.parse_inputs(project_id)
        payload = self.outline_state(project_id)
        payload["tenderPreview"] = _build_tender_preview(
            project_id,
            request,
            api_prefix=self.api_prefix,
            file_records=file_records,
            file_id_hint=file_id,
        )
        return payload

    async def save_outline(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = save_outline_state(project, (data or {}).get("nodes") or [])
        persist_workspace_project_state(project)
        return {**payload, "message": "目录已保存"}

    async def regenerate_outline(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = regenerate_outline_state(project)
        persist_workspace_project_state(project)
        return {**payload, "message": "已重生成目录审核稿"}

    async def confirm_outline(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = confirm_outline_state(project)
        persist_workspace_project_state(project)
        return payload

    async def tender_file(self, project_id: str, file_id: str, filename: str = "") -> FileResponse:
        file_records, _ = self.parse_inputs(project_id)
        record, path = _resolve_outline_tender_file(file_records, file_id)
        _ = filename
        return FileResponse(
            path=path,
            filename=str(record.get("name") or path.name),
        )

    async def tender_callback(
        self,
        project_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> JSONResponse:
        self.ensure_project(project_id)
        _ = data
        _validate_callback_token(request)
        return JSONResponse({"error": 0})


def _validate_callback_token(request: Request) -> None:
    expected = settings.onlyoffice_callback_token
    if not expected:
        return
    provided = request.query_params.get("oo_callback_token") or request.headers.get("x-onlyoffice-callback-token")
    if provided != expected:
        raise HTTPException(status_code=403, detail="OnlyOffice callback token invalid.")
