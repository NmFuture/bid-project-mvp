from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.services.store import store

router = APIRouter()


@router.get("/api/projects/{project_id}/outline")
async def get_outline(project_id: str) -> dict[str, Any]:
    return store.get_outline_state(project_id)


@router.put("/api/projects/{project_id}/outline")
async def save_outline(
    project_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    payload = store.save_outline(project_id, data.get("nodes") or [])
    return {**payload, "message": "目录已保存"}


@router.post("/api/projects/{project_id}/outline/regenerate")
async def regenerate_outline(project_id: str) -> dict[str, Any]:
    payload = store.regenerate_outline(project_id)
    return {**payload, "message": "已重生成目录审核稿"}


@router.post("/api/projects/{project_id}/outline/confirm")
async def confirm_outline(project_id: str) -> dict[str, Any]:
    return store.confirm_outline(project_id)

