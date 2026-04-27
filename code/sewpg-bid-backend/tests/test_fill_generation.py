from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.store import now_iso, store


class FillGenerationTests(unittest.TestCase):
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

    def _prepare_project_for_s7(self) -> str:
        response = self.client.post(
            "/api/projects",
            json={
                "name": "S7初稿生成项目",
                "customerName": "测试业主",
            },
        )
        response.raise_for_status()
        project_id = response.json()["id"]

        project_dir = settings.parsed_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        combined_text_path = project_dir / "combined.txt"
        combined_text_path.write_text(
            "\n".join(
                [
                    "# 文件：招标文件.docx",
                    "",
                    "第一章 项目概况",
                    "第二章 技术方案",
                    "第三章 实施与保障",
                    "项目要求投标文件包含总体方案、关键参数、实施组织与风险控制。",
                ]
            ),
            encoding="utf-8",
        )

        tender_path = settings.uploads_dir / project_id / "tender" / "招标文件.docx"
        tender_path.parent.mkdir(parents=True, exist_ok=True)
        tender_path.write_text("dummy", encoding="utf-8")

        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(tender_path),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[],
            summary={
                "fileCount": 1,
                "extractedCount": 0,
                "textLength": 128,
                "textPreview": "",
                "warnings": [],
            },
            parse_storage={
                "projectDir": str(project_dir),
                "combinedTextPath": str(combined_text_path),
                "manifestPath": "",
                "documents": [],
            },
        )

        store.save_generated_outline(
            project_id=project_id,
            nodes=[
                {
                    "id": "OL-1",
                    "title": "项目概况",
                    "children": [
                        {"id": "OL-1-1", "title": "项目背景", "children": []},
                    ],
                },
                {
                    "id": "OL-2",
                    "title": "技术方案",
                    "children": [
                        {"id": "OL-2-1", "title": "总体方案", "children": []},
                        {"id": "OL-2-2", "title": "关键参数响应", "children": []},
                    ],
                },
                {
                    "id": "OL-3",
                    "title": "实施与保障",
                    "children": [
                        {"id": "OL-3-1", "title": "实施组织", "children": []},
                        {"id": "OL-3-2", "title": "风险控制", "children": []},
                    ],
                },
            ],
            generated_at=now_iso(),
            summary="目录已生成。",
        )
        store.confirm_outline(project_id)
        store.run_gap_detection(project_id)
        gap_items = store.get_gap_filling(project_id)["items"]
        for index, item in enumerate(gap_items, start=1):
            store.submit_gap_material(
                project_id,
                {
                    "missingId": item["id"],
                    "files": [{"name": f"{item['id']}.docx", "size": 1024}],
                },
            )
            if index % 2:
                store.update_gap_item(project_id, item["id"], {"action": "resolve", "source": {"name": f"{item['id']}.docx"}})
            else:
                store.patch_missing_material(project_id, item["id"], {"status": "skipped", "reason": "MVP阶段跳过"})
        store.submit_gap_review(project_id)
        store.prepare_review_document(project_id)
        store.confirm_review(project_id)
        return project_id

    def test_run_fill_generation_returns_running_state_immediately(self) -> None:
        project_id = self._prepare_project_for_s7()

        with patch("app.api.routes.generation._schedule_fill_generation_job"):
            response = self.client.post(f"/api/projects/{project_id}/fill-generation/run")

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["percentage"], 5)
        self.assertEqual(payload["tasks"][0]["status"], "running")
        self.assertEqual(payload["tasks"][1]["status"], "pending")
        self.assertEqual(payload["events"][0]["step"], "bootstrap")
        self.assertEqual(payload["opencodeOutput"]["status"], "idle")

    def test_background_job_updates_running_state_then_writes_real_docx(self) -> None:
        from app.api.routes.generation import _handle_fill_progress, _run_fill_generation_job

        project_id = self._prepare_project_for_s7()
        store.start_fill_generation(project_id)

        _handle_fill_progress(
            project_id,
            "inputs_ready",
            {"sectionCount": 3, "templateHintCount": 0},
        )
        running_state = store.get_fill_state(project_id)
        self.assertEqual(running_state["status"], "running")
        self.assertEqual(running_state["percentage"], 30)
        self.assertEqual(running_state["tasks"][1]["status"], "running")
        self.assertEqual(running_state["events"][-1]["step"], "inputs_ready")

        def fake_generate(prompt, session_ready_callback=None):
            if session_ready_callback:
                session_ready_callback(
                    {
                        "sessionId": "ses-fill",
                        "providerId": "opencode",
                        "modelId": "big-pickle",
                    }
                )
            return {
                "summary": "初稿生成完成。",
                "sections": [
                    {
                        "nodeId": "OL-1",
                        "title": "项目概况",
                        "generationMode": "generated",
                        "content": "## 项目背景\n本项目位于测试区域，建设目标明确。",
                        "riskFlags": [],
                    },
                    {
                        "nodeId": "OL-2",
                        "title": "技术方案",
                        "generationMode": "generated_with_placeholder",
                        "content": "## 总体方案\n采用标准化方案。\n\n## 关键参数响应\n【待补充：关键参数实测值】",
                        "riskFlags": ["FACT_REQUIRED"],
                    },
                    {
                        "nodeId": "OL-3",
                        "title": "实施与保障",
                        "generationMode": "generated",
                        "content": "## 实施组织\n项目经理负责统筹。\n\n## 风险控制\n建立专项风险台账。",
                        "riskFlags": [],
                    },
                ],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": "ses-fill",
                    "providerId": "opencode",
                    "modelId": "big-pickle",
                    "receivedAt": "2026-04-20T00:00:00Z",
                    "parts": [
                        {"type": "reasoning", "text": "先按章节生成初稿。"},
                        {"type": "text", "text": "{\"summary\":\"初稿生成完成。\"}"},
                    ],
                },
            }

        with patch(
            "app.services.draft_generation.OpencodeClient.generate_draft_sections_with_trace",
            side_effect=fake_generate,
        ):
            _run_fill_generation_job(project_id, {})

        payload = store.get_fill_state(project_id)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["percentage"], 100)
        self.assertEqual(payload["output"]["fileType"], "docx")
        self.assertEqual(len(payload["sections"]), 3)
        self.assertEqual(payload["opencodeOutput"]["status"], "received")
        self.assertEqual(payload["opencodeOutput"]["parts"][0]["type"], "reasoning")

        document_response = self.client.get(f"/api/projects/{project_id}/document/file")
        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(document_response.content[:2], b"PK")

        local_path = settings.documents_dir / f"{project_id}.docx"
        doc = Document(local_path)
        full_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        self.assertIn("项目概况", full_text)
        self.assertIn("关键参数响应", full_text)
        self.assertIn("【待补充：关键参数实测值】", full_text)

    def test_get_coverage_returns_tree_after_fill_generation(self) -> None:
        from app.api.routes.generation import _run_fill_generation_job

        project_id = self._prepare_project_for_s7()
        store.start_fill_generation(project_id)

        with patch(
            "app.services.draft_generation.OpencodeClient.generate_draft_sections_with_trace",
            return_value={
                "summary": "初稿生成完成。",
                "sections": [
                    {
                        "nodeId": "OL-1",
                        "title": "项目概况",
                        "generationMode": "generated",
                        "content": "项目背景说明。",
                        "riskFlags": [],
                    },
                    {
                        "nodeId": "OL-2",
                        "title": "技术方案",
                        "generationMode": "placeholder",
                        "content": "【待补充：技术方案细节】",
                        "riskFlags": ["FACT_REQUIRED"],
                    },
                    {
                        "nodeId": "OL-3",
                        "title": "实施与保障",
                        "generationMode": "generated_with_placeholder",
                        "content": "实施组织说明。\n【待补充：风险清单】",
                        "riskFlags": ["FACT_REQUIRED"],
                    },
                ],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": "ses-coverage",
                    "providerId": "opencode",
                    "modelId": "big-pickle",
                    "receivedAt": "2026-04-20T00:00:00Z",
                    "parts": [],
                },
            },
        ):
            _run_fill_generation_job(project_id, {})

        coverage_response = self.client.get(f"/api/projects/{project_id}/coverage")
        self.assertEqual(coverage_response.status_code, 200)
        coverage = coverage_response.json()
        self.assertIn("tree", coverage)
        self.assertIn("partialItems", coverage)
        self.assertIn("noCoverItems", coverage)
        self.assertGreater(len(coverage["tree"]), 0)


if __name__ == "__main__":
    unittest.main()
