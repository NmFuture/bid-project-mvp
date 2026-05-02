from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from app.services.identity import CUSTOMER_REGISTRY
from app.services.audit_service import audit_service
from app.services.auth_service import auth_service

router = APIRouter()


@router.post("/api/auth/login")
async def auth_login(request: Request, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    email = str(data.get("email") or "").strip()
    try:
        payload = await auth_service.login(
            email=email,
            password=str(data.get("password") or ""),
            user_agent=request.headers.get("user-agent", ""),
            ip_address=request.client.host if request.client else "",
        )
    except Exception:
        await audit_service.record(
            action="登录失败",
            action_type="auth",
            module_id="auth",
            module_label="登录鉴权",
            target=email,
            status="失败",
            diff={"before": {}, "after": {"email": email}},
            ip_address=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
        raise
    await audit_service.record(
        action="登录成功",
        action_type="auth",
        module_id="auth",
        module_label="登录鉴权",
        target=email,
        user=payload.get("user"),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    return payload


@router.get("/api/auth/me")
async def auth_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return await auth_service.me(authorization)


@router.post("/api/auth/logout")
async def auth_logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    return await auth_service.logout(authorization)


@router.get("/api/customers/key-accounts")
async def key_accounts() -> dict[str, Any]:
    return {
        "items": [
            {
                "id": item["customerId"],
                "keyAccountId": f"KA-{item['customerId'].replace('CUST-', '')}",
                "customerId": item["customerId"],
                "name": item["customerCanonicalName"],
                "customerCanonicalName": item["customerCanonicalName"],
                "aliases": item["customerAliases"],
            }
            for item in CUSTOMER_REGISTRY
            if item["customerId"] != "CUST-SEWPG"
        ]
    }
