from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.services.job_queue import enqueue_generation_job, is_generation_locked
from app.services.outline_generation import generate_outline_for_project_with_progress
from app.services.store import store

router = APIRouter()


def _directory_tasks(step1: str, step2: str, step3: str) -> list[dict[str, Any]]:
    return [
        {"id": "task-1", "label": "准备目录候选", "status": step1},
        {"id": "task-2", "label": "futurecode 语义审核", "status": step2},
        {"id": "task-3", "label": "保存审核目录", "status": step3},
    ]


def _handle_directory_progress(project_id: str, stage: str, details: dict[str, Any] | None = None) -> None:
    meta = details or {}
    if stage == "inputs_ready":
        tender_file_count = int(meta.get("tenderFileCount") or 0)
        template_file_count = int(meta.get("templateFileCount") or 0)
        store.update_directory_generation_state(
            project_id,
            percentage=30,
            summary=f"已准备目录生成输入（招标文件 {tender_file_count} 个，投标模板 {template_file_count} 个），准备调用 futurecode。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message=f"已完成目录输入准备：招标文件 {tender_file_count} 个，投标模板 {template_file_count} 个。",
            event_step="hint_ready",
        )
        return

    if stage == "outline_session_ready":
        store.update_directory_generation_state(
            project_id,
            percentage=45,
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
        previous_parts = list((store.get_directory_state(project_id).get("opencodeOutput") or {}).get("parts") or [])
        parts = list(meta.get("parts") or [])
        first_delta = bool(parts) and not previous_parts
        store.update_directory_generation_state(
            project_id,
            percentage=65 if first_delta else 70,
            summary="futurecode 正在执行目录生成和语义审核，请稍候。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message="futurecode 已返回 S2 流式片段。" if first_delta else None,
            event_step="futurecode_delta",
            opencode_output=meta,
        )
        return

    if stage == "outline_fallback":
        store.update_directory_generation_state(
            project_id,
            percentage=60,
            summary="futurecode 调用暂不可用，正在使用同一 S2 Skill 脚本生成目录。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message=f"futurecode 调用失败，已切换到本地 Skill 脚本：{meta.get('error') or ''}",
            event_level="error",
            event_step="futurecode_fallback",
        )
        return

    if stage == "normalizing_result":
        chapter_count = int(meta.get("chapterCount") or 0)
        store.update_directory_generation_state(
            project_id,
            percentage=85,
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
        store.fail_directory_generation(
            project_id,
            str(exc),
            tasks=_directory_tasks("failed", "pending", "pending"),
        )
    except RuntimeError as exc:
        store.fail_directory_generation(
            project_id,
            str(exc),
            tasks=_directory_tasks("done", "failed", "pending"),
        )
    except Exception as exc:  # pragma: no cover
        store.fail_directory_generation(
            project_id,
            f"目录生成异常：{exc}",
            tasks=_directory_tasks("done", "failed", "pending"),
        )


def _schedule_directory_generation_job(project_id: str, data: dict[str, Any]) -> None:
    queue_result = enqueue_generation_job("directory_generation", project_id, data)
    if queue_result.queued or queue_result.locked:
        return

    worker = threading.Thread(
        target=_run_directory_generation_job,
        args=(project_id, data),
        daemon=True,
        name=f"directory-generation-{project_id}",
    )
    worker.start()


@router.get("/api/projects/{project_id}/directory-generation")
async def get_directory_generation(project_id: str) -> dict[str, Any]:
    return store.get_directory_state(project_id)


@router.get("/api/projects/{project_id}/directory-generation/stream")
async def stream_directory_generation(project_id: str, request: Request) -> StreamingResponse:
    store.get_directory_state(project_id)

    async def event_stream():
        last_payload: str | None = None
        last_keepalive_at = time.monotonic()

        while True:
            if await request.is_disconnected():
                break

            payload = store.get_directory_state(project_id)
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


@router.post("/api/projects/{project_id}/directory-generation/run")
async def run_directory_generation(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    current = store.get_directory_state(project_id)
    if current.get("status") == "running" or is_generation_locked("directory_generation", project_id):
        return JSONResponse(
            status_code=202,
            content={**current, "message": "目录生成任务正在执行中，请稍候。"},
        )

    try:
        payload = store.start_directory_generation(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _schedule_directory_generation_job(project_id, data)
    return JSONResponse(
        status_code=202,
        content={**payload, "message": "已开始生成目录，请稍候。"},
    )
