from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx
import os
import pytest
from uuid import uuid4
from sqlalchemy import delete, select

from app.core.config import settings
from app.main import app
from app.models import async_session
from app.models.materials import RawFile, RawFolder, WikiNode
from app.services.minio_client import minio_client
from app.services.peripheral import peripheral_store
from app.services.store import store


@unittest.skipUnless(os.getenv("BID_RUN_INTEGRATION") == "1", "requires PostgreSQL, MinIO, and Redis")
@pytest.mark.integration
@pytest.mark.skipif(os.getenv("BID_RUN_INTEGRATION") != "1", reason="requires PostgreSQL, MinIO, and Redis")
class PeripheralRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()
        self.run_id = uuid4().hex[:8]

        store.reset_for_tests(clear_persistent=True)
        peripheral_store.reset()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        )
        login = await self.client.post("/api/auth/login", json={"email": "admin@sewpg.com", "password": "123456"})
        login.raise_for_status()
        self.headers = {"Authorization": f"Bearer {login.json()['token']}"}

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self._cleanup_material_test_data()
        self.temp_dir.cleanup()

    async def _cleanup_material_test_data(self) -> None:
        async with async_session() as session:
            result = await session.execute(
                select(RawFile)
                .join(RawFolder)
                .where(RawFolder.path.like(f"%{self.run_id}%"))
            )
            for item in result.scalars().all():
                if item.minio_key:
                    minio_client.remove_object(item.minio_bucket or settings.minio_buckets["materials"], item.minio_key)
                ext = item.ext_fields or {}
                cleaned_key = str(ext.get("cleanedMinioKey") or "")
                if cleaned_key:
                    minio_client.remove_object(
                        str(ext.get("cleanedMinioBucket") or settings.minio_buckets["materials"]),
                        cleaned_key,
                    )

            await session.execute(delete(WikiNode).where(WikiNode.path.like(f"%{self.run_id}%")))
            await session.execute(delete(RawFolder).where(RawFolder.path.like(f"%{self.run_id}%")))
            await session.commit()

    async def create_project(self) -> str:
        response = await self.client.post(
            "/api/technical/projects",
            json={
                "name": "外围模块联调项目",
                "customerName": "测试业主",
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    async def test_raw_material_library_supports_list_and_mutation(self) -> None:
        tree_response = await self.client.get("/api/technical/materials/raw/tree")
        self.assertEqual(tree_response.status_code, 200)
        self.assertGreater(len(tree_response.json()["tree"]), 0)

        project_id = f"PRJ-TEST-{self.run_id}"
        bootstrap = await self.client.post(
            "/api/technical/materials/raw/folders/bootstrap",
            json={"projectId": project_id},
        )
        self.assertEqual(bootstrap.status_code, 200)

        create_folder = await self.client.post(
            "/api/technical/materials/raw/folders",
            json={"parentPath": f"技术标/项目素材/{project_id}", "folderName": f"补充资料-{self.run_id}"},
        )
        self.assertEqual(create_folder.status_code, 200)
        folder_path = create_folder.json()["folderPath"]

        upload = await self.client.post(
            "/api/technical/materials/raw/upload",
            data={"targetPath": folder_path},
            files=[
                (
                    "files",
                    (
                        "评分表.docx",
                        b"fake-docx-content",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        self.assertEqual(upload.status_code, 200)
        uploaded_item = upload.json()["items"][0]
        self.assertEqual(uploaded_item["folderPath"], folder_path)

        files = await self.client.get("/api/technical/materials/raw/files", params={"folderPath": folder_path})
        self.assertEqual(files.status_code, 200)
        self.assertEqual(files.json()["total"], 1)
        self.assertEqual(files.json()["items"][0]["name"], "评分表.docx")

        file_id = files.json()["items"][0]["id"]

        renamed = await self.client.patch(f"/api/technical/materials/raw/{file_id}", json={"name": "评分表-重命名.docx"})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["item"]["name"], "评分表-重命名.docx")

        download = await self.client.get(f"/api/technical/materials/raw/{file_id}/download")
        self.assertEqual(download.status_code, 200)
        self.assertIn("downloadUrl", download.json())
        self.assertTrue(download.json()["downloadUrl"].startswith("/api/technical/materials/raw/"))

    async def test_raw_material_library_supports_folder_upload(self) -> None:
        create_folder = await self.client.post(
            "/api/technical/materials/raw/folders",
            json={"parentPath": "技术标/通用素材", "folderName": f"目录上传测试-{self.run_id}"},
        )
        self.assertEqual(create_folder.status_code, 200)
        folder_path = create_folder.json()["folderPath"]

        upload = await self.client.post(
            "/api/technical/materials/raw/upload",
            data={"targetPath": folder_path},
            files=[
                (
                    "files",
                    (
                        "评分表.docx",
                        b"nested-content",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
                ("relativePaths", (None, "投标资料/附件/评分表.docx")),
            ],
        )
        self.assertEqual(upload.status_code, 200)
        uploaded_item = upload.json()["items"][0]
        self.assertEqual(uploaded_item["folderPath"], f"{folder_path}/投标资料/附件")
        self.assertEqual(uploaded_item["name"], "评分表.docx")

    async def test_business_raw_material_library_supports_upload_and_query(self) -> None:
        customer_name = f"华能集团-{self.run_id}"
        target_path = f"商务标/客户素材/{customer_name}/01-客户关系与专项证明"
        upload = await self.client.post(
            "/api/business/materials/raw/upload",
            data={
                "targetPath": target_path,
                "customerName": customer_name,
            },
            files=[
                (
                    "files",
                    (
                        "授权书.docx",
                        b"fake-business-docx-content",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        self.assertEqual(upload.status_code, 200)
        uploaded_item = upload.json()["items"][0]
        self.assertEqual(uploaded_item["bidType"], "商务标")
        self.assertEqual(uploaded_item["materialTier"], "customer")
        self.assertEqual(uploaded_item["customerName"], customer_name)
        self.assertEqual(uploaded_item["folderPath"], target_path)

        files = await self.client.get(
            "/api/business/materials/raw/files",
            params={"customerName": customer_name},
        )
        self.assertEqual(files.status_code, 200)
        self.assertEqual(files.json()["total"], 1)
        self.assertEqual(files.json()["items"][0]["name"], "授权书.docx")
        self.assertEqual(files.json()["items"][0]["bidType"], "商务标")

    async def test_identity_and_wiki_material_routes_return_frontend_ready_payloads(self) -> None:
        identity = await self.client.get("/api/technical/materials/identity-options")
        self.assertEqual(identity.status_code, 200)
        self.assertIn("customers", identity.json())
        self.assertIn("projects", identity.json())

        wiki = await self.client.get("/api/technical/materials/wiki")
        self.assertEqual(wiki.status_code, 200)
        wiki_payload = wiki.json()
        self.assertIn("tree", wiki_payload)
        self.assertIn("tagOptions", wiki_payload)
        self.assertIsNotNone(wiki_payload["selectedNode"])

        created = await self.client.post(
            "/api/technical/materials/wiki",
            json={"title": f"风资源说明-{self.run_id}", "isFolder": False},
        )
        self.assertEqual(created.status_code, 200)
        selected_node = created.json()["selectedNode"]
        self.assertEqual(selected_node["title"], f"风资源说明-{self.run_id}")

        node_id = selected_node["id"]
        updated = await self.client.put(
            f"/api/technical/materials/wiki/{node_id}",
            json={
                "title": f"风资源说明-更新-{self.run_id}",
                "markdownContent": "# 风资源说明\n\n需要补充测风塔数据。",
                "tags": ["风资源", "技术标"],
                "applicableTypes": ["技术标"],
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["selectedNode"]["title"], f"风资源说明-更新-{self.run_id}")

        refreshed = await self.client.post(f"/api/technical/materials/wiki/{node_id}/refresh-summary")
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("summary", refreshed.json())

    async def test_audit_settings_and_export_routes_are_available(self) -> None:
        project_id = await self.create_project()

        gateway = await self.client.get("/api/settings/llm-gateway", headers=self.headers)
        self.assertEqual(gateway.status_code, 200)
        self.assertIn("endpoint", gateway.json())

        gateway_test = await self.client.post(
            "/api/settings/llm-gateway/test",
            headers=self.headers,
            json={"endpoint": "https://gateway.example.com", "model": "gpt-5.4"},
        )
        self.assertEqual(gateway_test.status_code, 502)
        self.assertEqual(gateway_test.json()["code"], "LLM_TEST_FAILED")

        default_templates = await self.client.get("/api/settings/default-templates", headers=self.headers)
        self.assertEqual(default_templates.status_code, 200)
        self.assertIn("items", default_templates.json())

        health = await self.client.get("/api/settings/health", headers=self.headers)
        self.assertEqual(health.status_code, 200)
        self.assertIsInstance(health.json(), list)

        audit_list = await self.client.get("/api/technical/audit", headers=self.headers)
        self.assertEqual(audit_list.status_code, 200)
        audit_payload = audit_list.json()
        self.assertIn("filterOptions", audit_payload)

        audit_export = await self.client.get("/api/technical/audit/export", headers=self.headers)
        self.assertEqual(audit_export.status_code, 200)
        self.assertIn("fileName", audit_export.json())

        export_check = await self.client.get(f"/api/technical/projects/{project_id}/export/check")
        self.assertEqual(export_check.status_code, 200)
        self.assertIn("suggestedFileName", export_check.json())

        blocked_export = await self.client.post(
            f"/api/technical/projects/{project_id}/export",
            json={"format": "docx", "fileName": "投标文件_PRJ_TEST", "warningConfirmed": False},
        )
        self.assertEqual(blocked_export.status_code, 400)
        self.assertEqual(blocked_export.json()["code"], "EXPORT_WARNING_NOT_CONFIRMED")

        exported = await self.client.post(
            f"/api/technical/projects/{project_id}/export",
            json={"format": "docx", "fileName": "投标文件_PRJ_TEST", "warningConfirmed": True},
        )
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.json()["fileName"].endswith(".docx"))


if __name__ == "__main__":
    unittest.main()
