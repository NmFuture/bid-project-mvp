from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.services.audit_service import AuditService


# 与 event_service 测试同理：SQLite 不强制 VARCHAR 长度，用 CHECK 复现 Postgres 行为。
CREATE_TABLE_SQL = """
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(100) NOT NULL CHECK (length(user_id) <= 100),
    user_name VARCHAR(100) CHECK (length(user_name) <= 100),
    action VARCHAR(80) NOT NULL CHECK (length(action) <= 80),
    action_type VARCHAR(40) NOT NULL CHECK (length(action_type) <= 40),
    module_id VARCHAR(80) NOT NULL CHECK (length(module_id) <= 80),
    module_label VARCHAR(200) CHECK (length(module_label) <= 200),
    target VARCHAR(500) CHECK (length(target) <= 500),
    status VARCHAR(20) CHECK (length(status) <= 20),
    diff JSONB,
    meta JSONB,
    ip_address VARCHAR(80) CHECK (length(ip_address) <= 80),
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
"""


class AuditServiceColumnLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.execute(text(CREATE_TABLE_SQL))
        self.service = AuditService()
        patches = (
            patch("app.services.audit_service.async_session", self.session_factory),
            patch("app.services.audit_service.ensure_material_runtime_tables", new=AsyncMock()),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_record_truncates_overlong_target_from_request_body(self) -> None:
        # /api/auth/login 把请求体里的 email 原样写进 target，长度不受校验
        email = "a" * 800 + "@example.com"
        item = await self.service.record(
            action="登录失败",
            action_type="auth",
            module_id="auth",
            module_label="登录鉴权",
            target=email,
            status="失败",
            ip_address="203.0.113.10",
        )
        self.assertEqual(len(item["target"]), 500)
        self.assertTrue(item["target"].startswith("aaa"))
        self.assertTrue(item["target"].endswith("@example.com"))
        self.assertIn("…", item["target"])

    async def test_record_truncates_all_varchar_columns(self) -> None:
        item = await self.service.record(
            action="更新" * 60,
            action_type="config" * 20,
            module_id="settings" * 30,
            module_label="系统设置" * 80,
            target="https://example.com/" + "p" * 900,
            status="成功" * 40,
            user={"id": "u-" + "1" * 200, "name": "名" * 300},
            ip_address="203.0.113.10, " * 20,
        )
        self.assertEqual(len(item["action"]), 80)
        self.assertEqual(len(item["actionType"]), 40)
        self.assertEqual(len(item["module"]), 80)
        self.assertEqual(len(item["moduleLabel"]), 200)
        self.assertEqual(len(item["target"]), 500)
        self.assertEqual(len(item["status"]), 20)
        self.assertEqual(len(item["ipAddress"]), 80)

    async def test_record_keeps_normal_values_verbatim(self) -> None:
        item = await self.service.record(
            action="登录成功",
            action_type="auth",
            module_id="auth",
            module_label="登录鉴权",
            target="zhangsan@example.com",
            user={"id": "u-1", "name": "张三"},
            ip_address="203.0.113.10",
        )
        self.assertEqual(item["action"], "登录成功")
        self.assertEqual(item["target"], "zhangsan@example.com")
        self.assertEqual(item["status"], "成功")
        self.assertEqual(item["user"], "张三")
        self.assertEqual(item["ipAddress"], "203.0.113.10")


if __name__ == "__main__":
    unittest.main()
