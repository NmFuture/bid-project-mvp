from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.audit_service import audit_service
from app.services.bid_fill_generation_state import (
    fail_fill_generation_state,
    start_fill_generation_state,
    update_fill_generation_state,
)
from app.services.bid_project_service import BidProjectService
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE, require_bid_type
from app.services.business_draft_generation import generate_business_draft_for_project_with_progress
from app.services.job_queue import enqueue_generation_job, force_release_generation_lock, is_generation_locked
from app.services.local_job_executor import submit_local_job
from app.services.technical_draft_generation import generate_technical_draft_for_project_with_progress
from app.services.workspace_project_access import (
    get_any_workspace_project_runtime_state,
    get_workspace_project_runtime_state,
    persist_workspace_project_state,
    require_any_workspace_project_for_update,
    require_workspace_project_for_update,
)


FILL_GENERATION_STALE_AFTER_SEC = 60 * 60


def _generation_context(bid_type: str) -> dict[str, str]:
    normalized_bid_type = require_bid_type(
        bid_type,
        error_message="生成流程必须显式传入技术标或商务标。",
    )
    if normalized_bid_type == BUSINESS_BID_TYPE:
        return {
            "bidType": BUSINESS_BID_TYPE,
            "skill": "bid-business-assembler",
            "taskLabel": "调用商务标响应文件装配 skill",
            "documentLabel": "商务标响应文件",
            "actionLabel": "商务标响应文件装配",
        }
    return {
        "bidType": TECHNICAL_BID_TYPE,
        "skill": "bid-tech-assembler",
        "taskLabel": "调用技术标正文拼装 skill",
        "documentLabel": "技术标正文",
        "actionLabel": "技术标正文拼装",
    }


def _draft_generator_for_bid_type(bid_type: str) -> Callable[
    [str, dict[str, Any] | None, Callable[[str, dict[str, Any] | None], None] | None],
    dict[str, Any],
]:
    normalized_bid_type = require_bid_type(
        bid_type,
        error_message="生成流程必须显式传入技术标或商务标。",
    )
    if normalized_bid_type == BUSINESS_BID_TYPE:
        return generate_business_draft_for_project_with_progress
    return generate_technical_draft_for_project_with_progress


def _generation_job_bid_type(project_id: str, request_data: dict[str, Any], default_bid_type: str) -> str:
    normalized_default_bid_type = require_bid_type(
        default_bid_type,
        error_message="生成任务默认标类必须是技术标或商务标。",
    )
    hidden_bid_type = str(request_data.pop("__bidType", "") or "").strip()
    if hidden_bid_type:
        return require_bid_type(
            hidden_bid_type,
            error_message="生成任务标类必须是技术标或商务标。",
        )
    try:
        project = get_any_workspace_project_runtime_state(project_id, not_found_error=KeyError)
    except Exception:
        return normalized_default_bid_type
    return require_bid_type(
        project.get("bidType"),
        error_message="生成任务项目必须显式传入技术标或商务标。",
    )


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


def _fill_state(project_id: str) -> dict[str, Any]:
    return copy.deepcopy(_any_project(project_id)["fill_state"])


def _update_fill_generation(project_id: str, **kwargs: Any) -> dict[str, Any]:
    project = _any_project_for_update(project_id)
    state = update_fill_generation_state(project, **kwargs)
    persist_workspace_project_state(project)
    return state


