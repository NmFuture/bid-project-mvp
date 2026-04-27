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
            "/api/projects",
            json={
                "name": "外围模块联调项目",
                "customerName": "测试业主",
                "bidType": "技术标",
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    async def test_raw_material_library_supports_list_and_mutation(self) -> None:
        permissions = await self.client.get("/api/materials/raw/permissions")
        self.assertEqual(permissions.status_code, 200)
        self.assertEqual(permissions.json()["role"], "member")

        tree_response = await self.client.get("/api/materials/raw/tree")
        self.assertEqual(tree_response.status_code, 200)
        self.assertGreater(len(tree_response.json()["tree"]), 0)

        create_folder = await self.client.post(
            "/api/materials/raw/folders",
            json={"parentPath": f"项目素材/PRJ-TEST-{self.run_id}/技术标", "folderName": f"补充资料-{self.run_id}"},
        )
        self.assertEqual(create_folder.status_code, 200)
        folder_path = create_folder.json()["folderPath"]

        upload = await self.client.post(
            "/api/materials/raw/upload",
            data={"targetPath": folder_path, "bidType": "技术标"},
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

        files = await self.client.get("/api/materials/raw/files", params={"folderPath": folder_path})
        self.assertEqual(files.status_code, 200)
        self.assertEqual(files.json()["total"], 1)
        self.assertEqual(files.json()["items"][0]["name"], "评分表.docx")

        file_id = files.json()["items"][0]["id"]

        renamed = await self.client.patch(f"/api/materials/raw/{file_id}", json={"name": "评分表-重命名.docx"})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["item"]["name"], "评分表-重命名.docx")

        download = await self.client.get(f"/api/materials/raw/{file_id}/download")
        self.assertEqual(download.status_code, 200)
        self.assertIn("downloadUrl", download.json())

    async def test_raw_material_library_supports_folder_upload(self) -> None:
        create_folder = await self.client.post(
            "/api/materials/raw/folders",
            json={"parentPath": "通用素材/技术标", "folderName": f"目录上传测试-{self.run_id}"},
        )
        self.assertEqual(create_folder.status_code, 200)
        folder_path = create_folder.json()["folderPath"]

        upload = await self.client.post(
            "/api/materials/raw/upload",
            data={"targetPath": folder_path, "bidType": "技术标"},
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

    async def test_structured_and_wiki_material_routes_return_frontend_ready_payloads(self) -> None:
        structured = await self.client.get("/api/materials/structured")
        self.assertEqual(structured.status_code, 200)
        self.assertIn("items", structured.json())
        self.assertIn("tableOptions", structured.json())
        self.assertGreater(len(structured.json()["tableOptions"]), 0)

        wiki = await self.client.get("/api/materials/wiki")
        self.assertEqual(wiki.status_code, 200)
        wiki_payload = wiki.json()
        self.assertIn("tree", wiki_payload)
        self.assertIn("tagOptions", wiki_payload)
        self.assertIsNotNone(wiki_payload["selectedNode"])

        created = await self.client.post(
            "/api/materials/wiki",
            json={"title": f"风资源说明-{self.run_id}", "isFolder": False},
        )
        self.assertEqual(created.status_code, 200)
        selected_node = created.json()["selectedNode"]
        self.assertEqual(selected_node["title"], f"风资源说明-{self.run_id}")

        node_id = selected_node["id"]
        updated = await self.client.put(
            f"/api/materials/wiki/{node_id}",
            json={
                "title": f"风资源说明-更新-{self.run_id}",
                "markdownContent": "# 风资源说明\n\n需要补充测风塔数据。",
                "tags": ["风资源", "技术标"],
                "applicableTypes": ["技术标"],
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["selectedNode"]["title"], f"风资源说明-更新-{self.run_id}")

        refreshed = await self.client.post(f"/api/materials/wiki/{node_id}/refresh-summary")
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("summary", refreshed.json())

    async def test_audit_settings_and_export_routes_are_available(self) -> None:
        project_id = await self.create_project()

        gateway = await self.client.get("/api/settings/llm-gateway")
        self.assertEqual(gateway.status_code, 200)
        self.assertIn("endpoint", gateway.json())

        gateway_test = await self.client.post(
            "/api/settings/llm-gateway/test",
            json={"endpoint": "https://gateway.example.com", "model": "gpt-5.4"},
        )
        self.assertEqual(gateway_test.status_code, 200)
        self.assertTrue(gateway_test.json()["success"])

        dotx_upload = await self.client.post(
            "/api/settings/dotx-templates",
            json={"fileName": "标准模板.dotx", "fileSize": 1024, "version": "2026.04"},
        )
        self.assertEqual(dotx_upload.status_code, 200)
        dotx_id = dotx_upload.json()["item"]["id"]

        dotx_activate = await self.client.post(f"/api/settings/dotx-templates/{dotx_id}/activate")
        self.assertEqual(dotx_activate.status_code, 200)

        excel_upload = await self.client.post(
            "/api/settings/excel-templates",
            json={"tableKey": "performance_guarantee", "fileName": "性能保证.xlsx", "version": "2026.04"},
        )
        self.assertEqual(excel_upload.status_code, 200)
        excel_id = excel_upload.json()["item"]["id"]

        excel_activate = await self.client.post(f"/api/settings/excel-templates/{excel_id}/activate")
        self.assertEqual(excel_activate.status_code, 200)

        backup_create = await self.client.post("/api/settings/backups/create", json={"note": "联调前备份"})
        self.assertEqual(backup_create.status_code, 200)
        backup_id = backup_create.json()["item"]["id"]

        backup_restore = await self.client.post(f"/api/settings/backups/{backup_id}/restore")
        self.assertEqual(backup_restore.status_code, 200)

        health = await self.client.get("/api/settings/health")
        self.assertEqual(health.status_code, 200)
        self.assertIsInstance(health.json(), list)

        audit_list = await self.client.get("/api/audit")
        self.assertEqual(audit_list.status_code, 200)
        audit_payload = audit_list.json()
        self.assertIn("filterOptions", audit_payload)
        self.assertGreater(len(audit_payload["items"]), 0)

        audit_id = audit_payload["items"][0]["id"]
        audit_detail = await self.client.get(f"/api/audit/{audit_id}")
        self.assertEqual(audit_detail.status_code, 200)
        self.assertEqual(audit_detail.json()["id"], audit_id)

        audit_export = await self.client.get("/api/audit/export")
        self.assertEqual(audit_export.status_code, 200)
        self.assertIn("fileName", audit_export.json())

        export_check = await self.client.get(f"/api/projects/{project_id}/export/check")
        self.assertEqual(export_check.status_code, 200)
        self.assertIn("suggestedFileName", export_check.json())

        blocked_export = await self.client.post(
            f"/api/projects/{project_id}/export",
            json={"format": "docx", "fileName": "投标文件_PRJ_TEST", "warningConfirmed": False},
        )
        self.assertEqual(blocked_export.status_code, 400)
        self.assertEqual(blocked_export.json()["code"], "EXPORT_WARNING_NOT_CONFIRMED")

        exported = await self.client.post(
            f"/api/projects/{project_id}/export",
            json={"format": "docx", "fileName": "投标文件_PRJ_TEST", "warningConfirmed": True},
        )
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.json()["fileName"].endswith(".docx"))


if __name__ == "__main__":
    unittest.main()
