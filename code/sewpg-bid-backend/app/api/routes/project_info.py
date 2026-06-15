from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.project_info_options import project_info_options


router = APIRouter()


@router.get("/api/business/project-info/options")
async def get_business_project_info_options() -> dict[str, Any]:
    return project_info_options("business")


@router.get("/api/technical/project-info/options")
async def get_technical_project_info_options() -> dict[str, Any]:
    return project_info_options("technical")
