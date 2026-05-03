from __future__ import annotations

import tempfile
import unittest
import os
from io import BytesIO
from pathlib import Path

import pytest
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from app.services.store import store


def build_docx_bytes(*lines: str) -> bytes:
    file_obj = BytesIO()
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(file_obj)
    return file_obj.getvalue()


@unittest.skipUnless(os.getenv("BID_RUN_INTEGRATION") == "1", "requires PostgreSQL and MinIO")
@pytest.mark.integration
@pytest.mark.skipif(os.getenv("BID_RUN_INTEGRATION") != "1", reason="requires PostgreSQL and MinIO")
class SecuritySettingsOcrRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()
        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")
        login = self.client.post("/api/auth/login", json={"email": "admin@sewpg.com", "password": "123456"})
        self.assertEqual(login.status_code, 200)
        self.token = login.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.client.put(
            "/api/settings/ocr",
            headers=self.headers,
            json={"enabled": False, "model": "deepseek-ai/DeepSeek-OCR"},
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_auth_rejects_wrong_password_and_accepts_real_session(self) -> None:
        wrong = self.client.post("/api/auth/login", json={"email": "admin@sewpg.com", "password": "wrong"})
        self.assertEqual(wrong.status_code, 401)

        me = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["email"], "admin@sewpg.com")

        logout = self.client.post("/api/auth/logout", headers=self.headers)
        self.assertEqual(logout.status_code, 200)
        expired = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(expired.status_code, 401)

    def test_settings_default_templates_and_model_configs_are_real_and_masked(self) -> None:
        default_templates = self.client.get("/api/settings/default-templates", headers=self.headers)
        self.assertEqual(default_templates.status_code, 200)
        self.assertIn({"key": "technical", "label": "技术标"}, default_templates.json()["templateTypes"])

        upload = self.client.post(
            "/api/settings/default-templates",
            headers=self.headers,
            data={"templateType": "technical", "version": "2026.05"},
            files={
                "file": (
                    "默认技术标模板.docx",
                    build_docx_bytes("默认技术标模板", "第一章 技术响应"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        self.assertEqual(upload.status_code, 200)
        template_id = upload.json()["item"]["id"]
        self.assertTrue(upload.json()["item"]["isActive"])
        activate = self.client.post(f"/api/settings/default-templates/{template_id}/activate", headers=self.headers)
        self.assertEqual(activate.status_code, 200)
        self.assertTrue(activate.json()["item"]["isActive"])

        second_upload = self.client.post(
            "/api/settings/default-templates",
            headers=self.headers,
            data={"templateType": "technical", "version": "2026.05"},
            files={
                "file": (
                    "默认技术标模板-v2.docx",
                    build_docx_bytes("默认技术标模板 v2", "第一章 技术响应"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        self.assertEqual(second_upload.status_code, 200)
        technical_items = [
            item for item in second_upload.json()["items"]
            if item["templateType"] == "technical"
        ]
        self.assertEqual(len(technical_items), 1)
        self.assertTrue(technical_items[0]["isActive"])
        self.assertEqual(technical_items[0]["name"], "默认技术标模板-v2.docx")

        update_llm = self.client.put(
            "/api/settings/llm-gateway",
            headers=self.headers,
            json={
                "enabled": True,
                "providerId": "mimo",
                "baseUrl": "https://llm.example.com/v1/chat/completions",
                "apiKey": "sk-test-secret",
                "model": "demo-model",
                "opencodeBaseUrl": "http://opencode:4096",
                "timeoutMs": 12345,
                "maxTokens": 99,
            },
        )
        self.assertEqual(update_llm.status_code, 200)
        payload_text = update_llm.text
        self.assertNotIn("sk-test-secret", payload_text)
        llm_config = update_llm.json()["config"]
        self.assertIn("apiKeyMasked", llm_config)
        self.assertEqual(llm_config["providerId"], "mimo")
        self.assertEqual(llm_config["model"], "demo-model")
        self.assertEqual(llm_config["modelId"], "demo-model")
        self.assertEqual(llm_config["opencodeBaseUrl"], "http://opencode:4096")
        self.assertTrue(any(item["id"] == "demo-model" for item in llm_config["modelOptions"]))

        update_ocr = self.client.put(
            "/api/settings/ocr",
            headers=self.headers,
            json={
                "enabled": True,
                "baseUrl": "https://ocr.example.com/v1/chat/completions",
                "apiKey": "ocr-secret-key",
                "model": "deepseek-ai/DeepSeek-OCR",
                "timeoutMs": 60000,
            },
        )
        self.assertEqual(update_ocr.status_code, 200)
        self.assertNotIn("ocr-secret-key", update_ocr.text)

    def test_enabled_system_default_template_is_used_as_project_fallback(self) -> None:
        project = self.client.post(
            "/api/projects",
            headers=self.headers,
            json={"name": "默认模板测试项目", "customerName": "测试业主", "bidType": "商务标"},
        )
        self.assertEqual(project.status_code, 200)
        project_id = project.json()["id"]

        upload = self.client.post(
            "/api/settings/default-templates",
            headers=self.headers,
            data={"templateType": "business", "version": "2026.05"},
            files={
                "file": (
                    "默认商务标模板.docx",
                    build_docx_bytes("默认商务标模板", "第一章 商务响应"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        self.assertEqual(upload.status_code, 200)
        template_id = upload.json()["item"]["id"]
        activate = self.client.post(f"/api/settings/default-templates/{template_id}/activate", headers=self.headers)
        self.assertEqual(activate.status_code, 200)

        fallback = self.client.get(f"/api/projects/{project_id}/template-fallback", headers=self.headers)
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(fallback.json()["template"]["source"], "system-default")
        self.assertEqual(fallback.json()["template"]["templateType"], "business")
        self.assertEqual(fallback.json()["template"]["name"], "默认商务标模板.docx")

        disabled = self.client.put(
            f"/api/projects/{project_id}/template-fallback",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])
        enabled = self.client.put(
            f"/api/projects/{project_id}/template-fallback",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["enabled"])

        system_record = {
            "id": template_id,
            "name": "默认商务标模板.docx",
            "stored_name": "默认商务标模板.docx",
            "path": str(settings.uploads_dir / project_id / "system-default-template" / "默认商务标模板.docx"),
            "source": "system-default",
            "isFallback": True,
            "templateType": "business",
            "templateTypeLabel": "商务标",
        }
        with patch("app.services.template_store.resolve_fallback_bid_template_file_sync", return_value=system_record):
            _, template_files = store.get_parse_inputs(project_id)

        self.assertEqual(len(template_files), 1)
        self.assertEqual(template_files[0]["source"], "system-default")
        self.assertEqual(template_files[0]["templateType"], "business")

    def test_invalid_default_template_upload_is_rejected(self) -> None:
        upload = self.client.post(
            "/api/settings/default-templates",
            headers=self.headers,
            data={"templateType": "technical", "version": "2026.05"},
            files={
                "file": (
                    "默认技术标模板.docx",
                    b"fake-docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

        self.assertEqual(upload.status_code, 400)
        self.assertIn("有效 DOCX", upload.text)

    def test_audit_records_real_operations(self) -> None:
        email = f"audit-user-{id(self)}@example.com"
        user_create = self.client.post(
            "/api/settings/users",
            headers=self.headers,
            json={
                "name": "审计测试用户",
                "email": email,
                "dept": "测试部",
                "roles": ["标书经理"],
                "password": "123456",
            },
        )
        self.assertEqual(user_create.status_code, 200)
        user_id = user_create.json()["id"]
        user_update = self.client.put(
            f"/api/settings/users/{user_id}",
            headers=self.headers,
            json={"dept": "审计部", "password": "654321"},
        )
        self.assertEqual(user_update.status_code, 200)

        self.client.put(
            "/api/settings/ocr",
            headers=self.headers,
            json={
                "enabled": True,
                "baseUrl": "https://ocr.example.com/v1/chat/completions",
                "apiKey": "ocr-secret-key",
                "model": "deepseek-ai/DeepSeek-OCR",
            },
        )
        audit = self.client.get("/api/audit", headers=self.headers)
        self.assertEqual(audit.status_code, 200)
        actions = [item["action"] for item in audit.json()["items"]]
        self.assertIn("创建用户", actions)
        self.assertIn("更新用户", actions)
        self.assertIn("更新OCR 模型配置", actions)
        detail = self.client.get(f"/api/audit/{audit.json()['items'][0]['id']}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("diff", detail.json())
        payload_text = audit.text + detail.text
        self.assertNotIn("654321", payload_text)

    def test_ocr_requires_config_and_can_list_tasks(self) -> None:
        project = self.client.post(
            "/api/projects",
            headers=self.headers,
            json={"name": "OCR 测试项目", "customerName": "测试业主", "bidType": "技术标"},
        )
        self.assertEqual(project.status_code, 200)
        project_id = project.json()["id"]

        before = self.client.get(f"/api/projects/{project_id}/ocr/tasks", headers=self.headers)
        self.assertEqual(before.status_code, 200)

        run = self.client.post(
            f"/api/projects/{project_id}/ocr/tasks",
            headers=self.headers,
            files={"file": ("ocr.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        self.assertEqual(run.status_code, 400)

        tasks = self.client.get(f"/api/projects/{project_id}/ocr/tasks", headers=self.headers)
        self.assertEqual(tasks.status_code, 200)
        self.assertEqual(tasks.json()["total"], before.json()["total"])

    def test_ocr_success_persists_task_candidates_and_confirmation(self) -> None:
        project = self.client.post(
            "/api/projects",
            headers=self.headers,
            json={"name": "OCR 成功测试项目", "customerName": "测试业主", "bidType": "技术标"},
        )
        self.assertEqual(project.status_code, 200)
        project_id = project.json()["id"]
        self.client.put(
            "/api/settings/ocr",
            headers=self.headers,
            json={
                "enabled": True,
                "baseUrl": "https://ocr.example.com/v1",
                "apiKey": "ocr-secret-key",
                "model": "deepseek-ai/DeepSeek-OCR",
            },
        )

        fake_response = {
            "choices": [
                {
                    "message": {
                        "content": "Project: Wind Farm\nBid No: SEWPG-2026\nCapacity: 100MW"
                    }
                }
            ]
        }
        async def fake_post(*_args, **_kwargs):
            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return fake_response

            return Response()

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            run = self.client.post(
                f"/api/projects/{project_id}/ocr/tasks",
                headers=self.headers,
                files={"file": ("ocr.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            )

        self.assertEqual(run.status_code, 200)
        payload = run.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(payload["candidates"]), 3)
        candidate_id = payload["candidates"][0]["id"]

        confirm = self.client.post(
            f"/api/projects/{project_id}/ocr/candidates/{candidate_id}/confirm",
            headers=self.headers,
            json={"action": "confirm", "value": "Wind Farm"},
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()["item"]["status"], "confirmed")
        updated = self.client.get(f"/api/projects/{project_id}/parse-results", headers=self.headers)
        fields = updated.json()["structured"]["ocrConfirmedFields"]
        self.assertEqual(fields[0]["value"], "Wind Farm")


if __name__ == "__main__":
    unittest.main()
