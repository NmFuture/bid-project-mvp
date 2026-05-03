from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.draft_generation import generate_draft_for_project_with_progress
from app.services.audit_service import audit_service
from app.services.auth_service import current_user
from app.services.job_queue import enqueue_generation_job, is_generation_locked
from app.services.store import store

router = APIRouter()


def _fill_tasks(step1: str, step2: str, step3: str) -> list[dict[str, Any]]:
    return [
        {"id": "task-1", "label": "准备 S2 目录、Wiki 与素材库", "status": step1},
        {"id": "task-2", "label": "调用技术标正文拼装 skill", "status": step2},
        {"id": "task-3", "label": "写入 Word 正文", "status": step3},
    ]


def _project_audit_metadata(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        project = store.get_project(project_id)
    except Exception:
        project = {"id": project_id}
    return {
        "projectId": project_id,
        "projectName": str(project.get("name") or ""),
        "projectCode": str(project.get("projectCode") or project_id),
        "customerName": str(project.get("customerName") or ""),
        "bidType": str(project.get("bidType") or ""),
        "request": data or {},
    }


async def _record_generation_audit(
    *,
    project_id: str,
    action: str,
    status: str = "成功",
    user: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    diff: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    meta = _project_audit_metadata(project_id, data)
    meta.update(metadata or {})
    await audit_service.record(
        action=action,
        action_type="generate",
        module_id="generation",
        module_label="生成标书",
        target=str(meta.get("projectName") or project_id),
        status=status,
        user=user,
        diff=diff or {"before": {}, "after": {}},
        metadata=meta,
        ip_address=str(request.client.host) if request and request.client else "",
        user_agent=str(request.headers.get("user-agent") or "") if request else "",
    )


def _record_generation_audit_sync(**kwargs: Any) -> None:
    try:
        asyncio.run(_record_generation_audit(**kwargs))
    except Exception:
        return


def _handle_fill_progress(project_id: str, stage: str, details: dict[str, Any] | None = None) -> None:
    meta = details or {}
    if stage == "inputs_ready":
        wiki_card_count = int(meta.get("wikiCardCount") or 0)
        exported_material_count = int(meta.get("exportedMaterialCount") or 0)
        synthesized_material_card_count = int(meta.get("synthesizedMaterialCardCount") or 0)
        store.update_fill_generation_state(
            project_id,
            percentage=30,
            summary=f"已整理 S2 目录、Wiki 与素材库（Wiki 卡片 {wiki_card_count} 张，可拼装素材 {exported_material_count} 份），准备调用正文拼装 skill。",
            tasks=_fill_tasks("done", "running", "pending"),
            event_message=f"已完成输入准备：Wiki 卡片 {wiki_card_count} 张（其中素材库补卡 {synthesized_material_card_count} 张），可拼装素材 {exported_material_count} 份。",
            event_step="inputs_ready",
        )
        return

    if stage == "calling_assembler":
        manifest_path = str(meta.get("manifestPath") or "")
        work_dir = str(meta.get("workDir") or "")
        store.update_fill_generation_state(
            project_id,
            percentage=60,
            summary="正在调用 bid-tech-assembler 拼装技术标正文，请稍候。",
            tasks=_fill_tasks("done", "running", "pending"),
            event_message="已进入技术标正文拼装阶段，正在按 S2 目录 JSON 匹配素材并合并 Word。",
            event_step="assembly_waiting",
            opencode_output={
                "status": "waiting",
                "sessionId": manifest_path,
                "providerId": "local-skill",
                "modelId": "bid-tech-assembler",
                "receivedAt": "",
                "parts": [{"type": "text", "text": f"workDir={work_dir}\nmanifest={manifest_path}"}],
            },
        )
        return

    if stage == "assembler_session_ready":
        session_id = str(meta.get("sessionId") or "")
        provider_id = str(meta.get("providerId") or "")
        model_id = str(meta.get("modelId") or "")
        store.update_fill_generation_state(
            project_id,
            percentage=62,
            summary="正在调用 futurecode 执行 bid-tech-assembler，请稍候。",
            tasks=_fill_tasks("done", "running", "pending"),
            event_message="futurecode session 已建立，正在等待技术标正文拼装结果。",
            event_step="assembler_session_ready",
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

    if stage == "assembler_delta":
        parts = list(meta.get("parts") or [])
        current = store.get_fill_state(project_id)
        previous_parts = list((current.get("opencodeOutput") or {}).get("parts") or [])
        summary: str | None = None
        event_message: str | None = None
        if parts and not previous_parts:
            summary = "futurecode 已开始返回正文拼装片段。"
            event_message = "futurecode 已开始返回 S7 原始片段。"
        elif len(parts) > len(previous_parts):
            summary = "futurecode 正在执行正文拼装，请稍候。"

        store.update_fill_generation_state(
            project_id,
            percentage=70 if parts else None,
            summary=summary,
            tasks=_fill_tasks("done", "running", "pending"),
            event_message=event_message,
            event_step="assembler_streaming",
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

    if stage == "assembling_result":
        section_count = int(meta.get("sectionCount") or 0)
        used_material_count = int(meta.get("usedMaterialCount") or 0)
        unassembled_material_count = int(meta.get("unassembledMaterialCount") or 0)
        store.update_fill_generation_state(
            project_id,
            percentage=85,
            summary=f"正文拼装完成，已匹配 {used_material_count} 份素材，未拼素材 {unassembled_material_count} 份，正在写入 Word。",
            tasks=_fill_tasks("done", "done", "running"),
            event_message=f"正文拼装结果已返回，正在写入 {section_count} 个目录章节到 Word 正文。",
            event_step="assembling",
        )


def _run_fill_generation_job(project_id: str, data: dict[str, Any], user: dict[str, Any] | None = None) -> None:
    try:
        generate_draft_for_project_with_progress(
            project_id,
            data,
            progress_callback=lambda stage, details=None: _handle_fill_progress(project_id, stage, details),
        )
        state = store.get_fill_state(project_id)
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书完成",
            user=user,
            data=data,
            diff={"before": {}, "after": {"status": state.get("status"), "output": state.get("output")}},
            metadata={
                "percentage": state.get("percentage"),
                "sectionCount": len(state.get("sections") or []),
                "coverage": state.get("coverage") or {},
                "opencodeOutput": {
                    "status": (state.get("opencodeOutput") or {}).get("status"),
                    "sessionId": (state.get("opencodeOutput") or {}).get("sessionId"),
                    "providerId": (state.get("opencodeOutput") or {}).get("providerId"),
                    "modelId": (state.get("opencodeOutput") or {}).get("modelId"),
                },
            },
        )
    except ValueError as exc:
        store.fail_fill_generation(
            project_id,
            str(exc),
            tasks=_fill_tasks("failed", "pending", "pending"),
        )
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书失败",
            status="失败",
            user=user,
            data=data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__},
        )
    except RuntimeError as exc:
        current = store.get_fill_state(project_id)
        tasks = _fill_tasks("done", "failed", "pending")
        if int(current.get("percentage") or 0) >= 85:
            tasks = _fill_tasks("done", "done", "failed")
        store.fail_fill_generation(project_id, str(exc), tasks=tasks)
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书失败",
            status="失败",
            user=user,
            data=data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__, "percentage": current.get("percentage")},
        )
    except Exception as exc:  # pragma: no cover
        current = store.get_fill_state(project_id)
        tasks = _fill_tasks("done", "failed", "pending")
        if int(current.get("percentage") or 0) >= 85:
            tasks = _fill_tasks("done", "done", "failed")
        store.fail_fill_generation(project_id, f"正文拼装异常：{exc}", tasks=tasks)
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书失败",
            status="失败",
            user=user,
            data=data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__, "percentage": current.get("percentage")},
        )


