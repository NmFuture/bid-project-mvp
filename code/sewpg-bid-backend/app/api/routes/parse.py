from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from uuid import uuid4

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.api.utils import absolute_url, onlyoffice_backend_base_url
from app.core.config import settings
from app.services.onlyoffice_documents import WORD_MEDIA_TYPE, build_editor_session_key
from app.services.parsing import (
    IMAGE_SUFFIXES,
    extract_docx_text,
    materialize_appendix_docx,
    materialize_parse_appendix_docx_assets,
    parse_tender_documents,
)
from app.services.store import store

router = APIRouter()

_CHUNK_SIZE = 1024 * 1024


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


def _safe_display_name(filename: str | None, index: int) -> str:
    name = Path(filename or f"file-{index}").name.strip().replace("\x00", "")
    name = name.replace("/", "_").replace("\\", "_")
    if not name or name in {".", ".."}:
        name = f"file-{index}"

    suffix = Path(name).suffix
    stem = Path(name).stem or f"file-{index}"
    if len(name) > 180:
        stem = stem[:120]
        suffix = suffix[:20]
        name = f"{stem}{suffix}"
    return name


def _validate_upload_name(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.allowed_upload_extensions:
        allowed = ", ".join(settings.allowed_upload_extensions)
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix or '无扩展名'}。当前仅允许：{allowed}",
        )
    return suffix


async def _save_one_upload(
    target_dir: Path,
    folder: str,
    index: int,
    upload: UploadFile,
) -> dict[str, Any]:
    display_name = _safe_display_name(upload.filename, index)
    _validate_upload_name(display_name)
    stored_name = f"{folder}-{index}-{uuid4().hex}{Path(display_name).suffix}"
    path = target_dir / stored_name
    temp_path = target_dir / f".{stored_name}.part"

    size = 0
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_file_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"文件 {display_name} 超过大小限制 "
                            f"{store.format_size(settings.max_upload_file_size_bytes)}。"
                        ),
                    )
                handle.write(chunk)
        if size <= 0:
            raise HTTPException(status_code=400, detail=f"文件 {display_name} 为空。")
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    return {
        "id": f"{folder[:3].upper()}-{index}",
        "name": display_name,
        "stored_name": stored_name,
        "size_bytes": size,
        "size_label": store.format_size(size),
        "content_type": upload.content_type or "",
        "path": str(path),
    }


def _docx_has_extractable_text(path: Path) -> bool:
    try:
        return bool(extract_docx_text(path).strip())
    except Exception:
        return False


def _mark_deferred_ocr_for_templates(template_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in template_files:
        path = Path(str(item.get("path") or ""))
        if path.suffix.lower() in {".pdf", *IMAGE_SUFFIXES}:
            item["visualParsing"] = {
                "status": "deferred",
                "message": "模板文件为图片或 PDF，后续解析或目录生成将按需使用视觉模型读取。",
            }
        elif path.suffix.lower() == ".docx" and not _docx_has_extractable_text(path):
            item["visualParsing"] = {
                "status": "deferred",
                "message": "模板 DOCX 未提取到可用文本，后续解析或目录生成将按需使用视觉模型读取。",
            }
    return template_files


async def save_uploads(project_id: str, folder: str, files: list[UploadFile]) -> list[dict[str, Any]]:
    return await save_uploads_with_offset(project_id, folder, files, start_index=1)


async def save_uploads_with_offset(
    project_id: str,
    folder: str,
    files: list[UploadFile],
    start_index: int,
) -> list[dict[str, Any]]:
    target_dir = settings.uploads_dir / project_id / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict[str, Any]] = []
    try:
        for index, upload in enumerate(files, start=start_index):
            saved.append(await _save_one_upload(target_dir, folder, index, upload))
    except HTTPException:
        for item in saved:
            Path(str(item.get("path", ""))).unlink(missing_ok=True)
        raise
    return saved


@router.get("/api/projects/{project_id}/parse-results")
async def get_parse_results(project_id: str) -> dict[str, Any]:
    return materialize_parse_appendix_docx_assets(project_id, store.get_parse_result(project_id))


@router.get("/api/projects/{project_id}/parse-results/progress")
async def get_parse_progress(project_id: str) -> dict[str, Any]:
    return store.get_parse_progress(project_id)


def _document_type_by_suffix(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".") or "docx"
    if suffix == "pdf":
        return "pdf", "pdf"
    if suffix in {"xlsx", "xls"}:
        return suffix, "cell"
    if suffix in {"pptx", "ppt"}:
        return suffix, "slide"
    return suffix, "word"


