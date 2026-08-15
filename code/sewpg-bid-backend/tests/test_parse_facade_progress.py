from __future__ import annotations

import unittest
from unittest.mock import patch
from app.services.store import store

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_parse_progress_records_real_steps_and_completion(self) -> None:
        project_id = self.create_project()
        tender = "项目名称：进度测试项目\n单机容量：6.25MW\n".encode("utf-8")

        before = self.client.get(self.parse_results_url(project_id, "/progress"))
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()["status"], "idle")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )
        self.assertEqual(response.status_code, 200)

        progress = self.client.get(self.parse_results_url(project_id, "/progress"))
        self.assertEqual(progress.status_code, 200)
        payload = progress.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["percentage"], 100)
        steps = [event["step"] for event in payload["events"]]
        self.assertIn("upload", steps)
        self.assertIn("extract", steps)
        self.assertIn("skill", steps)
        self.assertIn("appendix", steps)
        self.assertIn("complete", steps)



    def test_parse_progress_completion_replaces_streaming_opencode_output(self) -> None:
        project_id = self.create_project()
        tender = "progress opencode output closeout test\n".encode("utf-8")

        structured = {
            "schemaVersion": "bid-tender-structured-v1",
            "projectDates": {"startDate": "", "endDate": ""},
            "appendices": [],
            "opencodeOutput": {
                "status": "received",
                "sessionId": "ses-s1",
                "parts": [{"type": "text", "text": "s1parse finalize completed"}],
                "earlyCompletion": True,
            },
        }

        with patch(
            "app.services.bid_parse_service.parse_tender_documents",
            return_value=(
                {"fileCount": 1, "extractedCount": 1, "textLength": 10, "textPreview": "", "warnings": []},
                {
                    "documents": [{"name": "tender.md", "pageCount": 1, "textLength": 10}],
                    "items": [{"id": "REQ-1", "title": "parsed"}],
                    "structured": structured,
                    "projectUpdates": {},
                },
            ),
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("tender.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        progress = self.client.get(self.parse_results_url(project_id, "/progress")).json()
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["opencodeOutput"]["status"], "received")
        self.assertNotEqual(progress["opencodeOutput"]["status"], "streaming")



    def test_parse_progress_completion_closes_stale_streaming_without_final_trace(self) -> None:
        project_id = self.create_project()
        tender = "progress stale streaming closeout test\n".encode("utf-8")

        def fake_parse(
            project_id,
            tender_files,
            *,
            bid_type,
            progress_callback=None,
            cancel_check=None,
            require_preparsed_pdf=False,
        ):
            if progress_callback:
                progress_callback(
                    "opencode_delta",
                    {
                        "status": "streaming",
                        "sessionId": "ses-stale",
                        "parts": [{"type": "text", "text": "agent is still writing"}],
                    },
                )
            return (
                {"fileCount": 1, "extractedCount": 1, "textLength": 10, "textPreview": "", "warnings": []},
                {
                    "documents": [{"name": "tender.md", "pageCount": 1, "textLength": 10}],
                    "items": [{"id": "REQ-1", "title": "parsed"}],
                    "structured": {
                        "schemaVersion": "bid-tender-structured-v1",
                        "projectDates": {"startDate": "", "endDate": ""},
                        "appendices": [],
                    },
                    "projectUpdates": {},
                },
            )

        with patch("app.services.bid_parse_service.parse_tender_documents", side_effect=fake_parse):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("tender.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        progress = self.client.get(self.parse_results_url(project_id, "/progress")).json()
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["opencodeOutput"]["status"], "received")
        self.assertEqual(progress["opencodeOutput"]["sessionId"], "ses-stale")



    def test_cancel_parse_endpoint_marks_progress_and_aborts_opencode_session(self) -> None:
        project_id = self.create_project()
        project = store.require_project_for_update(project_id)
        project["parse_progress"] = {
            "status": "running",
            "percentage": 80,
            "summary": "opencode 正在返回解析输出。",
            "startedAt": "2026-07-04T09:00:00Z",
            "completedAt": "",
            "events": [],
            "opencodeOutput": {
                "status": "streaming",
                "sessionId": "ses_cancel_parse_probe",
                "parts": [{"type": "text", "text": "s1parse 正在执行"}],
            },
        }
        store.persist_project_state(project)

        with patch(
            "app.services.bid_parse_service.OpencodeEngine.abort_session",
            return_value=True,
            create=True,
        ) as abort_session:
            response = self.client.post(self.parse_results_url(project_id, "/cancel"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "cancelled")
        self.assertTrue(payload["cancelRequested"])
        self.assertEqual(payload["opencodeOutput"]["status"], "cancelled")
        self.assertEqual(payload["opencodeAbort"]["sessionId"], "ses_cancel_parse_probe")
        self.assertTrue(payload["opencodeAbort"]["aborted"])
        abort_session.assert_called_once_with("ses_cancel_parse_probe")

        progress = self.client.get(self.parse_results_url(project_id, "/progress")).json()
        self.assertEqual(progress["status"], "cancelled")
        self.assertTrue(progress["cancelRequested"])



    def test_upload_parse_returns_cancelled_when_cancel_requested_before_completion(self) -> None:
        project_id = self.create_project()
        tender = "cancel before complete\n".encode("utf-8")

        def fake_parse(
            project_id_arg,
            tender_files,
            *,
            bid_type,
            progress_callback=None,
            cancel_check=None,
            require_preparsed_pdf=False,
        ):
            project = store.require_project_for_update(project_id_arg)
            progress = project.get("parse_progress")
            self.assertIsInstance(progress, dict)
            progress["status"] = "cancelled"
            progress["cancelRequested"] = True
            progress["summary"] = "已请求停止后端解析和 Opencode 任务。"
            project["parse_progress"] = progress
            store.persist_project_state(project)
            if cancel_check:
                self.assertTrue(cancel_check())
            return (
                {"fileCount": 1, "extractedCount": 1, "textLength": 10, "textPreview": "", "warnings": []},
                {
                    "documents": [{"name": "tender.md", "pageCount": 1, "textLength": 10}],
                    "items": [{"id": "REQ-1", "title": "should not be committed"}],
                    "structured": {
                        "schemaVersion": "bid-tender-structured-v1",
                        "appendices": [],
                    },
                    "projectUpdates": {},
                },
            )

        with patch("app.services.bid_parse_service.parse_tender_documents", side_effect=fake_parse):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("tender.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        project = store._require(project_id)
        self.assertNotEqual(project["parse_result"]["status"], "completed")
        self.assertEqual(project["parse_progress"]["status"], "cancelled")



    def test_business_template_extraction_progress_is_visible(self) -> None:
        project_id = self.create_business_project()
        tender = "business template progress test\n".encode("utf-8")

        def fake_parse(
            project_id,
            tender_files,
            *,
            bid_type,
            progress_callback=None,
            cancel_check=None,
            require_preparsed_pdf=False,
        ):
            if progress_callback:
                progress_callback(
                    "business_template_extraction_started",
                    {"documentCount": 1},
                )
                progress_callback(
                    "business_template_extraction_agent",
                    {
                        "status": "streaming",
                        "sessionId": "ses-template",
                        "parts": [{"type": "text", "text": "btplnav extracting templates"}],
                    },
                )
            return (
                {"fileCount": 1, "extractedCount": 1, "textLength": 10, "textPreview": "", "warnings": []},
                {
                    "documents": [{"name": "tender.md", "pageCount": 1, "textLength": 10}],
                    "items": [{"id": "REQ-1", "title": "parsed"}],
                    "structured": {
                        "schemaVersion": "bid-business-tender-structured-v1",
                        "fieldGroups": {},
                        "appendices": [],
                    },
                    "projectUpdates": {},
                },
            )

        with patch("app.services.bid_parse_service.parse_tender_documents", side_effect=fake_parse):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("tender.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        progress = self.client.get(self.parse_results_url(project_id, "/progress")).json()
        steps = [event["step"] for event in progress["events"]]
        self.assertIn("template", steps)
        self.assertEqual(progress["opencodeOutput"]["sessionId"], "ses-template")


class ParseStructuredHeartbeatTests(unittest.TestCase):

    """结构化解析心跳只刷新进度，不灌满事件环（events 只保留 80 条）。"""



    class _RecordingService:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            return None

        def update_parse_progress(self, project_id: str, **kwargs) -> dict:
            self.calls.append(kwargs)
            return {}



    def _delta(self, completed_shards: int, elapsed_seconds: int) -> dict:
        return {
            "status": "running",
            "shardProgress": completed_shards * 14,
            "completedShards": completed_shards,
            "totalShards": 7,
            "elapsedSeconds": elapsed_seconds,
        }



    def test_heartbeats_without_progress_do_not_append_events(self) -> None:
        from app.services.bid_parse_service import _progress_callback

        service = self._RecordingService()
        update = _progress_callback(service, "PRJ-0003")

        for index in range(6):
            update("opencode_delta", self._delta(0, 10 + index * 3))
        update("opencode_delta", self._delta(1, 40))
        update("opencode_delta", self._delta(1, 45))

        messages = [call["event_message"] for call in service.calls]
        logged = [message for message in messages if message]

        # 8 次心跳只落 2 条事件：首次进入 + 分片数真的变了
        self.assertEqual(len(service.calls), 8)
        self.assertEqual(len(logged), 2)
        self.assertIn("0/7 个分片", logged[0])
        self.assertIn("1/7 个分片", logged[1])

        # 百分比与摘要每次都刷新，卡死检测靠 heartbeatAt 而不是 events
        self.assertTrue(all(call.get("percentage") is not None for call in service.calls))
        self.assertIn("已完成 1/7 个分片", service.calls[-1]["summary"])



    def test_summary_falls_back_to_elapsed_when_shard_counts_missing(self) -> None:
        from app.services.bid_parse_service import _progress_callback

        service = self._RecordingService()
        update = _progress_callback(service, "PRJ-0003")
        update("opencode_delta", {"status": "streaming", "parts": [{"type": "text"}], "elapsedSeconds": 75})

        self.assertIn("已执行 1 分 15 秒", service.calls[-1]["summary"])
        self.assertIn("已返回 1 段输出", service.calls[-1]["event_message"])