def _schedule_fill_generation_job(project_id: str, data: dict[str, Any], user: dict[str, Any] | None = None) -> None:
    enqueue_data = dict(data or {})
    if user:
        enqueue_data["__auditUser"] = {
            "id": str(user.get("id") or ""),
            "name": str(user.get("name") or user.get("email") or ""),
            "email": str(user.get("email") or ""),
        }
    queue_result = enqueue_generation_job("fill_generation", project_id, enqueue_data)
    if queue_result.queued or queue_result.locked:
        return

    worker = threading.Thread(
        target=_run_fill_generation_job,
        args=(project_id, data, user),
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
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> JSONResponse:
    current = store.get_fill_state(project_id)
    if current.get("status") == "running" or is_generation_locked("fill_generation", project_id):
        return JSONResponse(
            status_code=202,
            content={**current, "message": "正文拼装任务正在执行中，请稍候。"},
        )

    try:
        payload = store.start_fill_generation(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await _record_generation_audit(
        project_id=project_id,
        action="开始生成标书",
        user=user,
        data=data,
        diff={"before": current, "after": {"status": payload.get("status"), "percentage": payload.get("percentage")}},
        metadata={"taskCount": len(payload.get("tasks") or [])},
        request=request,
    )
    _schedule_fill_generation_job(project_id, data, user)
    return JSONResponse(
        status_code=202,
        content={**payload, "message": "已开始拼装正文，请稍候。"},
    )
