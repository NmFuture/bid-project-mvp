from __future__ import annotations

import asyncio
import re
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, quote, urlparse

from fastapi.testclient import TestClient
from starlette.datastructures import URL as StarletteURL

from app.main import app
from app.core.config import settings
from app.services.bid_document_state import force_save_document_state
from app.services.bid_outline_state import confirm_outline_state, save_generated_outline_state
from app.services.onlyoffice_documents import build_editor_session_key, document_path
from app.services.peripheral import PeripheralError
from app.services.store import store
from app.services.technical_gap_repository import persist_technical_gap_project, require_technical_gap_project_for_update
from app.services.technical_gap_review import prepare_technical_review_document
from app.services.technical_gap_service import technical_gap_service
from app.services.technical_gap_state import ensure_technical_gap_state
from app.services.technical_material_store import technical_material_store


class _DummyRequest:
    base_url = StarletteURL("http://testserver/")
    url = StarletteURL("http://testserver/")


def _prepare_technical_review_document_for_tests(project_id: str) -> None:
    project = require_technical_gap_project_for_update(project_id)
    gap_state = ensure_technical_gap_state(project)
    prepare_technical_review_document(project, gap_state)
    persist_technical_gap_project(project)


def _document_state(project_id: str) -> dict:
    return store.get_project_runtime_state(project_id)["document_state"]


def _force_save_document_for_tests(project_id: str) -> None:
    project = store.require_project_for_update(project_id)
    force_save_document_state(project, project_id)
    store.persist_project_state(project)


def _save_generated_outline_for_tests(
    project_id: str,
    *,
    nodes: list[dict],
    generated_at: str,
    summary: str,
) -> dict:
    project = store.require_project_for_update(project_id)
    payload = save_generated_outline_state(
        project,
        nodes=nodes,
        generated_at=generated_at,
        summary=summary,
    )
    store.persist_project_state(project)
    return payload


