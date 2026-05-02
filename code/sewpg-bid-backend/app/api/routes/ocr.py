from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.services.auth_service import current_user
from app.services.ocr_service import ocr_service
from app.services.peripheral import PeripheralError

router = APIRouter()


def _peripheral_http_error(exc: PeripheralError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/api/projects/{project_id}/ocr/tasks")
async def ocr_tasks(
    project_id: str,
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await ocr_service.list_tasks(project_id)


@router.post("/api/projects/{project_id}/ocr/tasks")
async def ocr_run(
    project_id: str,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        content = await file.read()
        return await ocr_service.run_ocr(
            project_id=project_id,
            file_name=str(file.filename or "ocr-file"),
            content=content,
            mime_type=str(file.content_type or ""),
            user=user,
        )
    except PeripheralError as exc:
        raise _peripheral_http_error(exc) from exc
    finally:
        await file.close()


@router.get("/api/projects/{project_id}/ocr/tasks/{task_id}")
async def ocr_task_detail(
    project_id: str,
    task_id: str,
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        return await ocr_service.detail(project_id, task_id)
    except PeripheralError as exc:
        raise _peripheral_http_error(exc) from exc


@router.post("/api/projects/{project_id}/ocr/candidates/{candidate_id}/confirm")
async def ocr_candidate_confirm(
    project_id: str,
    candidate_id: str,
    data: dict[str, Any],
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        return await ocr_service.confirm_candidate(project_id, candidate_id, data, user=user)
    except PeripheralError as exc:
        raise _peripheral_http_error(exc) from exc
