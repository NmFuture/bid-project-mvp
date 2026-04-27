from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.store import store


class DirectoryGenerationTests(unittest.TestCase):
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

    def _prepare_project_with_parse_result(self) -> str:
        project = store.create_project(
            {
                "name": "目录生成联调项目",
                "customerName": "测试业主",
            }
        )
        project_id = project["id"]

        project_dir = settings.parsed_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        tender_path = settings.uploads_dir / project_id / "tender" / "招标文件.docx"
        tender_path.parent.mkdir(parents=True, exist_ok=True)
        tender_path.write_text("dummy", encoding="utf-8")

        combined_text_path = project_dir / "combined.txt"
        combined_text_path.write_text(
            "\n".join(
                [
                    "# 文件：招标文件.docx",
                    "",
                    "第一章 项目概况",
                    "第二章 技术方案",
                    "第三章 实施与保障",
                ]
            ),
            encoding="utf-8",
        )

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
                "textLength": 64,
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
        return project_id

    def test_generate_outline_for_project_updates_directory_and_outline_state(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.outline_generation.OpencodeClient.generate_outline_with_trace",
            return_value={
                "summary": "目录生成完成。",
                "nodes": [
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
                        "children": [],
                    },
                ],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": "ses-outline",
                    "providerId": "opencode",
                    "modelId": "big-pickle",
                    "receivedAt": "2026-04-20T00:00:00Z",
                    "parts": [
                        {"type": "reasoning", "text": "先组织目录骨架。"},
                        {"type": "text", "text": "{\"summary\":\"目录生成完成。\"}"},
                    ],
                },
            },
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["output"]["chapterCount"], 2)
        self.assertTrue(payload["events"])
        self.assertEqual(payload["events"][-1]["level"], "success")
        self.assertEqual(payload["opencodeOutput"]["status"], "received")
        self.assertEqual(payload["opencodeOutput"]["parts"][0]["type"], "reasoning")

        outline = store.get_outline_state(project_id)
        self.assertEqual(outline["reviewStatus"], "draft")
        self.assertEqual(len(outline["nodes"]), 2)
        self.assertEqual(outline["nodes"][0]["title"], "项目概况")
        self.assertEqual(outline["summary"]["totalNodeCount"], 3)

    def test_generate_outline_accepts_v2_toc_items_and_preserves_metadata(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.outline_generation.OpencodeClient.generate_outline_with_trace",
            return_value={
                "schema_version": "bid-toc-json-v1",
                "summary": {"total_items": 4, "annotation_counts": {"保留": 3, "适配": 1}},
                "items": [
                    {
                        "order": 1,
                        "number": "第一章",
                        "title": "项目概况",
                        "level": 1,
                        "annotation": "保留",
                        "source": "template",
                        "reason": "",
                    },
                    {
                        "order": 2,
                        "number": "1.1",
                        "title": "项目背景",
                        "level": 2,
                        "annotation": "适配",
                        "source": "wiki",
                        "reason": "项目名称替换",
                        "source_refs": [{"type": "wiki", "path": "技术标Wiki/项目背景"}],
                        "material_refs": [{"id": "RAW-1", "docx": "项目背景.docx"}],
                    },
                    {
                        "order": 3,
                        "number": "1.2",
                        "title": "项目范围",
                        "level": 2,
                        "annotation": "保留",
                        "source": "template",
                        "reason": "",
                    },
                    {
                        "order": 4,
                        "number": "第二章",
                        "title": "技术方案",
                        "level": 1,
                        "annotation": "保留",
                        "source": "template",
                        "reason": "",
                    },
                ],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": "ses-v2",
                    "providerId": "opencode",
                    "modelId": "big-pickle",
                    "receivedAt": "2026-04-20T00:00:00Z",
                    "parts": [],
                },
            },
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertEqual(payload["summary"], "目录生成完成，共 4 条目录项（保留3，适配1）。")
        self.assertEqual(payload["output"]["chapterCount"], 2)
        self.assertEqual(payload["opencodeOutput"]["skill"], "bid-toc-wiki-driven-v2")
        outline = store.get_outline_state(project_id)
        self.assertEqual(outline["nodes"][0]["title"], "第一章 项目概况")
        self.assertEqual(outline["nodes"][0]["children"][0]["title"], "项目背景")
        self.assertEqual(outline["nodes"][0]["children"][0]["annotation"], "适配")
        self.assertEqual(outline["nodes"][0]["children"][0]["id"], "OL-1-1")
        self.assertEqual(outline["nodes"][0]["children"][1]["id"], "OL-1-2")
        self.assertEqual(outline["nodes"][1]["id"], "OL-2")
        self.assertEqual(outline["nodes"][0]["children"][0]["sourceRefs"][0]["type"], "wiki")
        self.assertEqual(outline["nodes"][0]["children"][0]["materialRefs"][0]["id"], "RAW-1")

    def test_generate_outline_reads_v2_toc_from_output_file_summary(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        toc_path = settings.parsed_dir / project_id / "s2_toc_workdir" / "投标文件-总目录.json"

        def fake_generate_outline(prompt: str, session_ready_callback=None, stream_callback=None) -> dict[str, object]:
            toc_path.parent.mkdir(parents=True, exist_ok=True)
            toc_path.write_text(
                (
                    '{"schema_version":"bid-toc-json-v1","summary":{"total_items":2},'
                    '"items":[{"order":1,"number":"第一章","title":"项目概况","level":1,'
                    '"annotation":"保留","source":"template","reason":""},'
                    '{"order":2,"number":"1.1","title":"项目背景","level":2,'
                    '"annotation":"适配","source":"wiki","reason":""}]}'
                ),
                encoding="utf-8",
            )
            return {
                "schema_version": "bid-toc-json-v1",
                "outputFile": str(toc_path),
                "summary": {"total_items": 2},
                "itemCount": 2,
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": "ses-summary",
                    "providerId": "opencode",
                    "modelId": "big-pickle",
                    "receivedAt": "2026-04-20T00:00:00Z",
                    "parts": [{"type": "text", "text": "{\"outputFile\":\"...\"}"}],
                },
            }

        with patch(
            "app.services.outline_generation.OpencodeClient.generate_outline_with_trace",
            side_effect=fake_generate_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["output"]["chapterCount"], 1)
        self.assertEqual(payload["opencodeOutput"]["tocJsonPath"], str(toc_path))
        outline = store.get_outline_state(project_id)
        self.assertEqual(outline["nodes"][0]["title"], "第一章 项目概况")
        self.assertEqual(outline["nodes"][0]["children"][0]["title"], "项目背景")

    def test_generate_outline_prefers_template_headings_then_uses_tender_to_adjust(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        template_path = settings.uploads_dir / project_id / "template" / "投标模板.docx"
        template_path.parent.mkdir(parents=True, exist_ok=True)

        document = Document()
        document.add_paragraph("目录")
        document.add_paragraph("第1章 标前概述")
        document.add_paragraph("1.1 技术评分标准索引表")
        document.add_paragraph("第2章 技术标准")
        document.add_paragraph("第3章 风资源评估与机位排布方案")
        document.save(template_path)

        parse_result = store.get_parse_result(project_id)
        parse_storage = store.get_parse_storage(project_id)
        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(settings.uploads_dir / project_id / "tender" / "招标文件.docx"),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[
                {
                    "id": "TPL-1",
                    "name": "投标模板.docx",
                    "path": str(template_path),
                    "size_label": "2.0 MB",
                }
            ],
            summary=parse_result["summary"],
            parse_storage=parse_storage,
        )

        captured: dict[str, str] = {}

        def fake_generate_outline(
            prompt: str,
            session_ready_callback=None,
            stream_callback=None,
        ) -> dict[str, object]:
            captured["prompt"] = prompt
            if session_ready_callback:
                session_ready_callback(
                    {
                        "sessionId": "ses-template",
                        "providerId": "opencode",
                        "modelId": "big-pickle",
                    }
                )
            if stream_callback:
                stream_callback(
                    {
                        "status": "streaming",
                        "sessionId": "ses-template",
                        "providerId": "opencode",
                        "modelId": "big-pickle",
                        "receivedAt": "2026-04-20T00:00:00Z",
                        "parts": [{"type": "reasoning", "text": "优先沿用模板章节。"}],
                    }
                )
            return {
                "summary": "目录生成完成。",
                "nodes": [
                    {"id": "OL-1", "title": "标前概述", "children": []},
                    {"id": "OL-2", "title": "技术标准", "children": []},
                    {"id": "OL-3", "title": "实施与保障", "children": []},
                ],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": "ses-template",
                    "providerId": "opencode",
                    "modelId": "big-pickle",
                    "receivedAt": "2026-04-20T00:00:00Z",
                    "parts": [
                        {"type": "reasoning", "text": "优先沿用模板章节。"},
                        {"type": "text", "text": "{\"summary\":\"目录生成完成。\"}"},
                    ],
                },
            }

        with patch(
            "app.services.outline_generation.OpencodeClient.generate_outline_with_trace",
            side_effect=fake_generate_outline,
        ):
            generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        prompt = captured["prompt"]
        self.assertIn("先按投标模板目录起基础目录", prompt)
        self.assertIn("再对照招标要求删改、补改", prompt)
        self.assertIn("Bash 工具 timeout 必须设置为 600000", prompt)
        self.assertIn("不要先检查工作目录", prompt)
        self.assertIn("s2toc", prompt)
        self.assertIn("/s2.json", prompt)
        self.assertIn("不要改写命令或路径", prompt)
        self.assertIn("第1章 标前概述", prompt)
        self.assertIn("1.1 技术评分标准索引表", prompt)
        self.assertIn("第一章 项目概况", prompt)

    def test_run_directory_generation_returns_running_state_immediately(self) -> None:
        project_id = self._prepare_project_with_parse_result()

        with patch("app.api.routes.directory._schedule_directory_generation_job"):
            response = self.client.post(
                f"/api/projects/{project_id}/directory-generation/run",
                json={"outlineStrategy": "strict"},
            )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["tasks"][0]["status"], "running")
        self.assertEqual(payload["tasks"][1]["status"], "pending")

    def test_generate_outline_falls_back_when_opencode_returns_invalid_json(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.outline_generation.OpencodeClient.generate_outline_with_trace",
            side_effect=RuntimeError("opencode 返回的 JSON 无法解析。"),
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertEqual(payload["status"], "completed")
        self.assertGreaterEqual(payload["output"]["chapterCount"], 3)
        self.assertEqual(payload["opencodeOutput"]["status"], "failed")
        self.assertTrue(any(event["level"] == "warning" for event in payload["events"]))
        self.assertTrue(any("opencode 返回的 JSON 无法解析" in str(part.get("text", "")) for part in payload["opencodeOutput"]["parts"]))

    def test_opencode_delta_updates_streaming_parts_before_completion(self) -> None:
        from app.api.routes.directory import _handle_directory_progress

        project_id = self._prepare_project_with_parse_result()
        store.start_directory_generation(project_id)

        _handle_directory_progress(
            project_id,
            "calling_opencode",
            {
                "sessionId": "ses-streaming",
                "providerId": "opencode",
                "modelId": "big-pickle",
            },
        )
        _handle_directory_progress(
            project_id,
            "opencode_delta",
            {
                "status": "streaming",
                "sessionId": "ses-streaming",
                "providerId": "opencode",
                "modelId": "big-pickle",
                "receivedAt": "2026-04-21T00:00:00Z",
                "parts": [
                    {"type": "step-start", "text": ""},
                    {"type": "reasoning", "text": "先整理目录骨架。"},
                ],
            },
        )

        state = store.get_directory_state(project_id)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["opencodeOutput"]["status"], "streaming")
        self.assertEqual(state["opencodeOutput"]["sessionId"], "ses-streaming")
        self.assertEqual(state["opencodeOutput"]["parts"][1]["type"], "reasoning")
        self.assertEqual(state["events"][-1]["step"], "opencode_streaming")
        self.assertIn("原始片段", state["events"][-1]["message"])

    def test_background_job_updates_running_state_then_completes(self) -> None:
        from app.api.routes.directory import _handle_directory_progress, _run_directory_generation_job

        project_id = self._prepare_project_with_parse_result()
        store.start_directory_generation(project_id)

        _handle_directory_progress(
            project_id,
            "inputs_ready",
            {"tenderHintCount": 3, "templateHintCount": 1},
        )
        running_state = store.get_directory_state(project_id)
        self.assertEqual(running_state["status"], "running")
        self.assertEqual(running_state["percentage"], 30)
        self.assertEqual(running_state["tasks"][1]["status"], "running")
        self.assertEqual(running_state["events"][-1]["step"], "hint_ready")
        self.assertEqual(running_state["opencodeOutput"]["status"], "idle")

        _handle_directory_progress(
            project_id,
            "calling_opencode",
            {
                "sessionId": "ses-running",
                "providerId": "opencode",
                "modelId": "big-pickle",
            },
        )
        waiting_state = store.get_directory_state(project_id)
        self.assertEqual(waiting_state["opencodeOutput"]["status"], "waiting")
        self.assertEqual(waiting_state["opencodeOutput"]["sessionId"], "ses-running")
        self.assertEqual(waiting_state["opencodeOutput"]["modelId"], "big-pickle")

        with patch(
            "app.services.outline_generation.OpencodeClient.generate_outline_with_trace",
            return_value={
                "summary": "目录生成完成。",
                "nodes": [
                    {"id": "OL-1", "title": "项目概况", "children": []},
                    {"id": "OL-2", "title": "技术方案", "children": []},
                    {"id": "OL-3", "title": "实施与保障", "children": []},
                ],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": "ses-running",
                    "providerId": "opencode",
                    "modelId": "big-pickle",
                    "receivedAt": "2026-04-20T00:00:00Z",
                    "parts": [
                        {"type": "reasoning", "text": "目录骨架已整理。"},
                        {"type": "text", "text": "{\"summary\":\"目录生成完成。\"}"},
                    ],
                },
            },
        ):
            _run_directory_generation_job(project_id, {"outlineStrategy": "strict"})

        completed_state = store.get_directory_state(project_id)
        self.assertEqual(completed_state["status"], "completed")
        self.assertEqual(completed_state["percentage"], 100)
        self.assertEqual(completed_state["tasks"][2]["status"], "done")
        self.assertEqual(completed_state["events"][-1]["level"], "success")
        self.assertEqual(completed_state["opencodeOutput"]["status"], "received")
        self.assertEqual(completed_state["opencodeOutput"]["parts"][1]["type"], "text")

    def test_directory_generation_stream_returns_event_stream_payload(self) -> None:
        project_id = self._prepare_project_with_parse_result()
        store.complete_directory_generation(project_id, {})

        with self.client.stream(
            "GET",
            f"/api/projects/{project_id}/directory-generation/stream",
        ) as response:
            chunks = response.iter_text()
            first_chunk = next(chunks)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
        self.assertIn('"status": "completed"', first_chunk)
        self.assertIn('"summary": "目录生成完成。"', first_chunk)


if __name__ == "__main__":
    unittest.main()
