from __future__ import annotations

from pathlib import Path
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
    ensure_review_document,
    review_document_object_key,
    review_document_path,
    sync_document_to_minio,
    write_document,
)
from app.services.store import store

router = APIRouter()

def _allowed_host(host: str | None, allowed_hosts: tuple[str, ...]) -> bool:
    if not host:
        return False
    normalized = host.lower()
    allowed = {item.lower() for item in allowed_hosts}
    return "*" in allowed or normalized in allowed


def _add_callback_token(url: str) -> str:
    token = settings.onlyoffice_callback_token
    if not token:
        return url
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("oo_callback_token", token))
    return urlunparse(parsed._replace(query=urlencode(query)))


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


def _ensure_review_document_file(project_id: str) -> tuple[dict[str, Any], Path]:
    state = store.get_review_document_state(project_id)
    path = review_document_path(project_id)
    if state.get("parseStatus") == "completed":
        path = ensure_review_document(project_id, state["fileName"], state.get("content") or "")
    return state, path


def _build_review_document_payload(project_id: str, request: Request) -> dict[str, Any]:
    state, path = _ensure_review_document_file(project_id)
    if state.get("parseStatus") != "completed":
        raise HTTPException(status_code=400, detail="缺口处理确认预览尚未生成，请先在缺口处理页提交确认。")

    quoted_name = quote(state["fileName"])
    browser_file_url = absolute_url(request, f"/api/projects/{project_id}/review-items/document/file/{quoted_name}")
    browser_callback_url = _add_callback_token(
        absolute_url(request, f"/api/projects/{project_id}/review-items/document/callback")
    )
    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = f"{onlyoffice_base}/api/projects/{project_id}/review-items/document/file/{quoted_name}"
    onlyoffice_callback_url = _add_callback_token(
        f"{onlyoffice_base}/api/projects/{project_id}/review-items/document/callback"
    )

    return {
        "status": "ready",
        "parseStatus": state["parseStatus"],
        "parsedAt": state["parsedAt"],
        "documentId": state["documentId"],
        "sourceFileName": state.get("sourceFileName") or "",
        "fileName": state["fileName"],
        "fileType": state["fileType"],
        "fileUrl": browser_file_url,
        "lastSavedAt": state.get("lastSavedAt") or "",
        "version": state.get("version") or 1,
        "onlyoffice": {
            "documentKey": build_editor_session_key(path, state.get("version") or 1),
            "title": state["fileName"],
            "fileUrl": onlyoffice_file_url,
            "callbackUrl": onlyoffice_callback_url,
            "browserFileUrl": browser_file_url,
            "browserCallbackUrl": browser_callback_url,
            "user": {
                "id": "user-1",
                "name": "当前用户",
            },
        },
        "fallback": {
            "content": state.get("content") or "",
        },
    }


def _value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/projects/{project_id}/review-items")
async def list_review_items(project_id: str) -> dict[str, Any]:
    return store.get_review_items(project_id)


@router.post("/api/projects/{project_id}/review-items/prepare")
async def prepare_review_items(project_id: str) -> dict[str, Any]:
    try:
        return store.prepare_review_document(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.get("/api/projects/{project_id}/review-items/document")
async def get_review_document(project_id: str, request: Request) -> dict[str, Any]:
    return _build_review_document_payload(project_id, request)


@router.put("/api/projects/{project_id}/review-items/document/save")
async def save_review_document(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    content = str(data.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="保存内容不能为空。")
    state = store.save_review_document_content(project_id, content)
    path = ensure_review_document(project_id, state["fileName"], content)
    write_document(path, state["fileName"], content)
    sync_document_to_minio(path, review_document_object_key(project_id))
    return now_message("缺口处理确认预览已保存并回写。", _build_review_document_payload(project_id, request))


@router.post("/api/projects/{project_id}/review-items/document/force-save")
async def force_save_review_document(project_id: str, request: Request) -> dict[str, Any]:
    state = store.force_save_review_document(project_id)
    path = ensure_review_document(project_id, state["fileName"], state.get("content") or "")
    write_document(path, state["fileName"], state.get("content") or "")
    sync_document_to_minio(path, review_document_object_key(project_id))
    return now_message("缺口处理确认预览已触发保存回写。", _build_review_document_payload(project_id, request))


@router.post("/api/projects/{project_id}/review-items/document/callback")
async def review_document_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    _validate_callback_token(request)

    status = int(data.get("status") or 0)
    if status not in {2, 6} or not data.get("url"):
        return JSONResponse({"error": 0})

    download_url = _validate_download_url(str(data["url"]))
    target_path = review_document_path(project_id)
    try:
        await download_document_from_onlyoffice(
            download_url,
            target_path,
            max_bytes=settings.onlyoffice_download_max_bytes,
        )
        sync_document_to_minio(target_path, review_document_object_key(project_id))
    except (httpx.HTTPError, RuntimeError) as exc:
        return JSONResponse(status_code=502, content={"error": 1, "message": str(exc)})

    store.force_save_review_document(project_id)
    return JSONResponse({"error": 0})


@router.get("/api/projects/{project_id}/review-items/document/file")
async def review_document_file(project_id: str) -> FileResponse:
    return await review_document_file_by_name(project_id, "")


@router.get("/api/projects/{project_id}/review-items/document/file/{filename:path}")
async def review_document_file_by_name(project_id: str, filename: str) -> FileResponse:
    state, path = _ensure_review_document_file(project_id)
    if state.get("parseStatus") != "completed" or not path.exists():
        raise HTTPException(status_code=400, detail="缺口处理确认预览尚未生成。")
    return FileResponse(path=path, media_type=WORD_MEDIA_TYPE, filename=state["fileName"])


@router.post("/api/projects/{project_id}/review-items/confirm")
async def confirm_review(project_id: str) -> dict[str, Any]:
    try:
        return store.confirm_review(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
