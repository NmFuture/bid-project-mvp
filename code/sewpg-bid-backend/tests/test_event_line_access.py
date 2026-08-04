from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.store import store


class EventLineAccessTests(unittest.TestCase):
    """行为日志/审计端点的业务线角色隔离：T 不可访问 business，B 不可访问 technical。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def _login(self, email: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": settings.auth_admin_password},
        )
        self.assertEqual(response.status_code, 200, f"登录失败: {email}")
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_technical_role_forbidden_from_business_events_and_audit(self) -> None:
        headers = self._login("anbo@nmscholar.fun")  # 角色 T
        forbidden = [
            ("post", "/api/business/events"),
            ("get", "/api/business/events"),
            ("get", "/api/business/events/sessions"),
            ("get", "/api/business/events/sessions/sess-x"),
            ("get", "/api/business/audit"),
            ("get", "/api/business/audit/export"),
            ("get", "/api/business/audit/AUD-x"),
        ]
        for method, path in forbidden:
            if method == "post":
                response = self.client.post(path, headers=headers, json={})
            else:
                response = self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, 403, f"T 角色访问 {path} 应返回 403")

        own_line = self.client.get("/api/technical/events", headers=headers)
        self.assertEqual(own_line.status_code, 200)

    def test_business_role_forbidden_from_technical_events_and_audit(self) -> None:
        headers = self._login("mage@nmscholar.fun")  # 角色 B
        forbidden = [
            ("post", "/api/technical/events"),
            ("get", "/api/technical/events"),
            ("get", "/api/technical/events/sessions"),
            ("get", "/api/technical/events/sessions/sess-x"),
            ("get", "/api/technical/audit"),
            ("get", "/api/technical/audit/export"),
            ("get", "/api/technical/audit/AUD-x"),
        ]
        for method, path in forbidden:
            if method == "post":
                response = self.client.post(path, headers=headers, json={})
            else:
                response = self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, 403, f"B 角色访问 {path} 应返回 403")

        own_line = self.client.get("/api/business/events", headers=headers)
        self.assertEqual(own_line.status_code, 200)

    def test_tb_role_can_access_both_lines(self) -> None:
        headers = self._login("xiaoge@nmscholar.fun")  # 角色 TB
        for path in ("/api/technical/events", "/api/business/events"):
            response = self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, 200, f"TB 角色访问 {path} 应返回 200")


if __name__ == "__main__":
    unittest.main()
