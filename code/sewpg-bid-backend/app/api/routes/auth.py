from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

router = APIRouter()


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


@router.post("/api/auth/login")
async def auth_login(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    email = str(data.get("email") or "").strip()
    username = str(data.get("username") or data.get("name") or "").strip()
    user = build_mock_user(username or "当前用户", email)
    return {
        "token": "mock-token-U000-bootstrap",
        "user": user,
        "expiresIn": 86400,
    }


@router.get("/api/auth/me")
async def auth_me() -> dict[str, Any]:
    return {
        "token": "mock-token-U000-bootstrap",
        "user": build_mock_user("当前用户", "current.user@example.com"),
    }


@router.post("/api/auth/logout")
async def auth_logout() -> dict[str, str]:
    return {"message": "已退出登录"}


@router.get("/api/customers/key-accounts")
async def key_accounts() -> dict[str, Any]:
    return {
        "items": [
            {"id": "KA-HN", "name": "华能集团"},
            {"id": "KA-DT", "name": "大唐集团"},
            {"id": "KA-CG", "name": "国家能源集团"},
        ]
    }
