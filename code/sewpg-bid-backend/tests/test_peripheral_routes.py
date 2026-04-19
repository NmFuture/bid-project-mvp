from __future__ import annotations

import itertools
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.peripheral import peripheral_store
from app.services.store import store


class PeripheralRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.sqlite_path = base / "sqlite" / "app.db"
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store._projects = {}
        store._counter = itertools.count(1)
        peripheral_store.reset()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def create_project(self) -> str:
        response = self.client.post(
            "/api/projects",
            json={
                "name": "外围模块联调项目",
                "customerName": "测试业主",
                "bidType": "技术标",
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    def test_raw_material_library_supports_list_and_mutation(self) -> None:
        permissions = self.client.get("/api/materials/raw/permissions")
        self.assertEqual(permissions.status_code, 200)
        self.assertEqual(permissions.json()["role"], "member")

        tree_response = self.client.get("/api/materials/raw/tree")
        self.assertEqual(tree_response.status_code, 200)
        self.assertGreater(len(tree_response.json()["tree"]), 0)

        create_folder = self.client.post(
            "/api/materials/raw/folders",
            json={"parentPath": "项目定制/PRJ-TEST/技术标", "folderName": "补充资料"},
        )
        self.assertEqual(create_folder.status_code, 200)
        folder_path = create_folder.json()["folderPath"]

        upload = self.client.post(
            "/api/materials/raw/upload",
            json={
                "targetPath": folder_path,
                "files": [
                    {
                        "name": "评分表.docx",
                        "size": 2048,
                        "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    }
                ],
            },
        )
        self.assertEqual(upload.status_code, 200)
        uploaded_item = upload.json()["items"][0]
        self.assertEqual(uploaded_item["folderPath"], folder_path)

        files = self.client.get("/api/materials/raw/files", params={"folderPath": folder_path})
        self.assertEqual(files.status_code, 200)
        self.assertEqual(files.json()["total"], 1)
        self.assertEqual(files.json()["items"][0]["name"], "评分表.docx")

    def test_structured_and_wiki_material_routes_return_frontend_ready_payloads(self) -> None:
        structured = self.client.get("/api/materials/structured")
        self.assertEqual(structured.status_code, 200)
        self.assertIn("items", structured.json())
        self.assertGreater(len(structured.json()["items"]), 0)

        wiki = self.client.get("/api/materials/wiki")
        self.assertEqual(wiki.status_code, 200)
        wiki_payload = wiki.json()
        self.assertIn("tree", wiki_payload)
        self.assertIn("tagOptions", wiki_payload)
        self.assertIsNotNone(wiki_payload["selectedNode"])

        created = self.client.post(
            "/api/materials/wiki",
            json={"title": "风资源说明", "isFolder": False},
        )
        self.assertEqual(created.status_code, 200)
        selected_node = created.json()["selectedNode"]
        self.assertEqual(selected_node["title"], "风资源说明")

        node_id = selected_node["id"]
        updated = self.client.put(
            f"/api/materials/wiki/{node_id}",
            json={
                "title": "风资源说明-更新",
                "markdownContent": "# 风资源说明\n\n需要补充测风塔数据。",
                "tags": ["风资源", "技术标"],
                "applicableTypes": ["技术标"],
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["selectedNode"]["title"], "风资源说明-更新")

        refreshed = self.client.post(f"/api/materials/wiki/{node_id}/refresh-summary")
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("summary", refreshed.json())

    def test_audit_settings_and_export_routes_are_available(self) -> None:
        project_id = self.create_project()

        gateway = self.client.get("/api/settings/llm-gateway")
        self.assertEqual(gateway.status_code, 200)
        self.assertIn("endpoint", gateway.json())

        gateway_test = self.client.post(
            "/api/settings/llm-gateway/test",
            json={"endpoint": "https://gateway.example.com", "model": "gpt-5.4"},
        )
        self.assertEqual(gateway_test.status_code, 200)
        self.assertTrue(gateway_test.json()["success"])

        dotx_upload = self.client.post(
            "/api/settings/dotx-templates",
            json={"fileName": "标准模板.dotx", "fileSize": 1024, "version": "2026.04"},
        )
        self.assertEqual(dotx_upload.status_code, 200)
        dotx_id = dotx_upload.json()["item"]["id"]

        dotx_activate = self.client.post(f"/api/settings/dotx-templates/{dotx_id}/activate")
        self.assertEqual(dotx_activate.status_code, 200)

        excel_upload = self.client.post(
            "/api/settings/excel-templates",
            json={"tableKey": "performance_guarantee", "fileName": "性能保证.xlsx", "version": "2026.04"},
        )
        self.assertEqual(excel_upload.status_code, 200)
        excel_id = excel_upload.json()["item"]["id"]

        excel_activate = self.client.post(f"/api/settings/excel-templates/{excel_id}/activate")
        self.assertEqual(excel_activate.status_code, 200)

        backup_create = self.client.post("/api/settings/backups/create", json={"note": "联调前备份"})
        self.assertEqual(backup_create.status_code, 200)
        backup_id = backup_create.json()["item"]["id"]

        backup_restore = self.client.post(f"/api/settings/backups/{backup_id}/restore")
        self.assertEqual(backup_restore.status_code, 200)

        health = self.client.get("/api/settings/health")
        self.assertEqual(health.status_code, 200)
        self.assertIsInstance(health.json(), list)

        audit_list = self.client.get("/api/audit")
        self.assertEqual(audit_list.status_code, 200)
        audit_payload = audit_list.json()
        self.assertIn("filterOptions", audit_payload)
        self.assertGreater(len(audit_payload["items"]), 0)

        audit_id = audit_payload["items"][0]["id"]
        audit_detail = self.client.get(f"/api/audit/{audit_id}")
        self.assertEqual(audit_detail.status_code, 200)
        self.assertEqual(audit_detail.json()["id"], audit_id)

        audit_export = self.client.get("/api/audit/export")
        self.assertEqual(audit_export.status_code, 200)
        self.assertIn("fileName", audit_export.json())

        export_check = self.client.get(f"/api/projects/{project_id}/export/check")
        self.assertEqual(export_check.status_code, 200)
        self.assertIn("suggestedFileName", export_check.json())

        blocked_export = self.client.post(
            f"/api/projects/{project_id}/export",
            json={"format": "docx", "fileName": "投标文件_PRJ_TEST", "warningConfirmed": False},
        )
        self.assertEqual(blocked_export.status_code, 400)
        self.assertEqual(blocked_export.json()["code"], "EXPORT_WARNING_NOT_CONFIRMED")

        exported = self.client.post(
            f"/api/projects/{project_id}/export",
            json={"format": "docx", "fileName": "投标文件_PRJ_TEST", "warningConfirmed": True},
        )
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.json()["fileName"].endswith(".docx"))


if __name__ == "__main__":
    unittest.main()