def _fail_fill_generation(project_id: str, message: str, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    project = _any_project_for_update(project_id)
    state = fail_fill_generation_state(project, message=message, tasks=tasks)
    persist_workspace_project_state(project)
    return state


def _fill_tasks(step1: str, step2: str, step3: str, bid_type: str = "") -> list[dict[str, Any]]:
    ctx = _generation_context(bid_type) if bid_type else {"taskLabel": "调用正文拼装 skill"}
    return [
        {"id": "task-1", "label": "准备 S2 目录、Wiki 与素材库", "status": step1},
        {"id": "task-2", "label": ctx["taskLabel"], "status": step2},
        {"id": "task-3", "label": "写入并规范化 Word 正文", "status": step3},
    ]


def _failed_fill_tasks_for_percentage(percentage: int, bid_type: str) -> list[dict[str, Any]]:
    if percentage < 30:
        return _fill_tasks("failed", "pending", "pending", bid_type)
    if percentage < 85:
        return _fill_tasks("done", "failed", "pending", bid_type)
    return _fill_tasks("done", "done", "failed", bid_type)


def _project_audit_metadata(project_id: str, bid_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        project = get_workspace_project_runtime_state(
            project_id,
            bid_type=bid_type,
            not_found_error=KeyError,
            wrong_type_error=ValueError,
        )
    except Exception:
        project = {"id": project_id, "bidType": bid_type}
    return {
        "projectId": project_id,
        "projectName": str(project.get("name") or ""),
        "projectCode": str(project.get("projectCode") or project_id),
        "customerName": str(project.get("customerName") or ""),
        "bidType": str(project.get("bidType") or bid_type),
        "request": data or {},
    }


async def _record_generation_audit(
    *,
    project_id: str,
    action: str,
    status: str = "成功",
    user: dict[str, Any] | None = None,
    bid_type: str,
    data: dict[str, Any] | None = None,
    diff: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    meta = _project_audit_metadata(project_id, bid_type, data)
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


def _is_fill_generation_stale(current: dict[str, Any]) -> bool:
    if current.get("status") != "running":
        return False
    timestamps: list[datetime] = []
    for event in current.get("events") or []:
        if not isinstance(event, dict):
            continue
        parsed = _parse_iso_datetime(event.get("at"))
        if parsed:
            timestamps.append(parsed)
    output = current.get("opencodeOutput") if isinstance(current.get("opencodeOutput"), dict) else {}
    parsed_output = _parse_iso_datetime(output.get("receivedAt"))
    if parsed_output:
        timestamps.append(parsed_output)
    if not timestamps:
        return False
    age_sec = (datetime.now(UTC) - max(timestamps)).total_seconds()
    return age_sec > FILL_GENERATION_STALE_AFTER_SEC


def _recover_stale_fill_generation(project_id: str, current: dict[str, Any], bid_type: str) -> dict[str, Any]:
    force_release_generation_lock("fill_generation", project_id)
    return _fail_fill_generation(
        project_id,
        "S4 生成任务长时间无进展，系统已自动收口并释放任务锁。请重新点击生成标书。",
        tasks=_fill_tasks("done", "failed", "pending", bid_type),
    )


def _handle_fill_progress(
    project_id: str,
    stage: str,
    details: dict[str, Any] | None = None,
    *,
    bid_type: str,
) -> None:
    meta = details or {}
    ctx = _generation_context(bid_type)
    if stage == "inputs_ready":
        wiki_card_count = int(meta.get("wikiCardCount") or 0)
        exported_material_count = int(meta.get("exportedMaterialCount") or 0)
        synthesized_material_card_count = int(meta.get("synthesizedMaterialCardCount") or 0)
        _update_fill_generation(
            project_id,
            percentage=30,
            summary=f"已整理 S2 目录、Wiki 与素材库（Wiki 卡片 {wiki_card_count} 张，可装配素材 {exported_material_count} 份），准备调用{ctx['documentLabel']} skill。",
            tasks=_fill_tasks("done", "running", "pending", bid_type),
            event_message=f"已完成输入准备：Wiki 卡片 {wiki_card_count} 张（其中素材库补卡 {synthesized_material_card_count} 张），可拼装素材 {exported_material_count} 份。",
            event_step="inputs_ready",
        )
        return

    if stage == "calling_assembler":
        manifest_path = str(meta.get("manifestPath") or "")
        work_dir = str(meta.get("workDir") or "")
        _update_fill_generation(
            project_id,
            percentage=60,
            summary=f"正在调用 {ctx['skill']} 装配{ctx['documentLabel']}，请稍候。",
            tasks=_fill_tasks("done", "running", "pending", bid_type),
            event_message=f"已进入{ctx['actionLabel']}阶段，正在按 S2 目录 JSON 匹配素材并写入 Word。",
            event_step="assembly_waiting",
            opencode_output={
                "status": "waiting",
                "sessionId": manifest_path,
                "providerId": "local-skill",
                "modelId": ctx["skill"],
                "receivedAt": "",
                "parts": [{"type": "text", "text": f"workDir={work_dir}\nmanifest={manifest_path}"}],
            },
        )
        return

    if stage == "assembler_session_ready":
        session_id = str(meta.get("sessionId") or "")
        provider_id = str(meta.get("providerId") or "")
        model_id = str(meta.get("modelId") or "")
        _update_fill_generation(
            project_id,
            percentage=62,
            summary=f"正在调用 futurecode 执行 {ctx['skill']}，请稍候。",
            tasks=_fill_tasks("done", "running", "pending", bid_type),
            event_message=f"futurecode session 已建立，正在等待{ctx['actionLabel']}结果。",
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
        current = _fill_state(project_id)
        previous_parts = list((current.get("opencodeOutput") or {}).get("parts") or [])
        summary: str | None = None
        event_message: str | None = None
        if parts and not previous_parts:
            summary = "futurecode 已开始返回正文拼装片段。"
            event_message = "futurecode 已开始返回 S4 生成标书原始片段。"
        elif len(parts) > len(previous_parts):
            summary = "futurecode 正在执行正文拼装，请稍候。"

        _update_fill_generation(
            project_id,
            percentage=70 if parts else None,
            summary=summary,
            tasks=_fill_tasks("done", "running", "pending", bid_type),
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
        _update_fill_generation(
            project_id,
            percentage=85,
            summary=f"{ctx['documentLabel']}装配完成，已匹配 {used_material_count} 份素材，未装配素材 {unassembled_material_count} 份，正在写入 Word。",
            tasks=_fill_tasks("done", "done", "running", bid_type),
            event_message=f"{ctx['actionLabel']}结果已返回，正在写入 {section_count} 个目录章节到 Word。",
            event_step="assembling",
        )
        return

    if stage == "calling_format_cleaner":
        manifest_path = str(meta.get("manifestPath") or "")
        cleaner_skill = str(
            meta.get("skill")
            or ("bid-business-format-cleaner" if ctx["bidType"] == BUSINESS_BID_TYPE else "bid-tech-format-cleaner")
        )
        _update_fill_generation(
            project_id,
            percentage=90,
            summary=f"{ctx['documentLabel']}已拼装完成，正在进行 Word 格式规范化处理。",
            tasks=_fill_tasks("done", "done", "running", bid_type),
            event_message=f"已进入{ctx['documentLabel']}格式规范化阶段，正在统一标题样式、目录、页眉和分页。",
            event_step="format_cleaning",
            opencode_output={
                "status": "waiting",
                "sessionId": manifest_path,
                "providerId": "local-skill",
                "modelId": cleaner_skill,
                "receivedAt": "",
                "parts": [{"type": "text", "text": f"manifest={manifest_path}"}],
            },
        )
        return

    if stage == "format_cleaner_session_ready":
        cleaner_skill = str(meta.get("modelId") or meta.get("skill") or "")
        _update_fill_generation(
            project_id,
            percentage=91,
            summary=f"正在调用 futurecode 执行 {cleaner_skill or 'format-cleaner'}。",
            tasks=_fill_tasks("done", "done", "running", bid_type),
            event_message=f"futurecode session 已建立，正在等待{ctx['documentLabel']}格式清洗结果。",
            event_step="format_session_ready",
            opencode_output={
                "status": "waiting",
                "sessionId": str(meta.get("sessionId") or ""),
                "providerId": str(meta.get("providerId") or ""),
                "modelId": str(meta.get("modelId") or ""),
                "receivedAt": "",
                "parts": [],
            },
        )
        return

    if stage == "format_cleaner_delta":
        parts = list(meta.get("parts") or [])
        _update_fill_generation(
            project_id,
            percentage=93 if parts else None,
            summary=f"futurecode 正在执行{ctx['documentLabel']}格式规范化，请稍候。" if parts else None,
            tasks=_fill_tasks("done", "done", "running", bid_type),
            event_step="format_streaming",
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

    if stage == "format_cleaner_completed":
        summary = meta.get("summary") if isinstance(meta.get("summary"), dict) else {}
        unmatched = int(summary.get("unmatchedHeadingCount") or 0)
        risk_count = int(summary.get("riskCount") or 0)
        _update_fill_generation(
            project_id,
            percentage=96,
            summary=f"{ctx['documentLabel']}格式规范化完成，未匹配标题 {unmatched} 个，格式风险 {risk_count} 项，正在保存最终 Word。",
            tasks=_fill_tasks("done", "done", "running", bid_type),
            event_message=f"{ctx['documentLabel']}格式规范化完成：未匹配标题 {unmatched} 个，格式风险 {risk_count} 项。",
            event_level="success",
            event_step="format_done",
        )
        return

    if stage == "format_cleaner_failed":
        _update_fill_generation(
            project_id,
            percentage=94,
            summary=f"{ctx['documentLabel']}格式规范化失败，系统将保留正文拼装原稿继续输出。",
            tasks=_fill_tasks("done", "done", "running", bid_type),
            event_message=f"{ctx['documentLabel']}格式规范化失败，已降级使用未格式化正文：{meta.get('error') or '未知错误'}",
            event_level="warning",
            event_step="format_failed",
        )


def _run_fill_generation_job(
    project_id: str,
    data: dict[str, Any],
    user: dict[str, Any] | None = None,
    *,
    bid_type: str,
) -> None:
    request_data = dict(data or {})
    job_bid_type = _generation_job_bid_type(project_id, request_data, bid_type)
    try:
        draft_generator = _draft_generator_for_bid_type(job_bid_type)
        draft_generator(
            project_id,
            request_data,
            progress_callback=lambda stage, details=None: _handle_fill_progress(
                project_id,
                stage,
                details,
                bid_type=job_bid_type,
            ),
        )
        state = _fill_state(project_id)
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书完成",
            user=user,
            bid_type=job_bid_type,
            data=request_data,
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
        _fail_fill_generation(
            project_id,
            str(exc),
            tasks=_fill_tasks("failed", "pending", "pending", job_bid_type),
        )
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书失败",
            status="失败",
            user=user,
            bid_type=job_bid_type,
            data=request_data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__},
        )
    except RuntimeError as exc:
        current = _fill_state(project_id)
        tasks = _failed_fill_tasks_for_percentage(int(current.get("percentage") or 0), job_bid_type)
        _fail_fill_generation(project_id, str(exc), tasks=tasks)
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书失败",
            status="失败",
            user=user,
            bid_type=job_bid_type,
            data=request_data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__, "percentage": current.get("percentage")},
        )
    except Exception as exc:  # pragma: no cover
        current = _fill_state(project_id)
        tasks = _failed_fill_tasks_for_percentage(int(current.get("percentage") or 0), job_bid_type)
        _fail_fill_generation(project_id, f"正文拼装异常：{exc}", tasks=tasks)
        _record_generation_audit_sync(
            project_id=project_id,
            action="生成标书失败",
            status="失败",
            user=user,
            bid_type=job_bid_type,
            data=request_data,
            diff={"before": {}, "after": {"error": str(exc)}},
            metadata={"errorType": type(exc).__name__, "percentage": current.get("percentage")},
        )


def _schedule_fill_generation_job(
    project_id: str,
    data: dict[str, Any],
    user: dict[str, Any] | None = None,
    *,
    bid_type: str,
) -> None:
    enqueue_data = dict(data or {})
    enqueue_data["__bidType"] = bid_type
    if user:
        enqueue_data["__auditUser"] = {
            "id": str(user.get("id") or ""),
            "name": str(user.get("name") or user.get("email") or ""),
            "email": str(user.get("email") or ""),
        }
    queue_result = enqueue_generation_job("fill_generation", project_id, enqueue_data)
    if queue_result.queued or queue_result.locked:
        return

    submit_local_job(_run_fill_generation_job, project_id, data, user, bid_type=bid_type)


class BidGenerationService:
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

    def fill_state(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.ensure_project(project_id)["fill_state"])

    def start_fill_generation(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = start_fill_generation_state(project)
        persist_workspace_project_state(project)
        return payload

    def _with_generation_urls(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = copy.deepcopy(payload)
        output = data.get("output") if isinstance(data.get("output"), dict) else None
        if output is not None:
            output["fileUrl"] = f"{self.api_prefix}/{project_id}/document/file"
        return data

    async def status(self, project_id: str) -> dict[str, Any]:
        current = self.fill_state(project_id)
        if _is_fill_generation_stale(current):
            current = _recover_stale_fill_generation(project_id, current, self.project_service.bid_type)
        return self._with_generation_urls(project_id, current)

    async def run(
        self,
        project_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
        user: dict[str, Any] | None = None,
    ) -> JSONResponse:
        current = self.fill_state(project_id)
        if _is_fill_generation_stale(current):
            current = _recover_stale_fill_generation(project_id, current, self.project_service.bid_type)
        if current.get("status") == "running" or is_generation_locked("fill_generation", project_id):
            return JSONResponse(
                status_code=202,
                content={**self._with_generation_urls(project_id, current), "message": "正文拼装任务正在执行中，请稍候。"},
            )

        try:
            payload = self.start_fill_generation(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        request_data = data or {}
        await _record_generation_audit(
            project_id=project_id,
            action="开始生成标书",
            user=user,
            bid_type=self.project_service.bid_type,
            data=request_data,
            diff={"before": current, "after": {"status": payload.get("status"), "percentage": payload.get("percentage")}},
            metadata={"taskCount": len(payload.get("tasks") or [])},
            request=request,
        )
        _schedule_fill_generation_job(project_id, request_data, user, bid_type=self.project_service.bid_type)
        return JSONResponse(
            status_code=202,
            content={**self._with_generation_urls(project_id, payload), "message": "已开始拼装正文，请稍候。"},
        )
