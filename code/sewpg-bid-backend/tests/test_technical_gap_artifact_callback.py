from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.bid_project_repository import ProjectConcurrentUpdateError
from app.services.store import store
from app.services.technical_gap_domain import technical_gap_artifact_onlyoffice_payload
from app.services.technical_gap_repository import mutate_technical_gap_project


def _seed_gap_plan_with_artifact(project_id: str, artifact: dict) -> None:
    """绕过缺口识别，直接注入含一个 AI 填写产物的 gap plan。"""
    project = store._require(project_id)
    project["gap_state"] = {
        "recognitionStatus": "completed",
        "recognizedAt": "2026-08-09T00:00:00Z",
        "items": [],
        "submissions": [],
        "plan": {
            "schemaVersion": "bid-tech-gap-plan-v1",
            "projectId": project_id,
            "status": "ready",
            "items": [
                {
                    "id": "GAP-0001",
                    "number": "1",
                    "title": "测试目录项",
                    "level": 1,
                    "status": "filling",
                    "resolvedArtifacts": [artifact],
                }
            ],
        },
    }
    store._persist_project(project)


class TechnicalGapArtifactCallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.original_onlyoffice_callback_token = settings.onlyoffice_callback_token
        self.original_onlyoffice_download_allowed_hosts = settings.onlyoffice_download_allowed_hosts
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.onlyoffice_callback_token = ""
        settings.onlyoffice_download_allowed_hosts = ("127.0.0.1", "localhost", "onlyoffice")
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

        response = self.client.post(
            "/api/technical/projects",
            json={"name": "产物回写测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        self.project_id = response.json()["id"]

        self.artifact_path = settings.documents_dir / self.project_id / "technical/s4_gap_workdir/ai_fill/GAP-0001/filled.docx"
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_bytes(b"PK-original")
        self.artifact = {
            "id": "ART-AI-1",
            "source": "ai_fill",
            "fillTaskId": "TASK-1",
            "fileName": "filled.docx",
            "path": str(self.artifact_path),
            "s7Ready": True,
            "active": True,
        }
        _seed_gap_plan_with_artifact(self.project_id, self.artifact)

    def tearDown(self) -> None:
        self.client.close()
        settings.onlyoffice_callback_token = self.original_onlyoffice_callback_token
        settings.onlyoffice_download_allowed_hosts = self.original_onlyoffice_download_allowed_hosts
        self.temp_dir.cleanup()

    def _callback_url(self, artifact_id: str = "ART-AI-1") -> str:
        return f"/api/technical/projects/{self.project_id}/gaps/artifacts/{artifact_id}/callback"

    def _persisted_artifact(self) -> dict:
        project = store._require(self.project_id)
        return project["gap_state"]["plan"]["items"][0]["resolvedArtifacts"][0]

    def test_artifact_payload_carries_callback_url_and_versioned_document_key(self) -> None:
        payload = technical_gap_artifact_onlyoffice_payload(
            project_id=self.project_id,
            artifact_id="ART-AI-1",
            file_name="filled.docx",
            file_path=str(self.artifact_path),
            doc_version=2,
            browser_base_url="http://127.0.0.1:8000",
            onlyoffice_base_url="http://fastapi:8000",
        )

        self.assertIn(
            f"http://fastapi:8000/api/technical/projects/{self.project_id}/gaps/artifacts/ART-AI-1/callback",
            payload["callbackUrl"],
        )
        self.assertIn("oo_doc_version=2", payload["callbackUrl"])
        # documentKey 按文件内容版本化，不再是静态 {project_id}-{artifact_id}
        self.assertNotEqual(payload["documentKey"], f"{self.project_id}-ART-AI-1")
        self.assertTrue(payload["documentKey"].endswith("-v2"))

        self.artifact_path.write_bytes(b"PK-same-session-new-content")
        refreshed = technical_gap_artifact_onlyoffice_payload(
            project_id=self.project_id,
            artifact_id="ART-AI-1",
            file_name="filled.docx",
            file_path=str(self.artifact_path),
            doc_version=2,
            browser_base_url="http://127.0.0.1:8000",
            onlyoffice_base_url="http://fastapi:8000",
        )
        self.assertEqual(refreshed["documentKey"], payload["documentKey"])

    def test_detection_status_refreshes_artifact_session(self) -> None:
        response = self.client.get(f"/api/technical/projects/{self.project_id}/gaps-detection")

        self.assertEqual(response.status_code, 200)
        artifact = response.json()["gapPlan"]["items"][0]["resolvedArtifacts"][0]
        self.assertIn("callbackUrl", artifact["onlyoffice"])
        self.assertIn("/callback", artifact["onlyoffice"]["callbackUrl"])

    def test_artifact_callback_rejects_invalid_token(self) -> None:
        settings.onlyoffice_callback_token = "secret-token"

        response = self.client.post(
            self._callback_url(),
            params={"oo_callback_token": "wrong"},
            json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-original")

    def test_artifact_callback_rejects_superseded_artifact(self) -> None:
        self.artifact["supersededAt"] = "2026-08-09T01:00:00Z"
        self.artifact["active"] = False
        _seed_gap_plan_with_artifact(self.project_id, self.artifact)

        response = self.client.post(
            self._callback_url(),
            json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("已被新的选材或填写结果取代", response.json()["detail"])
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-original")

    def test_artifact_callback_rejects_unknown_artifact(self) -> None:
        response = self.client.post(
            self._callback_url("ART-MISSING"),
            json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
        )

        self.assertEqual(response.status_code, 404, response.text)

    def test_artifact_callback_ignores_non_save_status(self) -> None:
        response = self.client.post(
            self._callback_url(),
            json={"status": 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"error": 0})
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-original")
        self.assertNotIn("editedAt", self._persisted_artifact())

    def test_artifact_callback_status2_overwrites_file_and_records_edit_metadata(self) -> None:
        async def fake_download(download_url: str, target_path: Path, **kwargs) -> None:
            target_path.write_bytes(b"PK-edited")

        with patch(
            "app.services.technical_gap_service.download_document_from_onlyoffice",
            new=AsyncMock(side_effect=fake_download),
        ):
            response = self.client.post(
                self._callback_url(),
                json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"error": 0})
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-edited")
        persisted = self._persisted_artifact()
        self.assertTrue(persisted["editedAt"])
        self.assertEqual(persisted["editedBy"], "当前用户")
        self.assertEqual(persisted["ooDocVersion"], 2)
        # 目录项状态流转不动：保存只改文件与产物元数据，复核标记不新增不丢失
        self.assertNotIn("confirmed", persisted)
        self.assertTrue(persisted["s7Ready"])

    def test_same_session_accepts_repeated_status6_saves(self) -> None:
        contents = iter((b"PK-first-force-save", b"PK-second-force-save"))

        async def fake_download(download_url: str, target_path: Path, **kwargs) -> None:
            target_path.write_bytes(next(contents))

        with patch(
            "app.services.technical_gap_service.download_document_from_onlyoffice",
            new=AsyncMock(side_effect=fake_download),
        ):
            first = self.client.post(
                self._callback_url(),
                params={"oo_doc_version": "1"},
                json={"status": 6, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )
            second = self.client.post(
                self._callback_url(),
                params={"oo_doc_version": "1"},
                json={"status": 6, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )

        self.assertEqual(first.json(), {"error": 0})
        self.assertEqual(second.json(), {"error": 0})
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-second-force-save")
        persisted = self._persisted_artifact()
        self.assertEqual(persisted["ooDocVersion"], 1)
        self.assertEqual(persisted["ooContentRevision"], 2)

    def test_same_session_accepts_status6_then_final_status2(self) -> None:
        contents = iter((b"PK-force-save", b"PK-final-save"))

        async def fake_download(download_url: str, target_path: Path, **kwargs) -> None:
            target_path.write_bytes(next(contents))

        with patch(
            "app.services.technical_gap_service.download_document_from_onlyoffice",
            new=AsyncMock(side_effect=fake_download),
        ):
            force_save = self.client.post(
                self._callback_url(),
                params={"oo_doc_version": "1"},
                json={"status": 6, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )
            final_save = self.client.post(
                self._callback_url(),
                params={"oo_doc_version": "1"},
                json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )

        self.assertEqual(force_save.json(), {"error": 0})
        self.assertEqual(final_save.json(), {"error": 0})
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-final-save")
        persisted = self._persisted_artifact()
        self.assertEqual(persisted["ooDocVersion"], 2)
        self.assertEqual(persisted["ooContentRevision"], 2)

    def test_artifact_callback_rejects_non_ai_artifact(self) -> None:
        self.artifact["source"] = "manual_upload"
        _seed_gap_plan_with_artifact(self.project_id, self.artifact)

        response = self.client.post(
            self._callback_url(),
            json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("仅 AI 填写产物", response.json()["detail"])
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-original")

    def test_callback_preserves_project_update_that_happens_during_download(self) -> None:
        async def fake_download(download_url: str, target_path: Path, **kwargs) -> None:
            mutate_technical_gap_project(
                self.project_id,
                lambda project: project.update({"concurrentMarker": "preserved"}),
            )
            target_path.write_bytes(b"PK-edited-after-concurrent-update")

        with patch(
            "app.services.technical_gap_service.download_document_from_onlyoffice",
            new=AsyncMock(side_effect=fake_download),
        ):
            response = self.client.post(
                self._callback_url(),
                json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        project = store._require(self.project_id)
        self.assertEqual(project["concurrentMarker"], "preserved")
        self.assertTrue(self._persisted_artifact()["editedAt"])

    def test_callback_restores_file_when_state_commit_fails(self) -> None:
        async def fake_download(download_url: str, target_path: Path, **kwargs) -> None:
            target_path.write_bytes(b"PK-should-not-remain")

        with (
            patch(
                "app.services.technical_gap_service.download_document_from_onlyoffice",
                new=AsyncMock(side_effect=fake_download),
            ),
            patch(
                "app.services.technical_gap_service.mutate_technical_gap_project",
                side_effect=ProjectConcurrentUpdateError(self.project_id),
            ),
        ):
            response = self.client.post(
                self._callback_url(),
                json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-original")
        self.assertNotIn("editedAt", self._persisted_artifact())

    def test_artifact_callback_ignores_stale_document_version(self) -> None:
        self.artifact["ooDocVersion"] = 3
        _seed_gap_plan_with_artifact(self.project_id, self.artifact)

        async def fake_download(download_url: str, target_path: Path, **kwargs) -> None:
            raise AssertionError("低版本回调不应触发下载")

        with patch(
            "app.services.technical_gap_service.download_document_from_onlyoffice",
            new=AsyncMock(side_effect=fake_download),
        ):
            response = self.client.post(
                self._callback_url(),
                params={"oo_doc_version": "2"},
                json={"status": 2, "url": "http://127.0.0.1:8000/download/filled.docx"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"error": 0, "ignored": "stale_document_version"})
        self.assertEqual(self.artifact_path.read_bytes(), b"PK-original")
        self.assertEqual(self._persisted_artifact()["ooDocVersion"], 3)


if __name__ == "__main__":
    unittest.main()
