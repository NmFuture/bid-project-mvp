from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings
from app.services.parsing import parse_tender_documents
from app.services.store import store

router = APIRouter()

_CHUNK_SIZE = 1024 * 1024


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
    return store.get_parse_result(project_id)


@router.post("/api/projects/{project_id}/parse-results/run")
async def run_parse_without_upload(project_id: str) -> dict[str, Any]:
    tender_files, template_files = store.get_parse_inputs(project_id)
    if not tender_files:
        raise HTTPException(status_code=400, detail="当前项目还没有已上传的招标文件。")
    summary, parse_storage = parse_tender_documents(project_id, tender_files)
    parse_result = store.complete_parse(
        project_id,
        tender_files,
        template_files,
        summary=summary,
        parse_storage=parse_storage,
    )
    return {**parse_result, "message": "解析完成"}


@router.post("/api/projects/{project_id}/parse-results/upload-and-run")
async def upload_and_parse(
    project_id: str,
    tenderFiles: list[UploadFile] | None = File(default=None),
    templateFiles: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    existing_tender, existing_template = store.get_parse_inputs(project_id)
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
        merged_template = [*existing_template, *saved_template]
    else:
        merged_template = existing_template

    summary, parse_storage = parse_tender_documents(project_id, active_tender)
    parse_result = store.complete_parse(
        project_id,
        active_tender,
        merged_template,
        summary=summary,
        parse_storage=parse_storage,
    )
    return {
        **parse_result,
        "message": "上传成功，已自动完成解析。",
    }
