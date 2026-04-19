from __future__ import annotations

import copy
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.utils import absolute_url, now_message, onlyoffice_backend_base_url
from app.services.onlyoffice_documents import (
    WORD_MEDIA_TYPE,
    download_document_from_onlyoffice,
    ensure_document,
    write_document,
)
from app.services.store import store

router = APIRouter()


def build_document_payload(project_id: str, request: Request) -> dict[str, Any]:
    payload = store.get_document_state(project_id)
    doc_path = ensure_document(
        project_id,
        payload["fileName"],
        payload["fallback"]["content"],
    )

    quoted_name = quote(payload["fileName"])
    browser_file_url = absolute_url(request, f"/api/projects/{project_id}/document/file/{quoted_name}")
    browser_callback_url = absolute_url(request, f"/api/projects/{project_id}/document/callback")
    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = f"{onlyoffice_base}/api/projects/{project_id}/document/file/{quoted_name}"
    onlyoffice_callback_url = f"{onlyoffice_base}/api/projects/{project_id}/document/callback"

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
    payload = build_document_payload(project_id, request)
    return now_message("已刷新文档状态。", payload)


@router.post("/api/projects/{project_id}/document/callback")
async def onlyoffice_callback(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    status = int(data.get("status") or 0)
    if status in {2, 6} and data.get("url"):
        target_path = ensure_document(
            project_id,
            store.get_document_state(project_id)["fileName"],
            store.get_document_state(project_id)["fallback"]["content"],
        )
        await download_document_from_onlyoffice(str(data["url"]), target_path)
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
