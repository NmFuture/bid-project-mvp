from __future__ import annotations

import copy
import asyncio
import json
import re
import hashlib
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.utils import absolute_url, now_message, onlyoffice_backend_base_url
from app.core.config import settings
from app.services.business_assembly import BUSINESS_FORMAT_PRESETS, apply_business_document_format_preset
from app.services.business_document_editing import apply_controlled_business_rewrite
from app.services.onlyoffice_documents import (
    WORD_MEDIA_TYPE,
    build_editor_session_key,
    document_object_key,
    download_document_from_onlyoffice,
    ensure_document,
    refresh_document_session,
    sync_document_to_minio,
    write_document,
)
from app.services.opencode_client import OpencodeClient
from app.services.parse_profiles import normalize_bid_type
from app.services.store import store

router = APIRouter()

PDF_MEDIA_TYPE = "application/pdf"


def _add_callback_token(url: str) -> str:
    token = settings.onlyoffice_callback_token
    if not token:
        return url
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("oo_callback_token", token))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _add_query_param(url: str, key: str, value: Any) -> str:
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append((key, str(value)))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _allowed_host(host: str | None, allowed_hosts: tuple[str, ...]) -> bool:
    if not host:
        return False
    normalized = host.lower()
    allowed = {item.lower() for item in allowed_hosts}
    return "*" in allowed or normalized in allowed


def _validate_callback_token(request: Request) -> None:
    expected = settings.onlyoffice_callback_token
    if not expected:
        return
    supplied = request.query_params.get("oo_callback_token", "")
    if supplied != expected:
        raise HTTPException(status_code=403, detail="OnlyOffice callback token 无效。")


def _validate_download_url(download_url: str) -> str:
    parsed = urlparse(download_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="OnlyOffice 回写 URL 协议不被允许。")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="OnlyOffice 回写 URL 不允许包含认证信息。")
    if not _allowed_host(parsed.hostname, settings.onlyoffice_download_allowed_hosts):
        allowed = ", ".join(settings.onlyoffice_download_allowed_hosts)
        raise HTTPException(status_code=400, detail=f"OnlyOffice 回写 URL 主机不在白名单内：{allowed}")
    return download_url


async def _convert_document_to_pdf_via_onlyoffice(source_url: str, source_path: Path, target_path: Path) -> Path:
    base_url = settings.onlyoffice_internal_url.rstrip("/")
    if not base_url:
        raise RuntimeError("OnlyOffice 内部服务地址未配置。")
    source_ext = source_path.suffix.lower().lstrip(".") or "docx"
    async with httpx.AsyncClient(timeout=120) as client:
        payload = {
            "async": False,
            "filetype": source_ext,
            "key": hashlib.sha256(f"{source_path}:{source_path.stat().st_mtime_ns}:pdf".encode("utf-8")).hexdigest(),
            "outputtype": "pdf",
            "title": source_path.name,
            "url": source_url,
        }
        response = await client.post(f"{base_url}/ConvertService.ashx", json=payload)
        response.raise_for_status()
        content_type = str(response.headers.get("content-type") or "").lower()
        if "json" in content_type:
            result = response.json()
        else:
            root = ET.fromstring(response.text)
            result = {
                "error": root.findtext("Error") or root.findtext("error") or "",
                "fileUrl": root.findtext("FileUrl") or root.findtext("fileUrl") or root.findtext("fileurl") or "",
            }
        if result.get("error"):
            raise RuntimeError(f"OnlyOffice PDF 转换失败：{result.get('error')}")
        pdf_url = result.get("fileUrl") or result.get("fileurl")
        if not pdf_url:
            raise RuntimeError("OnlyOffice 未返回 PDF 下载地址。")
        download = await client.get(str(pdf_url))
        download.raise_for_status()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(download.content)
    return target_path


