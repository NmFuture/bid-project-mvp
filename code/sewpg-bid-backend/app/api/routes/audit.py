from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services.peripheral import peripheral_store

router = APIRouter()


@router.get("/api/audit")
async def audit_list(request: Request) -> dict[str, Any]:
    return peripheral_store.audit_list(dict(request.query_params))


@router.get("/api/audit/export")
async def audit_export(request: Request) -> dict[str, Any]:
    return peripheral_store.audit_export(dict(request.query_params))


@router.get("/api/audit/{audit_id}")
async def audit_detail(audit_id: str) -> dict[str, Any]:
    return peripheral_store.audit_detail(audit_id)
