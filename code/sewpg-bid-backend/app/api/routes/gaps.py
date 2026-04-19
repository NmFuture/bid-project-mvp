from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.services.store import store

router = APIRouter()


def _value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/projects/{project_id}/gaps-detection")
async def get_gap_detection(project_id: str) -> dict[str, Any]:
    return store.get_gap_detection(project_id)


@router.post("/api/projects/{project_id}/gaps-detection/run")
async def run_gap_detection(project_id: str) -> dict[str, Any]:
    payload = store.run_gap_detection(project_id)
    return {
        **payload,
        "message": f"识别完成，发现 {payload['summary']['totalMissing']} 项缺失素材。",
    }


@router.get("/api/projects/{project_id}/gaps")
async def get_gaps(project_id: str) -> dict[str, Any]:
    try:
        return store.get_gap_filling(project_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/api/projects/{project_id}/gaps/submit-review")
async def submit_gap_review(project_id: str) -> dict[str, Any]:
    try:
        return store.submit_gap_review(project_id)
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


@router.post("/api/projects/{project_id}/gaps/{gap_id}/upload")
async def upload_gap_material(
    project_id: str,
    gap_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    body = dict(data)
    body["missingId"] = gap_id
    try:
        return store.submit_gap_material(project_id, body)
    except ValueError as exc:
        raise _value_error(exc) from exc
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
