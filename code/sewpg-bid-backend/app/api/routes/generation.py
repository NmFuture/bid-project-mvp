from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from app.services.draft_generation import generate_draft_for_project_with_progress
from app.services.store import store

router = APIRouter()


def _fill_tasks(step1: str, step2: str, step3: str) -> list[dict[str, Any]]:
    return [
        {"id": "task-1", "label": "准备解析文本与目录", "status": step1},
        {"id": "task-2", "label": "调用初稿生成 skill", "status": step2},
        {"id": "task-3", "label": "写入 Word 初稿", "status": step3},
    ]


def _handle_fill_progress(project_id: str, stage: str, details: dict[str, Any] | None = None) -> None:
    meta = details or {}
    if stage == "inputs_ready":
        section_count = int(meta.get("sectionCount") or 0)
        template_hint_count = int(meta.get("templateHintCount") or 0)
        store.update_fill_generation_state(
            project_id,
            percentage=30,
            summary=f"已整理初稿输入（一级章节 {section_count} 个，模板线索 {template_hint_count} 条），准备调用 futurecode。",
            tasks=_fill_tasks("done", "running", "pending"),
            event_message=f"已完成输入准备：一级章节 {section_count} 个，模板线索 {template_hint_count} 条。",
            event_step="inputs_ready",
        )
        return

    if stage == "calling_opencode":
        session_id = str(meta.get("sessionId") or "")
        provider_id = str(meta.get("providerId") or "")
        model_id = str(meta.get("modelId") or "")
        store.update_fill_generation_state(
            project_id,
            percentage=60,
            summary="正在调用 futurecode 生成初稿，请稍候。",
            tasks=_fill_tasks("done", "running", "pending"),
            event_message="已进入 futurecode 初稿生成阶段，正在等待模型返回章节内容。",
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

    if stage == "assembling_result":
        section_count = int(meta.get("sectionCount") or 0)
        store.update_fill_generation_state(
            project_id,
            percentage=85,
            summary=f"futurecode 已返回章节内容，正在写入 {section_count} 个一级章节到 Word 初稿。",
            tasks=_fill_tasks("done", "done", "running"),
            event_message=f"futurecode 已返回章节内容，正在写入 {section_count} 个一级章节到 Word 初稿。",
            event_step="assembling",
        )


def _run_fill_generation_job(project_id: str, data: dict[str, Any]) -> None:
    try:
        generate_draft_for_project_with_progress(
            project_id,
            data,
            progress_callback=lambda stage, details=None: _handle_fill_progress(project_id, stage, details),
        )
    except ValueError as exc:
        store.fail_fill_generation(
            project_id,
            str(exc),
            tasks=_fill_tasks("failed", "pending", "pending"),
        )
    except RuntimeError as exc:
        current = store.get_fill_state(project_id)
        tasks = _fill_tasks("done", "failed", "pending")
        if int(current.get("percentage") or 0) >= 85:
            tasks = _fill_tasks("done", "done", "failed")
        store.fail_fill_generation(project_id, str(exc), tasks=tasks)
    except Exception as exc:  # pragma: no cover
        current = store.get_fill_state(project_id)
        tasks = _fill_tasks("done", "failed", "pending")
        if int(current.get("percentage") or 0) >= 85:
            tasks = _fill_tasks("done", "done", "failed")
        store.fail_fill_generation(project_id, f"初稿生成异常：{exc}", tasks=tasks)


def _schedule_fill_generation_job(project_id: str, data: dict[str, Any]) -> None:
    worker = threading.Thread(
        target=_run_fill_generation_job,
        args=(project_id, data),
        daemon=True,
        name=f"fill-generation-{project_id}",
    )
    worker.start()


@router.get("/api/projects/{project_id}/fill-generation")
async def get_fill_generation(project_id: str) -> dict[str, Any]:
    return store.get_fill_state(project_id)


@router.post("/api/projects/{project_id}/fill-generation/run")
async def run_fill_generation(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    current = store.get_fill_state(project_id)
    if current.get("status") == "running":
        return JSONResponse(
            status_code=202,
            content={**current, "message": "初稿生成任务正在执行中，请稍候。"},
        )

    try:
        payload = store.start_fill_generation(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _schedule_fill_generation_job(project_id, data)
    return JSONResponse(
        status_code=202,
        content={**payload, "message": "已开始生成初稿，请稍候。"},
    )
