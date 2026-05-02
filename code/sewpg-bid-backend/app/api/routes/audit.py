from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.services.auth_service import current_user
from app.services.audit_service import audit_service

router = APIRouter()


@router.get("/api/audit")
async def audit_list(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await audit_service.list(dict(request.query_params))


@router.get("/api/audit/export")
async def audit_export(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await audit_service.export(dict(request.query_params))


@router.get("/api/audit/{audit_id}")
async def audit_detail(audit_id: str, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await audit_service.detail(audit_id)
