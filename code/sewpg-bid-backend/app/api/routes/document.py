from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.utils import absolute_url, now_message, onlyoffice_backend_base_url
from app.core.config import settings
from app.services.onlyoffice_documents import (
    WORD_MEDIA_TYPE,
    build_editor_session_key,
    download_document_from_onlyoffice,
    ensure_document,
    refresh_document_session,
    write_document,
)
from app.services.store import store

router = APIRouter()


def _add_callback_token(url: str) -> str:
    token = settings.onlyoffice_callback_token
    if not token:
        return url
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("oo_callback_token", token))
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


def build_document_payload(project_id: str, request: Request) -> dict[str, Any]:
    payload = store.get_document_state(project_id)
    doc_path = ensure_document(
        project_id,
        payload["fileName"],
        payload["fallback"]["content"],
    )

    quoted_name = quote(payload["fileName"])
    browser_file_url = absolute_url(request, f"/api/projects/{project_id}/document/file/{quoted_name}")
    browser_callback_url = _add_callback_token(
        absolute_url(request, f"/api/projects/{project_id}/document/callback")
    )
    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = f"{onlyoffice_base}/api/projects/{project_id}/document/file/{quoted_name}"
    onlyoffice_callback_url = _add_callback_token(
        f"{onlyoffice_base}/api/projects/{project_id}/document/callback"
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
    payload = build_document_payload(project_id, request)
    return now_message("已刷新文档状态。", payload)


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

    download_url = _validate_download_url(str(data["url"]))
    document_state = store.get_document_state(project_id)
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
