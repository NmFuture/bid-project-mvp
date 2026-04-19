from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.utils import absolute_url, now_message, onlyoffice_backend_base_url
from app.services.onlyoffice_documents import (
    WORD_MEDIA_TYPE,
    download_document_from_onlyoffice,
    write_document,
)
from app.services.store import store

router = APIRouter()


def _review_document_path(project_id: str) -> Path:
    from app.core.config import settings

    return settings.documents_dir / f"{project_id}-review.docx"


def _ensure_review_document_file(project_id: str) -> tuple[dict[str, Any], Path]:
    state = store.get_review_document_state(project_id)
    path = _review_document_path(project_id)
    if state.get("parseStatus") == "completed":
        if not path.exists():
            write_document(path, state["fileName"], state.get("content") or "")
    return state, path


def _build_review_document_payload(project_id: str, request: Request) -> dict[str, Any]:
    state, path = _ensure_review_document_file(project_id)
    if state.get("parseStatus") != "completed":
        raise HTTPException(status_code=400, detail="S6 解析文档尚未生成，请先在 S5 提交审核触发解析。")

    quoted_name = quote(state["fileName"])
    browser_file_url = absolute_url(request, f"/api/projects/{project_id}/review-items/document/file/{quoted_name}")
    browser_callback_url = absolute_url(request, f"/api/projects/{project_id}/review-items/document/callback")
    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = f"{onlyoffice_base}/api/projects/{project_id}/review-items/document/file/{quoted_name}"
    onlyoffice_callback_url = f"{onlyoffice_base}/api/projects/{project_id}/review-items/document/callback"

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
            "documentKey": state["documentKey"],
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
    write_document(_review_document_path(project_id), state["fileName"], content)
    return now_message("S6 预览文档已保存并回写。", _build_review_document_payload(project_id, request))


@router.post("/api/projects/{project_id}/review-items/document/force-save")
async def force_save_review_document(project_id: str, request: Request) -> dict[str, Any]:
    state = store.force_save_review_document(project_id)
    write_document(_review_document_path(project_id), state["fileName"], state.get("content") or "")
    return now_message("S6 文档已触发保存回写。", _build_review_document_payload(project_id, request))


@router.post("/api/projects/{project_id}/review-items/document/callback")
async def review_document_callback(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    status = int(data.get("status") or 0)
    if status in {2, 6} and data.get("url"):
        target_path = _review_document_path(project_id)
        await download_document_from_onlyoffice(str(data["url"]), target_path)
        store.force_save_review_document(project_id)
    return JSONResponse({"error": 0})


@router.get("/api/projects/{project_id}/review-items/document/file")
async def review_document_file(project_id: str) -> FileResponse:
    return await review_document_file_by_name(project_id, "")


@router.get("/api/projects/{project_id}/review-items/document/file/{filename:path}")
async def review_document_file_by_name(project_id: str, filename: str) -> FileResponse:
    state, path = _ensure_review_document_file(project_id)
    if state.get("parseStatus") != "completed" or not path.exists():
        raise HTTPException(status_code=400, detail="S6 解析文档尚未生成。")
    return FileResponse(path=path, media_type=WORD_MEDIA_TYPE, filename=state["fileName"])


@router.post("/api/projects/{project_id}/review-items/confirm")
async def confirm_review(project_id: str) -> dict[str, Any]:
    try:
        return store.confirm_review(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
