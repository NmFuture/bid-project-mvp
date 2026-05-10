from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.utils import onlyoffice_backend_base_url
from app.services.peripheral import PeripheralError
from app.services.store import store

router = APIRouter()


def _value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/projects/{project_id}/business-gaps")
async def get_business_gaps(project_id: str, request: Request) -> dict[str, Any]:
    try:
        return store.get_business_gap_filling(
            project_id,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/api/projects/{project_id}/business-gaps/run")
async def run_business_gap_detection(project_id: str) -> dict[str, Any]:
    try:
        payload = store.run_business_gap_detection(project_id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        **payload,
        "message": f"商务标缺口计划生成完成，共 {summary.get('taskCount', 0)} 个任务。",
    }


@router.get("/api/projects/{project_id}/business-gaps/facts")
async def get_business_gap_project_facts(project_id: str) -> dict[str, Any]:
    try:
        return store.get_business_gap_fact_table(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.get("/api/projects/{project_id}/business-gaps/selectable-materials")
async def get_business_gap_selectable_materials(project_id: str, keyword: str = "") -> dict[str, Any]:
    try:
        return store.list_business_gap_selectable_materials(project_id, keyword=keyword)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/api/projects/{project_id}/business-gaps/facts/build")
async def build_business_gap_project_facts(project_id: str) -> dict[str, Any]:
    try:
        return store.build_business_gap_fact_table(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.put("/api/projects/{project_id}/business-gaps/facts")
async def save_business_gap_project_facts(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.save_business_gap_fact_table(project_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.patch("/api/projects/{project_id}/business-gaps/tasks/{task_id}")
async def update_business_gap_task(
    project_id: str,
    task_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.update_business_gap_task(project_id, task_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap task not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/toc/{toc_node_id}/manual-task")
async def create_business_gap_manual_task(
    project_id: str,
    toc_node_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.create_business_gap_manual_task(project_id, toc_node_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap toc ref not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/tasks/{task_id}/confirm-artifact")
async def confirm_business_gap_artifact(
    project_id: str,
    task_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.confirm_business_gap_artifact(project_id, task_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap artifact not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/tasks/{task_id}/upload")
async def upload_business_gap_artifact(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.upload_business_gap_artifact(
            project_id,
            task_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap task not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/tasks/{task_id}/upload-files")
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
        return store.upload_business_gap_artifact_bytes(
            project_id,
            task_id,
            records,
            operator=operator,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap task not found") from exc
    finally:
        for upload in uploads:
            await upload.close()


@router.delete("/api/projects/{project_id}/business-gaps/tasks/{task_id}/artifacts/{artifact_id}")
async def remove_business_gap_artifact(
    project_id: str,
    task_id: str,
    artifact_id: str,
    request: Request,
) -> dict[str, Any]:
    try:
        return store.remove_business_gap_artifact(
            project_id,
            task_id,
            artifact_id,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap artifact not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/tasks/{task_id}/select-material")
async def select_business_gap_material(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return await store.select_business_gap_material(
            project_id,
            task_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except PeripheralError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap task not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/tasks/{task_id}/select-template")
async def select_business_gap_template(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.select_business_gap_template(
            project_id,
            task_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap task not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/tasks/{task_id}/ai-draft")
async def ai_draft_business_gap_task(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.run_business_gap_ai_draft(
            project_id,
            task_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap task not found") from exc


@router.post("/api/projects/{project_id}/business-gaps/tasks/{task_id}/sync-artifact-material")
async def sync_business_gap_artifact_to_material(
    project_id: str,
    task_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.sync_business_gap_artifact_to_material_library(
            project_id,
            task_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Business gap artifact not found") from exc
    except PeripheralError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/projects/{project_id}/business-gaps/artifacts/{artifact_id}/content/{filename:path}")
async def business_gap_artifact_content(project_id: str, artifact_id: str, filename: str) -> FileResponse:
    try:
        artifact = store.get_business_gap_artifact(project_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    path = Path(str(artifact.get("filePath") or artifact.get("path") or ""))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(path, filename=str(artifact.get("fileName") or filename or path.name))
