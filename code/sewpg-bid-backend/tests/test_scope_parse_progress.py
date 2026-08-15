import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from app.services.bid_ocr_service import BidOcrService
from app.services.file_utils import format_size_mb
from app.services.bid_parse_state import (
    complete_parse_state,
    parse_progress_snapshot_state,
    source_file_type,
    start_parse_progress_state,
    update_parse_progress_state,
    update_template_files_state,
)
from app.services.bid_parse_service import _progress_callback

from bid_scope_helpers import (
    _DummyOcrProjectService,
)


def test_bid_ocr_service_injects_workspace_audit_metadata() -> None:
    service = BidOcrService(_DummyOcrProjectService())

    with patch("app.services.bid_ocr_service.ocr_service.run_ocr", new=AsyncMock(return_value={"status": "completed"})) as run_ocr:
        payload = asyncio.run(
            service.run(
                project_id="PRJ-BIZ-OCR",
                file_name="ocr.png",
                content=b"fake",
                mime_type="image/png",
                user={"id": "u1", "name": "测试用户"},
            )
        )

    assert payload["status"] == "completed"
    run_kwargs = run_ocr.await_args.kwargs
    assert run_kwargs["project_id"] == "PRJ-BIZ-OCR"
    assert run_kwargs["audit_metadata"] == {
        "projectId": "PRJ-BIZ-OCR",
        "projectName": "商务 OCR 项目",
        "projectCode": "BIZ-OCR-001",
        "customerName": "测试业主",
        "bidType": "商务标",
    }

    with patch(
        "app.services.bid_ocr_service.ocr_service.confirm_candidate",
        new=AsyncMock(return_value={"message": "ok"}),
    ) as confirm_candidate:
        payload = asyncio.run(
            service.confirm_candidate(
                "PRJ-BIZ-OCR",
                "OC-001",
                {"action": "confirm", "value": "确认值"},
                user={"id": "u1", "name": "测试用户"},
            )
        )

    assert payload["message"] == "ok"
    confirm_kwargs = confirm_candidate.await_args.kwargs
    assert confirm_kwargs["audit_metadata"]["bidType"] == "商务标"
    assert confirm_kwargs["audit_metadata"]["projectId"] == "PRJ-BIZ-OCR"


def test_bid_parse_state_rules_are_outside_store() -> None:
    project = {
        "id": "PRJ-PARSE",
        "name": "解析状态项目",
        "bidType": "商务标",
        "currentStage": 3,
        "startDate": "",
        "endDate": "",
        "deadline": "",
        "parse_result": {"project": {}},
    }
    tender_files = [{"id": "TEN-1", "name": "招标文件.pdf", "size_label": "1.0 MB"}]
    template_files = [{"id": "TPL-1", "name": "商务模板.docx", "size_label": "0.5 MB"}]

    parse_result = complete_parse_state(
        project,
        tender_files,
        template_files,
        summary={"fileCount": 1, "extractedCount": 1, "textLength": 900, "textPreview": "预览", "warnings": []},
        parse_storage={
            "projectUpdates": {"startDate": "2026-05-25"},
            "documents": [{"name": "招标文件.pdf", "pageCount": 8, "textLength": 900}],
            "items": [{"id": "REQ-1", "title": "商务响应"}],
            "structured": {"appendices": []},
        },
    )
    progress = start_parse_progress_state(project, "开始解析商务标。")
    progress = update_parse_progress_state(
        project,
        status="completed",
        percentage=120,
        summary="解析完成。",
        event_message="商务标解析完成。",
        event_step="complete",
        event_level="success",
    )
    template_payload = update_template_files_state(
        project,
        [{"id": "TPL-2", "name": "新模板.docx", "size_label": "0.6 MB"}],
    )
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    parse_source = Path("app/services/bid_parse_state.py").read_text(encoding="utf-8")

    assert source_file_type("说明.md") == "MD"
    assert parse_result["project"]["stageLabel"] == "素材匹配"
    assert parse_result["sourceFiles"][0]["type"] == "PDF"
    assert parse_result["sourceFiles"][0]["pageCount"] == 8
    assert project["startDate"] == "2026-05-25"
    assert progress["percentage"] == 100
    assert progress["events"][-1]["message"] == "商务标解析完成。"
    assert template_payload["project"]["templateFiles"][0]["name"] == "新模板.docx"
    assert project["parse_result"]["project"]["templateFiles"][0]["id"] == "TPL-2"
    assert format_size_mb(2 * 1024 * 1024) == "2.0 MB"
    assert "from app.services.bid_parse_state import" not in store_source
    assert "complete_parse_state(" not in store_source
    assert "def get_parse_result(" not in store_source
    assert "def get_parse_storage(" not in store_source
    assert "def get_parse_progress(" not in store_source
    assert "def get_parse_inputs(" not in store_source
    assert "def start_parse_progress(" not in store_source
    assert "def update_parse_progress(" not in store_source
    assert "def update_parse_result(" not in store_source
    assert "def update_template_files(" not in store_source
    assert "start_parse_progress_state" not in store_source
    assert "update_parse_progress_state(" not in store_source
    assert "update_parse_result_state(" not in store_source
    assert "update_template_files_state(project, template_files)" not in store_source
    assert "def format_size" not in store_source
    assert "format_size_mb" not in store_source
    assert "def source_file_type" in parse_source
    assert "def complete_parse_state" in parse_source
    assert "def update_parse_progress_state" in parse_source
    assert "def update_parse_result_state" in parse_source
    assert "def update_template_files_state" in parse_source
    assert "def complete_parse(" not in store_source
    assert "from app.services.bid_parse_state import complete_parse_state" not in store_source
    assert "def _source_file_type" not in store_source
    assert "build_parse_event" not in store_source
    assert '"解析完成，提取 {payload.get' not in store_source


