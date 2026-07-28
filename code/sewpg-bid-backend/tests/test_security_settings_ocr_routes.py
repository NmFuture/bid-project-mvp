from __future__ import annotations

import asyncio
import copy
import itertools
import json
import os
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from docx import Document
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from app.models import async_session
from app.models.materials import AuditLog, AuthSession, OcrCandidate, OcrTask, SystemConfig, SystemUser, TemplateAsset
from app.services.audit_service import audit_service
from app.services.auth_service import _password_hash
from app.services.bid_project_state import project_parse_input_records
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.minio_client import minio_client
from app.services.system_settings import OPENCODE_RUNTIME_CONFIG_PATH, system_settings_service
from app.services.store import store


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
        self.run_id = uuid4().hex
        self.project_ids: set[str] = set()
        self.template_asset_ids: set[int] = set()
        self.user_ids: set[str] = set()
        self.token = ""
        self.test_user_id = f"U-TEST-{self.run_id[:12]}"
        self.test_user_name = f"设置联调测试-{self.run_id}"
        self.test_user_email = f"settings-test-{self.run_id}@example.com"
        self.test_user_agent = f"security-settings-ocr-test/{self.run_id}"
        self.original_data_dirs = (settings.uploads_dir, settings.documents_dir, settings.parsed_dir)
        self.original_store_projects = copy.deepcopy(store._projects)
        self.original_store_counter_start = next(store._counter)
        store._counter = itertools.count(self.original_store_counter_start)
        self.addCleanup(self._restore_store_state)

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self._restore_data_dirs)

        self.runtime_config_existed = OPENCODE_RUNTIME_CONFIG_PATH.exists()
        self.runtime_config_bytes = OPENCODE_RUNTIME_CONFIG_PATH.read_bytes() if self.runtime_config_existed else b""
        self.runtime_parent_existed = {
            OPENCODE_RUNTIME_CONFIG_PATH.parent: OPENCODE_RUNTIME_CONFIG_PATH.parent.exists(),
            OPENCODE_RUNTIME_CONFIG_PATH.parent.parent: OPENCODE_RUNTIME_CONFIG_PATH.parent.parent.exists(),
        }
        self.addCleanup(self._restore_runtime_config)

        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()
        store.reset_for_tests()
        store._load_projects()
        store._counter = itertools.count(store._next_project_number())
        asyncio.run(self._snapshot_persistent_state())
        self._register_persistent_cleanups()
        asyncio.run(self._create_test_operator())
        self.client = self.enterContext(
            TestClient(
                app,
                base_url="http://127.0.0.1:8000",
                headers={"user-agent": self.test_user_agent},
            )
        )
        login = self.client.post("/api/auth/login", json={"email": self.test_user_email, "password": "123456"})
        self.assertEqual(login.status_code, 200)
        self.token = login.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        disable_ocr = self.client.put(
            "/api/settings/ocr",
            headers=self.headers,
            json={"enabled": False, "model": "deepseek-ai/DeepSeek-OCR"},
        )
        self.assertEqual(disable_ocr.status_code, 200)

    @staticmethod
    def _run_async_cleanup(cleanup: Any, *args: Any) -> None:
        asyncio.run(cleanup(*args))

    def _register_persistent_cleanups(self) -> None:
        for key in ("llm", "ocr"):
            self.addCleanup(self._run_async_cleanup, self._restore_model_config, key)
        self.addCleanup(self._cleanup_projects)
        self.addCleanup(self._run_async_cleanup, self._cleanup_users)
        self.addCleanup(self._run_async_cleanup, self._cleanup_auth_sessions)
        self.addCleanup(self._run_async_cleanup, self._cleanup_audit_logs)
        for asset_id, is_active in self.template_active_snapshot.items():
            self.addCleanup(
                self._run_async_cleanup,
                self._restore_template_active,
                asset_id,
                is_active,
            )
        self.addCleanup(self._run_async_cleanup, self._cleanup_template_rows)
        self.addCleanup(self._run_async_cleanup, self._cleanup_ocr_tasks)
        self.addCleanup(self._run_async_cleanup, self._cleanup_ocr_candidates)
        self.addCleanup(self._run_async_cleanup, self._cleanup_template_objects)

    def _restore_store_state(self) -> None:
        store._projects = self.original_store_projects
        store._counter = itertools.count(self.original_store_counter_start)

    def _restore_data_dirs(self) -> None:
        settings.uploads_dir, settings.documents_dir, settings.parsed_dir = self.original_data_dirs

    def _restore_runtime_config(self) -> None:
        if self.runtime_config_existed:
            OPENCODE_RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            OPENCODE_RUNTIME_CONFIG_PATH.write_bytes(self.runtime_config_bytes)
            return

        OPENCODE_RUNTIME_CONFIG_PATH.unlink(missing_ok=True)
        for parent, existed in self.runtime_parent_existed.items():
            if not existed:
                try:
                    parent.rmdir()
                except OSError:
                    pass

    async def _snapshot_persistent_state(self) -> None:
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await session.commit()
            configs = (
                await session.execute(select(SystemConfig).where(SystemConfig.key.in_(("llm", "ocr"))))
            ).scalars().all()
            templates = (
                await session.execute(select(TemplateAsset).where(TemplateAsset.asset_type == "default_template"))
            ).scalars().all()
            self.config_snapshot = {
                row.key: {
                    "value": copy.deepcopy(row.value),
                    "sensitive": row.sensitive,
                    "updated_by": row.updated_by,
                    "updated_at": row.updated_at,
                }
                for row in configs
            }
            self.template_active_snapshot = {int(row.id): bool(row.is_active) for row in templates}
            self.system_user_ids_snapshot = set((await session.execute(select(SystemUser.id))).scalars().all())

    async def _create_test_operator(self) -> None:
        async with async_session() as session:
            session.add(
                SystemUser(
                    id=self.test_user_id,
                    name=self.test_user_name,
                    email=self.test_user_email,
                    password_hash=_password_hash("123456"),
                    dept="测试部",
                    roles=["管理员"],
                    status="active",
                )
            )
            await session.commit()
        self.user_ids.add(self.test_user_id)

    async def _cleanup_template_objects(self) -> None:
        if not self.template_asset_ids:
            return
        async with async_session() as session:
            assets = (
                await session.execute(
                    select(TemplateAsset).where(TemplateAsset.id.in_(self.template_asset_ids))
                )
            ).scalars().all()

        errors: list[Exception] = []
        for asset in assets:
            if not asset.minio_key:
                continue
            try:
                minio_client.remove_object(
                    asset.minio_bucket or settings.minio_buckets["templates"],
                    asset.minio_key,
                )
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError(f"清理系统默认模板 MinIO 对象失败，共 {len(errors)} 个") from errors[0]

    async def _cleanup_template_rows(self) -> None:
        if not self.template_asset_ids:
            return
        async with async_session() as session:
            await session.execute(delete(TemplateAsset).where(TemplateAsset.id.in_(self.template_asset_ids)))
            await session.commit()

    async def _restore_template_active(self, asset_id: int, is_active: bool) -> None:
        async with async_session() as session:
            await session.execute(
                update(TemplateAsset).where(TemplateAsset.id == asset_id).values(is_active=is_active)
            )
            await session.commit()

    async def _cleanup_ocr_candidates(self) -> None:
        if not self.project_ids:
            return
        async with async_session() as session:
            await session.execute(delete(OcrCandidate).where(OcrCandidate.project_id.in_(self.project_ids)))
            await session.commit()

    async def _cleanup_ocr_tasks(self) -> None:
        if not self.project_ids:
            return
        async with async_session() as session:
            await session.execute(delete(OcrTask).where(OcrTask.project_id.in_(self.project_ids)))
            await session.commit()

    async def _cleanup_audit_logs(self) -> None:
        async with async_session() as session:
            await session.execute(
                delete(AuditLog).where(
                    (AuditLog.user_id == self.test_user_id)
                    | (AuditLog.user_agent == self.test_user_agent)
                )
            )
            await session.commit()

    async def _cleanup_auth_sessions(self) -> None:
        async with async_session() as session:
            await session.execute(delete(AuthSession).where(AuthSession.user_id == self.test_user_id))
            await session.commit()

    async def _cleanup_users(self) -> None:
        async with async_session() as session:
            bootstrap_user_ids = {"U-ADMIN", "U-ROLE-T", "U-ROLE-B", "U-ROLE-TB"}
            created_user_ids = (
                self.user_ids
                | {self.test_user_id}
                | (bootstrap_user_ids - self.system_user_ids_snapshot)
            )
            if created_user_ids:
                await session.execute(delete(SystemUser).where(SystemUser.id.in_(created_user_ids)))
            await session.commit()

    async def _restore_model_config(self, key: str) -> None:
        async with async_session() as session:
            snapshot = self.config_snapshot.get(key)
            if snapshot is None:
                await session.execute(delete(SystemConfig).where(SystemConfig.key == key))
            else:
                await session.execute(
                    update(SystemConfig)
                    .where(SystemConfig.key == key)
                    .values(**snapshot)
                )
            await session.commit()

    def _cleanup_projects(self) -> None:
        errors: list[Exception] = []
        for project_id in sorted(self.project_ids):
            try:
                store.delete_project(project_id)
            except KeyError:
                pass
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError(f"清理测试项目失败，共 {len(errors)} 个") from errors[0]

    def _track_project(self, response: Any) -> Any:
        if response.status_code == 200:
            project_id = str(response.json().get("id") or "")
            if project_id:
                self.project_ids.add(project_id)
        return response

    def _track_template(self, response: Any) -> Any:
        if response.status_code == 200:
            template_id = str((response.json().get("item") or {}).get("id") or "")
            if template_id:
                self.template_asset_ids.add(int(template_id.replace("TPL-", "")))
        return response

    def _track_user(self, response: Any) -> Any:
        if response.status_code == 200:
            user_id = str(response.json().get("id") or "")
            if user_id:
                self.user_ids.add(user_id)
        return response

    def _wait_for_ocr_task(
        self,
        project_id: str,
        task_id: str,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """通过公开接口等待 lifespan worker 将 OCR 任务处理到终态。"""
        deadline = time.monotonic() + timeout
        last_payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = self.client.get(
                f"/api/technical/projects/{project_id}/ocr/tasks/{task_id}",
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, response.text)
            last_payload = response.json()
            if last_payload.get("status") in ("completed", "failed"):
                return last_payload
            time.sleep(0.05)
        self.fail(f"OCR task {task_id} did not reach terminal state: {last_payload}")

    def test_auth_rejects_wrong_password_and_accepts_real_session(self) -> None:
        wrong = self.client.post("/api/auth/login", json={"email": self.test_user_email, "password": "wrong"})
        self.assertEqual(wrong.status_code, 401)

        me = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["email"], self.test_user_email)

        logout = self.client.post("/api/auth/logout", headers=self.headers)
        self.assertEqual(logout.status_code, 200)
        expired = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(expired.status_code, 401)

    def test_settings_default_templates_and_model_configs_are_real_and_masked(self) -> None:
        default_templates = self.client.get("/api/settings/default-templates", headers=self.headers)
        self.assertEqual(default_templates.status_code, 200)
        self.assertIn({"key": "technical", "label": "技术标"}, default_templates.json()["templateTypes"])

        upload = self._track_template(self.client.post(
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
        ))
        self.assertEqual(upload.status_code, 200)
        template_id = upload.json()["item"]["id"]
        self.assertTrue(upload.json()["item"]["isActive"])
        activate = self.client.post(f"/api/settings/default-templates/{template_id}/activate", headers=self.headers)
        self.assertEqual(activate.status_code, 200)
        self.assertTrue(activate.json()["item"]["isActive"])

        second_upload = self._track_template(self.client.post(
            "/api/settings/default-templates",
            headers=self.headers,
            data={"templateType": "technical", "version": "2026.06"},
            files={
                "file": (
                    "默认技术标模板-v2.docx",
                    build_docx_bytes("默认技术标模板 v2", "第一章 技术响应"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        ))
        self.assertEqual(second_upload.status_code, 200)
        second_template_id = second_upload.json()["item"]["id"]
        technical_items = {
            item["id"]: item for item in second_upload.json()["items"]
            if item["id"] in {template_id, second_template_id}
        }
        self.assertEqual(set(technical_items), {template_id, second_template_id})
        self.assertFalse(technical_items[template_id]["isActive"])
        self.assertEqual(technical_items[template_id]["version"], "2026.05")
        self.assertEqual(technical_items[template_id]["name"], "默认技术标模板.docx")
        self.assertTrue(technical_items[second_template_id]["isActive"])
        self.assertEqual(technical_items[second_template_id]["version"], "2026.06")
        self.assertEqual(technical_items[second_template_id]["name"], "默认技术标模板-v2.docx")

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
        project = self._track_project(self.client.post(
            "/api/business/projects",
            headers=self.headers,
            json={"name": f"默认模板测试项目-{self.run_id}", "customerName": "测试业主"},
        ))
        self.assertEqual(project.status_code, 200)
        project_id = project.json()["id"]

        upload = self._track_template(self.client.post(
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
        ))
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
        email = f"audit-user-{self.run_id}@example.com"
        user_create = self._track_user(self.client.post(
            "/api/settings/users",
            headers=self.headers,
            json={
                "name": "审计测试用户",
                "email": email,
                "dept": "测试部",
                "roles": ["标书经理"],
                "password": "123456",
            },
        ))
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
        current_items = [item for item in audit["items"] if item["user"] == self.test_user_name]
        actions = [item["action"] for item in current_items]
        self.assertIn("创建用户", actions)
        self.assertIn("更新用户", actions)
        self.assertIn("更新OCR 模型配置", actions)
        detail = asyncio.run(audit_service.detail(current_items[0]["id"]))
        self.assertIn("diff", detail)
        payload_text = json.dumps(audit, ensure_ascii=False) + json.dumps(detail, ensure_ascii=False)
        self.assertNotIn("654321", payload_text)
        self.assertEqual(self.client.get("/api/audit", headers=self.headers).status_code, 404)

    def test_ocr_requires_config_and_can_list_tasks(self) -> None:
        project = self._track_project(self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": f"OCR 测试项目-{self.run_id}", "customerName": "测试业主"},
        ))
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
        project = self._track_project(self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": f"OCR 成功测试项目-{self.run_id}", "customerName": "测试业主"},
        ))
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
            completed = self._wait_for_ocr_task(project_id, task_id)

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
        ocr_logs = [
            item for item in technical_audit.json()["items"]
            if item["actionType"] == "ocr" and item["metadata"].get("projectId") == project_id
        ]
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
        self.assertEqual(
            [
                item for item in business_audit.json()["items"]
                if item["actionType"] == "ocr" and item["metadata"].get("projectId") == project_id
            ],
            [],
        )

    def test_unlimited_ocr_image_uses_required_vllm_request_recipe(self) -> None:
        project = self._track_project(self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": f"Unlimited OCR 测试项目-{self.run_id}", "customerName": "测试业主"},
        ))
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
            self._wait_for_ocr_task(project_id, task_id)

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
        project = self._track_project(self.client.post(
            "/api/technical/projects",
            headers=self.headers,
            json={"name": f"OCR 重试测试项目-{self.run_id}", "customerName": "测试业主"},
        ))
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
            completed = self._wait_for_ocr_task(project_id, task_id)

        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["retryCount"], 2)
        # 首次 + 2 次重试 = 3 次调用
        self.assertEqual(call_count, 3)


if __name__ == "__main__":
    unittest.main()
