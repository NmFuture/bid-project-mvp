from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from app.models import async_session
from app.models.materials import OcrTask
from app.services.audit_service import audit_service
from app.services.bid_project_state import project_parse_input_records
from app.services.ocr_service import ocr_service
from app.services.system_settings import system_settings_service
from app.services.store import store
from sqlalchemy import select


def build_docx_bytes(*lines: str) -> bytes:
    file_obj = BytesIO()
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(file_obj)
    return file_obj.getvalue()


def parse_inputs_for_tests(project_id: str):
    project = store.get_project_runtime_state(project_id)
    return project_parse_input_records(project_id, project)


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

    def _drain_task(self, task_id: str) -> dict[str, Any]:
        """在测试环境中手动驱动 OCR worker 把任务跑到终态。"""

        async def _run() -> dict[str, Any]:
            # 避免测试里自动启动的后台 worker 与手动处理冲突
            await ocr_service.stop_worker()
            for _ in range(5):
                await ocr_service._process_task(task_id)
                async with async_session() as session:
                    task = (
                        await session.execute(select(OcrTask).where(OcrTask.id == task_id))
                    ).scalar_one_or_none()
                    if task is not None and task.status in ("completed", "failed"):
                        return task.to_dict()
            async with async_session() as session:
                task = (
                    await session.execute(select(OcrTask).where(OcrTask.id == task_id))
                ).scalar_one_or_none()
                if task is None:
                    raise AssertionError(f"OCR task {task_id} disappeared")
                raise AssertionError(f"OCR task {task_id} did not reach terminal state: {task.status} / {task.error_message}")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_run())
            finally:
                loop.close()
        else:
            return asyncio.run_coroutine_threadsafe(_run(), loop).result()

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
        self.assertTrue(update_llm.json()["opencodeRestartRequired"])
        runtime_config_path = update_llm.json()["opencodeRuntimeConfigPath"]
        self.assertTrue(runtime_config_path.endswith("_runtime/opencode/opencode.runtime.json"))
        self.assertTrue(Path(runtime_config_path).exists())
        runtime_config = json.loads(Path(runtime_config_path).read_text(encoding="utf-8"))
        self.assertEqual(runtime_config["model"], "mimo/demo-model")
        self.assertEqual(runtime_config["provider"]["mimo"]["options"]["baseURL"], "https://llm.example.com/v1/chat/completions")
        self.assertEqual(runtime_config["provider"]["mimo"]["options"]["apiKey"], "sk-test-secret")

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

    def test_llm_chat_completions_url_normalization_supports_deepseek_base_url(self) -> None:
        self.assertEqual(
            system_settings_service._chat_completions_url("https://api.deepseek.com"),
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(
            system_settings_service._chat_completions_url("https://api.deepseek.com/v1"),
            "https://api.deepseek.com/v1/chat/completions",
        )
        self.assertEqual(
            system_settings_service._chat_completions_url("https://api.deepseek.com/chat/completions"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_enabled_system_default_template_is_used_as_project_fallback(self) -> None:
        project = self.client.post(
            "/api/business/projects",
            headers=self.headers,
            json={"name": "默认模板测试项目", "customerName": "测试业主"},
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

        fallback = self.client.get(f"/api/business/projects/{project_id}/template-fallback", headers=self.headers)
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(fallback.json()["template"]["source"], "system-default")
        self.assertEqual(fallback.json()["template"]["templateType"], "business")
        self.assertEqual(fallback.json()["template"]["name"], "默认商务标模板.docx")

        disabled = self.client.put(
            f"/api/business/projects/{project_id}/template-fallback",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])
        enabled = self.client.put(
            f"/api/business/projects/{project_id}/template-fallback",
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
            _, template_files = parse_inputs_for_tests(project_id)

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
        audit = asyncio.run(audit_service.list({}))
        actions = [item["action"] for item in audit["items"]]
        self.assertIn("创建用户", actions)
        self.assertIn("更新用户", actions)
        self.assertIn("更新OCR 模型配置", actions)
        detail = asyncio.run(audit_service.detail(audit["items"][0]["id"]))
        self.assertIn("diff", detail)
        payload_text = json.dumps(audit, ensure_ascii=False) + json.dumps(detail, ensure_ascii=False)
        self.assertNotIn("654321", payload_text)
        self.assertEqual(self.client.get("/api/audit", headers=self.headers).status_code, 404)

    def test_ocr_requires_config_and_can_list_tasks(self) -> None:
        project = self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": "OCR 测试项目", "customerName": "测试业主"},
        )
        self.assertEqual(project.status_code, 200)
        project_id = project.json()["id"]

        before = self.client.get(f"/api/technical/projects/{project_id}/ocr/tasks", headers=self.headers)
        self.assertEqual(before.status_code, 200)

        run = self.client.post(
            f"/api/technical/projects/{project_id}/ocr/tasks",
            headers=self.headers,
            files={"file": ("ocr.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        self.assertEqual(run.status_code, 400)

        tasks = self.client.get(f"/api/technical/projects/{project_id}/ocr/tasks", headers=self.headers)
        self.assertEqual(tasks.status_code, 200)
        self.assertEqual(tasks.json()["total"], before.json()["total"])

    def test_ocr_success_persists_task_candidates_and_confirmation(self) -> None:
        project = self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": "OCR 成功测试项目", "customerName": "测试业主"},
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
                f"/api/technical/projects/{project_id}/ocr/tasks",
                headers=self.headers,
                files={"file": ("ocr.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            )
            self.assertEqual(run.status_code, 200)
            payload = run.json()
            self.assertEqual(payload["status"], "pending")
            task_id = payload["id"]
            completed = self._drain_task(task_id)

        self.assertEqual(completed["status"], "completed")

        detail = self.client.get(f"/api/technical/projects/{project_id}/ocr/tasks/{task_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(len(payload["candidates"]), 3)
        candidate_id = payload["candidates"][0]["id"]

        confirm = self.client.post(
            f"/api/technical/projects/{project_id}/ocr/candidates/{candidate_id}/confirm",
            headers=self.headers,
            json={"action": "confirm", "value": "Wind Farm"},
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()["item"]["status"], "confirmed")
        updated = self.client.get(f"/api/technical/projects/{project_id}/parse-results", headers=self.headers)
        fields = updated.json()["structured"]["ocrConfirmedFields"]
        self.assertEqual(fields[0]["value"], "Wind Farm")

        technical_audit = self.client.get("/api/technical/audit", headers=self.headers)
        self.assertEqual(technical_audit.status_code, 200)
        ocr_logs = [item for item in technical_audit.json()["items"] if item["actionType"] == "ocr"]
        self.assertGreaterEqual(len(ocr_logs), 2)
        self.assertTrue(all(item["metadata"].get("bidType") == "技术标" for item in ocr_logs))
        self.assertTrue(all(item["metadata"].get("projectId") == project_id for item in ocr_logs))
        run_log = next(item for item in ocr_logs if item["action"] == "执行 OCR 识别")
        self.assertEqual(run_log["metadata"]["candidateCount"], 3)

        detail = self.client.get(f"/api/technical/audit/{run_log['id']}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["metadata"]["bidType"], "技术标")
        business_detail = self.client.get(f"/api/business/audit/{run_log['id']}", headers=self.headers)
        self.assertEqual(business_detail.status_code, 404)
        business_audit = self.client.get("/api/business/audit", headers=self.headers)
        self.assertEqual(business_audit.status_code, 200)
        self.assertEqual([item for item in business_audit.json()["items"] if item["actionType"] == "ocr"], [])

    def test_unlimited_ocr_image_uses_required_vllm_request_recipe(self) -> None:
        project = self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": "Unlimited OCR 测试项目", "customerName": "测试业主"},
        )
        self.assertEqual(project.status_code, 200)
        project_id = project.json()["id"]
        self.client.put(
            "/api/settings/ocr",
            headers=self.headers,
            json={
                "enabled": True,
                "baseUrl": "http://unlimited-ocr:8000/v1",
                "model": "baidu/Unlimited-OCR",
                "timeoutMs": 60000,
                "maxTokens": 8192,
            },
        )

        captured: dict[str, Any] = {}

        async def fake_post(*_args, **kwargs):
            captured.update(kwargs)

            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {"choices": [{"message": {"content": "<|ref|>Project: Wind Farm<|/ref|><|det|>[[1,2,3,4]]<|/det|>"}}]}

            return Response()

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            run = self.client.post(
                f"/api/technical/projects/{project_id}/ocr/tasks",
                headers=self.headers,
                files={"file": ("ocr.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            )
            self.assertEqual(run.status_code, 200)
            self.assertEqual(run.json()["status"], "pending")
            task_id = run.json()["id"]
            self._drain_task(task_id)

        payload = captured["json"]
        self.assertEqual(payload["model"], "baidu/Unlimited-OCR")
        self.assertEqual(payload["messages"][0]["content"][0]["text"], "<image>document parsing.")
        self.assertFalse(payload["skip_special_tokens"])
        self.assertEqual(payload["vllm_xargs"], {"ngram_size": 35, "window_size": 128})

        detail = self.client.get(f"/api/technical/projects/{project_id}/ocr/tasks/{task_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("<|det|>", json.dumps(detail.json()))
        self.assertEqual(detail.json()["candidates"][0]["fieldValue"], "Wind Farm")

    def test_ocr_task_retries_and_eventually_fails(self) -> None:
        project = self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": "OCR 重试测试项目", "customerName": "测试业主"},
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

        call_count = 0

        async def fake_post(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1

            class Response:
                status_code = 500
                text = "OCR service error"

                @staticmethod
                def json():
                    return {}

            return Response()

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            run = self.client.post(
                f"/api/technical/projects/{project_id}/ocr/tasks",
                headers=self.headers,
                files={"file": ("ocr.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            )
            self.assertEqual(run.status_code, 200)
            self.assertEqual(run.json()["status"], "pending")
            task_id = run.json()["id"]
            completed = self._drain_task(task_id)

        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["retryCount"], 2)
        # 首次 + 2 次重试 = 3 次调用
        self.assertEqual(call_count, 3)


if __name__ == "__main__":
    unittest.main()