def test_parse_progress_state_records_phase_counts_and_heartbeat() -> None:
    project = {
        "id": "PRJ-PARSE-PHASE",
        "name": "解析进度细化项目",
        "bidType": "技术标",
        "currentStage": 1,
        "startDate": "",
        "endDate": "",
        "deadline": "",
        "parse_result": {"project": {}},
    }

    started = start_parse_progress_state(project, "开始解析技术标。")
    progress = update_parse_progress_state(
        project,
        percentage=52,
        summary="正在生成附表 Word：12 / 80。",
        event_message="附表 Word 已生成 12 / 80。",
        event_step="appendix",
        phase_key="appendix",
        phase_label="生成附表 Word",
        phase_percent=35,
        current=12,
        total=80,
    )

    assert started["phaseKey"] == "start"
    assert progress["phaseKey"] == "appendix"
    assert progress["phaseLabel"] == "生成附表 Word"
    assert progress["phasePercent"] == 35
    assert progress["current"] == 12
    assert progress["total"] == 80
    assert progress["heartbeatAt"]
    assert project["parse_progress"]["heartbeatAt"] == progress["heartbeatAt"]


def test_running_parse_progress_percentage_is_monotonic() -> None:
    project = {
        "id": "PRJ-PARSE-MONOTONIC",
        "name": "解析进度单调项目",
        "bidType": "技术标",
        "currentStage": 1,
        "startDate": "",
        "endDate": "",
        "deadline": "",
        "parse_result": {"project": {}},
    }

    start_parse_progress_state(project, "开始解析技术标。")
    update_parse_progress_state(
        project,
        percentage=78,
        summary="opencode 正在解析。",
        phase_key="opencode",
        phase_label="Opencode 结构化解析",
        phase_percent=45,
    )
    progress = update_parse_progress_state(
        project,
        percentage=72,
        summary="opencode 仍在执行。",
        event_message="opencode 仍在执行。",
        event_step="opencode",
        phase_key="opencode",
        phase_label="Opencode 结构化解析",
        phase_percent=50,
    )

    assert progress["percentage"] == 78
    assert progress["phasePercent"] == 50
    assert progress["summary"] == "opencode 仍在执行。"


def test_parse_progress_snapshot_marks_stale_running_heartbeat_without_mutating_state() -> None:
    project = {
        "id": "PRJ-PARSE-STALE",
        "name": "解析进度陈旧项目",
        "bidType": "技术标",
        "currentStage": 1,
        "updatedAt": "2026-07-04T09:00:00Z",
        "parse_progress": {
            "status": "running",
            "percentage": 40,
            "summary": "正在生成附表 Word。",
            "phaseKey": "appendix",
            "phaseLabel": "生成附表 Word",
            "phasePercent": 20,
            "heartbeatAt": "2026-07-04T09:00:00Z",
            "staleAfterSeconds": 60,
            "events": [],
        },
    }

    progress = parse_progress_snapshot_state(project, now="2026-07-04T09:02:30Z")

    assert progress["status"] == "stale"
    assert progress["phaseKey"] == "appendix"
    assert progress["stale"] is True
    assert "长时间没有进度更新" in progress["summary"]
    assert project["parse_progress"]["status"] == "running"


