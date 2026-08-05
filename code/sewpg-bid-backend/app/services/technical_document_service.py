from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException, Request

from app.core.config import DEFAULT_OPENCODE_MODEL_ID, DEFAULT_OPENCODE_PROVIDER_ID, settings
from app.services.bid_document_state import apply_technical_document_format_to_project
from app.services.bid_document_flow import BidDocumentService
from app.services.bid_document_flow import _build_document_payload
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.bid_project_service import technical_project_service
from app.services.onlyoffice_documents import (
    document_object_key,
    ensure_document,
    refresh_document_session,
    sync_document_to_minio,
)
from app.services.opencode_client import OpencodeClient
from app.services.technical_document_format import TECH_FORMAT_PRESETS, apply_technical_document_format_preset
from app.services.url_utils import now_message
from app.services.workspace_project_access import persist_workspace_project_state, require_workspace_project_for_update


logger = logging.getLogger(__name__)

TECHNICAL_CHAT_DISABLED_TOOLS = {
    tool_id: False
    for tool_id in (
        "invalid",
        "question",
        "bash",
        "read",
        "glob",
        "grep",
        "edit",
        "write",
        "task",
        "webfetch",
        "todowrite",
        "websearch",
        "codesearch",
        "skill",
        "apply_patch",
    )
}


class TechnicalChatSessionExpiredError(RuntimeError):
    pass


class TechnicalChatSessionCannotContinueError(RuntimeError):
    pass


def _technical_project_for_update(project_id: str) -> dict[str, Any]:
    return require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=lambda _project_id: HTTPException(
            status_code=404,
            detail=technical_project_service.not_found_message,
        ),
        wrong_type_error=lambda _project_id: HTTPException(
            status_code=400,
            detail=technical_project_service.wrong_type_message,
        ),
    )


def _existing_session_prompt_result(
    client: OpencodeClient,
    session_id: str,
    prompt: str,
) -> dict[str, Any]:
    response = client.send_prompt(
        session_id,
        prompt,
        tools=TECHNICAL_CHAT_DISABLED_TOOLS,
    )
    info = response.get("info") if isinstance(response.get("info"), dict) else {}
    if info.get("error"):
        raise RuntimeError(OpencodeClient._format_response_error(info["error"]))
    return {
        "sessionId": session_id,
        "providerId": client.provider_id,
        "modelId": client.model_id,
        "baseUrl": client.base_url,
        "reply": client.extract_text_response(response),
        "opencodeOutput": client._build_output_trace(session_id, response),
    }


def _is_missing_chat_session_error(error: Exception) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, httpx.HTTPStatusError) and current.response.status_code == 404:
            return True
        current = current.__cause__ or current.__context__

    text = str(error or "").lower()
    explicit_markers = (
        "session not found",
        "session_not_found",
        "sessionnotfound",
        "unknown session",
        "session does not exist",
        "session expired",
        "会话不存在",
        "未找到会话",
        "会话已失效",
    )
    return any(marker in text for marker in explicit_markers)


def _send_technical_chat_prompt(
    title: str,
    prompt: str,
    *,
    session_id: str = "",
    session_base_url: str = "",
    session_provider_id: str = "",
    session_model_id: str = "",
    new_session_prompt: str = "",
) -> dict[str, Any]:
    configured_client = OpencodeClient(
        base_url=session_base_url or None,
        provider_id=session_provider_id or None,
        model_id=session_model_id or None,
    )
    try:
        if session_id:
            return _existing_session_prompt_result(configured_client, session_id, prompt)
        result = configured_client.send_text_prompt(
            title,
            prompt,
            tools=TECHNICAL_CHAT_DISABLED_TOOLS,
        )
        result["baseUrl"] = configured_client.base_url
        return result
    except Exception as first_exc:
        first_error = str(first_exc)
        if session_id and _is_missing_chat_session_error(first_exc):
            raise TechnicalChatSessionExpiredError(first_error) from first_exc
        if session_id and not OpencodeClient.is_model_not_found_error(first_error):
            raise
        fallback_provider = settings.opencode_provider_id or DEFAULT_OPENCODE_PROVIDER_ID
        fallback_model = settings.opencode_model_id or DEFAULT_OPENCODE_MODEL_ID
        is_default_model = (
            configured_client.provider_id == fallback_provider
            and configured_client.model_id == fallback_model
            and configured_client.base_url == settings.opencode_base_url.rstrip("/")
        )
        if is_default_model and not OpencodeClient.is_model_not_found_error(first_error):
            raise

        fallback_client = OpencodeClient(
            base_url=settings.opencode_base_url,
            provider_id=fallback_provider,
            model_id=fallback_model,
        )
        if session_id and fallback_client.base_url != configured_client.base_url:
            raise TechnicalChatSessionCannotContinueError(first_error) from first_exc
        try:
            if session_id and fallback_client.base_url == configured_client.base_url:
                result = _existing_session_prompt_result(fallback_client, session_id, prompt)
            else:
                result = fallback_client.send_text_prompt(
                    f"{title}（默认模型重试）",
                    new_session_prompt or prompt,
                    tools=TECHNICAL_CHAT_DISABLED_TOOLS,
                )
                result["baseUrl"] = fallback_client.base_url
            result["fallbackModelUsed"] = True
            result["primaryModelError"] = first_error
            return result
        except Exception as second_exc:
            raise RuntimeError(
                f"系统设置模型不可用：{first_error}；默认 opencode 模型重试也失败：{second_exc}"
            ) from second_exc


