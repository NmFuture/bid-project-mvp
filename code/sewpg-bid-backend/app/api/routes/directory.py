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
        {"id": "task-1", "label": "解析章节线索", "status": step1},
        {"id": "task-2", "label": "调用目录生成 skill", "status": step2},
        {"id": "task-3", "label": "保存目录结果", "status": step3},
    ]


def _handle_directory_progress(project_id: str, stage: str, details: dict[str, Any] | None = None) -> None:
    meta = details or {}
    if stage == "inputs_ready":
        tender_hint_count = int(meta.get("tenderHintCount") or 0)
        template_hint_count = int(meta.get("templateHintCount") or 0)
        store.update_directory_generation_state(
            project_id,
            percentage=30,
            summary=f"已提取章节线索（招标 {tender_hint_count} 条，模板 {template_hint_count} 条），准备调用 futurecode。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message=f"已完成章节线索提取：招标 {tender_hint_count} 条，模板 {template_hint_count} 条。",
            event_step="hint_ready",
        )
        return

    if stage == "calling_opencode":
        session_id = str(meta.get("sessionId") or "")
        provider_id = str(meta.get("providerId") or "")
        model_id = str(meta.get("modelId") or "")
        store.update_directory_generation_state(
            project_id,
            percentage=60,
            summary="正在调用 futurecode 生成目录，请稍候。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message="已进入 futurecode 生成阶段，正在等待模型返回目录结果。",
            event_step="opencode_waiting",
            opencode_output={
                "status": "waiting",
                "sessionId": session_id,
                "providerId": provider_id,
                "modelId": model_id,
                "receivedAt": "",
                "parts": [],
            },
        )
        return

    if stage == "opencode_delta":
        parts = list(meta.get("parts") or [])
        current = store.get_directory_state(project_id)
        previous_parts = list((current.get("opencodeOutput") or {}).get("parts") or [])
        summary: str | None = None
        event_message: str | None = None

        if parts and not previous_parts:
            summary = "futurecode 已开始流式返回目录片段。"
            event_message = "futurecode 已开始返回原始片段。"
        elif len(parts) > len(previous_parts):
            summary = "futurecode 正在流式输出目录内容，请稍候。"

        store.update_directory_generation_state(
            project_id,
            percentage=70 if parts else None,
            summary=summary,
            tasks=_directory_tasks("done", "running", "pending"),
            event_message=event_message,
            event_step="opencode_streaming",
            opencode_output={
                "status": str(meta.get("status") or ("streaming" if parts else "waiting")),
                "sessionId": str(meta.get("sessionId") or ""),
                "providerId": str(meta.get("providerId") or ""),
                "modelId": str(meta.get("modelId") or ""),
                "receivedAt": str(meta.get("receivedAt") or ""),
                "parts": parts,
            },
        )
        return

    if stage == "normalizing_result":
        chapter_count = int(meta.get("chapterCount") or 0)
        store.update_directory_generation_state(
            project_id,
            percentage=85,
            summary=f"futurecode 已返回目录结果，正在整理 {chapter_count} 个章节节点。",
            tasks=_directory_tasks("done", "done", "running"),
            event_message=f"futurecode 已返回结果，正在整理 {chapter_count} 个章节节点。",
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