def test_opencode_progress_callback_does_not_regress_when_snapshot_parts_shrink() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.project = {
                "id": "PRJ-OPENCODE-MONOTONIC",
                "name": "opencode 进度单调项目",
                "bidType": "技术标",
                "currentStage": 1,
                "parse_result": {"project": {}},
            }
            start_parse_progress_state(self.project, "开始解析技术标。")

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-OPENCODE-MONOTONIC"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
            assert project_id == "PRJ-OPENCODE-MONOTONIC"
            return update_parse_progress_state(self.project, **kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-OPENCODE-MONOTONIC")

    callback(
        "opencode_delta",
        {
            "status": "streaming",
            "sessionId": "ses-progress",
            "parts": [{"type": "text", "text": str(index)} for index in range(4)],
        },
    )
    first_percentage = service.project["parse_progress"]["percentage"]
    callback(
        "opencode_delta",
        {
            "status": "streaming",
            "sessionId": "ses-progress",
            "parts": [{"type": "text", "text": "snapshot shrank"}],
        },
    )

    assert service.project["parse_progress"]["percentage"] == first_percentage
    assert service.project["parse_progress"]["phaseKey"] == "opencode"


def test_opencode_heartbeat_idle_time_advances_visible_progress() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.project = {
                "id": "PRJ-OPENCODE-HEARTBEAT",
                "name": "opencode heartbeat progress",
                "bidType": "技术标",
                "currentStage": 1,
                "parse_result": {"project": {}},
            }
            start_parse_progress_state(self.project, "开始解析技术标。")

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-OPENCODE-HEARTBEAT"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
            assert project_id == "PRJ-OPENCODE-HEARTBEAT"
            return update_parse_progress_state(self.project, **kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-OPENCODE-HEARTBEAT")
    base_parts = [{"type": "text", "text": str(index)} for index in range(3)]

    callback("opencode_delta", {"status": "streaming", "parts": base_parts})
    first_percentage = service.project["parse_progress"]["percentage"]

    callback(
        "opencode_delta",
        {
            "status": "streaming",
            "parts": base_parts,
            "heartbeat": True,
            "heartbeatIndex": 1,
            "idleSeconds": 60,
        },
    )

    progress = service.project["parse_progress"]
    assert progress["phaseKey"] == "opencode"
    assert progress["phasePercent"] >= 60
    assert progress["percentage"] > first_percentage


def test_opencode_elapsed_time_advances_visible_progress_when_idle_resets() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.project = {
                "id": "PRJ-OPENCODE-ELAPSED",
                "name": "opencode elapsed progress",
                "bidType": "技术标",
                "currentStage": 1,
                "parse_result": {"project": {}},
            }
            start_parse_progress_state(self.project, "开始解析技术标。")

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-OPENCODE-ELAPSED"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
            assert project_id == "PRJ-OPENCODE-ELAPSED"
            return update_parse_progress_state(self.project, **kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-OPENCODE-ELAPSED")
    base_parts = [{"type": "text", "text": str(index)} for index in range(3)]

    callback("opencode_delta", {"status": "streaming", "parts": base_parts, "elapsedSeconds": 30})

    callback(
        "opencode_delta",
        {
            "status": "streaming",
            "parts": base_parts,
            "heartbeat": True,
            "heartbeatIndex": 1,
            "idleSeconds": 10,
            "elapsedSeconds": 240,
        },
    )

    progress = service.project["parse_progress"]
    assert progress["phaseKey"] == "opencode"
    assert progress["phasePercent"] >= 95
    assert progress["percentage"] >= 94


def test_opencode_progress_uses_user_facing_structured_parse_message() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.project = {
                "id": "PRJ-STRUCTURED-PARSE-MESSAGE",
                "name": "structured parse message",
                "bidType": "技术标",
                "currentStage": 1,
                "parse_result": {"project": {}},
            }
            start_parse_progress_state(self.project, "开始解析技术标。")

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-STRUCTURED-PARSE-MESSAGE"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
            assert project_id == "PRJ-STRUCTURED-PARSE-MESSAGE"
            return update_parse_progress_state(self.project, **kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-STRUCTURED-PARSE-MESSAGE")

    callback(
        "opencode_delta",
        {
            "status": "streaming",
            "parts": [{"type": "text", "text": "internal"}],
            "heartbeat": True,
            "heartbeatIndex": 3,
            "idleSeconds": 30,
            "elapsedSeconds": 261,
        },
    )

    progress = service.project["parse_progress"]
    latest_event = progress["events"][-1]["message"]
    visible_text = f"{progress['phaseLabel']} {progress['summary']} {latest_event}"
    assert progress["phaseLabel"] == "结构化解析中"
    assert progress["summary"] == "正在识别招标文件中的技术要求和原文依据，已执行 4 分 21 秒。"
    # 事件写的是「推进了多少」而不是「还活着」：纯心跳不再落事件，否则 80 条事件环
    # 会被刷满，上传/提取/附表的阶段记录全被挤掉。
    assert latest_event == "结构化解析已返回 1 段输出，已执行 4 分 21 秒。"
    assert "AI" not in visible_text
    assert "Opencode" not in visible_text
    assert "opencode" not in visible_text
    assert "S1" not in visible_text
    assert "输出片段" not in visible_text


def test_word_progress_uses_configured_stage_weight_table() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-WORD-WEIGHTS"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> None:
            assert project_id == "PRJ-WORD-WEIGHTS"
            self.calls.append(kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-WORD-WEIGHTS")

    callback("upload_ready", {"fileCount": 1})
    callback(
        "extracting_file_progress",
        {
            "fileName": "招标文件-技术规范.docx",
            "fileExtension": ".docx",
            "current": 1,
            "total": 1,
            "progress": 50,
            "textLength": 12000,
        },
    )
    callback("local_structure_started", {"documentCount": 1, "fileExtension": ".docx"})
    callback("local_structure_finished", {"itemCount": 12, "fileExtension": ".docx"})
    callback("appendices_started", {"documentCount": 1, "fileExtension": ".docx"})
    callback("docx_appendix_materializing", {"title": "附表C.1", "current": 40, "total": 80})
    callback("appendices_extracted", {"appendixCount": 80, "generatedCount": 80, "fileExtension": ".docx"})
    callback("skill_manifest_ready", {"fileExtension": ".docx"})
    callback("complete", {"extractedCount": 58, "appendixCount": 80})

    assert service.calls[0]["percentage"] == 8
    assert service.calls[0]["phase_label"] == "上传文件中"
    assert service.calls[1]["phase_label"] == "Word 处理中"
    assert 8 < service.calls[1]["percentage"] < 24
    assert service.calls[2]["percentage"] == 24
    assert service.calls[2]["phase_label"] == "整理文档线索中"
    assert service.calls[3]["percentage"] == 34
    assert service.calls[4]["percentage"] == 34
    assert service.calls[4]["phase_label"] == "提取附表中"
    assert 40 < service.calls[5]["percentage"] < 62
    assert service.calls[5]["phase_label"] == "提取附表中"
    assert service.calls[6]["percentage"] == 62
    assert service.calls[7]["percentage"] == 68
    assert service.calls[7]["phase_label"] == "准备结构化解析中"
    assert service.calls[8]["percentage"] == 97
    assert service.calls[8]["phase_label"] == "写入解析结果中"


def test_pdf_progress_uses_pdf_weight_table_and_elapsed_task_text() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-PDF-WEIGHTS"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> None:
            assert project_id == "PRJ-PDF-WEIGHTS"
            self.calls.append(kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-PDF-WEIGHTS")

    callback(
        "extracting_file",
        {
            "fileName": "招标文件-技术规范.pdf",
            "fileExtension": ".pdf",
            "current": 1,
            "total": 1,
            "fileCount": 1,
        },
    )
    callback(
        "pdf_extracting_progress",
        {
            "fileName": "招标文件-技术规范.pdf",
            "elapsedSeconds": 120,
            "currentPage": 22,
            "totalPages": 44,
            "tableCount": 47,
        },
    )
    callback(
        "file_extracted",
        {
            "fileName": "招标文件-技术规范.pdf",
            "fileExtension": ".pdf",
            "textLength": 300000,
            "current": 1,
            "total": 1,
            "fileCount": 1,
        },
    )
    callback("local_structure_started", {"documentCount": 1, "fileExtension": ".pdf"})
    callback("local_structure_finished", {"itemCount": 58, "fileExtension": ".pdf"})
    callback("appendices_started", {"documentCount": 1, "fileExtension": ".pdf"})
    callback("appendices_extracted", {"appendixCount": 65, "generatedCount": 65, "fileExtension": ".pdf"})

    assert service.calls[0]["percentage"] == 8
    assert service.calls[0]["phase_label"] == "PDF 处理中"
    assert service.calls[1]["phase_label"] == "PDF 处理中"
    assert 8 < service.calls[1]["percentage"] < 42
    assert "正在解析页面与表格" in service.calls[1]["summary"]
    assert "已执行 2 分 0 秒" in service.calls[1]["summary"]
    assert "已处理 22 / 44 页" in service.calls[1]["summary"]
    assert service.calls[2]["percentage"] == 42
    assert service.calls[3]["percentage"] == 42
    assert service.calls[3]["phase_label"] == "整理文档线索中"
    assert service.calls[4]["percentage"] == 50
    assert service.calls[5]["percentage"] == 50
    assert service.calls[5]["phase_label"] == "提取附表中"
    assert service.calls[6]["percentage"] == 62


def test_single_file_extracting_progress_moves_past_initial_floor() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-DOCX-EXTRACT"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> None:
            assert project_id == "PRJ-DOCX-EXTRACT"
            self.calls.append(kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-DOCX-EXTRACT")

    callback("extract_started", {"fileCount": 1})
    callback(
        "extracting_file",
        {
            "fileName": "招标文件-技术规范.docx",
            "current": 1,
            "total": 1,
            "fileCount": 1,
        },
    )
    callback(
        "extracting_file_progress",
        {
            "fileName": "招标文件-技术规范.docx",
            "current": 1,
            "total": 1,
            "progress": 50,
            "textLength": 12000,
        },
    )

    assert service.calls[1]["percentage"] > 8
    assert service.calls[-1]["percentage"] > service.calls[1]["percentage"]
    assert service.calls[-1]["percentage"] < 24


def test_pdf_extracting_progress_allows_long_docling_page_window() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-PDF-EXTRACT"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> None:
            assert project_id == "PRJ-PDF-EXTRACT"
            self.calls.append(kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-PDF-EXTRACT")

    callback(
        "extracting_file",
        {
            "fileName": "招标文件-技术规范.pdf",
            "fileExtension": ".pdf",
            "current": 1,
            "total": 1,
            "fileCount": 1,
        },
    )

    assert service.calls[-1]["stale_after_seconds"] == 1800


def test_docx_appendix_materializing_progress_reports_current_candidate() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-DOCX-PROGRESS"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> None:
            assert project_id == "PRJ-DOCX-PROGRESS"
            self.calls.append(kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-DOCX-PROGRESS")

    callback(
        "docx_appendix_materializing",
        {
            "title": "附表H.6 关键部件情况表",
            "current": 80,
            "total": 80,
        },
    )

    assert service.calls
    progress = service.calls[-1]
    assert progress["phase_key"] == "appendix"
    assert progress["phase_label"] == "提取附表中"
    assert progress["phase_percent"] < 100
    assert progress["current"] == 80
    assert progress["total"] == 80
    assert progress["percentage"] == 62
    assert "80 / 80" in progress["summary"]


def test_docx_appendix_materializing_heartbeat_reports_elapsed_wait() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-DOCX-HEARTBEAT"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> None:
            assert project_id == "PRJ-DOCX-HEARTBEAT"
            self.calls.append(kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-DOCX-HEARTBEAT")

    callback(
        "docx_appendix_materializing",
        {
            "title": "技术附表I",
            "current": 80,
            "total": 80,
            "heartbeat": True,
            "heartbeatIndex": 3,
            "elapsedSeconds": 45,
        },
    )

    progress = service.calls[-1]
    assert progress["phase_percent"] < 100
    assert "45" in progress["summary"]
    assert "45" in progress["event_message"]


def test_docx_appendix_scanning_progress_reports_waiting_heartbeat() -> None:
    class DummyParseService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def raise_if_parse_cancel_requested(self, project_id: str) -> None:
            assert project_id == "PRJ-DOCX-SCAN"

        def update_parse_progress(self, project_id: str, **kwargs: Any) -> None:
            assert project_id == "PRJ-DOCX-SCAN"
            self.calls.append(kwargs)

    service = DummyParseService()
    callback = _progress_callback(service, "PRJ-DOCX-SCAN")

    callback(
        "docx_appendix_scanning",
        {
            "fileName": "招标文件-技术规范.docx",
            "heartbeat": True,
            "heartbeatIndex": 2,
            "elapsedSeconds": 30,
        },
    )

    progress = service.calls[-1]
    assert progress["phase_key"] == "appendix"
    assert progress["percentage"] == 35
    assert progress["phase_percent"] > 0
    assert "30" in progress["summary"]
    assert "30" in progress["event_message"]
