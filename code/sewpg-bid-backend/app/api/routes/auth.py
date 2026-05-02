from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, status

from app.services.identity import CUSTOMER_REGISTRY

router = APIRouter()

MOCK_AUTH_TOKEN = "mock-token-U000-bootstrap"


def build_mock_user(name: str, email: str) -> dict[str, Any]:
    display_name = name.strip() or "当前用户"
    normalized_email = email.strip() or "current.user@example.com"
    return {
        "id": "U000",
        "name": display_name,
        "email": normalized_email,
        "avatar": display_name[:1] or "当",
        "dept": "解决方案部",
        "roles": ["管理员"],
        "role": "admin",
    }


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录状态已失效",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录状态已失效",
        )
    return token.strip()


def require_mock_session(authorization: str | None) -> None:
    token = extract_bearer_token(authorization)
    if token != MOCK_AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录状态已失效",
        )


@router.post("/api/auth/login")
async def auth_login(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    email = str(data.get("email") or "").strip()
    username = str(data.get("username") or data.get("name") or "").strip()
    user = build_mock_user(username or "当前用户", email)
    return {
        "token": MOCK_AUTH_TOKEN,
        "user": user,
        "expiresIn": 86400,
    }


@router.get("/api/auth/me")
async def auth_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_mock_session(authorization)
    return {
        "token": MOCK_AUTH_TOKEN,
        "user": build_mock_user("当前用户", "current.user@example.com"),
    }


@router.post("/api/auth/logout")
async def auth_logout() -> dict[str, str]:
    return {"message": "已退出登录"}


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
