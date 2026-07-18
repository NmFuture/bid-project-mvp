from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.api.utils import minio_streaming_response, onlyoffice_backend_base_url
from app.services.auth_service import current_user
from app.services.bid_ocr_service import technical_ocr_service
from app.services.bid_parse_service import technical_parse_service
from app.services.bid_project_service import technical_project_service
from app.services.technical_delivery_service import technical_coverage_service, technical_export_service
from app.services.technical_directory_service import technical_directory_service
from app.services.technical_document_service import technical_document_service
from app.services.technical_generation_service import technical_generation_service
from app.services.technical_gap_service import technical_gap_service
from app.services.technical_audit_service import technical_audit_service
from app.services.peripheral import PeripheralError
from app.services.technical_material_store import technical_material_store
from app.services.technical_wiki_generation import generate_technical_wiki

router = APIRouter()


def _ensure_technical_project(project_id: str) -> dict[str, Any]:
    return technical_project_service.ensure_project(project_id)


@router.get("/api/technical/projects")
async def list_technical_projects(
    status: str = "",
    reviewDecision: str = "",
    dateRange: str = "",
    page: int = 1,
    pageSize: int = 12,
) -> dict[str, Any]:
    return technical_project_service.list(
        status=status,
        review_decision=reviewDecision,
        date_range=dateRange,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/technical/projects")
async def create_technical_project(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return technical_project_service.create(data)


@router.get("/api/technical/projects/{project_id}")
async def get_technical_project(project_id: str) -> dict[str, Any]:
    return technical_project_service.get(project_id)


@router.put("/api/technical/projects/{project_id}")
async def update_technical_project(project_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_project_service.update(project_id, data)


@router.delete("/api/technical/projects/{project_id}")
async def delete_technical_project(project_id: str) -> dict[str, str]:
    return await technical_project_service.delete(project_id)


@router.get("/api/technical/projects/{project_id}/materials-path")
async def get_technical_materials_path(project_id: str) -> dict[str, Any]:
    return technical_project_service.materials_path(project_id)


@router.get("/api/technical/projects/{project_id}/template-fallback")
async def get_technical_template_fallback(project_id: str) -> dict[str, Any]:
    return await technical_project_service.template_fallback(project_id)


@router.put("/api/technical/projects/{project_id}/template-fallback")
async def update_technical_template_fallback(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_project_service.update_template_fallback(project_id, data)


@router.get("/api/technical/projects/{project_id}/materials/parse-status")
async def get_technical_material_parse_status(project_id: str) -> dict[str, Any]:
    return technical_project_service.parse_status(project_id)


@router.get("/api/technical/projects/{project_id}/ocr/tasks")
async def list_technical_ocr_tasks(
    project_id: str,
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await technical_ocr_service.list_tasks(project_id)


@router.post("/api/technical/projects/{project_id}/ocr/tasks")
async def run_technical_ocr(
    project_id: str,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        content = await file.read()
        return await technical_ocr_service.run(
            project_id=project_id,
            file_name=str(file.filename or "ocr-file"),
            content=content,
            mime_type=str(file.content_type or ""),
            user=user,
        )
    finally:
        await file.close()


@router.get("/api/technical/projects/{project_id}/ocr/tasks/{task_id}")
async def get_technical_ocr_task(
    project_id: str,
    task_id: str,
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await technical_ocr_service.detail(project_id, task_id)


@router.post("/api/technical/projects/{project_id}/ocr/candidates/{candidate_id}/confirm")
async def confirm_technical_ocr_candidate(
    project_id: str,
    candidate_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await technical_ocr_service.confirm_candidate(project_id, candidate_id, data, user=user)


@router.get("/api/technical/projects/{project_id}/stages")
async def list_technical_stages(project_id: str) -> list[dict[str, Any]]:
    return technical_project_service.stages(project_id)


@router.put("/api/technical/projects/{project_id}/stages/{stage}")
async def update_technical_stage(
    project_id: str,
    stage: int,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return technical_project_service.update_stage(project_id, stage, data)


@router.get("/api/technical/projects/{project_id}/parse-results")
async def get_technical_parse_results(project_id: str) -> dict[str, Any]:
    return await technical_parse_service.results(project_id)


@router.get("/api/technical/projects/{project_id}/parse-results/progress")
async def get_technical_parse_progress(project_id: str) -> dict[str, Any]:
    return await technical_parse_service.progress(project_id)


@router.post("/api/technical/projects/{project_id}/parse-results/cancel")
async def cancel_technical_parse(project_id: str) -> dict[str, Any]:
    return await technical_parse_service.cancel(project_id)


@router.post("/api/technical/projects/{project_id}/parse-results/run")
async def run_technical_parse(project_id: str) -> dict[str, Any]:
    return await technical_parse_service.run_without_upload(project_id)


@router.post("/api/technical/projects/{project_id}/parse-results/upload-and-run")
async def upload_and_parse_technical(
    project_id: str,
    tenderFiles: list[UploadFile] | None = File(default=None),
    templateFiles: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    return await technical_parse_service.upload_and_parse(
        project_id,
        tender_files=tenderFiles,
        template_files=templateFiles,
    )


@router.post("/api/technical/projects/{project_id}/template-files/upload")
async def upload_technical_template_files(
    project_id: str,
    templateFiles: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    return await technical_parse_service.upload_template_files(project_id, template_files=templateFiles)


@router.get("/api/technical/projects/{project_id}/parse-results/appendices/{appendix_id}/preview")
async def get_technical_appendix_preview(project_id: str, appendix_id: str, request: Request) -> dict[str, Any]:
    return await technical_parse_service.appendix_preview(project_id, appendix_id, request)


@router.api_route(
    "/api/technical/projects/{project_id}/parse-results/appendices/{appendix_id}/file",
    methods=["GET", "HEAD"],
)
async def get_technical_appendix_file(project_id: str, appendix_id: str) -> FileResponse:
    return await technical_parse_service.appendix_file(project_id, appendix_id)


@router.api_route(
    "/api/technical/projects/{project_id}/parse-results/appendices/{appendix_id}/file/{filename:path}",
    methods=["GET", "HEAD"],
)
async def get_technical_appendix_file_by_name(project_id: str, appendix_id: str, filename: str) -> FileResponse:
    return await technical_parse_service.appendix_file(project_id, appendix_id, filename)


@router.post("/api/technical/projects/{project_id}/parse-results/appendices/callback")
async def technical_appendix_onlyoffice_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await technical_parse_service.appendix_callback(project_id, request, data)


@router.post("/api/technical/projects/{project_id}/parse-results/appendices/{appendix_id}/approve")
async def approve_technical_appendix_asset(
    project_id: str,
    appendix_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_parse_service.approve_appendix_asset(project_id, appendix_id, data)


@router.post("/api/technical/projects/{project_id}/parse-results/appendices/approve")
async def approve_all_technical_appendix_assets(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_parse_service.approve_all_appendix_assets(project_id, data)


@router.get("/api/technical/projects/{project_id}/directory-generation")
async def get_technical_directory_generation(project_id: str) -> dict[str, Any]:
    return await technical_directory_service.generation_status(project_id)


@router.get("/api/technical/projects/{project_id}/directory-generation/stream")
async def stream_technical_directory_generation(project_id: str, request: Request) -> StreamingResponse:
    return await technical_directory_service.generation_stream(project_id, request)


@router.post("/api/technical/projects/{project_id}/directory-generation/run")
async def run_technical_directory_generation(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await technical_directory_service.run_generation(project_id, data)


@router.get("/api/technical/projects/{project_id}/outline")
async def get_technical_outline(project_id: str, request: Request, fileId: str = "") -> dict[str, Any]:
    return await technical_directory_service.outline(project_id, request, file_id=fileId)


@router.put("/api/technical/projects/{project_id}/outline")
async def save_technical_outline(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_directory_service.save_outline(project_id, data)


@router.post("/api/technical/projects/{project_id}/outline/regenerate")
async def regenerate_technical_outline(project_id: str) -> dict[str, Any]:
    return await technical_directory_service.regenerate_outline(project_id)


@router.post("/api/technical/projects/{project_id}/outline/confirm")
async def confirm_technical_outline(project_id: str) -> dict[str, Any]:
    return await technical_directory_service.confirm_outline(project_id)


@router.get("/api/technical/projects/{project_id}/outline/tender-files/{file_id}/file")
async def get_technical_outline_tender_file(project_id: str, file_id: str) -> FileResponse:
    return await technical_directory_service.tender_file(project_id, file_id)


@router.get("/api/technical/projects/{project_id}/outline/tender-files/{file_id}/file/{filename:path}")
async def get_technical_outline_tender_file_by_name(
    project_id: str,
    file_id: str,
    filename: str,
) -> FileResponse:
    return await technical_directory_service.tender_file(project_id, file_id, filename)


@router.post("/api/technical/projects/{project_id}/outline/tender-files/callback")
async def technical_outline_tender_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await technical_directory_service.tender_callback(project_id, request, data)


@router.get("/api/technical/projects/{project_id}/gaps-detection")
async def get_technical_gap_detection(project_id: str) -> dict[str, Any]:
    return await technical_gap_service.detection_status(project_id)


@router.post("/api/technical/projects/{project_id}/gaps-detection/run")
def run_technical_gap_detection(project_id: str) -> dict[str, Any]:
    return technical_gap_service.run_detection(project_id)


@router.get("/api/technical/projects/{project_id}/gaps")
async def get_technical_gaps(project_id: str, request: Request) -> dict[str, Any]:
    return await technical_gap_service.gaps(project_id, request)


@router.post("/api/technical/projects/{project_id}/gaps/{gap_id}/upload")
def upload_technical_gap_material(
    project_id: str,
    gap_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return technical_gap_service.upload_material(project_id, gap_id, request, data)


@router.get("/api/technical/projects/{project_id}/gaps/artifacts/{artifact_id}/content/{filename:path}")
async def get_technical_gap_artifact_content(
    project_id: str,
    artifact_id: str,
    filename: str,
) -> FileResponse:
    return await technical_gap_service.artifact_content(project_id, artifact_id, filename)


@router.post("/api/technical/projects/{project_id}/gaps/{gap_id}/artifacts/{artifact_id}/confirm")
def confirm_technical_gap_ai_fill_artifact(
    project_id: str,
    gap_id: str,
    artifact_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return technical_gap_service.confirm_ai_fill_artifact(project_id, gap_id, artifact_id, data)


@router.post("/api/technical/projects/{project_id}/gaps/{gap_id}/select-material")
async def select_technical_gap_material(
    project_id: str,
    gap_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_gap_service.select_material(project_id, gap_id, request, data)


@router.post("/api/technical/projects/{project_id}/gaps/submit-review")
async def submit_technical_gap_review(project_id: str) -> dict[str, Any]:
    return await technical_gap_service.submit_review(project_id)


@router.get("/api/technical/projects/{project_id}/gaps/facts")
async def get_technical_gap_project_facts(project_id: str) -> dict[str, Any]:
    return await technical_gap_service.facts(project_id)


@router.post("/api/technical/projects/{project_id}/gaps/facts/build")
async def build_technical_gap_project_facts(project_id: str) -> dict[str, Any]:
    return await technical_gap_service.build_facts(project_id)


@router.put("/api/technical/projects/{project_id}/gaps/facts")
async def save_technical_gap_project_facts(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_gap_service.save_facts(project_id, data)


@router.put("/api/technical/projects/{project_id}/gaps/{gap_id}")
async def update_technical_gap(
    project_id: str,
    gap_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_gap_service.update_gap(project_id, gap_id, data)


@router.post("/api/technical/projects/{project_id}/gaps/recheck")
async def recheck_technical_gaps(project_id: str) -> dict[str, Any]:
    return await technical_gap_service.recheck(project_id)


@router.post("/api/technical/projects/{project_id}/gaps/{gap_id}/ai-fill")
def ai_fill_technical_gap_material(
    project_id: str,
    gap_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return technical_gap_service.ai_fill(project_id, gap_id, request, data)


@router.post("/api/technical/projects/{project_id}/gaps/ai-fill-all")
def ai_fill_all_technical_gap_materials(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return technical_gap_service.ai_fill_all(project_id, request, data)


@router.get("/api/technical/projects/{project_id}/materials/submissions")
async def list_technical_gap_submissions(project_id: str) -> dict[str, Any]:
    return await technical_gap_service.submissions(project_id)


@router.post("/api/technical/projects/{project_id}/materials/submissions")
async def submit_technical_gap_material(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_gap_service.submit_material(project_id, data)


@router.patch("/api/technical/projects/{project_id}/materials/missing/{missing_id}")
async def patch_technical_missing_material(
    project_id: str,
    missing_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_gap_service.patch_missing(project_id, missing_id, data)


@router.get("/api/technical/projects/{project_id}/fill-generation")
async def get_technical_fill_generation(project_id: str) -> dict[str, Any]:
    return await technical_generation_service.status(project_id)


@router.post("/api/technical/projects/{project_id}/fill-generation/run")
async def run_technical_fill_generation(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> JSONResponse:
    return await technical_generation_service.run(project_id, request, data, user)


@router.get("/api/technical/projects/{project_id}/coverage")
async def get_technical_coverage(project_id: str) -> dict[str, Any]:
    return await technical_coverage_service.coverage(project_id)


@router.get("/api/technical/projects/{project_id}/document")
async def get_technical_document(project_id: str, request: Request) -> dict[str, Any]:
    return await technical_document_service.document(project_id, request)


@router.put("/api/technical/projects/{project_id}/document/save")
async def save_technical_document(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_document_service.save_document(project_id, request, data)


@router.get("/api/technical/projects/{project_id}/document/file")
async def download_technical_document_file(project_id: str) -> FileResponse:
    return await technical_document_service.document_file(project_id)


@router.get("/api/technical/projects/{project_id}/document/file/{filename:path}")
async def download_technical_document_file_by_name(project_id: str, filename: str) -> FileResponse:
    return await technical_document_service.document_file(project_id, filename)


@router.post("/api/technical/projects/{project_id}/document/callback")
async def technical_onlyoffice_callback(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await technical_document_service.document_callback(project_id, request, data)


@router.post("/api/technical/projects/{project_id}/document/force-save")
async def force_save_technical_document(project_id: str, request: Request) -> dict[str, Any]:
    return await technical_document_service.force_save_document(project_id, request)


@router.post("/api/technical/projects/{project_id}/document/technical-format")
async def apply_technical_document_format(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await technical_document_service.apply_format(project_id, request, data)


@router.get("/api/technical/projects/{project_id}/final-document")
async def get_technical_final_document(project_id: str, request: Request) -> dict[str, Any]:
    return await technical_document_service.final_document(project_id, request)


@router.get("/api/technical/projects/{project_id}/final-document/file")
async def download_technical_final_document_file(project_id: str) -> FileResponse:
    return await technical_document_service.final_document_file(project_id)


@router.get("/api/technical/projects/{project_id}/final-document/pdf")
async def prepare_technical_final_document_pdf(project_id: str, request: Request) -> dict[str, Any]:
    return await technical_document_service.final_document_pdf(project_id, request)


@router.get("/api/technical/projects/{project_id}/final-document/pdf/file")
async def download_technical_final_document_pdf(project_id: str) -> FileResponse:
    return await technical_document_service.final_document_pdf_file(project_id)


@router.get("/api/technical/projects/{project_id}/export/check")
async def technical_export_check(project_id: str) -> dict[str, Any]:
    return await technical_export_service.check(project_id)


@router.post("/api/technical/projects/{project_id}/export", response_model=None)
async def technical_export_document(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    return await technical_export_service.export(project_id, request, data)


@router.get("/api/technical/materials/identity-options")
async def technical_identity_options() -> dict[str, Any]:
    return await technical_material_store.identity_options()


@router.get("/api/technical/materials/turbine-model-options")
async def technical_turbine_model_options() -> dict[str, Any]:
    return await technical_material_store.turbine_model_options()


@router.get("/api/technical/materials/raw/tree")
async def technical_raw_tree() -> dict[str, Any]:
    return await technical_material_store.raw_tree()


@router.get("/api/technical/materials/index")
async def technical_material_index() -> dict[str, Any]:
    """技术标三级目录结构 JSON 索引（供 Wiki 构建/项目解析参考）。

    若索引尚未生成（首次访问或被清空），即时重建一次再返回。
    """
    from app.services.technical_material_index import (
        load_technical_material_index,
        rebuild_technical_material_index,
    )

    payload = load_technical_material_index()
    if not payload:
        payload = await rebuild_technical_material_index()
    return payload


@router.put("/api/technical/materials/index/tags")
async def set_technical_material_index_tags(
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """对索引中某节点设置 tag（tag 真值落 JSON 索引自身）。

    入参：{ "targetId": "RAW-0012" | "<folderId>" | "<目录path>", "tags": [...] }
    - targetId 以 RAW- 开头 → 文件；否则按 folderId 或目录 path 定位 tier/3 级目录。
    - tags 经 normalize_material_tags 规整（与文件 tag 同一套规则）。
    """
    from app.services.technical_material_index import set_tags_for_node

    target_id = str(data.get("targetId") or "").strip()
    try:
        node = await set_tags_for_node(target_id=target_id, tags=data.get("tags"))
    except (ValueError, LookupError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "node": node}


@router.get("/api/technical/materials/raw/files")
async def technical_raw_files(
    folderPath: str = "",
    projectId: str = "",
    customerName: str = "",
    materialTier: str = "",
    cleanStatus: str = "",
    keyword: str = "",
    turbineModel: str = "",
    title: str = "",
    tag: list[str] = Query(default_factory=list),
    bidType: str = "",
    recursive: bool = True,
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    return await technical_material_store.raw_files(
        folder_path=folderPath,
        project_id=projectId,
        customer_name=customerName,
        material_tier=materialTier,
        clean_status=cleanStatus,
        keyword=keyword,
        turbine_model=turbineModel,
        title=title,
        tag=tag,
        recursive=recursive,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/technical/materials/raw/folders/bootstrap")
async def technical_raw_bootstrap_folders(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.raw_bootstrap_folders(project_id=str(data.get("projectId") or ""))


@router.post("/api/technical/materials/raw/folders")
async def technical_raw_create_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.raw_create_folder(
        parent_path=str(data.get("parentPath") or ""),
        folder_name=str(data.get("folderName") or data.get("name") or ""),
    )


@router.delete("/api/technical/materials/raw/folders")
async def technical_raw_delete_folder(path: str = Query(default="")) -> dict[str, Any]:
    return await technical_material_store.raw_delete_folder(path)


@router.post("/api/technical/materials/raw/upload")
async def technical_raw_upload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    data: dict[str, Any]
    if "multipart/form-data" in content_type:
        form = await request.form()
        uploads = [upload for upload in form.getlist("files") if hasattr(upload, "filename") and hasattr(upload, "file")]
        relative_paths = [str(value or "") for value in form.getlist("relativePaths")]
        target_path = str(form.get("targetPath") or "")
        data = {
            "targetPath": technical_material_store.ensure_path(target_path, "目标目录") if target_path else "",
            "projectId": str(form.get("projectId") or ""),
            "projectCode": str(form.get("projectCode") or ""),
            "projectName": str(form.get("projectName") or ""),
            "materialTier": str(form.get("materialTier") or ""),
            "customerId": str(form.get("customerId") or ""),
            "customerName": str(form.get("customerName") or ""),
            "tags": form.getlist("tags"),
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
        target_path = str(data.get("targetPath") or "")
        data["targetPath"] = technical_material_store.ensure_path(target_path, "目标目录") if target_path else ""

    return await technical_material_store.raw_upload(
        target_path=str(data.get("targetPath") or ""),
        project_id=str(data.get("projectId") or ""),
        project_code=str(data.get("projectCode") or ""),
        project_name=str(data.get("projectName") or ""),
        material_tier=str(data.get("materialTier") or ""),
        customer_id=str(data.get("customerId") or ""),
        customer_name=str(data.get("customerName") or ""),
        tags=data.get("tags") or [],
        on_conflict=str(data.get("onConflict") or ""),
        files=list(data.get("files") or []),
    )


@router.post("/api/technical/materials/raw/tag-import/preview")
async def technical_raw_tag_import_preview(request: Request) -> dict[str, Any]:
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise PeripheralError(400, "请上传标签清单 Excel 文件。", "TAG_IMPORT_FILE_REQUIRED")
    file_bytes = await upload.read()
    use_fuzzy = str(form.get("useFuzzy") or "").strip().lower() in {"1", "true", "yes", "on"}
    import_mode = "overwrite" if str(form.get("importMode") or "").strip().lower() == "overwrite" else "merge"
    return await technical_material_store.raw_tag_import_preview(
        target_path=str(form.get("targetPath") or ""),
        file_bytes=file_bytes,
        use_fuzzy=use_fuzzy,
        import_mode=import_mode,
    )


@router.post("/api/technical/materials/raw/tag-import/commit")
async def technical_raw_tag_import_commit(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise PeripheralError(400, "没有可导入的标签条目。", "TAG_IMPORT_EMPTY_ITEMS")
    return await technical_material_store.raw_tag_import_commit(items=items)


@router.patch("/api/technical/materials/raw/{file_id}")
async def technical_raw_update_file(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.raw_update_file(
        file_id=file_id,
        name=str(data.get("name") or ""),
        business_material_kind=str(data.get("businessMaterialKind") or ""),
        tags=data.get("tags"),
        update_tags="tags" in data,
        tag_mode=str(data.get("tagMode") or "overwrite"),
    )


@router.post("/api/technical/materials/raw/batch-delete")
async def technical_raw_batch_delete(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    file_ids: list[str] = [str(fid) for fid in (data.get("fileIds") or []) if fid]
    if not file_ids:
        return {"succeeded": [], "failed": [], "message": "未提供文件 ID"}
    return await technical_material_store.raw_batch_delete_files(file_ids)


@router.post("/api/technical/materials/raw/batch-tags")
async def technical_raw_batch_tags(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    file_ids: list[str] = [str(fid) for fid in (data.get("fileIds") or []) if fid]
    tags: Any = data.get("tags") or []
    tag_mode: str = str(data.get("tagMode") or "overwrite")
    if not file_ids:
        return {"succeeded": [], "failed": [], "message": "未提供文件 ID"}
    return await technical_material_store.raw_batch_tags(file_ids, tags=tags, tag_mode=tag_mode)


@router.post("/api/technical/materials/raw/certificate-time/batch")
async def technical_raw_certificate_time_batch(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    file_ids = [str(item) for item in (data.get("fileIds") or []) if str(item or "").strip()]
    return await technical_material_store.raw_certificate_time_batch(
        folder_path=str(data.get("folderPath") or ""),
        file_ids=file_ids,
        limit=int(data.get("limit") or 50),
    )


@router.post("/api/technical/materials/raw/{file_id}/split/preview")
async def technical_raw_preview_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.preview_technical_split(
        file_id=file_id,
        target_path=str(data.get("targetPath") or ""),
        ai_mode=str(data.get("aiMode") or data.get("mode") or "auto"),
    )


@router.post("/api/technical/materials/raw/{file_id}/split/confirm")
async def technical_raw_confirm_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    fragments = data.get("fragments") if "fragments" in data else data.get("items")
    return await technical_material_store.confirm_technical_split(
        file_id=file_id,
        fragments=list(fragments or []),
        target_path=str(data.get("targetPath") or ""),
        on_conflict=str(data.get("onConflict") or ""),
    )


@router.post("/api/technical/materials/raw/{file_id}/business-split/preview")
async def technical_raw_preview_legacy_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_raw_preview_split(file_id, data)


@router.post("/api/technical/materials/raw/{file_id}/business-split/confirm")
async def technical_raw_confirm_legacy_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_raw_confirm_split(file_id, data)


@router.post("/api/technical/materials/raw/move")
async def technical_raw_move_file(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    file_id = str(data.get("fileId") or data.get("id") or "")
    return await technical_material_store.raw_move_file(
        file_id=file_id,
        target_path=str(data.get("targetPath") or ""),
        on_conflict=str(data.get("onConflict") or ""),
    )


@router.post("/api/technical/materials/raw/folders/move")
async def technical_raw_move_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.raw_move_folder(
        source_path=str(data.get("sourcePath") or ""),
        target_parent_path=str(data.get("targetParentPath") or data.get("targetPath") or ""),
    )


@router.delete("/api/technical/materials/raw/{file_id}")
async def technical_raw_delete_file(file_id: str) -> dict[str, Any]:
    return await technical_material_store.raw_delete_file(file_id)


@router.get("/api/technical/materials/raw/{file_id}/download")
async def technical_raw_download_file(file_id: str) -> dict[str, Any]:
    return await technical_material_store.raw_download_file(file_id)


@router.get("/api/technical/materials/raw/{file_id}/content")
async def technical_raw_download_content(file_id: str) -> StreamingResponse:
    payload = await technical_material_store.raw_download_content(file_id)
    return minio_streaming_response(payload)


@router.get("/api/technical/materials/raw/{file_id}/preview-content")
async def technical_raw_preview_content(file_id: str) -> StreamingResponse:
    payload = await technical_material_store.raw_download_content(file_id)
    return minio_streaming_response(payload, inline=True)


@router.get("/api/technical/materials/raw/{file_id}/cleaned/preview")
async def technical_raw_preview_cleaned_file(file_id: str, request: Request) -> dict[str, Any]:
    return await technical_material_store.raw_cleaned_preview(
        file_id,
        browser_base_url=str(request.base_url).rstrip("/"),
        onlyoffice_base_url=onlyoffice_backend_base_url(request),
    )


@router.get("/api/technical/materials/raw/{file_id}/cleaned/content")
async def technical_raw_download_cleaned_content(file_id: str) -> StreamingResponse:
    payload = await technical_material_store.raw_download_cleaned_content(file_id)
    return minio_streaming_response(
        payload,
        default_file_name="cleaned.docx",
        default_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/api/technical/materials/raw/{file_id}/cleaned/content/{filename:path}")
async def technical_raw_download_cleaned_content_by_name(file_id: str, filename: str) -> StreamingResponse:
    _ = filename
    payload = await technical_material_store.raw_download_cleaned_content(file_id)
    return minio_streaming_response(
        payload,
        default_file_name="cleaned.docx",
        default_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/api/technical/materials/wiki")
async def technical_wiki_list(nodeId: str = "", bidType: str = "") -> dict[str, Any]:
    _ = bidType
    return await technical_material_store.wiki_list(nodeId)


@router.get("/api/technical/materials/wiki/certificate-time")
async def technical_wiki_certificate_time() -> dict[str, Any]:
    return await technical_material_store.certificate_time_registry()


@router.patch("/api/technical/materials/wiki/certificate-time/{file_id}")
async def technical_wiki_update_certificate_time(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.update_certificate_time(file_id, data)


@router.get("/api/technical/materials/certificates")
async def technical_certificate_ledger() -> dict[str, Any]:
    return await technical_material_store.certificate_time_registry()


@router.get("/api/technical/materials/certificates/suggestions")
async def technical_certificate_suggestions() -> dict[str, Any]:
    return await technical_material_store.certificate_time_suggestions()


@router.put("/api/technical/materials/certificates/scopes")
async def technical_update_certificate_scopes(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.update_certificate_time_scopes(data)


@router.post("/api/technical/materials/certificates/incremental")
async def technical_run_certificate_incremental(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.run_certificate_time_incremental(data)


@router.post("/api/technical/materials/certificates/{file_id}/recognize")
async def technical_recognize_certificate_ledger(file_id: str) -> dict[str, Any]:
    return await technical_material_store.recognize_certificate_time(file_id)


@router.post("/api/technical/materials/certificates/bulk-delete")
async def technical_delete_certificate_ledgers(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.delete_certificate_times(data)


@router.patch("/api/technical/materials/certificates/{file_id}")
async def technical_update_certificate_ledger(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.update_certificate_time(file_id, data)


@router.delete("/api/technical/materials/certificates/{file_id}")
async def technical_delete_certificate_ledger(file_id: str) -> dict[str, Any]:
    return await technical_material_store.delete_certificate_time(file_id)


@router.post("/api/technical/materials/wiki/bootstrap")
async def technical_wiki_bootstrap(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await generate_technical_wiki(
        reference_path=str(data.get("referencePath") or ""),
        mode=str(data.get("mode") or "create"),
        fallback_to_deterministic=bool(data.get("fallbackToDeterministic")),
    )


@router.post("/api/technical/materials/wiki")
async def technical_wiki_create(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.wiki_create(
        parent_id=str(data.get("parentId") or ""),
        title=str(data.get("title") or "新建节点"),
        is_folder=bool(data.get("isFolder")),
    )


@router.put("/api/technical/materials/wiki/{node_id}")
async def technical_wiki_update(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.wiki_update(node_id, data)


@router.delete("/api/technical/materials/wiki/{node_id}")
async def technical_wiki_delete(node_id: str, bidType: str = Query(default="")) -> dict[str, Any]:
    _ = bidType
    return await technical_material_store.wiki_delete(node_id)


@router.post("/api/technical/materials/wiki/{node_id}/move")
async def technical_wiki_move(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await technical_material_store.wiki_move(
        node_id=node_id,
        target_id=str(data.get("targetId") or ""),
        mode=str(data.get("mode") or "inside"),
    )


@router.post("/api/technical/materials/wiki/{node_id}/attachments")
async def technical_wiki_upload_attachment(node_id: str, request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        return await technical_material_store.wiki_upload_attachment(
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
    return await technical_material_store.wiki_upload_attachment(
        node_id=node_id,
        file_name=str(data.get("fileName") or ""),
        file_size=data.get("fileSize"),
        data=decoded,
        mime_type=str(data.get("mimeType") or ""),
    )


@router.post("/api/technical/materials/wiki/{node_id}/refresh-summary")
async def technical_wiki_refresh_summary(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _ = data
    return await technical_material_store.wiki_refresh_summary(node_id)


@router.delete("/api/technical/materials/wiki/attachments/{attachment_id}")
async def technical_wiki_delete_attachment(attachment_id: str, bidType: str = Query(default="")) -> dict[str, Any]:
    _ = bidType
    return await technical_material_store.wiki_delete_attachment(attachment_id)


@router.get("/api/technical/materials/wiki/attachments/{attachment_id}/content")
async def technical_wiki_download_attachment_content(attachment_id: str) -> StreamingResponse:
    payload = await technical_material_store.wiki_download_attachment_content(attachment_id)
    return minio_streaming_response(payload)


@router.get("/api/technical/audit")
async def technical_audit_list(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await technical_audit_service.list(dict(request.query_params))


@router.get("/api/technical/audit/export")
async def technical_audit_export(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await technical_audit_service.export(dict(request.query_params))


@router.get("/api/technical/audit/{audit_id}")
async def technical_audit_detail(audit_id: str, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await technical_audit_service.detail(audit_id)
