from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import Header, HTTPException, status
from sqlalchemy import select

from app.core.config import settings
from app.models import async_session
from app.models.materials import AuthSession, SystemUser
from app.services.material_runtime_tables import ensure_material_runtime_tables


def now_utc() -> datetime:
    return datetime.now(UTC)


def _password_hash(password: str, *, salt: bytes | None = None, iterations: int = 260_000) -> str:
    raw_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), raw_salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(raw_salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = str(encoded).split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录状态已失效")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录状态已失效")
    return token.strip()


class AuthService:
    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await session.commit()

    async def ensure_bootstrap_admin(self) -> None:
        await self._ensure_tables()
        async with async_session() as session:
            existing = (
                await session.execute(select(SystemUser).where(SystemUser.email == settings.auth_admin_email))
            ).scalar_one_or_none()
            if existing is not None:
                return
            user = SystemUser(
                id="U-ADMIN",
                name=settings.auth_admin_name,
                email=settings.auth_admin_email,
                password_hash=_password_hash(settings.auth_admin_password),
                dept="解决方案部",
                roles=["管理员", "标书经理"],
                status="active",
            )
            session.add(user)
            await session.commit()

    async def ensure_role_seed_users(self) -> None:
        await self._ensure_tables()
        seed = [
            ("U-ROLE-T", "安博", "anbo@nmscholar.fun", "技术中心 / 风电技术部", ["T"]),
            ("U-ROLE-B", "马哥", "mage@nmscholar.fun", "商务中心 / 投标商务部", ["B"]),
            ("U-ROLE-TB", "肖哥", "xiaoge@nmscholar.fun", "投标管理中心", ["TB"]),
        ]
        default_password = settings.auth_admin_password
        async with async_session() as session:
            for uid, name, email, dept, roles in seed:
                existing = (
                    await session.execute(select(SystemUser).where(SystemUser.email == email))
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                session.add(
                    SystemUser(
                        id=uid,
                        name=name,
                        email=email,
                        password_hash=_password_hash(default_password),
                        dept=dept,
                        roles=roles,
                        status="active",
                    )
                )
            await session.commit()

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str = "",
        ip_address: str = "",
    ) -> dict[str, Any]:
        await self.ensure_bootstrap_admin()
        await self.ensure_role_seed_users()
        normalized_email = str(email or "").strip().lower()
        if not normalized_email or not password:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")

        async with async_session() as session:
            user = (
                await session.execute(select(SystemUser).where(SystemUser.email == normalized_email))
            ).scalar_one_or_none()
            if user is None or str(user.status or "") != "active" or not _verify_password(password, user.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")

            token = secrets.token_urlsafe(40)
            expires_at = now_utc() + timedelta(seconds=settings.auth_session_ttl_sec)
            session.add(
                AuthSession(
                    token=token,
                    user_id=user.id,
                    expires_at=expires_at,
                    user_agent=user_agent,
                    ip_address=ip_address,
                )
            )
            await session.commit()
            public_user = user.to_public_dict()

        return {
            "token": token,
            "user": public_user,
            "expiresIn": settings.auth_session_ttl_sec,
        }

    async def authenticate_token(self, token: str) -> dict[str, Any]:
        await self.ensure_bootstrap_admin()
        async with async_session() as session:
            auth_session = (
                await session.execute(select(AuthSession).where(AuthSession.token == token))
            ).scalar_one_or_none()
            if auth_session is None or auth_session.revoked_at is not None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录状态已失效")
            expires_at = auth_session.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now_utc():
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录状态已失效")
            user = (
                await session.execute(select(SystemUser).where(SystemUser.id == auth_session.user_id))
            ).scalar_one_or_none()
            if user is None or str(user.status or "") != "active":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录状态已失效")
            return user.to_public_dict()

    async def me(self, authorization: str | None) -> dict[str, Any]:
        token = extract_bearer_token(authorization)
        user = await self.authenticate_token(token)
        return {"token": token, "user": user}

    async def logout(self, authorization: str | None) -> dict[str, str]:
        token = extract_bearer_token(authorization)
        await self._ensure_tables()
        async with async_session() as session:
            auth_session = (
                await session.execute(select(AuthSession).where(AuthSession.token == token))
            ).scalar_one_or_none()
            if auth_session is not None and auth_session.revoked_at is None:
                auth_session.revoked_at = now_utc()
                await session.commit()
        return {"message": "已退出登录"}

    async def list_users(self) -> dict[str, Any]:
        await self.ensure_bootstrap_admin()
        async with async_session() as session:
            users = (
                await session.execute(select(SystemUser).order_by(SystemUser.created_at, SystemUser.email))
            ).scalars().all()
            items = [user.to_public_dict() for user in users]
        return {"items": items, "total": len(items)}

    async def create_user(self, data: dict[str, Any], *, operator: dict[str, Any] | None = None) -> dict[str, Any]:
        await self.ensure_bootstrap_admin()
        email = str(data.get("email") or "").strip().lower()
        password = str(data.get("password") or data.get("initialPassword") or "123456")
        if not email:
            raise HTTPException(status_code=400, detail="邮箱不能为空")
        async with async_session() as session:
            existing = (await session.execute(select(SystemUser).where(SystemUser.email == email))).scalar_one_or_none()
            if existing is not None:
                raise HTTPException(status_code=409, detail="用户邮箱已存在")
            user = SystemUser(
                id=f"U-{uuid4().hex[:10]}",
                name=str(data.get("name") or email.split("@", 1)[0]),
                email=email,
                password_hash=_password_hash(password),
                dept=str(data.get("dept") or "未分配"),
                roles=list(data.get("roles") or []),
                status=str(data.get("status") or "active"),
            )
            session.add(user)
            await session.commit()
            created = user.to_public_dict()

        from app.services.audit_service import audit_service

        await audit_service.record(
            action="创建用户",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=email,
            user=operator,
            diff={"before": {}, "after": created},
        )
        return created

    async def update_user(
        self,
        user_id: str,
        data: dict[str, Any],
        *,
        operator: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.ensure_bootstrap_admin()
        async with async_session() as session:
            user = (await session.execute(select(SystemUser).where(SystemUser.id == user_id))).scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            before = user.to_public_dict()
            for key in ("name", "email", "dept", "roles", "status"):
                if key in data:
                    setattr(user, key, data[key])
            if data.get("password"):
                user.password_hash = _password_hash(str(data["password"]))
            await session.commit()
            after = user.to_public_dict()

        from app.services.audit_service import audit_service

        audit_after = {**after}
        if data.get("password"):
            audit_after["passwordUpdated"] = True
        await audit_service.record(
            action="更新用户",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=str(after.get("email") or user_id),
            user=operator,
            diff={"before": before, "after": audit_after},
        )
        return {"message": "Updated", "item": after}


auth_service = AuthService()


async def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = extract_bearer_token(authorization)
    return await auth_service.authenticate_token(token)