def _confirm_outline_for_tests(project_id: str) -> dict:
    project = store.require_project_for_update(project_id)
    payload = confirm_outline_state(project)
    store.persist_project_state(project)
    return payload


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
            "app.services.technical_gap_planner.OpencodeClient.run_bid_tech_gap_planner_with_trace",
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
            "/api/technical/projects",
            json={
                "name": "OnlyOffice 联调项目",
                "customerName": "测试业主",
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    def create_business_project(self) -> str:
        response = self.client.post(
            "/api/business/projects",
            json={
                "name": "商务 OnlyOffice 联调项目",
                "customerName": "测试业主",
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    def create_project_with_review_document(self) -> str:
        project_id = self.create_project()
        _save_generated_outline_for_tests(
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
        _confirm_outline_for_tests(project_id)
        technical_gap_service.run_detection(project_id)
        for item in asyncio.run(technical_gap_service.gaps(project_id, _DummyRequest()))["items"]:
            asyncio.run(
                technical_gap_service.update_gap(
                    project_id,
                    item["id"],
                    {"status": "skipped", "reason": "测试中人工确认忽略"},
                )
            )
        asyncio.run(technical_gap_service.recheck(project_id))
        asyncio.run(technical_gap_service.submit_review(project_id))
        _prepare_technical_review_document_for_tests(project_id)
        return project_id

    def test_document_file_is_real_docx(self) -> None:
        project_id = self.create_project()

        response = self.client.get(f"/api/technical/projects/{project_id}/document/file")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        )
        self.assertEqual(response.content[:2], b"PK")

    def test_technical_final_pdf_file_is_downloadable(self) -> None:
        project_id = self.create_project()
        pdf_path = document_path(project_id).with_suffix(".pdf")
        pdf_bytes = b"%PDF-1.4\n% project-specific sentinel\n%%EOF\n"
        pdf_path.write_bytes(pdf_bytes)

        response = self.client.get(f"/api/technical/projects/{project_id}/final-document/pdf/file")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/pdf"))
        self.assertIn(".pdf", response.headers["content-disposition"].lower())
        self.assertEqual(response.content, pdf_bytes)

    def test_technical_document_format_endpoint_uses_technical_service(self) -> None:
        project_id = self.create_project()

        with patch(
            "app.services.technical_document_service.apply_technical_document_format_preset",
            return_value={
                "preset": "custom",
                "label": "自定义技术标格式",
                "description": "测试格式",
                "summary": {"updated": 1},
            },
        ) as formatter, patch("app.services.technical_document_service.sync_document_to_minio"):
            response = self.client.post(
                f"/api/technical/projects/{project_id}/document/technical-format",
                json={"preset": "custom", "styleOverrides": {"bodySizePt": 13}},
            )

        self.assertEqual(response.status_code, 200)
        formatter.assert_called_once_with(project_id, "custom", {"bodySizePt": 13})
        payload = response.json()
        self.assertEqual(payload["payload"]["format"]["preset"], "custom")
        state = _document_state(project_id)
        self.assertEqual(state["technicalFormatPreset"], "custom")
        self.assertEqual(state["technicalFormatLabel"], "自定义技术标格式")

    def test_business_document_format_endpoint_uses_business_service(self) -> None:
        project_id = self.create_business_project()

        with patch(
            "app.services.business_document_service.apply_business_document_format_preset",
            return_value={
                "preset": "custom",
                "label": "自定义商务标格式",
                "description": "测试格式",
                "summary": {"updated": 1},
            },
        ) as formatter, patch("app.services.business_document_service.sync_document_to_minio"):
            response = self.client.post(
                f"/api/business/projects/{project_id}/document/business-format",
                json={"preset": "custom", "styleOverrides": {"bodySizePt": 12}},
            )

        self.assertEqual(response.status_code, 200)
        formatter.assert_called_once_with(project_id, "custom", {"bodySizePt": 12})
        payload = response.json()
        self.assertEqual(payload["payload"]["format"]["preset"], "custom")
        state = _document_state(project_id)
        self.assertEqual(state["businessFormatPreset"], "custom")
        self.assertEqual(state["businessFormatLabel"], "自定义商务标格式")

    def test_document_session_uses_docker_reachable_urls_for_local_dev(self) -> None:
        project_id = self.create_project()

        with patch("app.services.url_utils.detect_lan_ip", return_value="192.168.31.148"):
            response = self.client.get(f"/api/technical/projects/{project_id}/document")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        expected_host = "host.docker.internal:8000" if platform.system() == "Darwin" else "192.168.31.148:8000"
        self.assertIn(expected_host, payload["onlyoffice"]["fileUrl"])
        self.assertIn(expected_host, payload["onlyoffice"]["callbackUrl"])

    def test_document_session_falls_back_to_host_docker_internal_when_lan_ip_unavailable_on_darwin(self) -> None:
        if platform.system() != "Darwin":
            self.skipTest("Darwin-only fallback behavior")

        project_id = self.create_project()

        with patch("app.services.url_utils.detect_lan_ip", return_value=""):
            response = self.client.get(f"/api/technical/projects/{project_id}/document")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("host.docker.internal:8000", payload["onlyoffice"]["fileUrl"])
        self.assertIn("host.docker.internal:8000", payload["onlyoffice"]["callbackUrl"])

    def test_explicit_onlyoffice_backend_base_url_is_used_for_document_route(self) -> None:
        project_id = self.create_project()
        settings.onlyoffice_backend_base_url = "http://fastapi:8000"

        document_response = self.client.get(f"/api/technical/projects/{project_id}/document")

        self.assertEqual(document_response.status_code, 200)

        document_payload = document_response.json()
        document_file_url = urlparse(document_payload["onlyoffice"]["fileUrl"])
        self.assertEqual(
            f"{document_file_url.scheme}://{document_file_url.netloc}{document_file_url.path}",
            f"http://fastapi:8000/api/technical/projects/{project_id}/document/file/{quote(document_payload['fileName'])}",
        )
        self.assertEqual(parse_qs(document_file_url.query).get("doc_version"), ["1"])
        document_callback_url = urlparse(document_payload["onlyoffice"]["callbackUrl"])
        self.assertEqual(
            f"{document_callback_url.scheme}://{document_callback_url.netloc}{document_callback_url.path}",
            f"http://fastapi:8000/api/technical/projects/{project_id}/document/callback",
        )
        self.assertEqual(parse_qs(document_callback_url.query).get("oo_doc_version"), ["1"])

    def test_document_callback_rejects_invalid_token(self) -> None:
        project_id = self.create_project()
        settings.onlyoffice_callback_token = "secret-token"

        response = self.client.post(
            f"/api/technical/projects/{project_id}/document/callback",
            params={"oo_callback_token": "wrong"},
            json={"status": 6, "url": "http://127.0.0.1:8000/api/technical/projects/foo/document/file/x.docx"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("callback token", response.text)

    def test_document_callback_rejects_disallowed_download_host(self) -> None:
        project_id = self.create_project()
        settings.onlyoffice_callback_token = "secret-token"

        response = self.client.post(
            f"/api/technical/projects/{project_id}/document/callback",
            params={"oo_callback_token": "secret-token"},
            json={"status": 6, "url": "https://attacker.example.com/malware.docx"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("白名单", response.text)

    def test_file_routes_accept_filename_suffix_alias(self) -> None:
        project_id = self.create_project()

        document_response = self.client.get(f"/api/technical/projects/{project_id}/document")

        self.assertEqual(document_response.status_code, 200)

        document_file_url = document_response.json()["fileUrl"]

        document_file = self.client.get(document_file_url.replace("http://127.0.0.1:8000", ""))

        self.assertEqual(document_file.status_code, 200)
        self.assertEqual(document_file.content[:2], b"PK")

    def test_force_save_route_refreshes_document_session_key(self) -> None:
        project_id = self.create_project()

        initial_response = self.client.get(f"/api/technical/projects/{project_id}/document")
        self.assertEqual(initial_response.status_code, 200)
        initial_key = initial_response.json()["onlyoffice"]["documentKey"]

        refresh_response = self.client.post(f"/api/technical/projects/{project_id}/document/force-save")
        self.assertEqual(refresh_response.status_code, 200)
        refreshed_key = refresh_response.json()["payload"]["onlyoffice"]["documentKey"]

        self.assertNotEqual(initial_key, refreshed_key)
        self.assertEqual(
            refreshed_key,
            build_editor_session_key(document_path(project_id), refresh_response.json()["payload"]["version"]),
        )

        latest_response = self.client.get(f"/api/technical/projects/{project_id}/document")
        self.assertEqual(latest_response.status_code, 200)
        self.assertEqual(latest_response.json()["onlyoffice"]["documentKey"], refreshed_key)

    def test_route_payload_uses_real_document_file_keys(self) -> None:
        project_id = self.create_project()

        _force_save_document_for_tests(project_id)

        document_response = self.client.get(f"/api/technical/projects/{project_id}/document")

        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(
            document_response.json()["onlyoffice"]["documentKey"],
            build_editor_session_key(document_path(project_id), document_response.json()["version"]),
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
            "fileUrl": "http://127.0.0.1:8000/api/technical/materials/raw/RAW-0007/cleaned/content/%E6%B8%85%E6%B4%97%E7%A8%BF.docx",
            "onlyoffice": {
                "documentKey": "material-RAW-0007-v1",
                "title": "清洗稿.docx",
                "fileUrl": "http://fastapi:8000/api/technical/materials/raw/RAW-0007/cleaned/content/%E6%B8%85%E6%B4%97%E7%A8%BF.docx",
                "browserFileUrl": "http://127.0.0.1:8000/api/technical/materials/raw/RAW-0007/cleaned/content/%E6%B8%85%E6%B4%97%E7%A8%BF.docx",
                "fileType": "docx",
                "documentType": "word",
                "user": {"id": "user-1", "name": "当前用户"},
            },
        }

        with patch.object(
            technical_material_store,
            "raw_cleaned_preview",
            new=AsyncMock(return_value=preview_payload),
            create=True,
        ) as mocked:
            response = self.client.get("/api/technical/materials/raw/RAW-0007/cleaned/preview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["onlyoffice"]["fileUrl"], preview_payload["onlyoffice"]["fileUrl"])
        self.assertEqual(payload["onlyoffice"]["browserFileUrl"], preview_payload["onlyoffice"]["browserFileUrl"])
        self.assertEqual(payload["onlyoffice"]["documentType"], "word")
        mocked.assert_awaited_once()

    def test_cleaned_material_preview_route_blocks_unavailable_cleaned_word(self) -> None:
        with patch.object(
            technical_material_store,
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
            response = self.client.get("/api/technical/materials/raw/RAW-0008/cleaned/preview")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "RAW_CLEANED_PREVIEW_UNAVAILABLE")

    def test_original_material_preview_route_returns_onlyoffice_session(self) -> None:
        settings.onlyoffice_backend_base_url = "http://fastapi:8000"
        preview_payload = {
            "status": "ready",
            "fileId": "RAW-0009",
            "fileName": "业绩台账.xlsx",
            "fileType": "xlsx",
            "documentType": "cell",
            "fileUrl": "http://127.0.0.1:8000/api/technical/materials/raw/RAW-0009/content",
            "onlyoffice": {
                "documentKey": "material-RAW-0009-original-v1",
                "title": "业绩台账.xlsx",
                "fileUrl": "http://fastapi:8000/api/technical/materials/raw/RAW-0009/content",
                "browserFileUrl": "http://127.0.0.1:8000/api/technical/materials/raw/RAW-0009/content",
                "fileType": "xlsx",
                "documentType": "cell",
                "user": {"id": "user-1", "name": "当前用户"},
            },
        }

        with patch.object(
            technical_material_store,
            "raw_original_preview",
            new=AsyncMock(return_value=preview_payload),
            create=True,
        ) as mocked:
            response = self.client.get("/api/technical/materials/raw/RAW-0009/preview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["fileType"], "xlsx")
        self.assertEqual(payload["documentType"], "cell")
        self.assertEqual(payload["onlyoffice"]["fileUrl"], preview_payload["onlyoffice"]["fileUrl"])
        self.assertTrue(payload["onlyoffice"]["fileUrl"].endswith("/content"))
        mocked.assert_awaited_once()

    def test_original_material_preview_route_blocks_unsupported_type(self) -> None:
        with patch.object(
            technical_material_store,
            "raw_original_preview",
            new=AsyncMock(
                side_effect=PeripheralError(
                    400,
                    "该文件类型暂不支持在线预览。",
                    "RAW_ORIGINAL_PREVIEW_UNSUPPORTED",
                )
            ),
            create=True,
        ):
            response = self.client.get("/api/technical/materials/raw/RAW-0010/preview")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "RAW_ORIGINAL_PREVIEW_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