class TechnicalDocumentService(BidDocumentService):
    async def chat(
        self,
        project_id: str,
        data: dict[str, Any] | None,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        message = str((data or {}).get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="请输入需要咨询的技术标问题。")

        user_id = str(user.get("id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=401, detail="无法识别当前用户。")

        project = _technical_project_for_update(project_id)
        requested_session_id = str((data or {}).get("sessionId") or "").strip()
        sessions = project.get("technical_chat_sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        if requested_session_id:
            binding = sessions.get(user_id)
            bound_session_id = str(binding.get("sessionId") or "") if isinstance(binding, dict) else ""
            if bound_session_id != requested_session_id:
                raise HTTPException(status_code=409, detail="该技术标对话会话不属于当前项目和用户，请新建对话。")
        else:
            binding = {}

        initial_prompt = f"""
你是技术标投标文件共创助手。请只围绕技术标正文的内容组织、表达优化、风险提示和补写建议回答。
不得编造技术参数、标准条款、性能承诺或项目事实；不要自动修改 Word 文件。

项目上下文：
- 项目 ID：{project_id}
- 项目名称：{project.get("name") or project_id}
- 项目编号：{project.get("projectCode") or ""}
- 招标人/客户：{project.get("customerName") or project.get("owner") or ""}

用户本次请求：
{message}

请用中文输出可直接供操作人员参考的建议；不确定的内容要明确提示人工核验。
""".strip()
        prompt = message if requested_session_id else initial_prompt

        try:
            result = await asyncio.to_thread(
                _send_technical_chat_prompt,
                "技术标共创对话",
                prompt,
                session_id=requested_session_id,
                session_base_url=str(binding.get("baseUrl") or "") if isinstance(binding, dict) else "",
                session_provider_id=str(binding.get("providerId") or "") if isinstance(binding, dict) else "",
                session_model_id=str(binding.get("modelId") or "") if isinstance(binding, dict) else "",
                new_session_prompt=initial_prompt,
            )
            reply = str(result.get("reply") or "").strip()
            session_id = str(result.get("sessionId") or "").strip()
            if not reply:
                raise RuntimeError("opencode 未返回有效文本。")
            if not session_id:
                raise RuntimeError("opencode 未返回有效 sessionId。")

            latest_project = _technical_project_for_update(project_id)
            latest_sessions = latest_project.get("technical_chat_sessions")
            sessions = dict(latest_sessions) if isinstance(latest_sessions, dict) else {}
            sessions[user_id] = {
                "sessionId": session_id,
                "providerId": str(result.get("providerId") or ""),
                "modelId": str(result.get("modelId") or ""),
                "baseUrl": str(result.get("baseUrl") or ""),
                "updatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
            latest_project["technical_chat_sessions"] = sessions
            persist_workspace_project_state(latest_project)
            return {
                "message": "AI 回复已生成。",
                "reply": reply,
                "sessionId": session_id,
                "providerId": result.get("providerId") or "",
                "modelId": result.get("modelId") or "",
                "fallbackModelUsed": bool(result.get("fallbackModelUsed")),
                "opencodeOutput": result.get("opencodeOutput") or {},
            }
        except TechnicalChatSessionExpiredError as exc:
            raise HTTPException(status_code=409, detail="技术标对话会话已失效，请新建对话。") from exc
        except TechnicalChatSessionCannotContinueError as exc:
            raise HTTPException(
                status_code=409,
                detail="默认模型服务无法续接当前技术标对话，请新建对话。",
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(
                "technical chat failed project_id=%s user_id=%s",
                project_id,
                user_id,
            )
            raise HTTPException(
                status_code=502,
                detail="技术标 AI 对话服务暂不可用，请稍后重试。",
            ) from exc

    async def apply_format(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project_id)
        preset = str((data or {}).get("preset") or "standard").strip() or "standard"
        if preset not in TECH_FORMAT_PRESETS:
            raise HTTPException(status_code=400, detail="未知技术标格式预设。")
        style_overrides = (data or {}).get("styleOverrides") if isinstance((data or {}).get("styleOverrides"), dict) else None
        try:
            result = await asyncio.to_thread(
                apply_technical_document_format_preset,
                project_id,
                preset,
                style_overrides,
            )
            project_state = _technical_project_for_update(project_id)
            state = apply_technical_document_format_to_project(project_state, result)
            persist_workspace_project_state(project_state)
            doc_path = ensure_document(project_id, state["fileName"], state["fallback"]["content"])
            refresh_document_session(doc_path)
            sync_document_to_minio(doc_path, document_object_key(project_id))
            return now_message(
                f"已应用{result.get('label') or '技术标格式'}。",
                {
                    "format": result,
                    "document": _build_document_payload(project_id, request, self.api_prefix, state),
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"技术标格式切换失败：{exc}") from exc


technical_document_service = TechnicalDocumentService(technical_project_service, "/api/technical/projects")
