from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from fastapi import HTTPException, Request

from app.core.config import settings
from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type
from app.services.bid_document_state import apply_business_document_format_to_project, force_save_document_state
from app.services.bid_document_flow import BidDocumentService, _build_document_payload
from app.services.bid_project_service import business_project_service
from app.services.business_assembly import BUSINESS_FORMAT_PRESETS, apply_business_document_format_preset
from app.services.business_document_editing import apply_controlled_business_rewrite
from app.services.onlyoffice_documents import (
    document_object_key,
    ensure_document,
    refresh_document_session,
    sync_document_to_minio,
)
from app.services.opencode_client import OpencodeClient
from app.services.url_utils import now_message
from app.services.workspace_project_access import persist_workspace_project_state, require_workspace_project_for_update


def _project_bid_label(project: dict[str, Any]) -> str:
    return require_bid_type(
        project.get("bidType"),
        error_message="商务文档处理必须显式传入商务标项目。",
    )


def _business_project_for_update(project_id: str) -> dict[str, Any]:
    return require_workspace_project_for_update(
        project_id,
        bid_type=BUSINESS_BID_TYPE,
        not_found_error=lambda _project_id: HTTPException(
            status_code=404,
            detail=business_project_service.not_found_message,
        ),
        wrong_type_error=lambda _project_id: HTTPException(
            status_code=400,
            detail=business_project_service.wrong_type_message,
        ),
    )


def _send_business_chat_prompt(title: str, prompt: str) -> dict[str, Any]:
    try:
        return OpencodeClient().send_text_prompt(title, prompt)
    except Exception as first_exc:
        first_error = str(first_exc)
        configured_client = OpencodeClient()
        fallback_provider = settings.opencode_provider_id or "opencode"
        fallback_model = settings.opencode_model_id or "big-pickle"
        is_default_model = (
            configured_client.provider_id == fallback_provider
            and configured_client.model_id == fallback_model
            and configured_client.base_url == settings.opencode_base_url.rstrip("/")
        )
        if is_default_model and not OpencodeClient.is_model_not_found_error(first_error):
            raise
        try:
            result = OpencodeClient(
                base_url=settings.opencode_base_url,
                provider_id=fallback_provider,
                model_id=fallback_model,
            ).send_text_prompt(f"{title}（默认模型重试）", prompt)
            result["fallbackModelUsed"] = True
            result["primaryModelError"] = first_error
            return result
        except Exception as second_exc:
            raise RuntimeError(
                f"系统设置模型不可用：{first_error}；默认 opencode 模型重试也失败：{second_exc}"
            ) from second_exc