def _resolve_appendix_docx(project_id: str, appendix_id: str) -> tuple[dict[str, Any], Path]:
    parse_result = store.get_parse_result(project_id)
    structured = parse_result.get("structured") if isinstance(parse_result, dict) else {}
    appendices = structured.get("appendices") if isinstance(structured, dict) else []
    for appendix in appendices if isinstance(appendices, list) else []:
        if not isinstance(appendix, dict):
            continue
        if str(appendix.get("id") or "") != appendix_id:
            continue
        item = materialize_appendix_docx(project_id, appendix)
        path = Path(str(item.get("docxPath") or ""))
        if not path.exists():
            raise HTTPException(status_code=404, detail="附表 Word 文件不存在。")
        return item, path
    raise HTTPException(status_code=404, detail="未找到对应的附表。")


def _build_appendix_preview(project_id: str, appendix_id: str, request: Request) -> dict[str, Any]:
    appendix, path = _resolve_appendix_docx(project_id, appendix_id)
    file_name = path.name
    file_type, document_type = _document_type_by_suffix(path)
    quoted_name = quote(file_name)
    browser_file_url = absolute_url(
        request,
        f"/api/projects/{project_id}/parse-results/appendices/{appendix_id}/file/{quoted_name}",
    )
    browser_callback_url = _add_callback_token(
        absolute_url(request, f"/api/projects/{project_id}/parse-results/appendices/callback"),
    )
    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = (
        f"{onlyoffice_base}/api/projects/{project_id}/parse-results/appendices/{appendix_id}/file/{quoted_name}"
    )
    onlyoffice_callback_url = _add_callback_token(
        f"{onlyoffice_base}/api/projects/{project_id}/parse-results/appendices/callback",
    )
    return {
        **appendix,
        "fileUrl": browser_file_url,
        "onlyoffice": {
            "documentKey": build_editor_session_key(path),
            "title": appendix.get("title") or file_name,
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


@router.get("/api/projects/{project_id}/parse-results/appendices/{appendix_id}/preview")
async def get_appendix_preview(project_id: str, appendix_id: str, request: Request) -> dict[str, Any]:
    return _build_appendix_preview(project_id, appendix_id, request)


@router.get("/api/projects/{project_id}/parse-results/appendices/{appendix_id}/file")
async def get_appendix_file(project_id: str, appendix_id: str) -> FileResponse:
    return await get_appendix_file_by_name(project_id, appendix_id, "")


@router.get("/api/projects/{project_id}/parse-results/appendices/{appendix_id}/file/{filename:path}")
async def get_appendix_file_by_name(project_id: str, appendix_id: str, filename: str) -> FileResponse:
    appendix, path = _resolve_appendix_docx(project_id, appendix_id)
    _ = filename
    return FileResponse(
        path=path,
        media_type=WORD_MEDIA_TYPE,
        filename=Path(str(appendix.get("workspacePath") or path.name)).name,
    )


@router.post("/api/projects/{project_id}/parse-results/appendices/callback")
async def appendix_onlyoffice_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    _ = project_id
    _ = data
    _validate_callback_token(request)
    return JSONResponse({"error": 0})


def _progress_callback(project_id: str):
    def update(event: str, details: dict[str, Any] | None = None) -> None:
        payload = details or {}
        if event == "upload_ready":
            store.update_parse_progress(
                project_id,
                percentage=15,
                summary=f"已保存 {payload.get('fileCount', 0)} 个招标文件，准备提取文本。",
                event_step="upload",
                event_message=f"已保存 {payload.get('fileCount', 0)} 个招标文件。",
            )
        elif event == "extract_started":
            store.update_parse_progress(
                project_id,
                percentage=25,
                summary="正在提取招标文件文本。",
                event_step="extract",
                event_message=f"开始提取 {payload.get('fileCount', 0)} 个招标文件。",
            )
        elif event == "file_extracted":
            store.update_parse_progress(
                project_id,
                percentage=40,
                summary="招标文件文本提取中。",
                event_step="extract",
                event_message=f"{payload.get('fileName', '招标文件')} 已提取 {payload.get('textLength', 0)} 字。",
            )
        elif event == "appendices_extracted":
            store.update_parse_progress(
                project_id,
                percentage=55,
                summary="正在识别附表并生成空表 Word。",
                event_step="appendix",
                event_message=(
                    f"识别附表 {payload.get('appendixCount', 0)} 个，"
                    f"已生成 {payload.get('generatedCount', 0)} 个 Word 空表。"
                ),
            )
        elif event == "skill_manifest_ready":
            store.update_parse_progress(
                project_id,
                percentage=65,
                summary="解析 Skill 输入已准备，正在调用 opencode。",
                event_step="skill",
                event_message="S1 解析 Skill manifest 已生成。",
            )
        elif event == "opencode_delta":
            store.update_parse_progress(
                project_id,
                percentage=80,
                summary="opencode 正在返回解析输出。",
                event_step="opencode",
                event_message="收到 opencode 解析输出片段。",
                opencode_output=payload,
            )
        elif event == "complete":
            store.update_parse_progress(
                project_id,
                status="completed",
                percentage=100,
                summary=f"解析完成，提取 {payload.get('extractedCount', 0)} 条结构化要求。",
                event_step="complete",
                event_level="success",
                event_message=(
                    f"解析完成，提取 {payload.get('extractedCount', 0)} 条结构化要求，"
                    f"附表 {payload.get('appendixCount', 0)} 个。"
                ),
            )

    return update


@router.post("/api/projects/{project_id}/parse-results/run")
async def run_parse_without_upload(project_id: str) -> dict[str, Any]:
    tender_files, template_files = store.get_parse_inputs(project_id, include_fallback=False)
    if not tender_files:
        raise HTTPException(status_code=400, detail="当前项目还没有已上传的招标文件。")
    store.start_parse_progress(project_id)
    store.update_parse_progress(
        project_id,
        percentage=15,
        summary="正在复用已上传招标文件进行解析。",
        event_step="upload",
        event_message=f"复用 {len(tender_files)} 个已上传招标文件。",
    )
    try:
        summary, parse_storage = parse_tender_documents(
            project_id,
            tender_files,
            progress_callback=_progress_callback(project_id),
        )
    except Exception as exc:
        store.update_parse_progress(
            project_id,
            status="failed",
            percentage=100,
            summary=f"解析失败：{exc}",
            event_step="failed",
            event_level="error",
            event_message=f"解析失败：{exc}",
        )
        raise
    parse_result = store.complete_parse(
        project_id,
        tender_files,
        template_files,
        summary=summary,
        parse_storage=parse_storage,
    )
    parse_result = materialize_parse_appendix_docx_assets(project_id, parse_result)
    return {**parse_result, "message": "解析完成"}


@router.post("/api/projects/{project_id}/parse-results/upload-and-run")
async def upload_and_parse(
    project_id: str,
    tenderFiles: list[UploadFile] | None = File(default=None),
    templateFiles: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    existing_tender, existing_template = store.get_parse_inputs(project_id, include_fallback=False)
    tender_files = tenderFiles or []
    template_files = templateFiles or []

    if tender_files:
        active_tender = await save_uploads(project_id, "tender", tender_files)
    else:
        active_tender = existing_tender

    if not active_tender:
        raise HTTPException(status_code=400, detail="请至少上传 1 个招标文件。")

    if template_files:
        saved_template = await save_uploads_with_offset(
            project_id,
            "template",
            template_files,
            start_index=len(existing_template) + 1,
        )
        merged_template = [*existing_template, *_mark_deferred_ocr_for_templates(saved_template)]
    else:
        merged_template = existing_template

    store.start_parse_progress(project_id)
    _progress_callback(project_id)("upload_ready", {"fileCount": len(active_tender)})
    try:
        summary, parse_storage = parse_tender_documents(
            project_id,
            active_tender,
            progress_callback=_progress_callback(project_id),
        )
    except Exception as exc:
        store.update_parse_progress(
            project_id,
            status="failed",
            percentage=100,
            summary=f"解析失败：{exc}",
            event_step="failed",
            event_level="error",
            event_message=f"解析失败：{exc}",
        )
        raise
    parse_result = store.complete_parse(
        project_id,
        active_tender,
        merged_template,
        summary=summary,
        parse_storage=parse_storage,
    )
    parse_result = materialize_parse_appendix_docx_assets(project_id, parse_result)
    return {
        **parse_result,
        "message": "上传成功，已自动完成解析。",
    }


@router.post("/api/projects/{project_id}/template-files/upload")
async def upload_template_files(
    project_id: str,
    templateFiles: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    existing_tender, existing_template = store.get_parse_inputs(project_id, include_fallback=False)
    parse_result = store.get_parse_result(project_id)
    files = templateFiles or []

    if not existing_tender or parse_result.get("status") != "completed":
        raise HTTPException(status_code=400, detail="请先在“审核”模块完成招标文件解析并确认参与投标。")

    if not files:
        raise HTTPException(status_code=400, detail="请至少上传 1 个模板文件。")

    saved_template = await save_uploads_with_offset(
        project_id,
        "template",
        files,
        start_index=len(existing_template) + 1,
    )
    merged_template = [*existing_template, *_mark_deferred_ocr_for_templates(saved_template)]
    payload = store.update_template_files(project_id, merged_template)
    return {
        **payload,
        "message": "模板文件上传成功。",
    }
