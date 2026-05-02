from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.utils import absolute_url, onlyoffice_backend_base_url
from app.core.config import settings
from app.services.onlyoffice_documents import build_editor_session_key
from app.services.store import store

router = APIRouter()
_OUTLINE_PREVIEW_EXTENSIONS = {".doc", ".docx", ".pdf"}


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


def _resolve_outline_tender_file(project_id: str, file_id: str) -> tuple[dict[str, Any], Path]:
    file_records, _ = store.get_parse_inputs(project_id)
    for item in file_records:
        if str(item.get("id") or "") != file_id:
            continue
        path = Path(str(item.get("path") or ""))
        if not path.exists():
            raise HTTPException(status_code=404, detail="招标文件不存在或已被删除。")
        return item, path
    raise HTTPException(status_code=404, detail="未找到对应的招标文件。")


def _document_type_by_suffix(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        return "pdf", "pdf"
    if suffix in {"xlsx", "xls"}:
        return suffix, "cell"
    if suffix in {"pptx", "ppt"}:
        return suffix, "slide"
    return suffix or "docx", "word"


def _build_tender_preview(project_id: str, request: Request, file_id_hint: str = "") -> dict[str, Any]:
    file_records, _ = store.get_parse_inputs(project_id)
    source_files = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
        }
        for item in file_records
    ]

    if not source_files:
        return {
            "status": "empty",
            "message": "暂无招标文件可预览，请先在“审核”模块上传并解析。",
            "sourceFiles": [],
            "onlyoffice": None,
        }

    candidate = None
    candidate_path = None
    ordered_records = list(file_records)
    if file_id_hint:
        ordered_records = sorted(
            ordered_records,
            key=lambda item: 0 if str(item.get("id") or "") == file_id_hint else 1,
        )

    for item in ordered_records:
        path = Path(str(item.get("path") or ""))
        suffix = path.suffix.lower()
        if suffix not in _OUTLINE_PREVIEW_EXTENSIONS:
            continue
        if not path.exists():
            continue
        candidate = item
        candidate_path = path
        break

    if not candidate or not candidate_path:
        return {
            "status": "unsupported",
            "message": "当前招标文件类型暂不支持 OnlyOffice 预览（支持 .doc/.docx/.pdf）。",
            "sourceFiles": source_files,
            "onlyoffice": None,
        }

    file_id = str(candidate.get("id") or "")
    file_name = str(candidate.get("name") or candidate_path.name)
    file_type, document_type = _document_type_by_suffix(candidate_path)
    quoted_name = quote(file_name)

    browser_file_url = absolute_url(
        request,
        f"/api/projects/{project_id}/outline/tender-files/{file_id}/file/{quoted_name}",
    )
    browser_callback_url = _add_callback_token(
        absolute_url(request, f"/api/projects/{project_id}/outline/tender-files/callback"),
    )

    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = (
        f"{onlyoffice_base}/api/projects/{project_id}/outline/tender-files/{file_id}/file/{quoted_name}"
    )
    onlyoffice_callback_url = _add_callback_token(
        f"{onlyoffice_base}/api/projects/{project_id}/outline/tender-files/callback",
    )

    return {
        "status": "ready",
        "message": "",
        "sourceFiles": source_files,
        "activeFile": {
            "id": file_id,
            "name": file_name,
            "fileType": file_type,
            "documentType": document_type,
        },
        "onlyoffice": {
            "documentKey": build_editor_session_key(candidate_path),
            "title": file_name,
            "fileType": file_type,
            "documentType": document_type,
            "fileUrl": onlyoffice_file_url,
            "callbackUrl": onlyoffice_callback_url,
            "browserFileUrl": browser_file_url,
            "browserCallbackUrl": browser_callback_url,
            "user": {
                "id": "user-1",
                "name": "当前用户",
            },
        },
    }


@router.get("/api/projects/{project_id}/outline")
async def get_outline(project_id: str, request: Request, fileId: str = "") -> dict[str, Any]:
    payload = store.get_outline_state(project_id)
    payload["tenderPreview"] = _build_tender_preview(project_id, request, fileId)
    return payload


@router.put("/api/projects/{project_id}/outline")
async def save_outline(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    payload = store.save_outline(project_id, data.get("nodes") or [])
    return {**payload, "message": "目录已保存"}


@router.post("/api/projects/{project_id}/outline/regenerate")
async def regenerate_outline(project_id: str) -> dict[str, Any]:
    payload = store.regenerate_outline(project_id)
    return {**payload, "message": "已重生成目录审核稿"}


@router.post("/api/projects/{project_id}/outline/confirm")
async def confirm_outline(project_id: str) -> dict[str, Any]:
    return store.confirm_outline(project_id)


@router.get("/api/projects/{project_id}/outline/tender-files/{file_id}/file")
async def get_outline_tender_file(project_id: str, file_id: str) -> FileResponse:
    return await get_outline_tender_file_by_name(project_id, file_id, "")


@router.get("/api/projects/{project_id}/outline/tender-files/{file_id}/file/{filename:path}")
async def get_outline_tender_file_by_name(
    project_id: str,
    file_id: str,
    filename: str,
) -> FileResponse:
    record, path = _resolve_outline_tender_file(project_id, file_id)
    _ = filename
    return FileResponse(
        path=path,
        filename=str(record.get("name") or path.name),
    )


@router.post("/api/projects/{project_id}/outline/tender-files/callback")
async def outline_tender_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    _ = project_id
    _ = data
    _validate_callback_token(request)
    return JSONResponse({"error": 0})