def _extract_rewrite_suggestion(
    reply: str,
    original_text: str,
    instruction: str,
    bid_label: str = BUSINESS_BID_TYPE,
) -> dict[str, Any]:
    text = str(reply or "").strip()
    replacement = text
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if match:
        text = match.group(1)
    else:
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            text = text[brace_start : brace_end + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = {}
    if isinstance(parsed, dict):
        replacement = str(parsed.get("replacementText") or parsed.get("replacement") or "").strip() or replacement
        reason = str(parsed.get("reason") or parsed.get("revisionReason") or "").strip()
        risk = str(parsed.get("riskTip") or parsed.get("riskTips") or "").strip()
    else:
        reason = ""
        risk = ""
    return {
        "schemaVersion": "business-controlled-rewrite-suggestion-v1",
        "originalText": str(original_text or "").strip(),
        "replacementText": replacement.strip(),
        "instruction": str(instruction or "").strip(),
        "reason": reason or f"已根据用户润色要求优化{bid_label}投标表达。",
        "riskTip": risk or "请确认替换文本未改变招标文件要求、承诺边界、金额、日期和主体信息。",
        "rawReply": reply,
    }


class BusinessDocumentService(BidDocumentService):
    async def chat(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        bid_label = _project_bid_label(project)
        message = str((data or {}).get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="请输入需要对话或润色的内容。")
        history = (data or {}).get("history") if isinstance((data or {}).get("history"), list) else []
        document_state = project.get("document_state") if isinstance(project.get("document_state"), dict) else {}
        fill_state = project.get("fill_state") if isinstance(project.get("fill_state"), dict) else {}
        context = {
            "projectId": project_id,
            "bidType": bid_label,
            "projectName": project.get("name") or project_id,
            "projectCode": project.get("projectCode") or "",
            "customerName": project.get("customerName") or project.get("owner") or "",
            "documentFileName": document_state.get("fileName") or "",
            "generationSummary": fill_state.get("summary") or "",
        }
        recent_history = [
            {
                "role": str(item.get("role") or ""),
                "content": str(item.get("content") or "")[:1200],
            }
            for item in history[-6:]
            if isinstance(item, dict)
        ]
        prompt = f"""
你是{bid_label}投标文件共创助手。请只围绕{bid_label}正文的语言润色、表达优化、风险提示和补写建议回答，不要编造项目事实，不要自动修改 Word 文件。

项目上下文：
{context}

上下文对话：
{recent_history}

用户本次请求：
{message}

请用中文输出可直接给操作人参考的建议；如果用户要求润色，请给出“可替换文本”。
""".strip()

        try:
            result = await asyncio.to_thread(_send_business_chat_prompt, f"{bid_label}共创对话", prompt)
            reply = str(result.get("reply") or "").strip()
            if not reply:
                raise RuntimeError("opencode 未返回有效文本。")
            return {
                "message": "AI 回复已生成。",
                "reply": reply,
                "sessionId": result.get("sessionId") or "",
                "providerId": result.get("providerId") or "",
                "modelId": result.get("modelId") or "",
                "fallbackModelUsed": bool(result.get("fallbackModelUsed")),
                "primaryModelError": result.get("primaryModelError") or "",
                "opencodeOutput": result.get("opencodeOutput") or {},
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{bid_label} AI 对话调用 opencode 失败：{exc}") from exc

    async def suggest_rewrite(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        bid_label = _project_bid_label(project)
        original_text = str((data or {}).get("originalText") or "").strip()
        instruction = str((data or {}).get("instruction") or "").strip()
        if not original_text:
            raise HTTPException(status_code=400, detail="请粘贴需要润色的原文段落。")
        if len(original_text) > 4000:
            raise HTTPException(status_code=400, detail="原文段落过长，请先缩短到单个段落或小片段。")
        if not instruction:
            instruction = f"在不改变事实、承诺边界、金额、日期和主体信息的前提下，优化为正式、审慎、可履约的{bid_label}投标表达。"

        prompt = f"""
你是{bid_label}投标文件润色助手。请只改写用户提供的原文，不要扩写无依据事实，不要新增承诺，不要改变金额、日期、单位、项目名称、招标编号、法律责任边界。

项目上下文：
- 项目名称：{project.get("name") or project_id}
- 招标编号/项目编号：{project.get("projectCode") or ""}
- 招标人/客户：{project.get("customerName") or project.get("owner") or ""}

原文：
{original_text}

润色要求：
{instruction}

请只输出严格 JSON，不要 Markdown，不要解释。格式如下：
{{
  "replacementText": "可直接替换原文的润色文本",
  "reason": "一句话说明修改理由",
  "riskTip": "一句话提示需要人工复核的风险"
}}
""".strip()

        try:
            result = await asyncio.to_thread(_send_business_chat_prompt, f"{bid_label}受控润色建议", prompt)
            reply = str(result.get("reply") or "").strip()
            if not reply:
                raise RuntimeError("opencode 未返回有效润色建议。")
            suggestion = _extract_rewrite_suggestion(reply, original_text, instruction, bid_label)
            if not suggestion["replacementText"]:
                raise RuntimeError("opencode 未返回可替换文本。")
            return {
                "message": "已生成受控润色建议，请审核后再应用到 Word。",
                "suggestion": suggestion,
                "providerId": result.get("providerId") or "",
                "modelId": result.get("modelId") or "",
                "fallbackModelUsed": bool(result.get("fallbackModelUsed")),
                "primaryModelError": result.get("primaryModelError") or "",
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{bid_label}受控润色建议生成失败：{exc}") from exc

    async def apply_rewrite(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        bid_label = _project_bid_label(project)
        original_text = str((data or {}).get("originalText") or "").strip()
        replacement_text = str((data or {}).get("replacementText") or "").strip()
        if not original_text or not replacement_text:
            raise HTTPException(status_code=400, detail="原文和替换文本不能为空。")
        try:
            result = await asyncio.to_thread(
                apply_controlled_business_rewrite,
                project_id,
                original_text=original_text,
                replacement_text=replacement_text,
                operator=str((data or {}).get("operator") or "当前用户"),
            )
            project_state = _business_project_for_update(project_id)
            state = force_save_document_state(project_state, project_id)
            persist_workspace_project_state(project_state)
            doc_path = ensure_document(project_id, state["fileName"], state["fallback"]["content"])
            refresh_document_session(doc_path)
            sync_document_to_minio(doc_path, document_object_key(project_id))
            return now_message(
                f"已按审核后的替换文本更新{bid_label}正文。",
                {
                    "rewrite": result,
                    "document": _build_document_payload(project_id, request, self.api_prefix, state),
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{bid_label}正文受控替换失败：{exc}") from exc

    async def apply_format(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        bid_label = _project_bid_label(project)
        preset = str((data or {}).get("preset") or "standard").strip() or "standard"
        if preset not in BUSINESS_FORMAT_PRESETS:
            raise HTTPException(status_code=400, detail="未知商务标格式预设。")
        style_overrides = (data or {}).get("styleOverrides") if isinstance((data or {}).get("styleOverrides"), dict) else None
        try:
            result = await asyncio.to_thread(
                apply_business_document_format_preset,
                project_id,
                preset,
                style_overrides,
            )
            project_state = _business_project_for_update(project_id)
            state = apply_business_document_format_to_project(project_state, result)
            persist_workspace_project_state(project_state)
            doc_path = ensure_document(project_id, state["fileName"], state["fallback"]["content"])
            refresh_document_session(doc_path)
            sync_document_to_minio(doc_path, document_object_key(project_id))
            return now_message(
                f"已应用{result.get('label') or f'{bid_label}格式'}。",
                {
                    "format": result,
                    "document": _build_document_payload(project_id, request, self.api_prefix, state),
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{bid_label}格式切换失败：{exc}") from exc


business_document_service = BusinessDocumentService(business_project_service, "/api/business/projects")
