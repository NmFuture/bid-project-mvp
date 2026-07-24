from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.store import store


class AuthRoutesTests(unittest.TestCase):
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

    def test_auth_login_returns_frontend_session_shape(self) -> None:
        login_response = self.client.post(
            "/api/auth/login",
            json={"email": "admin@sewpg.com", "password": "123456"},
        )
        self.assertEqual(login_response.status_code, 200)
        login_payload = login_response.json()
        self.assertIn("token", login_payload)
        self.assertIn("user", login_payload)
        self.assertEqual(login_payload["user"]["email"], "admin@sewpg.com")

    def test_auth_me_rejects_missing_or_invalid_token(self) -> None:
        missing_response = self.client.get("/api/auth/me")
        self.assertEqual(missing_response.status_code, 401)

        invalid_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        self.assertEqual(invalid_response.status_code, 401)

    def test_auth_me_accepts_login_token(self) -> None:
        login_response = self.client.post(
            "/api/auth/login",
            json={"email": "admin@sewpg.com", "password": "123456"},
        )
        token = login_response.json()["token"]

        me_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me_response.status_code, 200)
        me_payload = me_response.json()
        self.assertIn("token", me_payload)
        self.assertIn("user", me_payload)
        self.assertEqual(me_payload["user"]["name"], "当前用户")


if __name__ == "__main__":
    unittest.main()
