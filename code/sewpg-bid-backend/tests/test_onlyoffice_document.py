from __future__ import annotations

import re
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.onlyoffice_documents import build_editor_session_key, document_path
from app.services.material_store import material_store
from app.services.peripheral import PeripheralError
from app.services.store import store


class OnlyOfficeDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.original_onlyoffice_backend_base_url = settings.onlyoffice_backend_base_url
        self.original_onlyoffice_callback_token = settings.onlyoffice_callback_token
        self.original_onlyoffice_download_allowed_hosts = settings.onlyoffice_download_allowed_hosts
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.onlyoffice_backend_base_url = ""
        settings.onlyoffice_callback_token = ""
        settings.onlyoffice_download_allowed_hosts = ("127.0.0.1", "localhost", "onlyoffice")
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")
        self.gap_planner_patcher = patch(
            "app.services.gap_planning.OpencodeClient.run_bid_tech_gap_planner_with_trace",
            side_effect=RuntimeError("offline test fallback"),
        )
        self.gap_planner_patcher.start()

    def tearDown(self) -> None:
        self.gap_planner_patcher.stop()
        self.client.close()
        settings.onlyoffice_backend_base_url = self.original_onlyoffice_backend_base_url
        settings.onlyoffice_callback_token = self.original_onlyoffice_callback_token
        settings.onlyoffice_download_allowed_hosts = self.original_onlyoffice_download_allowed_hosts
        self.temp_dir.cleanup()

    def create_project(self) -> str:
        response = self.client.post(
            "/api/projects",
            json={
                "name": "OnlyOffice 联调项目",
                "customerName": "测试业主",
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    def create_project_with_review_document(self) -> str:
        project_id = self.create_project()
        store.save_generated_outline(
            project_id=project_id,
            nodes=[
                {
                    "id": "OL-1",
                    "title": "第1章 标前概述",
                    "children": [
                        {"id": "OL-1-1", "title": "技术评分标准索引表", "children": []},
                        {"id": "OL-1-2", "title": "投标方案优势说明", "children": []},
                    ],
                },
                {
                    "id": "OL-2",
                    "title": "第2章 技术标准",
                    "children": [
                        {"id": "OL-2-1", "title": "性能保证", "children": []},
                    ],
                },
            ],
            generated_at="2026-04-20T00:00:00Z",
            summary="目录已生成。",
        )
        store.confirm_outline(project_id)
        store.run_gap_detection(project_id)
        for item in store.get_gap_filling(project_id)["items"]:
            store.update_gap_item(project_id, item["id"], {"status": "skipped", "reason": "测试中人工确认忽略"})
        store.check_gap_plan_integrity(project_id)
        store.submit_gap_review(project_id)
        store.prepare_review_document(project_id)
        return project_id

    def test_document_file_is_real_docx(self) -> None:
        project_id = self.create_project()

        response = self.client.get(f"/api/projects/{project_id}/document/file")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        )
        self.assertEqual(response.content[:2], b"PK")

    def test_document_session_uses_docker_reachable_urls_for_local_dev(self) -> None:
        project_id = self.create_project()

        with patch("app.api.utils.detect_lan_ip", return_value="192.168.31.148"):
            response = self.client.get(f"/api/projects/{project_id}/document")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        expected_host = "192.168.31.148:8000"
        self.assertIn(expected_host, payload["onlyoffice"]["fileUrl"])
        self.assertIn(expected_host, payload["onlyoffice"]["callbackUrl"])

    def test_document_session_falls_back_to_host_docker_internal_when_lan_ip_unavailable_on_darwin(self) -> None:
        if platform.system() != "Darwin":
            self.skipTest("Darwin-only fallback behavior")

        project_id = self.create_project()

        with patch("app.api.utils.detect_lan_ip", return_value=""):
            response = self.client.get(f"/api/projects/{project_id}/document")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("host.docker.internal:8000", payload["onlyoffice"]["fileUrl"])
        self.assertIn("host.docker.internal:8000", payload["onlyoffice"]["callbackUrl"])

    def test_explicit_onlyoffice_backend_base_url_is_used_for_document_and_review_routes(self) -> None:
        project_id = self.create_project_with_review_document()
        settings.onlyoffice_backend_base_url = "http://fastapi:8000"

        document_response = self.client.get(f"/api/projects/{project_id}/document")
        review_response = self.client.get(f"/api/projects/{project_id}/review-items/document")

        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(review_response.status_code, 200)

        document_payload = document_response.json()
        review_payload = review_response.json()
        self.assertEqual(
            document_payload["onlyoffice"]["fileUrl"],
            f"http://fastapi:8000/api/projects/{project_id}/document/file/{quote(document_payload['fileName'])}",
        )
        self.assertEqual(
            document_payload["onlyoffice"]["callbackUrl"],
            f"http://fastapi:8000/api/projects/{project_id}/document/callback",
        )
        self.assertEqual(
            review_payload["onlyoffice"]["fileUrl"],
            f"http://fastapi:8000/api/projects/{project_id}/review-items/document/file/{quote(review_payload['fileName'])}",
        )
        self.assertEqual(
            review_payload["onlyoffice"]["callbackUrl"],
            f"http://fastapi:8000/api/projects/{project_id}/review-items/document/callback",
        )

    def test_document_callback_rejects_invalid_token(self) -> None:
        project_id = self.create_project()
        settings.onlyoffice_callback_token = "secret-token"

        response = self.client.post(
            f"/api/projects/{project_id}/document/callback",
            params={"oo_callback_token": "wrong"},
            json={"status": 6, "url": "http://127.0.0.1:8000/api/projects/foo/document/file/x.docx"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("callback token", response.text)

    def test_review_callback_rejects_invalid_token(self) -> None:
        project_id = self.create_project_with_review_document()
        settings.onlyoffice_callback_token = "secret-token"

        response = self.client.post(
            f"/api/projects/{project_id}/review-items/document/callback",
            params={"oo_callback_token": "bad"},
            json={"status": 6, "url": "http://127.0.0.1:8000/api/projects/foo/document/file/x.docx"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("callback token", response.text)

    def test_document_callback_rejects_disallowed_download_host(self) -> None:
        project_id = self.create_project()
        settings.onlyoffice_callback_token = "secret-token"

        response = self.client.post(
            f"/api/projects/{project_id}/document/callback",
            params={"oo_callback_token": "secret-token"},
            json={"status": 6, "url": "https://attacker.example.com/malware.docx"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("白名单", response.text)

    def test_file_routes_accept_filename_suffix_alias(self) -> None:
        project_id = self.create_project_with_review_document()

        review_response = self.client.get(f"/api/projects/{project_id}/review-items/document")
        document_response = self.client.get(f"/api/projects/{project_id}/document")

        self.assertEqual(review_response.status_code, 200)
        self.assertEqual(document_response.status_code, 200)

        review_file_url = review_response.json()["fileUrl"]
        document_file_url = document_response.json()["fileUrl"]

        review_file = self.client.get(review_file_url.replace("http://127.0.0.1:8000", ""))
        document_file = self.client.get(document_file_url.replace("http://127.0.0.1:8000", ""))

        self.assertEqual(review_file.status_code, 200)
        self.assertEqual(document_file.status_code, 200)
        self.assertEqual(review_file.content[:2], b"PK")
        self.assertEqual(document_file.content[:2], b"PK")

    def test_force_save_route_refreshes_document_session_key(self) -> None:
        project_id = self.create_project()

        initial_response = self.client.get(f"/api/projects/{project_id}/document")
        self.assertEqual(initial_response.status_code, 200)
        initial_key = initial_response.json()["onlyoffice"]["documentKey"]

        refresh_response = self.client.post(f"/api/projects/{project_id}/document/force-save")
        self.assertEqual(refresh_response.status_code, 200)
        refreshed_key = refresh_response.json()["payload"]["onlyoffice"]["documentKey"]

        self.assertNotEqual(initial_key, refreshed_key)
        self.assertEqual(
            refreshed_key,
            build_editor_session_key(document_path(project_id), refresh_response.json()["payload"]["version"]),
        )

        latest_response = self.client.get(f"/api/projects/{project_id}/document")
        self.assertEqual(latest_response.status_code, 200)
        self.assertEqual(latest_response.json()["onlyoffice"]["documentKey"], refreshed_key)

    def test_route_payload_uses_real_document_file_keys(self) -> None:
        project_id = self.create_project_with_review_document()

        store.force_save_document(project_id)
        store.force_save_review_document(project_id)

        document_response = self.client.get(f"/api/projects/{project_id}/document")
        review_response = self.client.get(f"/api/projects/{project_id}/review-items/document")

        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(review_response.status_code, 200)
        self.assertEqual(
            document_response.json()["onlyoffice"]["documentKey"],
            build_editor_session_key(document_path(project_id), document_response.json()["version"]),
        )
        self.assertEqual(
            review_response.json()["onlyoffice"]["documentKey"],
            build_editor_session_key(
                settings.documents_dir / f"{project_id}-review.docx",
                review_response.json()["version"],
            ),
        )

    def test_editor_session_key_is_ascii_safe_for_onlyoffice_paths(self) -> None:
        path = settings.documents_dir / "APPX-0003-附表A.1 投标机型总方案信息表169.docx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PK-test-docx")

        key = build_editor_session_key(path)

        self.assertLessEqual(len(key), 128)
        self.assertRegex(key, re.compile(r"^[A-Za-z0-9._=-]+$"))
        self.assertNotIn("附表", key)
        self.assertNotIn(" ", key)

    def test_cleaned_material_preview_route_returns_onlyoffice_session(self) -> None:
        settings.onlyoffice_backend_base_url = "http://fastapi:8000"
        preview_payload = {
            "status": "ready",
            "fileId": "RAW-0007",
            "fileName": "清洗稿.docx",
            "fileUrl": "http://127.0.0.1:8000/api/materials/raw/RAW-0007/cleaned/content/%E6%B8%85%E6%B4%97%E7%A8%BF.docx",
            "onlyoffice": {
                "documentKey": "material-RAW-0007-v1",
                "title": "清洗稿.docx",
                "fileUrl": "http://fastapi:8000/api/materials/raw/RAW-0007/cleaned/content/%E6%B8%85%E6%B4%97%E7%A8%BF.docx",
                "browserFileUrl": "http://127.0.0.1:8000/api/materials/raw/RAW-0007/cleaned/content/%E6%B8%85%E6%B4%97%E7%A8%BF.docx",
                "fileType": "docx",
                "documentType": "word",
                "user": {"id": "user-1", "name": "当前用户"},
            },
        }

        with patch.object(
            material_store,
            "raw_cleaned_preview",
            new=AsyncMock(return_value=preview_payload),
            create=True,
        ) as mocked:
            response = self.client.get("/api/materials/raw/RAW-0007/cleaned/preview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["onlyoffice"]["fileUrl"], preview_payload["onlyoffice"]["fileUrl"])
        self.assertEqual(payload["onlyoffice"]["browserFileUrl"], preview_payload["onlyoffice"]["browserFileUrl"])
        self.assertEqual(payload["onlyoffice"]["documentType"], "word")
        mocked.assert_awaited_once()

    def test_cleaned_material_preview_route_blocks_unavailable_cleaned_word(self) -> None:
        with patch.object(
            material_store,
            "raw_cleaned_preview",
            new=AsyncMock(
                side_effect=PeripheralError(
                    400,
                    "素材清洗完成后才可预览清洗稿。",
                    "RAW_CLEANED_PREVIEW_UNAVAILABLE",
                )
            ),
            create=True,
        ):
            response = self.client.get("/api/materials/raw/RAW-0008/cleaned/preview")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "RAW_CLEANED_PREVIEW_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
