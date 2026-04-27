from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.services.store import store

router = APIRouter()


@router.get("/api/projects")
async def list_projects(
    status: str = "",
    bidType: str = "",
    dateRange: str = "",
    page: int = 1,
    pageSize: int = 12,
) -> dict[str, Any]:
    return store.list_projects(
        status=status,
        bid_type=bidType,
        date_range=dateRange,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/projects")
async def create_project(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return store.create_project(data)


@router.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    return store.get_project(project_id)


@router.put("/api/projects/{project_id}")
async def update_project(project_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return store.update_project(project_id, data)


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    store.delete_project(project_id)
    return {"message": "项目已删除"}


@router.get("/api/projects/{project_id}/cockpit")
async def project_cockpit(project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    return {
        "summary": "当前按 MVP 主链路推进，关键集成点是解析、目录、正文拼装、OnlyOffice。",
        "deadline": project.get("deadline") or "",
        "tasks": [
            {"id": "task-1", "label": "完成 S1 模板上传", "status": "done" if project["currentStage"] > 1 else "pending"},
            {"id": "task-2", "label": "完成 S2 目录生成", "status": "done" if project["currentStage"] > 2 else "pending"},
            {"id": "task-3", "label": "完成 S7 正文拼装", "status": "done" if project["currentStage"] > 7 else "pending"},
        ],
    }


@router.get("/api/projects/{project_id}/materials-path")
async def project_materials_path(project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    identity = project.get("identity") or {}
    material_project_code = str(identity.get("projectCode") or project.get("projectCode") or project["id"])
    material_project_id = str(identity.get("projectId") or project["id"])
    return {
        "projectId": project["id"],
        "bidProjectId": project["id"],
        "bidProjectCode": project.get("projectCode") or project["id"],
        "materialProjectId": material_project_id,
        "materialProjectCode": material_project_code,
        "projectCode": material_project_code,
        "identity": identity,
        "path": f"项目素材/{material_project_id}/{project['bidType']}",
    }


@router.get("/api/projects/{project_id}/stages")
async def list_stages(project_id: str) -> list[dict[str, Any]]:
    return store.get_stages(project_id)


@router.put("/api/projects/{project_id}/stages/{stage}")
async def update_stage(
    project_id: str,
    stage: int,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return store.update_stage(project_id, stage, data)