async def _convert_document_to_pdf_locally(source_path: Path, target_path: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="business-pdf-") as tmp:
        output_dir = Path(tmp)
        command = [
            "libreoffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(source_path),
        ]
        try:
            await asyncio.to_thread(
                subprocess.run,
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("本地 PDF 兜底失败：未安装 libreoffice。") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("本地 PDF 兜底失败：转换超时。") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(f"本地 PDF 兜底失败：{detail or exc}") from exc
        converted = output_dir / f"{source_path.stem}.pdf"
        if not converted.exists():
            matches = list(output_dir.glob("*.pdf"))
            converted = matches[0] if matches else converted
        if not converted.exists():
            raise RuntimeError("本地 PDF 兜底失败：未生成 PDF 文件。")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(converted.read_bytes())
        return target_path


def build_document_payload(project_id: str, request: Request) -> dict[str, Any]:
    payload = store.get_document_state(project_id)
    document_version = payload.get("version") or 1
    doc_path = ensure_document(
        project_id,
        payload["fileName"],
        payload["fallback"]["content"],
    )

    quoted_name = quote(payload["fileName"])
    browser_file_url = _add_query_param(
        absolute_url(request, f"/api/projects/{project_id}/document/file/{quoted_name}"),
        "doc_version",
        document_version,
    )
    browser_callback_url = _add_callback_token(
        _add_query_param(
            absolute_url(request, f"/api/projects/{project_id}/document/callback"),
            "oo_doc_version",
            document_version,
        )
    )
    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = _add_query_param(
        f"{onlyoffice_base}/api/projects/{project_id}/document/file/{quoted_name}",
        "doc_version",
        document_version,
    )
    onlyoffice_callback_url = _add_callback_token(
        _add_query_param(
            f"{onlyoffice_base}/api/projects/{project_id}/document/callback",
            "oo_doc_version",
            document_version,
        )
    )

    return {
        **payload,
        "fileUrl": browser_file_url,
        "sourceFileUrl": browser_file_url,
        "onlyoffice": {
            **payload["onlyoffice"],
            "fileUrl": onlyoffice_file_url,
            "callbackUrl": onlyoffice_callback_url,
            "browserFileUrl": browser_file_url,
            "browserCallbackUrl": browser_callback_url,
            # Bind the editor session key to the actual file on disk so OnlyOffice
            # does not reuse a stale cached conversion after the document changes.
            "documentKey": build_editor_session_key(doc_path, payload.get("version") or 1),
        },
    }


@router.get("/api/projects/{project_id}/document")
async def get_document(project_id: str, request: Request) -> dict[str, Any]:
    return build_document_payload(project_id, request)


@router.put("/api/projects/{project_id}/document/save")
async def save_document_content(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    content = str(data.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="保存内容不能为空。")
    payload = store.save_document_content(project_id, content)
    write_document(
        ensure_document(project_id, payload["fileName"], content),
        payload["fileName"],
        content,
    )
    sync_document_to_minio(ensure_document(project_id, payload["fileName"], content), document_object_key(project_id))
    response_payload = build_document_payload(project_id, request)
    return now_message("文档已保存并回写。", response_payload)


@router.post("/api/projects/{project_id}/document/force-save")
async def force_save_document(project_id: str, request: Request) -> dict[str, Any]:
    state = store.force_save_document(project_id)
    doc_path = ensure_document(
        project_id,
        state["fileName"],
        state["fallback"]["content"],
    )
    refresh_document_session(doc_path)
    sync_document_to_minio(doc_path, document_object_key(project_id))
    payload = build_document_payload(project_id, request)
    return now_message("已刷新文档状态。", payload)


def _ensure_business_project(project_id: str) -> dict[str, Any]:
    try:
        project = store.get_project_runtime_state(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    if normalize_bid_type(str(project.get("bidType") or "")) != "商务标":
        raise HTTPException(status_code=400, detail="该接口仅支持商务标项目。")
    return project


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


def _extract_rewrite_suggestion(reply: str, original_text: str, instruction: str) -> dict[str, Any]:
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
        "reason": reason or "已根据用户润色要求优化商务投标表达。",
        "riskTip": risk or "请确认替换文本未改变招标文件要求、承诺边界、金额、日期和主体信息。",
        "rawReply": reply,
    }


@router.post("/api/projects/{project_id}/document/business-chat")
async def business_document_chat(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    project = _ensure_business_project(project_id)
    message = str(data.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="请输入需要对话或润色的内容。")
    history = data.get("history") if isinstance(data.get("history"), list) else []
    document_state = store.get_document_state(project_id)
    fill_state = store.get_fill_state(project_id)
    context = {
        "projectId": project_id,
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
你是商务标投标文件共创助手。请只围绕商务标正文的语言润色、表达优化、风险提示和补写建议回答，不要编造项目事实，不要自动修改 Word 文件。

项目上下文：
{context}

最近对话：
{recent_history}

用户本次请求：
{message}

请用中文输出可直接给操作人参考的建议；如果用户要求润色，请给出“可替换文本”。
""".strip()

    try:
        result = await asyncio.to_thread(_send_business_chat_prompt, "商务标 S4 共创对话", prompt)
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
        raise HTTPException(status_code=502, detail=f"商务标 AI 对话调用 opencode 失败：{exc}") from exc


@router.post("/api/projects/{project_id}/document/business-rewrite/suggest")
async def suggest_business_document_rewrite(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    project = _ensure_business_project(project_id)
    original_text = str(data.get("originalText") or "").strip()
    instruction = str(data.get("instruction") or "").strip()
    if not original_text:
        raise HTTPException(status_code=400, detail="请粘贴需要润色的原文段落。")
    if len(original_text) > 4000:
        raise HTTPException(status_code=400, detail="原文段落过长，请先缩短到单个段落或小片段。")
    if not instruction:
        instruction = "在不改变事实、承诺边界、金额、日期和主体信息的前提下，优化为正式、审慎、可履约的商务投标表达。"

    prompt = f"""
你是商务标投标文件润色助手。请只改写用户提供的原文，不要扩写无依据事实，不要新增承诺，不要改变金额、日期、单位、项目名称、招标编号、法律责任边界。

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
        result = await asyncio.to_thread(_send_business_chat_prompt, "商务标 S4 受控润色建议", prompt)
        reply = str(result.get("reply") or "").strip()
        if not reply:
            raise RuntimeError("opencode 未返回有效润色建议。")
        suggestion = _extract_rewrite_suggestion(reply, original_text, instruction)
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
        raise HTTPException(status_code=502, detail=f"商务标受控润色建议生成失败：{exc}") from exc


@router.post("/api/projects/{project_id}/document/business-rewrite/apply")
async def apply_business_document_rewrite(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    _ensure_business_project(project_id)
    original_text = str(data.get("originalText") or "").strip()
    replacement_text = str(data.get("replacementText") or "").strip()
    if not original_text or not replacement_text:
        raise HTTPException(status_code=400, detail="原文和替换文本不能为空。")
    try:
        result = await asyncio.to_thread(
            apply_controlled_business_rewrite,
            project_id,
            original_text=original_text,
            replacement_text=replacement_text,
            operator=str(data.get("operator") or "当前用户"),
        )
        state = store.force_save_document(project_id)
        doc_path = ensure_document(project_id, state["fileName"], state["fallback"]["content"])
        refresh_document_session(doc_path)
        sync_document_to_minio(doc_path, document_object_key(project_id))
        return now_message(
            "已按审核后的替换文本更新商务标正文。",
            {
                "rewrite": result,
                "document": build_document_payload(project_id, request),
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"商务标正文受控替换失败：{exc}") from exc


@router.post("/api/projects/{project_id}/document/business-format")
async def apply_business_document_format(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    _ensure_business_project(project_id)
    preset = str(data.get("preset") or "standard").strip() or "standard"
    if preset not in BUSINESS_FORMAT_PRESETS:
        raise HTTPException(status_code=400, detail="未知商务标格式预设。")
    style_overrides = data.get("styleOverrides") if isinstance(data.get("styleOverrides"), dict) else None
    try:
        result = await asyncio.to_thread(
            apply_business_document_format_preset,
            project_id,
            preset,
            style_overrides,
        )
        state = store.apply_business_document_format(project_id, result)
        doc_path = ensure_document(project_id, state["fileName"], state["fallback"]["content"])
        refresh_document_session(doc_path)
        sync_document_to_minio(doc_path, document_object_key(project_id))
        return now_message(
            f"已应用{result.get('label') or '商务标格式'}。",
            {
                "format": result,
                "document": build_document_payload(project_id, request),
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"商务标格式切换失败：{exc}") from exc


@router.post("/api/projects/{project_id}/document/callback")
async def onlyoffice_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    _validate_callback_token(request)

    status = int(data.get("status") or 0)
    if status not in {2, 6} or not data.get("url"):
        return JSONResponse({"error": 0})

    document_state = store.get_document_state(project_id)
    callback_version_raw = request.query_params.get("oo_doc_version")
    if callback_version_raw:
        try:
            callback_version = int(callback_version_raw)
            current_version = int(document_state.get("version") or 1)
        except (TypeError, ValueError):
            callback_version = current_version = 0
        if callback_version and current_version and callback_version < current_version:
            # After S4 format normalization the editor is remounted with a new
            # versioned callback URL. Late callbacks from the old OnlyOffice
            # session must not overwrite the freshly formatted document.
            return JSONResponse({"error": 0, "ignored": "stale_document_version"})

    download_url = _validate_download_url(str(data["url"]))
    target_path = ensure_document(
        project_id,
        document_state["fileName"],
        document_state["fallback"]["content"],
    )

    try:
        await download_document_from_onlyoffice(
            download_url,
            target_path,
            max_bytes=settings.onlyoffice_download_max_bytes,
        )
        sync_document_to_minio(target_path, document_object_key(project_id))
    except (httpx.HTTPError, RuntimeError) as exc:
        return JSONResponse(status_code=502, content={"error": 1, "message": str(exc)})

    store.force_save_document(project_id)
    return JSONResponse({"error": 0})


@router.get("/api/projects/{project_id}/document/file")
async def download_document_file(project_id: str) -> FileResponse:
    return await download_document_file_by_name(project_id, "")


@router.get("/api/projects/{project_id}/document/file/{filename:path}")
async def download_document_file_by_name(project_id: str, filename: str) -> FileResponse:
    payload = store.get_document_state(project_id)
    doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
    return FileResponse(
        path=doc_path,
        media_type=WORD_MEDIA_TYPE,
        filename=payload["fileName"],
    )


@router.get("/api/projects/{project_id}/final-document")
async def get_final_document(project_id: str, request: Request) -> dict[str, Any]:
    payload = copy.deepcopy(store.get_final_document(project_id))
    payload["fileUrl"] = absolute_url(request, f"/api/projects/{project_id}/final-document/file")
    return payload


@router.get("/api/projects/{project_id}/final-document/file")
async def download_final_document_file(project_id: str) -> FileResponse:
    payload = store.get_document_state(project_id)
    doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
    return FileResponse(
        path=doc_path,
        media_type=WORD_MEDIA_TYPE,
        filename=payload["fileName"],
    )


@router.get("/api/projects/{project_id}/final-document/pdf")
async def prepare_final_document_pdf(project_id: str, request: Request) -> dict[str, Any]:
    payload = store.get_document_state(project_id)
    doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
    pdf_name = f"{Path(payload['fileName']).stem}.pdf"
    pdf_path = doc_path.with_suffix(".pdf")
    if not pdf_path.exists() or pdf_path.stat().st_mtime_ns < doc_path.stat().st_mtime_ns:
        source_url = f"{onlyoffice_backend_base_url(request).rstrip('/')}/api/projects/{project_id}/final-document/file"
        try:
            await _convert_document_to_pdf_via_onlyoffice(source_url, doc_path, pdf_path)
        except Exception as exc:
            try:
                await _convert_document_to_pdf_locally(doc_path, pdf_path)
            except Exception as fallback_exc:
                raise HTTPException(status_code=502, detail=f"PDF 生成失败：{exc}；本地兜底也失败：{fallback_exc}") from fallback_exc
    return {
        "message": "PDF 已生成。",
        "fileUrl": absolute_url(request, f"/api/projects/{project_id}/final-document/pdf/file"),
        "fileName": pdf_name,
        "format": "pdf",
    }


@router.get("/api/projects/{project_id}/final-document/pdf/file")
async def download_final_document_pdf(project_id: str) -> FileResponse:
    payload = store.get_document_state(project_id)
    doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
    pdf_path = doc_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF 尚未生成，请先点击下载 PDF。")
    return FileResponse(
        path=pdf_path,
        media_type=PDF_MEDIA_TYPE,
        filename=f"{Path(payload['fileName']).stem}.pdf",
    )
