from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.store import store

router = APIRouter()


@router.get("/api/projects/{project_id}/coverage")
async def get_coverage(project_id: str) -> dict[str, Any]:
    return store.get_coverage(project_id)
