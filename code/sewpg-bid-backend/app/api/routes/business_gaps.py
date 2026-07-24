from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.services.business_gap_service import business_gap_service
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError


def _ensure_business_project(project_id: str) -> dict[str, Any]:
    try:
        return business_gap_service.ensure_project(project_id)
    except PeripheralError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


router = APIRouter(dependencies=[Depends(_ensure_business_project)])


def _raise_service_error(exc: Exception, not_found_detail: str) -> None:
    if isinstance(exc, PeripheralError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if isinstance(exc, (RuntimeError, ValueError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=not_found_detail) from exc
    raise exc


@router.get("/api/business/projects/{project_id}/business-gaps")
async def get_business_gaps(project_id: str, request: Request) -> dict[str, Any]:
    try:
        return business_gap_service.gaps(project_id, request)
    except Exception as exc:
        _raise_service_error(exc, "Business gap plan not found")


@router.post("/api/business/projects/{project_id}/business-gaps/run")
async def run_business_gap_detection(project_id: str) -> dict[str, Any]:
    try:
        return business_gap_service.run_detection(project_id)
    except Exception as exc:
        _raise_service_error(exc, "Business gap plan not found")


@router.get("/api/business/projects/{project_id}/business-gaps/facts")
async def get_business_gap_project_facts(project_id: str) -> dict[str, Any]:
    try:
        return business_gap_service.facts(project_id)
    except Exception as exc:
        _raise_service_error(exc, "Business gap facts not found")


@router.get("/api/business/projects/{project_id}/business-gaps/selectable-materials")
async def get_business_gap_selectable_materials(project_id: str, keyword: str = "") -> dict[str, Any]:
    try:
        return business_gap_service.selectable_materials(project_id, keyword=keyword)
    except Exception as exc:
        _raise_service_error(exc, "Business gap material not found")


@router.get("/api/business/projects/{project_id}/business-gaps/materials/{material_id}/preview")
async def preview_business_gap_material(
    project_id: str,
    material_id: str,
    request: Request,
    mode: str = "quick",
) -> dict[str, Any]:
    try:
        return await business_gap_service.material_preview(project_id, material_id, request, mode=mode)
    except Exception as exc:
        _raise_service_error(exc, "Business gap material not found")


@router.get("/api/business/projects/{project_id}/business-gaps/materials/{material_id}/content/{filename:path}")
async def business_gap_material_preview_content(project_id: str, material_id: str, filename: str) -> StreamingResponse:
    try:
        payload = await business_gap_service.material_preview_content(project_id, material_id)
    except Exception as exc:
        _raise_service_error(exc, "Business gap material not found")
    response = minio_client.get_object_response(payload["bucket"], payload["key"])

    def iterate_chunks():
        try:
            for chunk in response.stream(64 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(
        iterate_chunks(),
        media_type=str(payload.get("mimeType") or "application/octet-stream"),
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(str(payload.get('fileName') or filename or 'preview.bin'))}"},
    )


@router.post("/api/business/projects/{project_id}/business-gaps/facts/build")
async def build_business_gap_project_facts(project_id: str) -> dict[str, Any]:
    try:
        return await business_gap_service.build_facts(project_id)
    except Exception as exc:
        _raise_service_error(exc, "Business gap facts not found")


@router.put("/api/business/projects/{project_id}/business-gaps/facts")
async def save_business_gap_project_facts(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return await business_gap_service.save_facts(project_id, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap facts not found")


@router.patch("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}")
async def update_business_gap_task(
    project_id: str,
    task_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return business_gap_service.update_task(project_id, task_id, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap task not found")


@router.post("/api/business/projects/{project_id}/business-gaps/toc/{toc_node_id}/manual-task")
async def create_business_gap_manual_task(
    project_id: str,
    toc_node_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return business_gap_service.create_manual_task(project_id, toc_node_id, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap toc ref not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/confirm-artifact")
async def confirm_business_gap_artifact(
    project_id: str,
    task_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return business_gap_service.confirm_artifact(project_id, task_id, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap artifact not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/upload")
async def upload_business_gap_artifact(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return business_gap_service.upload_artifact(project_id, task_id, request, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap task not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/upload-files")
async def upload_business_gap_artifact_files(
    project_id: str,
    task_id: str,
    request: Request,
    files: list[UploadFile] | None = File(default=None),
    operator: str = Form(default="当前用户"),
) -> dict[str, Any]:
    uploads = files or []
    if not uploads:
        raise HTTPException(status_code=400, detail="至少需要上传一个文件。")
    records: list[dict[str, Any]] = []
    try:
        for upload in uploads:
            raw = await upload.read()
            records.append(
                {
                    "name": Path(upload.filename or "upload.bin").name,
                    "mimeType": upload.content_type or "",
                    "rawBytes": raw,
                }
            )
        return business_gap_service.upload_artifact_files(project_id, task_id, request, records, operator=operator)
    except Exception as exc:
        _raise_service_error(exc, "Business gap task not found")
    finally:
        for upload in uploads:
            await upload.close()


@router.delete("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/artifacts/{artifact_id}")
async def remove_business_gap_artifact(
    project_id: str,
    task_id: str,
    artifact_id: str,
    request: Request,
) -> dict[str, Any]:
    try:
        return business_gap_service.remove_artifact(project_id, task_id, artifact_id, request)
    except Exception as exc:
        _raise_service_error(exc, "Business gap artifact not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/select-material")
async def select_business_gap_material(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return await business_gap_service.select_material(project_id, task_id, request, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap task not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/select-template")
async def select_business_gap_template(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return business_gap_service.select_template(project_id, task_id, request, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap task not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/ai-draft")
async def ai_draft_business_gap_task(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return await business_gap_service.ai_draft(project_id, task_id, request, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap task not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/table-fill")
async def table_fill_business_gap_task(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return await business_gap_service.table_fill(project_id, task_id, request, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap task not found")


@router.post("/api/business/projects/{project_id}/business-gaps/tasks/{task_id}/sync-artifact-material")
async def sync_business_gap_artifact_to_material(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return await business_gap_service.sync_artifact_to_material(project_id, task_id, request, data)
    except Exception as exc:
        _raise_service_error(exc, "Business gap artifact not found")


@router.get("/api/business/projects/{project_id}/business-gaps/artifacts/{artifact_id}/content/{filename:path}")
async def business_gap_artifact_content(project_id: str, artifact_id: str, filename: str) -> FileResponse:
    try:
        artifact = business_gap_service.artifact(project_id, artifact_id)
    except Exception as exc:
        _raise_service_error(exc, "Artifact not found")
    path = Path(str(artifact.get("filePath") or artifact.get("path") or ""))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(path, filename=str(artifact.get("fileName") or filename or path.name))
