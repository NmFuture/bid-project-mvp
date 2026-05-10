from __future__ import annotations

from typing import Any

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.utils import onlyoffice_backend_base_url
from app.services.peripheral import PeripheralError
from app.services.store import store

router = APIRouter()


def _value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/projects/{project_id}/gaps-detection")
async def get_gap_detection(project_id: str) -> dict[str, Any]:
    return store.get_gap_detection(project_id)


@router.post("/api/projects/{project_id}/gaps-detection/run")
def run_gap_detection(project_id: str) -> dict[str, Any]:
    # Sync handler (not ``async def``) so FastAPI runs it in run_in_threadpool.
    # The store call eventually fans into ``_run_async`` (gap_planning), which
    # would deadlock if this ran on the event loop thread. See gap_planning._run_async.
    try:
        payload = store.run_gap_detection(project_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **payload,
        "message": f"缺口识别完成，共识别 {payload['summary']['totalTocItems']} 个目录项。",
    }


@router.get("/api/projects/{project_id}/gaps")
async def get_gaps(project_id: str, request: Request) -> dict[str, Any]:
    try:
        return store.get_gap_filling(
            project_id,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/api/projects/{project_id}/gaps/submit-review")
async def submit_gap_review(project_id: str) -> dict[str, Any]:
    try:
        return store.submit_gap_review(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.get("/api/projects/{project_id}/gaps/facts")
async def get_gap_project_facts(project_id: str) -> dict[str, Any]:
    return store.get_gap_fact_table(project_id)


@router.post("/api/projects/{project_id}/gaps/facts/build")
async def build_gap_project_facts(project_id: str) -> dict[str, Any]:
    try:
        return store.build_gap_fact_table(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.put("/api/projects/{project_id}/gaps/facts")
async def save_gap_project_facts(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.save_gap_fact_table(project_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/api/projects/{project_id}/gaps/ai-fill-all")
def ai_fill_all_gap_materials(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    # Sync handler so FastAPI offloads to a thread-pool worker. The store call
    # walks every gap and may take many minutes; the inner gap_planning code
    # also uses ``_run_async`` which only works off the event loop thread.
    try:
        return store.run_gap_ai_fill_all(
            project_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.put("/api/projects/{project_id}/gaps/{gap_id}")
async def update_gap(
    project_id: str,
    gap_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.update_gap_item(project_id, gap_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gap not found") from exc


@router.post("/api/projects/{project_id}/gaps/recheck")
async def recheck_gaps(project_id: str) -> dict[str, Any]:
    try:
        return {
            "message": "缺口完整性校验完成。",
            "integrity": store.check_gap_plan_integrity(project_id),
        }
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/api/projects/{project_id}/gaps/{gap_id}/ai-fill")
def ai_fill_gap_material(
    project_id: str,
    gap_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    # Sync handler — store.run_gap_ai_fill chains into gap_planning._run_async.
    try:
        return store.run_gap_ai_fill(
            project_id,
            gap_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gap not found") from exc


@router.get("/api/projects/{project_id}/gaps/artifacts/{artifact_id}/content/{filename:path}")
async def gap_artifact_content(project_id: str, artifact_id: str, filename: str) -> FileResponse:
    try:
        artifact = store.get_gap_artifact(project_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    path = Path(str(artifact.get("path") or ""))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(
        path,
        filename=str(artifact.get("fileName") or filename or path.name),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.post("/api/projects/{project_id}/gaps/{gap_id}/upload")
def upload_gap_material(
    project_id: str,
    gap_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    # Sync handler — store.upload_gap_artifact chains into gap_planning._run_async
    # via _allowed_material_index when registering the artifact against scope.
    try:
        return store.upload_gap_artifact(
            project_id,
            gap_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gap not found") from exc


@router.post("/api/projects/{project_id}/gaps/{gap_id}/select-material")
async def select_gap_material(
    project_id: str,
    gap_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return await store.select_gap_material(
            project_id,
            gap_id,
            data,
            browser_base_url=str(request.base_url).rstrip("/"),
            onlyoffice_base_url=onlyoffice_backend_base_url(request),
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    except PeripheralError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gap not found") from exc


@router.get("/api/projects/{project_id}/materials/submissions")
async def list_gap_submissions(project_id: str) -> dict[str, Any]:
    return store.list_gap_submissions(project_id)


@router.post("/api/projects/{project_id}/materials/submissions")
async def submit_gap_material(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.submit_gap_material(project_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gap not found") from exc


@router.patch("/api/projects/{project_id}/materials/missing/{missing_id}")
async def patch_missing_material(
    project_id: str,
    missing_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    try:
        return store.patch_missing_material(project_id, missing_id, data)
    except ValueError as exc:
        raise _value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gap not found") from exc
