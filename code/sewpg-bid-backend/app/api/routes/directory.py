from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

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
            summary=f"已提取章节线索（招标 {tender_hint_count} 条，模板 {template_hint_count} 条），准备调用 opencode。",
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
            summary="正在调用 opencode 生成目录，请稍候。",
            tasks=_directory_tasks("done", "running", "pending"),
            event_message="已进入 opencode 生成阶段，正在等待模型返回目录结果。",
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

    if stage == "normalizing_result":
        chapter_count = int(meta.get("chapterCount") or 0)
        store.update_directory_generation_state(
            project_id,
            percentage=85,
            summary=f"opencode 已返回目录结果，正在整理 {chapter_count} 个章节节点。",
            tasks=_directory_tasks("done", "done", "running"),
            event_message=f"opencode 已返回结果，正在整理 {chapter_count} 个章节节点。",
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


@router.post("/api/projects/{project_id}/directory-generation/run")
async def run_directory_generation(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    current = store.get_directory_state(project_id)
    if current.get("status") == "running":
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
