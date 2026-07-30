from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.api.utils import minio_streaming_response, onlyoffice_backend_base_url
from app.services.auth_service import current_user
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.business_audit_service import business_audit_service
from app.services.business_directory_service import business_directory_service
from app.services.business_document_service import business_document_service
from app.services.business_generation_service import business_generation_service
from app.services.business_material_store import business_material_store
from app.services.bid_ocr_service import business_ocr_service
from app.services.bid_parse_service import business_parse_service
from app.services.bid_project_service import business_project_service
from app.services.material_tags import normalize_material_tags
from app.services.business_wiki_generation import generate_business_wiki

router = APIRouter()


def _ensure_business_project(project_id: str) -> dict[str, Any]:
    return business_project_service.ensure_project(project_id)


def _business_payload(data: dict[str, Any] | None = None) -> dict[str, Any]:
    return business_project_service.payload(data)


@router.get("/api/business/projects")
async def list_business_projects(
    status: str = "",
    reviewDecision: str = "",
    dateRange: str = "",
    page: int = 1,
    pageSize: int = 12,
) -> dict[str, Any]:
    return business_project_service.list(
        status=status,
        review_decision=reviewDecision,
        date_range=dateRange,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/business/projects")
async def create_business_project(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return business_project_service.create(data)


@router.get("/api/business/projects/{project_id}")
async def get_business_project(project_id: str) -> dict[str, Any]:
    return business_project_service.get(project_id)


@router.put("/api/business/projects/{project_id}")
async def update_business_project(project_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_project_service.update(project_id, data)


@router.delete("/api/business/projects/{project_id}")
async def delete_business_project(project_id: str) -> dict[str, str]:
    return await business_project_service.delete(project_id)


@router.get("/api/business/projects/{project_id}/materials-path")
async def get_business_materials_path(project_id: str) -> dict[str, Any]:
    return business_project_service.materials_path(project_id)


@router.get("/api/business/projects/{project_id}/template-fallback")
async def get_business_template_fallback(project_id: str) -> dict[str, Any]:
    return await business_project_service.template_fallback(project_id)


@router.put("/api/business/projects/{project_id}/template-fallback")
async def update_business_template_fallback(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_project_service.update_template_fallback(project_id, data)


@router.put("/api/business/projects/{project_id}/stages/{stage}")
async def update_business_stage(
    project_id: str,
    stage: int,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return business_project_service.update_stage(project_id, stage, data)


@router.get("/api/business/projects/{project_id}/stages")
async def list_business_stages(project_id: str) -> list[dict[str, Any]]:
    return business_project_service.stages(project_id)


@router.get("/api/business/projects/{project_id}/materials/parse-status")
async def get_business_material_parse_status(project_id: str) -> dict[str, Any]:
    return business_project_service.parse_status(project_id)


@router.get("/api/business/projects/{project_id}/ocr/tasks")
async def list_business_ocr_tasks(
    project_id: str,
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await business_ocr_service.list_tasks(project_id)


@router.post("/api/business/projects/{project_id}/ocr/tasks")
async def run_business_ocr(
    project_id: str,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        content = await file.read()
        return await business_ocr_service.run(
            project_id=project_id,
            file_name=str(file.filename or "ocr-file"),
            content=content,
            mime_type=str(file.content_type or ""),
            user=user,
        )
    finally:
        await file.close()


@router.get("/api/business/projects/{project_id}/ocr/tasks/{task_id}")
async def get_business_ocr_task(
    project_id: str,
    task_id: str,
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await business_ocr_service.detail(project_id, task_id)


@router.post("/api/business/projects/{project_id}/ocr/candidates/{candidate_id}/confirm")
async def confirm_business_ocr_candidate(
    project_id: str,
    candidate_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await business_ocr_service.confirm_candidate(project_id, candidate_id, data, user=user)


@router.get("/api/business/projects/{project_id}/parse-results")
async def get_business_parse_results(project_id: str) -> dict[str, Any]:
    return await business_parse_service.results(project_id)


@router.get("/api/business/projects/{project_id}/parse-results/progress")
async def get_business_parse_progress(project_id: str) -> dict[str, Any]:
    return await business_parse_service.progress(project_id)


@router.post("/api/business/projects/{project_id}/parse-results/cancel")
async def cancel_business_parse(project_id: str) -> dict[str, Any]:
    return await business_parse_service.cancel(project_id)


@router.get("/api/business/projects/{project_id}/parse-results/appendices/{appendix_id}/preview")
async def get_business_appendix_preview(project_id: str, appendix_id: str, request: Request) -> dict[str, Any]:
    return await business_parse_service.appendix_preview(project_id, appendix_id, request)


@router.api_route(
    "/api/business/projects/{project_id}/parse-results/appendices/{appendix_id}/file",
    methods=["GET", "HEAD"],
)
async def get_business_appendix_file(project_id: str, appendix_id: str) -> FileResponse:
    return await business_parse_service.appendix_file(project_id, appendix_id)


@router.api_route(
    "/api/business/projects/{project_id}/parse-results/appendices/{appendix_id}/file/{filename:path}",
    methods=["GET", "HEAD"],
)
async def get_business_appendix_file_by_name(project_id: str, appendix_id: str, filename: str) -> FileResponse:
    return await business_parse_service.appendix_file(project_id, appendix_id, filename)


@router.post("/api/business/projects/{project_id}/parse-results/appendices/callback")
async def business_appendix_onlyoffice_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await business_parse_service.appendix_callback(project_id, request, data)


@router.post("/api/business/projects/{project_id}/parse-results/appendices/{appendix_id}/approve")
async def approve_business_appendix_asset(
    project_id: str,
    appendix_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_parse_service.approve_appendix_asset(project_id, appendix_id, data)


@router.post("/api/business/projects/{project_id}/parse-results/appendices/approve")
async def approve_all_business_appendix_assets(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_parse_service.approve_all_appendix_assets(project_id, data)


@router.post("/api/business/projects/{project_id}/parse-results/business-scoring/approve")
async def approve_business_scoring_asset(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_parse_service.approve_business_scoring(project_id, data)


@router.get("/api/business/projects/{project_id}/parse-results/commitment-letters/{letter_id}/preview")
async def get_business_commitment_letter_preview(project_id: str, letter_id: str, request: Request) -> dict[str, Any]:
    return await business_parse_service.commitment_letter_preview(project_id, letter_id, request)


@router.api_route(
    "/api/business/projects/{project_id}/parse-results/commitment-letters/{letter_id}/file",
    methods=["GET", "HEAD"],
)
async def get_business_commitment_letter_file(project_id: str, letter_id: str) -> FileResponse:
    return await business_parse_service.commitment_letter_file(project_id, letter_id)


@router.api_route(
    "/api/business/projects/{project_id}/parse-results/commitment-letters/{letter_id}/file/{filename:path}",
    methods=["GET", "HEAD"],
)
async def get_business_commitment_letter_file_by_name(project_id: str, letter_id: str, filename: str) -> FileResponse:
    return await business_parse_service.commitment_letter_file(project_id, letter_id, filename)


@router.post("/api/business/projects/{project_id}/parse-results/commitment-letters/callback")
async def business_commitment_letter_onlyoffice_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await business_parse_service.commitment_letter_callback(project_id, request, data)


@router.post("/api/business/projects/{project_id}/parse-results/commitment-letters/{letter_id}/approve")
async def approve_business_commitment_letter_asset(
    project_id: str,
    letter_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_parse_service.approve_commitment_letter_asset(project_id, letter_id, data)


@router.post("/api/business/projects/{project_id}/parse-results/commitment-letters/approve")
async def approve_all_business_commitment_letter_assets(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_parse_service.approve_all_commitment_letter_assets(project_id, data)


@router.post("/api/business/projects/{project_id}/parse-results/run")
async def run_business_parse(project_id: str, response: Response) -> dict[str, Any]:
    payload = await business_parse_service.run_without_upload(project_id)
    if str(payload.get("status") or "") == "queued":
        response.status_code = 202
    return payload


@router.post("/api/business/projects/{project_id}/parse-results/upload-and-run")
async def upload_and_parse_business(
    project_id: str,
    response: Response,
    tenderFiles: list[UploadFile] | None = File(default=None),
    templateFiles: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    payload = await business_parse_service.upload_and_parse(
        project_id,
        tender_files=tenderFiles,
        template_files=templateFiles,
    )
    if str(payload.get("status") or "") == "queued":
        response.status_code = 202
    return payload


@router.post("/api/business/projects/{project_id}/template-files/upload")
async def upload_business_template_files(
    project_id: str,
    templateFiles: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    return await business_parse_service.upload_template_files(project_id, template_files=templateFiles)


@router.get("/api/business/projects/{project_id}/directory-generation")
async def get_business_directory_generation(project_id: str) -> dict[str, Any]:
    return await business_directory_service.generation_status(project_id)


@router.post("/api/business/projects/{project_id}/directory-generation/run")
async def run_business_directory_generation(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await business_directory_service.run_generation(project_id, data)


@router.get("/api/business/projects/{project_id}/outline")
async def get_business_outline(project_id: str, request: Request, fileId: str = "") -> dict[str, Any]:
    return await business_directory_service.outline(project_id, request, file_id=fileId)


@router.put("/api/business/projects/{project_id}/outline")
async def save_business_outline(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_directory_service.save_outline(project_id, data)


@router.post("/api/business/projects/{project_id}/outline/confirm")
async def confirm_business_outline(project_id: str) -> dict[str, Any]:
    return await business_directory_service.confirm_outline(project_id)


@router.get("/api/business/projects/{project_id}/outline/tender-files/{file_id}/file")
async def get_business_outline_tender_file(project_id: str, file_id: str) -> FileResponse:
    return await business_directory_service.tender_file(project_id, file_id)


@router.get("/api/business/projects/{project_id}/outline/tender-files/{file_id}/file/{filename:path}")
async def get_business_outline_tender_file_by_name(
    project_id: str,
    file_id: str,
    filename: str,
) -> FileResponse:
    return await business_directory_service.tender_file(project_id, file_id, filename)


@router.post("/api/business/projects/{project_id}/outline/tender-files/callback")
async def business_outline_tender_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await business_directory_service.tender_callback(project_id, request, data)


@router.get("/api/business/projects/{project_id}/fill-generation")
async def get_business_fill_generation(project_id: str) -> dict[str, Any]:
    return await business_generation_service.status(project_id)


@router.post("/api/business/projects/{project_id}/fill-generation/run")
async def run_business_fill_generation(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> JSONResponse:
    return await business_generation_service.run(project_id, request, data, user)


@router.get("/api/business/projects/{project_id}/document")
async def get_business_document(project_id: str, request: Request) -> dict[str, Any]:
    return await business_document_service.document(project_id, request)


@router.put("/api/business/projects/{project_id}/document/save")
async def save_business_document(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_document_service.save_document(project_id, request, data)


@router.get("/api/business/projects/{project_id}/document/file")
async def download_business_document_file(project_id: str) -> FileResponse:
    return await business_document_service.document_file(project_id)


@router.get("/api/business/projects/{project_id}/document/file/{filename:path}")
async def download_business_document_file_by_name(project_id: str, filename: str) -> FileResponse:
    return await business_document_service.document_file(project_id, filename)


@router.post("/api/business/projects/{project_id}/document/callback")
async def business_onlyoffice_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await business_document_service.document_callback(project_id, request, data)


@router.post("/api/business/projects/{project_id}/document/business-chat")
async def business_document_chat(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_document_service.chat(project_id, data)


@router.post("/api/business/projects/{project_id}/document/business-rewrite/suggest")
async def suggest_business_document_rewrite(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_document_service.suggest_rewrite(project_id, data)


@router.post("/api/business/projects/{project_id}/document/business-rewrite/apply")
async def apply_business_document_rewrite(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_document_service.apply_rewrite(project_id, request, data)


@router.post("/api/business/projects/{project_id}/document/business-format")
async def apply_business_document_format(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await business_document_service.apply_format(project_id, request, data)


@router.get("/api/business/projects/{project_id}/final-document")
async def get_business_final_document(project_id: str, request: Request) -> dict[str, Any]:
    return await business_document_service.final_document(project_id, request)


@router.get("/api/business/projects/{project_id}/final-document/file")
async def download_business_final_document_file(project_id: str) -> FileResponse:
    return await business_document_service.final_document_file(project_id)


@router.get("/api/business/projects/{project_id}/final-document/pdf")
async def prepare_business_final_document_pdf(project_id: str, request: Request) -> dict[str, Any]:
    return await business_document_service.final_document_pdf(project_id, request)


@router.get("/api/business/projects/{project_id}/final-document/pdf/file")
async def download_business_final_document_pdf(project_id: str) -> FileResponse:
    return await business_document_service.final_document_pdf_file(project_id)


@router.get("/api/business/materials/identity-options")
async def business_identity_options() -> dict[str, Any]:
    return await business_material_store.identity_options()


@router.get("/api/business/materials/raw/tree")
async def business_raw_tree() -> dict[str, Any]:
    return await business_material_store.raw_tree()


@router.get("/api/business/materials/raw/files")
async def business_raw_files(
    folderPath: str = "",
    projectId: str = "",
    customerName: str = "",
    materialTier: str = "",
    cleanStatus: str = "",
    businessMaterialKind: str = "",
    tag: list[str] = Query(default=[]),
    title: str = "",
    keyword: str = "",
    recursive: bool = True,
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    return await business_material_store.raw_files(
        folder_path=folderPath,
        project_id=projectId,
        customer_name=customerName,
        material_tier=materialTier,
        clean_status=cleanStatus,
        business_material_kind=businessMaterialKind,
        tag=tag,
        title=title,
        keyword=keyword,
        recursive=recursive,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/business/materials/raw/upload")
async def business_raw_upload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    data: dict[str, Any]
    if "multipart/form-data" in content_type:
        form = await request.form()
        uploads = [upload for upload in form.getlist("files") if hasattr(upload, "filename") and hasattr(upload, "file")]
        relative_paths = [str(value or "") for value in form.getlist("relativePaths")]
        target_path = business_material_store.ensure_path(str(form.get("targetPath") or ""), "目标目录")
        data = {
            "targetPath": target_path,
            "projectId": str(form.get("projectId") or ""),
            "projectCode": str(form.get("projectCode") or ""),
            "projectName": str(form.get("projectName") or ""),
            "bidType": BUSINESS_BID_TYPE,
            "materialTier": str(form.get("materialTier") or ""),
            "businessMaterialKind": str(form.get("businessMaterialKind") or ""),
            "tags": normalize_material_tags(form.getlist("tags") or form.get("tags")),
            "customerId": str(form.get("customerId") or ""),
            "customerName": str(form.get("customerName") or ""),
            "onConflict": str(form.get("onConflict") or ""),
            "files": [
                {
                    "name": str(getattr(upload, "filename", "") or ""),
                    "type": str(getattr(upload, "content_type", "") or ""),
                    "mimeType": str(getattr(upload, "content_type", "") or ""),
                    "relativePath": relative_paths[index] if index < len(relative_paths) else "",
                    "upload": upload,
                }
                for index, upload in enumerate(uploads)
            ],
        }
    else:
        try:
            data = await request.json()
        except Exception:
            data = {}
        data = _business_payload(data)
        data["targetPath"] = business_material_store.ensure_path(str(data.get("targetPath") or ""), "目标目录")

    return await business_material_store.raw_upload(
        target_path=str(data.get("targetPath") or ""),
        project_id=str(data.get("projectId") or ""),
        project_code=str(data.get("projectCode") or ""),
        project_name=str(data.get("projectName") or ""),
        material_tier=str(data.get("materialTier") or ""),
        business_material_kind=str(data.get("businessMaterialKind") or ""),
        tags=data.get("tags"),
        customer_id=str(data.get("customerId") or ""),
        customer_name=str(data.get("customerName") or ""),
        on_conflict=str(data.get("onConflict") or ""),
        files=list(data.get("files") or []),
    )


@router.post("/api/business/materials/raw/folders")
async def business_raw_create_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.raw_create_folder(
        parent_path=str(data.get("parentPath") or ""),
        folder_name=str(data.get("folderName") or data.get("name") or ""),
    )


@router.delete("/api/business/materials/raw/folders")
async def business_raw_delete_folder(path: str = Query(default="")) -> dict[str, Any]:
    return await business_material_store.raw_delete_folder(path)


@router.patch("/api/business/materials/raw/folders")
async def business_raw_rename_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.raw_rename_folder(
        path=str(data.get("path") or data.get("folderPath") or ""),
        new_name=str(data.get("newName") or data.get("folderName") or data.get("name") or ""),
    )


@router.patch("/api/business/materials/raw/{file_id}")
async def business_raw_update_file(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.raw_update_file(
        file_id,
        name=str(data.get("name") or ""),
        business_material_kind=str(data.get("businessMaterialKind") or ""),
        tags=data.get("tags"),
        update_tags="tags" in data,
        tag_mode=str(data.get("tagMode") or "overwrite"),
    )


@router.delete("/api/business/materials/raw/{file_id}")
async def business_raw_delete_file(file_id: str) -> dict[str, Any]:
    return await business_material_store.raw_delete_file(file_id)


@router.get("/api/business/materials/raw/{file_id}/download")
async def business_raw_download_file(file_id: str) -> dict[str, Any]:
    return await business_material_store.raw_download_file(file_id)


@router.get("/api/business/materials/raw/{file_id}/content")
async def business_raw_download_content(file_id: str) -> StreamingResponse:
    payload = await business_material_store.raw_download_content(file_id)
    return minio_streaming_response(payload)


@router.get("/api/business/materials/raw/{file_id}/preview")
async def business_raw_preview_original_file(file_id: str, request: Request) -> dict[str, Any]:
    return await business_material_store.raw_original_preview(
        file_id,
        browser_base_url=str(request.base_url).rstrip("/"),
        onlyoffice_base_url=onlyoffice_backend_base_url(request),
    )


@router.get("/api/business/materials/raw/{file_id}/preview-content")
async def business_raw_preview_content(file_id: str) -> StreamingResponse:
    payload = await business_material_store.raw_download_content(file_id)
    return minio_streaming_response(payload, inline=True)


@router.post("/api/business/materials/raw/move")
async def business_raw_move_file(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    # 统一 fileId/id 优先级为 fileId 优先，与技术标一致（L4）
    file_id = str(data.get("fileId") or data.get("id") or "")
    return await business_material_store.raw_move_file(
        file_id=file_id,
        target_path=str(data.get("targetPath") or ""),
        on_conflict=str(data.get("onConflict") or ""),
    )


@router.post("/api/business/materials/raw/batch-delete")
async def business_raw_batch_delete(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    file_ids: list[str] = [str(fid) for fid in (data.get("fileIds") or []) if fid]
    if not file_ids:
        return {"succeeded": [], "failed": [], "message": "未提供文件 ID"}
    return await business_material_store.raw_batch_delete_files(file_ids)


@router.post("/api/business/materials/raw/batch-tags")
async def business_raw_batch_tags(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    file_ids: list[str] = [str(fid) for fid in (data.get("fileIds") or []) if fid]
    tags: Any = data.get("tags") or []
    tag_mode: str = str(data.get("tagMode") or "overwrite")
    if not file_ids:
        return {"succeeded": [], "failed": [], "message": "未提供文件 ID"}
    return await business_material_store.raw_batch_tags(file_ids, tags=tags, tag_mode=tag_mode)


@router.post("/api/business/materials/raw/folders/move")
async def business_raw_move_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.raw_move_folder(
        source_path=str(data.get("sourcePath") or ""),
        target_parent_path=str(data.get("targetParentPath") or ""),
    )


@router.post("/api/business/materials/raw/{file_id}/business-split/preview")
async def business_raw_preview_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.preview_business_split(
        file_id=file_id,
        target_path=str(data.get("targetPath") or ""),
        ai_mode=str(data.get("aiMode") or data.get("mode") or "auto"),
    )


@router.post("/api/business/materials/raw/{file_id}/business-split/confirm")
async def business_raw_confirm_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    fragments = data.get("fragments") if "fragments" in data else data.get("items")
    return await business_material_store.confirm_business_split(
        file_id=file_id,
        fragments=list(fragments or []),
        target_path=str(data.get("targetPath") or ""),
        on_conflict=str(data.get("onConflict") or ""),
    )


@router.get("/api/business/materials/raw/{file_id}/cleaned/preview")
async def business_raw_preview_cleaned_file(file_id: str, request: Request) -> dict[str, Any]:
    return await business_material_store.raw_cleaned_preview(
        file_id,
        browser_base_url=str(request.base_url).rstrip("/"),
        onlyoffice_base_url=onlyoffice_backend_base_url(request),
    )


@router.get("/api/business/materials/raw/{file_id}/cleaned/content")
async def business_raw_download_cleaned_content(file_id: str) -> StreamingResponse:
    payload = await business_material_store.raw_download_cleaned_content(file_id)
    return minio_streaming_response(
        payload,
        default_file_name="cleaned.docx",
        default_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/api/business/materials/raw/{file_id}/cleaned/content/{filename:path}")
async def business_raw_download_cleaned_content_by_name(file_id: str, filename: str) -> StreamingResponse:
    _ = filename
    payload = await business_material_store.raw_download_cleaned_content(file_id)
    return minio_streaming_response(
        payload,
        default_file_name="cleaned.docx",
        default_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/api/business/materials/wiki")
async def business_wiki_list(nodeId: str = "", bidType: str = "") -> dict[str, Any]:
    _ = bidType
    return await business_material_store.wiki_list(nodeId)


@router.post("/api/business/materials/wiki/bootstrap")
async def business_wiki_bootstrap(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await generate_business_wiki(
        reference_path=str(data.get("referencePath") or ""),
        mode=str(data.get("mode") or "create"),
        fallback_to_deterministic=bool(data.get("fallbackToDeterministic")),
    )


@router.post("/api/business/materials/wiki")
async def business_wiki_create(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.wiki_create(
        parent_id=str(data.get("parentId") or ""),
        title=str(data.get("title") or "新建节点"),
        is_folder=bool(data.get("isFolder")),
    )


@router.put("/api/business/materials/wiki/{node_id}")
async def business_wiki_update(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.wiki_update(node_id, data)


@router.delete("/api/business/materials/wiki/{node_id}")
async def business_wiki_delete(node_id: str, bidType: str = Query(default="")) -> dict[str, Any]:
    _ = bidType
    return await business_material_store.wiki_delete(node_id)


@router.post("/api/business/materials/wiki/{node_id}/move")
async def business_wiki_move(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await business_material_store.wiki_move(
        node_id=node_id,
        target_id=str(data.get("targetId") or ""),
        mode=str(data.get("mode") or "inside"),
    )


@router.post("/api/business/materials/wiki/{node_id}/attachments")
async def business_wiki_upload_attachment(node_id: str, request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        return await business_material_store.wiki_upload_attachment(
            node_id=node_id,
            file_name=str(getattr(upload, "filename", "") or form.get("fileName") or ""),
            file_size=form.get("fileSize"),
            upload=upload,
            mime_type=str(getattr(upload, "content_type", "") or ""),
        )

    data = await request.json()
    raw_bytes = data.get("data")
    decoded = None
    if raw_bytes is not None:
        raw_text = str(raw_bytes)
        if raw_text.startswith("data:"):
            raw_text = raw_text.split(",", 1)[-1]
        decoded = base64.b64decode(raw_text)
    return await business_material_store.wiki_upload_attachment(
        node_id=node_id,
        file_name=str(data.get("fileName") or ""),
        file_size=data.get("fileSize"),
        data=decoded,
        mime_type=str(data.get("mimeType") or ""),
    )


@router.post("/api/business/materials/wiki/{node_id}/refresh-summary")
async def business_wiki_refresh_summary(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _ = data
    return await business_material_store.wiki_refresh_summary(node_id)


@router.delete("/api/business/materials/wiki/attachments/{attachment_id}")
async def business_wiki_delete_attachment(attachment_id: str, bidType: str = Query(default="")) -> dict[str, Any]:
    _ = bidType
    return await business_material_store.wiki_delete_attachment(attachment_id)


@router.get("/api/business/materials/wiki/attachments/{attachment_id}/content")
async def business_wiki_download_attachment_content(attachment_id: str) -> StreamingResponse:
    payload = await business_material_store.wiki_download_attachment_content(attachment_id)
    return minio_streaming_response(payload)


@router.get("/api/business/audit")
async def business_audit_list(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await business_audit_service.list(dict(request.query_params))


@router.get("/api/business/audit/export")
async def business_audit_export(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await business_audit_service.export(dict(request.query_params))


@router.get("/api/business/audit/{audit_id}")
async def business_audit_detail(audit_id: str, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await business_audit_service.detail(audit_id)
