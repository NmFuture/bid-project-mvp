from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "fastapi",
        "mode": "skeleton",
        "project_store_backend": settings.project_store_backend,
        "uploads_dir": str(settings.uploads_dir),
        "documents_dir": str(settings.documents_dir),
        "opencode_base_url": settings.opencode_base_url,
        "onlyoffice_internal_url": settings.onlyoffice_internal_url,
    }


@router.get("/api/healthz")
async def api_healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "fastapi-api",
        "mode": "skeleton",
        "paths": {
            "uploads_dir": str(settings.uploads_dir),
            "documents_dir": str(settings.documents_dir),
            "parsed_dir": str(settings.parsed_dir),
        },
        "project_store_backend": settings.project_store_backend,
    }


@router.get("/api/root", name="root")
async def root() -> dict[str, str]:
    return {"status": "ok"}
