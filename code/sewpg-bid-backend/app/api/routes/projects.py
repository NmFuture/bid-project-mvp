from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.services.identity import build_project_material_scope
from app.services.store import store
from app.services.template_store import template_fallback_payload

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


@router.get("/api/projects/{project_id}/template-fallback")
async def get_template_fallback(project_id: str) -> dict[str, Any]:
    context = store.template_fallback_context(project_id)
    return await template_fallback_payload(
        project_id=project_id,
        bid_type=str(context["bidType"]),
        enabled=bool(context["enabled"]),
        source_id=str(context["sourceId"]),
        has_project_template=bool(context["hasProjectTemplate"]),
    )


@router.put("/api/projects/{project_id}/template-fallback")
async def update_template_fallback(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    store.update_template_fallback(project_id, data)
    context = store.template_fallback_context(project_id)
    return await template_fallback_payload(
        project_id=project_id,
        bid_type=str(context["bidType"]),
        enabled=bool(context["enabled"]),
        source_id=str(context["sourceId"]),
        has_project_template=bool(context["hasProjectTemplate"]),
    )


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    store.delete_project(project_id)
    return {"message": "项目已删除"}


@router.get("/api/projects/{project_id}/cockpit")
async def project_cockpit(project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    return {
        "summary": "当前按技术标 6 节点主链路推进，关键集成点是模板与目录、缺口处理、生成标书和 OnlyOffice 共创。",
        "startDate": project.get("startDate") or "",
        "endDate": project.get("endDate") or project.get("deadline") or "",
        "deadline": project.get("deadline") or "",
        "tasks": [
            {"id": "task-1", "label": "完成模板与目录", "status": "done" if project["currentStage"] > 1 else "pending"},
            {"id": "task-2", "label": "完成目录审核", "status": "done" if project["currentStage"] > 2 else "pending"},
            {"id": "task-3", "label": "完成生成标书", "status": "done" if project["currentStage"] > 4 else "pending"},
        ],
    }


@router.get("/api/projects/{project_id}/materials-path")
async def project_materials_path(project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    scope = build_project_material_scope(project)
    identity = scope["identity"]
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
        "path": f"技术标/项目素材/{material_project_id}",
        "bidType": scope["bidType"],
        "readableScopes": scope["readableScopes"],
        "paths": scope["paths"],
        "summary": scope["summary"],
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
