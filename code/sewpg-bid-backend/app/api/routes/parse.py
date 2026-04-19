from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings
from app.services.parsing import parse_tender_documents
from app.services.store import store

router = APIRouter()


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
    for index, upload in enumerate(files, start=start_index):
        raw = await upload.read()
        filename = upload.filename or f"file-{index}"
        path = target_dir / filename
        path.write_bytes(raw)
        saved.append(
            {
                "id": f"{folder[:3].upper()}-{index}",
                "name": filename,
                "size_bytes": len(raw),
                "size_label": store.format_size(len(raw)),
                "content_type": upload.content_type or "",
                "path": str(path),
            }
        )
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
