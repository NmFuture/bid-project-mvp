from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header

from app.services.auth_service import auth_service
from app.services.dashboard_service import dashboard_service

router = APIRouter()


@router.get("/api/dashboard")
async def get_dashboard(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    me = await auth_service.me(authorization)
    user = me.get("user") if isinstance(me, dict) else {}
    return await dashboard_service.build(user or {})
