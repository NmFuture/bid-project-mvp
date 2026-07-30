import ast
import asyncio
import copy
import json
import re
from base64 import b64encode
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from openpyxl import Workbook
from starlette.datastructures import URL

import app.services.technical_gap_service as technical_gap_service_module
import app.services.business_parse_assets as business_parse_assets_module
import app.services.technical_gap_actions as technical_gap_actions_module
import app.services.technical_gap_ai_fill as technical_gap_ai_fill_module
from app.services.bid_ocr_service import BidOcrService
from app.services.business_gap_repository import persist_business_gap_project, require_business_gap_project_for_update
from app.services.business_gap_service import business_gap_service
from app.services.file_utils import format_size_label, format_size_mb, safe_segment
from app.services.bid_document_state import (
    apply_business_document_format_to_project,
    apply_technical_document_format_to_project,
    final_document_state,
    force_save_document_state,
    save_document_content_state,
)
from app.services.bid_fill_generation_state import (
    format_duration,
    format_file_size,
    save_fill_generation_result_state,
    start_fill_generation_state,
)
from app.services.bid_fill_state import default_fill_state, fill_document_label, fill_task_label
from app.services.bid_outline_state import regenerated_outline_nodes
from app.services.bid_parse_state import (
    complete_parse_state,
    parse_progress_snapshot_state,
    source_file_type,
    start_parse_progress_state,
    update_parse_progress_state,
    update_template_files_state,
)
from app.services.bid_parse_service import _progress_callback
from app.services.bid_project_state import (
    create_project_state,
    normalize_project_identity_state,
    normalize_review_decision,
    normalize_template_fallback_state,
    project_list_state,
    project_parse_input_records,
    project_detail_state,
    project_stages_state,
    project_summary_state,
    project_template_fallback_context,
    update_project_state,
    update_stage_state,
    update_template_fallback_state,
)
from app.services.bid_runtime_state import ensure_project_runtime_states, now_iso, outline_nodes_from_toc_items, recover_parse_result
from app.services.technical_coverage import build_technical_coverage
from app.services.technical_gap_planner import _allowed_technical_material_index
from app.services.technical_appendix_source_matrix import load_appendix_source_matrix_for_project
from app.services.store import store
from app.services.business_gap_fact_table import (
    PROJECT_FACT_TABLE_SCHEMA_VERSION as BUSINESS_FACT_TABLE_SCHEMA_VERSION,
)
from app.services.technical_gap_fact_table import PROJECT_FACT_TABLE_SCHEMA_VERSION
from app.services.technical_gap_repository import persist_technical_gap_project, require_technical_gap_project_for_update
from app.services.technical_gap_review import (
    build_technical_review_document_content,
    build_technical_review_payload,
    confirm_technical_review,
    force_save_technical_review_document,
    prepare_technical_review_document,
    save_technical_review_document_content,
    technical_review_source_file_name,
)
from app.services.technical_gap_service import technical_gap_service
from app.services.technical_gap_state import ensure_technical_review_document_state
from app.services.peripheral import PeripheralError
from app.services.technical_material_store import technical_material_store


class _DummyRequest:
    base_url = URL("http://testserver/")
    url = URL("http://testserver/")


class _DummyOcrProjectService:
    bid_type = "商务标"

    @staticmethod
    def ensure_project(project_id: str) -> dict[str, Any]:
        return {
            "id": project_id,
            "name": "商务 OCR 项目",
            "projectCode": "BIZ-OCR-001",
            "customerName": "测试业主",
            "bidType": "商务标",
        }


def _seed_business_gap_project(plan: dict) -> str:
    store.reset_for_tests()
    project = store.create_project({"name": "商务标服务拆分测试项目", "customerName": "测试业主", "bidType": "商务标"})
    project_id = project["id"]
    record = store._require(project_id)
    record["business_gap_state"].update(
        {
            "recognitionStatus": "completed",
            "recognizedAt": now_iso(),
            "plan": plan,
            "integrity": {},
        }
    )
    store._persist_project(record)
    return project_id


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


def _seed_technical_gap_project(plan: dict) -> str:
    store.reset_for_tests()
    project = store.create_project({"name": "技术标服务拆分测试项目", "customerName": "测试业主", "bidType": "技术标"})
    project_id = project["id"]
    record = store._require(project_id)
    record["gap_state"].update(
        {
            "recognitionStatus": "completed",
            "recognizedAt": now_iso(),
            "plan": plan,
            "items": copy.deepcopy(plan.get("items") or []),
            "integrity": {},
            # build_facts 门控 seed：测试绕过实时表上传，直接注入小清单作为项目 specs
            "factSpecs": {
                "fileName": "测试实时表.xlsx",
                "uploadedAt": "2026-07-27T00:00:00",
                "specs": [
                    {
                        "seq": 1,
                        "key": "招标编号",
                        "label": "招标编号",
                        "reviewLabel": "",
                        "sourceFile": "",
                        "placeholder": "",
                        "note": "",
                        "needsConfirmation": False,
                        "referenceFile": "招标文件",
                        "valueRequired": True,
                        "sourceKind": "tender",
                        "aliases": [],
                    }
                ],
            },
        }
    )
    store._persist_project(record)
    return project_id


def test_technical_gap_review_rules_are_in_technical_modules() -> None:
    project = {"id": "PRJ-TECH-REVIEW", "name": "技术标评审测试项目", "bidType": "技术标"}
    gap_state = {
        "submittedForReview": True,
        "reviewConfirmed": False,
        "reviewedAt": "",
        "submissions": [{"missingId": "TG-1", "fileName": "方案.docx"}],
        "items": [
            {
                "id": "TG-1",
                "section": "技术方案",
                "title": "总体方案",
                "bidType": "技术标",
                "status": "resolved",
                "priority": "high",
                "resolvedSource": "方案.docx",
                "resolvedAt": "2026-05-25T00:00:00Z",
            },
            {
                "id": "TG-2",
                "section": "实施保障",
                "title": "施工组织",
                "bidType": "技术标",
                "status": "skipped",
                "priority": "medium",
                "skipReason": "无需补充",
            },
        ],
    }

    review_state = ensure_technical_review_document_state(project)
    payload = build_technical_review_payload(project, gap_state)
    content = build_technical_review_document_content(project, gap_state)
    prepared = prepare_technical_review_document(project, gap_state)
    saved = save_technical_review_document_content(project, "人工保存后的确认内容")
    forced = force_save_technical_review_document(project)
    confirmed = confirm_technical_review(project, gap_state)

    assert review_state["fileName"] == "技术标评审测试项目_缺口处理确认预览.docx"
    assert payload["status"] == "ready"
    assert payload["summary"] == {"total": 2, "resolvedCount": 1, "skippedCount": 1, "pendingCount": 0}
    assert payload["items"][0]["submission"]["fileName"] == "方案.docx"
    assert technical_review_source_file_name(gap_state) == "方案.docx"
    assert "已补录：1 项" in content
    assert "未补录：1 项" in content
    assert prepared["payload"]["parseStatus"] == "completed"
    assert saved["version"] == 2
    assert saved["content"] == "人工保存后的确认内容"
    assert forced["version"] == 3
    assert confirmed["reviewStatus"] == "confirmed"
    assert confirmed["payload"]["confirmed"] is True


def test_technical_gap_review_helpers_are_removed_from_store() -> None:
    source = Path("app/services/store.py").read_text(encoding="utf-8")
    review_source = Path("app/services/technical_gap_review.py").read_text(encoding="utf-8")
    state_source = Path("app/services/technical_gap_state.py").read_text(encoding="utf-8")
    assembly_source = Path("app/services/tech_assembly.py").read_text(encoding="utf-8")

    assert "from app.services.technical_gap_review import" not in source
    assert "from app.services.technical_gap_state import" not in source
    assert "def get_review_items" not in source
    assert "def prepare_review_document" not in source
    assert "def get_review_document_state" not in source
    assert "def save_review_document_content" not in source
    assert "def force_save_review_document" not in source
    assert "def confirm_review" not in source
    assert "def _ensure_gap_state" not in source
    assert "def _legacy_gap_items_from_plan" not in source
    assert "def _build_gap_detection_payload" not in source
    assert "def _default_review_document_state" not in source
    assert "def _find_gap_item" not in source
    assert "def _find_gap_plan_item" not in source
    assert "def _build_review_payload" not in source
    assert "请先在缺口处理页提交确认后再生成预览文档。" not in source
    assert "缺口处理确认预览已生成，可继续生成标书。" not in source
    assert "缺口处理已确认，可进入标书生成。" not in source
    assert "def _collect_outline_candidates" not in source
    assert "def _build_gap_items_from_outline" not in source
    assert "technical_gap_artifact_onlyoffice_payload" not in source
    assert "normalize_technical_gap_plan_fill_task_skills" not in source
    assert "def build_technical_review_payload" in review_source
    assert "def build_technical_review_document_content" in review_source
    assert "def prepare_technical_review_document" in review_source
    assert "def save_technical_review_document_content" in review_source
    assert "def force_save_technical_review_document" in review_source
    assert "def confirm_technical_review" in review_source
    assert "def ensure_technical_review_document_state" in state_source
    assert "build_technical_review_payload" not in assembly_source
    assert "ensure_technical_gap_state" in assembly_source
    assert "store.get_review_items" not in assembly_source
    assert "store._require(project_id).get(\"gap_state\")" not in assembly_source


def test_technical_coverage_rules_are_outside_store_and_delivery_service() -> None:
    project = {
        "outline_state": {
            "nodes": [
                {"id": "N-1", "title": "技术方案", "children": []},
                {"id": "N-2", "title": "实施保障", "children": []},
                {"id": "N-3", "title": "质量控制", "children": []},
            ]
        },
        "fill_state": {
            "sections": [
                {"nodeId": "N-1", "generationMode": "generated"},
                {"nodeId": "N-2", "generationMode": "generated_with_placeholder"},
            ]
        },
    }

    payload = build_technical_coverage(project)
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    delivery_source = Path("app/services/technical_delivery_service.py").read_text(encoding="utf-8")
    coverage_source = Path("app/services/technical_coverage.py").read_text(encoding="utf-8")

    assert payload["percentage"] == 50
    assert payload["fullCover"] == 1
    assert payload["partialCover"] == 1
    assert payload["noCover"] == 1
    assert payload["partialItems"][0]["id"] == "N-2"
    assert payload["noCoverItems"][0]["id"] == "N-3"
    assert "from app.services.technical_coverage import" not in store_source
    assert "def get_coverage" not in store_source
    assert "from app.services.store import store" not in delivery_source
    assert "store.get_coverage" not in delivery_source
    assert "build_technical_coverage(project)" in delivery_source
    assert "def _build_coverage_tree" not in store_source
    assert "def build_technical_coverage_tree" in coverage_source


def test_technical_gap_material_index_uses_technical_material_store() -> None:
    async def fake_raw_files(**kwargs):
        assert "bid_type" not in kwargs
        assert str(kwargs.get("folder_path") or "").startswith("技术标/")
        return {
            "items": [
                {
                    "id": "RAW-TECH-0001",
                    "name": "技术方案.docx",
                    "folderPath": "技术标/通用素材",
                    "materialTier": "standard",
                    "cleanStatus": "cleaned",
                    "hasCleanedWord": True,
                    "cleanedFileName": "技术方案.docx",
                }
            ],
            "total": 1,
        }

    material_scope = {
        "bidType": "技术标",
        "readableScopes": [
            {
                "path": "技术标/通用素材",
                "materialTier": "standard",
            }
        ],
    }

    with patch("app.services.technical_gap_planner.technical_material_store.raw_files", side_effect=fake_raw_files) as raw_files:
        items = _allowed_technical_material_index(material_scope, {"model": "WTG-1"})

    assert raw_files.call_count == 1
    assert items[0]["id"] == "RAW-TECH-0001"


def test_technical_gap_material_index_scopes_customer_and_project_by_identity() -> None:
    async def fake_raw_files(**kwargs):
        tier = str(kwargs.get("material_tier") or "")
        if tier == "standard":
            return {
                "items": [
                    {
                        "id": "RAW-STANDARD",
                        "name": "EW10.0-220 技术方案.docx",
                        "folderPath": "技术标/标准文件/EW10.0-220上置",
                        "materialTier": "standard",
                    }
                ],
                "total": 1,
            }
        if tier == "customer" and kwargs.get("customer_name") == "华能集团":
            return {
                "items": [
                    {
                        "id": "RAW-CUSTOMER",
                        "name": "与华能集团签署的战略合作协议.docx",
                        "folderPath": "技术标/客户定制/华能",
                        "materialTier": "customer",
                    }
                ],
                "total": 1,
            }
        if tier == "project" and kwargs.get("project_id") == "MATPRJ-001":
            return {
                "items": [
                    {
                        "id": "RAW-PROJECT",
                        "name": "项目风资源评估报告.docx",
                        "folderPath": "技术标/项目定制/项目全名/风资源评估报告",
                        "materialTier": "project",
                    }
                ],
                "total": 1,
            }
        return {"items": [], "total": 0}

    material_scope = {
        "bidType": "技术标",
        "readableScopes": [
            {
                "path": "技术标/标准文件",
                "materialTier": "standard",
            },
            {
                "path": "技术标/客户定制/华能集团",
                "materialTier": "customer",
                "customerName": "华能集团",
            },
            {
                "path": "技术标/项目定制/MATPRJ-001",
                "materialTier": "project",
                "projectId": "MATPRJ-001",
            },
        ],
    }

    with patch(
        "app.services.technical_gap_planner.technical_material_store.raw_files",
        side_effect=fake_raw_files,
    ) as raw_files:
        items = _allowed_technical_material_index(material_scope, {"model": "EW10.0-220上置"})

    assert [item["id"] for item in items] == ["RAW-STANDARD", "RAW-CUSTOMER", "RAW-PROJECT"]
    assert raw_files.call_args_list[0].kwargs["folder_path"] == "技术标/标准文件"
    assert raw_files.call_args_list[1].kwargs["folder_path"] == "技术标/客户定制"
    assert raw_files.call_args_list[1].kwargs["customer_name"] == "华能集团"
    assert raw_files.call_args_list[2].kwargs["folder_path"] == "技术标/项目定制"
    assert raw_files.call_args_list[2].kwargs["project_id"] == "MATPRJ-001"
    assert all(
        call.kwargs["turbine_model"]["model"] == "EW10.0-220上置"
        for call in raw_files.call_args_list
    )


def test_technical_material_raw_files_use_index_tags_as_source_of_truth() -> None:
    db_payload = {
        "items": [
            {
                "id": "RAW-0001",
                "name": "技术方案.docx",
                "folderPath": "技术标/通用素材/施工组织",
                "bidType": "技术标",
                "tags": ["DB标签"],
            },
            {
                "id": "RAW-0002",
                "name": "吊装方案.docx",
                "folderPath": "技术标/通用素材/施工组织",
                "bidType": "技术标",
                "tags": ["数据库旧标签"],
            },
        ],
        "total": 2,
        "page": 1,
        "pageSize": 100000,
        "tagOptions": ["DB标签", "数据库旧标签"],
    }
    index_tags = {
        "RAW-0001": ["索引标签", "施工"],
        "RAW-0002": ["吊装"],
    }

    async def run_case() -> dict[str, Any]:
        with patch("app.services.technical_material_store.material_store.raw_files", AsyncMock(return_value=db_payload)) as raw_files, patch(
            "app.services.technical_material_index.load_technical_material_index",
            return_value={"schemaVersion": 2, "tiers": []},
        ), patch(
            "app.services.technical_material_index.file_tags_by_id",
            return_value=index_tags,
        ):
            payload = await technical_material_store.raw_files(
                folder_path="技术标/通用素材",
                tag=["索引"],
                page=1,
                page_size=20,
            )
        raw_files.assert_awaited_once()
        return payload

    payload = asyncio.run(run_case())
    assert [item["id"] for item in payload["items"]] == ["RAW-0001"]
    assert payload["items"][0]["tags"] == ["索引标签", "施工"]
    assert payload["tagOptions"] == ["索引标签", "施工", "吊装"]


def test_technical_gap_service_uses_technical_action_boundary() -> None:
    source = Path(technical_gap_service_module.__file__).read_text(encoding="utf-8")

    assert "from app.services.gap_planning import" not in source
    assert "app.services.gap_planning" not in source


def test_technical_gap_actions_own_upload_and_select_logic() -> None:
    source = Path(technical_gap_actions_module.__file__).read_text(encoding="utf-8")
    ai_source = Path(technical_gap_ai_fill_module.__file__).read_text(encoding="utf-8")
    planner_source = Path("app/services/technical_gap_planner.py").read_text(encoding="utf-8")
    domain_source = Path("app/services/technical_gap_domain.py").read_text(encoding="utf-8")
    state_source = Path("app/services/technical_gap_state.py").read_text(encoding="utf-8")
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")

    assert "register_manual_gap_upload" not in source
    assert "prepare_existing_gap_material_files" not in source
    assert "register_existing_gap_material" not in source
    assert "run_ai_fill_for_gap" not in source.replace("run_technical_ai_fill_for_gap", "")
    assert "app.services.gap_planning" not in source
    assert "app.services.gap_planning" not in ai_source
    assert "app.services.gap_planning" not in planner_source
    assert "app.services.gap_planning" not in domain_source
    assert "app.services.gap_planning" not in state_source
    assert "app.services.gap_planning" not in store_source
    assert not Path("app/services/gap_planning.py").exists()


def test_business_gap_services_do_not_import_technical_gap_planning() -> None:
    for path in [
        "app/services/business_gap_domain.py",
        "app/services/business_gap_fact_table.py",
        "app/services/business_gap_service.py",
        "app/services/business_gap_table_fill.py",
    ]:
        source = Path(path).read_text(encoding="utf-8")
        assert "from app.services.gap_planning import" not in source
        assert "app.services.gap_planning" not in source


def test_technical_gap_service_uses_technical_fact_table_boundary() -> None:
    source = Path(technical_gap_service_module.__file__).read_text(encoding="utf-8")
    fact_source = Path("app/services/technical_gap_fact_table.py").read_text(encoding="utf-8")
    business_fact_source = Path("app/services/business_gap_fact_table.py").read_text(encoding="utf-8")

    assert "app.services.business_gap_fact_table" not in source
    assert "app.services.technical_gap_fact_table" in source
    assert "business_material_store" not in fact_source
    assert "technical_material_store" not in business_fact_source
    assert "businessGapTask" not in fact_source
    assert "商务待填写字段" not in fact_source
    assert "business_fact_labels_from_task" not in fact_source
    assert "technicalGapTask" in fact_source
    assert "技术待填写字段" in fact_source


def test_business_assembly_does_not_own_technical_formatting() -> None:
    source = Path("app/services/business_assembly.py").read_text(encoding="utf-8")
    document_source = Path("app/services/bid_document_flow.py").read_text(encoding="utf-8")
    business_document_source = Path("app/services/business_document_service.py").read_text(encoding="utf-8")
    technical_document_source = Path("app/services/technical_document_service.py").read_text(encoding="utf-8")

    assert "apply_technical_document_format_preset" not in source
    assert "TECH_FORMAT_PRESETS" not in source
    assert "technical_workspace_stage_dir" not in source
    assert "app.services.technical_document_format" not in document_source
    assert "app.services.business_assembly" not in document_source
    assert "app.services.business_document_editing" not in document_source
    assert "OpencodeClient" not in document_source
    assert "BusinessDocumentService" not in document_source
    assert "app.services.business_assembly" in business_document_source
    assert "app.services.business_document_editing" in business_document_source
    assert "OpencodeClient" in business_document_source
    assert "apply_technical_document_format_preset" not in business_document_source
    assert "TECH_FORMAT_PRESETS" not in business_document_source
    assert "app.services.technical_document_format" in technical_document_source
    assert "apply_technical_document_format_preset" in technical_document_source
    assert "app.services.business_assembly" not in technical_document_source
    assert "app.services.business_document_editing" not in technical_document_source
    assert "OpencodeClient" not in technical_document_source


def test_business_and_technical_document_format_state_rules_are_split() -> None:
    business_project = {
        "id": "BIZ-DOC",
        "document_state": {"version": 1, "onlyoffice": {}},
        "fill_state": {},
    }
    technical_project = {
        "id": "TECH-DOC",
        "document_state": {"version": 2, "onlyoffice": {}},
        "fill_state": {},
    }

    business_state = apply_business_document_format_to_project(
        business_project,
        {"preset": "formal", "label": "商务正式版", "summary": {"changed": 2}},
        updated_at="2026-05-25T00:00:00Z",
    )
    technical_state = apply_technical_document_format_to_project(
        technical_project,
        {"preset": "technical", "label": "技术正式版", "summary": {"changed": 3}},
        updated_at="2026-05-25T00:01:00Z",
    )
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    document_state_source = Path("app/services/bid_document_state.py").read_text(encoding="utf-8")
    business_state_source = Path("app/services/business_document_state.py").read_text(encoding="utf-8")
    technical_state_source = Path("app/services/technical_document_state.py").read_text(encoding="utf-8")

    assert business_state["version"] == 2
    assert business_state["businessFormatPreset"] == "formal"
    assert business_project["fill_state"]["lastBusinessFormat"]["label"] == "商务正式版"
    assert technical_state["version"] == 3
    assert technical_state["technicalFormatPreset"] == "technical"
    assert technical_project["fill_state"]["lastTechnicalFormat"]["label"] == "技术正式版"
    assert "from app.services.business_document_state" not in store_source
    assert "from app.services.technical_document_state" not in store_source
    assert "from app.services.bid_document_state import" not in store_source
    assert "apply_business_document_format_state" not in store_source
    assert "apply_technical_document_format_state" not in store_source
    assert "def apply_business_document_format(" not in store_source
    assert "def apply_technical_document_format(" not in store_source
    assert '"businessFormatPreset"' not in store_source
    assert '"technicalFormatPreset"' not in store_source
    assert '"lastBusinessFormat"' not in store_source
    assert '"lastTechnicalFormat"' not in store_source
    assert "from app.services.business_document_state import apply_business_document_format_state" in document_state_source
    assert "from app.services.technical_document_state import apply_technical_document_format_state" in document_state_source
    assert '"businessFormatPreset"' in business_state_source
    assert '"technicalFormatPreset"' in technical_state_source


def test_bid_document_state_rules_are_outside_store() -> None:
    project = {
        "id": "PRJ-DOC-STATE",
        "document_state": {
            "fileName": "文档状态测试_正文.docx",
            "fileType": "docx",
            "version": 1,
            "lastSavedAt": "",
            "fallback": {"content": ""},
            "onlyoffice": {"documentKey": "PRJ-DOC-STATE-v1"},
        },
    }

    saved = save_document_content_state(project, "PRJ-DOC-STATE", "# 新正文")
    forced = force_save_document_state(project, "PRJ-DOC-STATE")
    final_payload = final_document_state(project)
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    document_state_source = Path("app/services/bid_document_state.py").read_text(encoding="utf-8")

    assert saved["version"] == 2
    assert saved["fallback"]["content"] == "# 新正文"
    assert saved["onlyoffice"]["documentKey"] == "PRJ-DOC-STATE-v2"
    assert forced["version"] == 3
    assert forced["onlyoffice"]["documentKey"] == "PRJ-DOC-STATE-v3"
    assert final_payload["ready"] is True
    assert final_payload["fileName"] == "文档状态测试_正文.docx"
    assert "from app.services.bid_document_state import" not in store_source
    assert "def get_document_state(" not in store_source
    assert "def save_document_content(" not in store_source
    assert "def force_save_document(" not in store_source
    assert "def get_final_document(" not in store_source
    assert "save_document_content_state(project, project_id, content)" not in store_source
    assert "force_save_document_state(project, project_id)" not in store_source
    assert "return final_document_state(self._require(project_id))" not in store_source
    assert "def save_document_content_state" in document_state_source
    assert "def force_save_document_state" in document_state_source
    assert "def final_document_state" in document_state_source
    assert "state[\"onlyoffice\"][\"documentKey\"] = f\"{project_id}-v{next_version}\"" not in store_source


def test_bid_fill_state_labels_are_outside_store() -> None:
    business_state = default_fill_state({"bidType": "商务标"})
    technical_state = default_fill_state({"bidType": "技术标"})
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    fill_source = Path("app/services/bid_fill_state.py").read_text(encoding="utf-8")
    runtime_source = Path("app/services/bid_runtime_state.py").read_text(encoding="utf-8")

    assert fill_document_label({"bidType": "商务标"}) == "商务标正文"
    assert fill_task_label({"bidType": "技术标"}) == "组装技术标正文"
    for call in (fill_task_label, fill_document_label, default_fill_state):
        try:
            call({})
        except ValueError:
            pass
        else:
            raise AssertionError(f"{call.__name__} should require explicit bidType")
    assert business_state["tasks"][1]["label"] == "调用商务标正文拼装 skill"
    assert technical_state["tasks"][1]["label"] == "组装技术标正文"
    assert "def fill_task_label" not in store_source
    assert "def fill_document_label" not in store_source
    assert "def default_fill_tasks" not in store_source
    assert "def default_fill_state" not in store_source
    assert "from app.services.bid_fill_state import" not in store_source
    assert "from app.services.bid_fill_state import default_fill_state, default_fill_tasks" in runtime_source
    assert "def fill_task_label" in fill_source
    assert "def default_fill_state" in fill_source
    assert "or TECHNICAL_BID_TYPE" not in fill_source


def test_bid_fill_generation_state_rules_are_outside_store() -> None:
    business_project = {
        "id": "PRJ-BIZ-FILL",
        "name": "商务正文项目",
        "bidType": "商务标",
        "document_state": {"version": 1, "lastSavedAt": "", "fallback": {}, "onlyoffice": {}},
    }
    technical_project = {"id": "PRJ-TECH-FILL", "name": "技术正文项目", "bidType": "技术标"}

    business_running = start_fill_generation_state(business_project)
    technical_running = start_fill_generation_state(technical_project)
    business_saved = save_fill_generation_result_state(
        business_project,
        project_id="PRJ-BIZ-FILL",
        summary="商务标正文拼装完成。",
        sections=[{"nodeId": "BIZ-1", "title": "商务响应", "generationMode": "generated"}],
        content="# 商务响应\n\n已拼装。",
        filled_at="2026-05-25T00:00:00Z",
        run_duration_sec=75,
        file_size_bytes=1536,
    )
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    generation_source = Path("app/services/bid_fill_generation_state.py").read_text(encoding="utf-8")

    assert business_running["summary"].startswith("已开始拼装商务标正文")
    assert business_running["tasks"][1]["label"] == "调用商务标正文拼装 skill"
    assert technical_running["summary"].startswith("已开始拼装技术标正文")
    assert technical_running["tasks"][1]["label"] == "组装技术标正文"
    assert business_saved["runDuration"] == "1分15秒"
    assert business_saved["output"]["size"] == "1.5 KB"
    assert business_saved["events"][-1]["message"] == "商务标正文拼装完成，已输出 1 个目录章节。"
    assert business_project["document_state"]["onlyoffice"]["documentKey"] == "PRJ-BIZ-FILL-v1"
    assert format_duration(5) == "5秒"
    assert format_file_size(2 * 1024 * 1024) == "2.0 MB"
    assert "from app.services.bid_fill_generation_state import" not in store_source
    assert "start_fill_generation_state(project)" not in store_source
    assert "save_fill_generation_result_state(" not in store_source
    assert "complete_fill_generation_state(project" not in store_source
    assert "def complete_fill_generation(" not in store_source
    assert "def start_fill_generation(" not in store_source
    assert "def update_fill_generation_state(" not in store_source
    assert "def fail_fill_generation(" not in store_source
    assert "def save_fill_generation_result(" not in store_source
    assert "def start_fill_generation_state" in generation_source
    assert "def update_fill_generation_state" in generation_source
    assert "def fail_fill_generation_state" in generation_source
    assert "def complete_fill_generation_state" in generation_source
    assert "def save_fill_generation_result_state" in generation_source
    assert "def _format_duration" not in store_source
    assert "def _format_file_size" not in store_source
    assert "已开始拼装{document_label}" not in store_source
    assert "已输出 {len(sections)} 个目录章节" not in store_source


def test_bid_runtime_recovery_rules_are_outside_store() -> None:
    nodes = outline_nodes_from_toc_items(
        [
            {"level": 1, "title": "商务响应", "number": "一、", "source_refs": [{"file": "toc.docx"}]},
            {"level": 2, "title": "授权文件", "number": "1.1", "material_refs": [{"id": "MAT-1"}]},
        ]
    )
    project = {"id": "PRJ-NO-WORKSPACE", "name": "无工作区项目", "bidType": "商务标"}
    try:
        recover_parse_result({"id": "PRJ-MISSING-BID-TYPE", "name": "缺标类运行态项目"})
    except ValueError:
        pass
    else:
        raise AssertionError("recover_parse_result should require explicit bidType")
    try:
        ensure_project_runtime_states({"id": "PRJ-MISSING-BID-TYPE", "name": "缺标类运行态项目"})
    except ValueError:
        pass
    else:
        raise AssertionError("ensure_project_runtime_states should require explicit bidType")
    recovered_empty = recover_parse_result(project)
    recovered_project = ensure_project_runtime_states(project)
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    runtime_source = Path("app/services/bid_runtime_state.py").read_text(encoding="utf-8")

    assert nodes[0]["tocNumber"] == "一、"
    assert nodes[0]["children"][0]["tocNumber"] == "1.1"
    assert nodes[0]["sourceRefs"][0]["file"] == "toc.docx"
    assert nodes[0]["children"][0]["materialRefs"][0]["id"] == "MAT-1"
    assert recovered_empty["status"] == "idle"
    assert recovered_empty["project"]["id"] == "PRJ-NO-WORKSPACE"
    assert recovered_project["parse_result"]["status"] == "idle"
    assert recovered_project["directory_state"]["status"] == "idle"
    assert recovered_project["outline_state"]["reviewStatus"] == "draft"
    assert recovered_project["fill_state"]["tasks"][1]["label"] == "调用商务标正文拼装 skill"
    assert recovered_project["document_state"]["documentId"] == "DOC-PRJ-NO-WORKSPACE"
    assert "from app.services.bid_runtime_state import" in store_source
    assert "now_iso as runtime_now_iso" not in store_source
    assert "return ensure_project_runtime_states(project)" in store_source
    assert "def now_iso" not in store_source
    assert "from app.services.store import now_iso" not in store_source
    assert "from app.services.bid_fill_state import default_fill_state" not in store_source
    assert "from app.services.bid_parse_state import default_parse_progress" not in store_source
    assert "from app.services.bid_project_state import default_document_state" not in store_source
    assert "def _recover_parse_result" not in store_source
    assert "def _recover_parse_storage" not in store_source
    assert "def _recover_directory_state" not in store_source
    assert "def _recover_outline_state" not in store_source
    assert "def _outline_nodes_from_toc_items" not in store_source
    assert "business-workspace" not in store_source
    assert "technical-workspace" not in store_source
    assert "workspace_parse_dir" not in store_source
    assert "def recover_parse_result" in runtime_source
    assert "def recover_directory_state" in runtime_source
    assert "def ensure_project_runtime_states" in runtime_source
    assert "def now_iso" in runtime_source
    assert "def outline_nodes_from_toc_items" in runtime_source
    assert "business_workspace_dir" in runtime_source
    assert "technical-workspace" in runtime_source


def test_technical_runtime_can_recover_directory_from_existing_toc(tmp_path, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "documents_dir", tmp_path)
    toc_path = tmp_path / "PRJ-TECH-TOC" / "technical-workspace" / "s2_toc_workdir" / "toc.json"
    toc_path.parent.mkdir(parents=True)
    toc_path.write_text(
        json.dumps(
            {
                "generatedAt": "2026-05-26T00:00:00Z",
                "items": [
                    {"level": 1, "title": "技术方案", "number": "1"},
                    {"level": 2, "title": "风机参数", "number": "1.1"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    recovered = ensure_project_runtime_states(
        {"id": "PRJ-TECH-TOC", "name": "技术目录恢复项目", "bidType": "技术标"}
    )

    assert recovered["directory_state"]["status"] == "completed"
    assert recovered["directory_state"]["opencodeOutput"]["tocJsonPath"] == str(toc_path)
    assert recovered["directory_state"]["summary"] == "已从技术标 S2 目录产物恢复目录状态。"
    assert recovered["outline_state"]["reviewStatus"] == "confirmed"
    assert recovered["outline_state"]["nodes"][0]["title"] == "技术方案"
    assert recovered["outline_state"]["nodes"][0]["children"][0]["title"] == "风机参数"
    assert recovered["outline_state"]["recoveredFrom"] == str(toc_path)


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
    assert latest_event == "结构化解析仍在执行，已执行 4 分 21 秒。"
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


def test_bid_outline_state_rules_are_outside_store() -> None:
    business_nodes = regenerated_outline_nodes(
        {
            "id": "PRJ-BIZ",
            "name": "商务目录项目",
            "bidType": "商务标",
            "outline_state": {"nodes": [{"id": "BIZ-1", "title": "商务响应文件", "children": []}]},
        }
    )
    technical_nodes = regenerated_outline_nodes({"id": "PRJ-TECH", "name": "技术目录项目", "bidType": "技术标"})
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    outline_source = Path("app/services/bid_outline_state.py").read_text(encoding="utf-8")

    assert business_nodes[0]["title"] == "商务响应文件"
    assert not any(node["title"] == "技术方案" for node in business_nodes)
    assert any(node["title"] == "技术方案" for node in technical_nodes)
    assert "from app.services.bid_outline_state import" not in store_source
    assert "def complete_directory_generation_state" in outline_source
    assert "def update_directory_generation_state" in outline_source
    assert "def save_generated_outline_state" in outline_source
    assert "def save_outline_state" in outline_source
    assert "def load_directory_rule_evidence" in outline_source
    assert "def regenerate_outline_state" in outline_source
    assert "def confirm_outline_state" in outline_source
    assert "def regenerated_outline_nodes" in outline_source
    assert "outline_nodes_from_directory_toc" in outline_source
    assert "def _load_directory_rule_evidence" not in store_source
    assert "def _regenerated_outline_nodes" not in store_source
    assert "complete_directory_generation_state(project" not in store_source
    assert "def complete_directory_generation(" not in store_source
    assert "def save_generated_outline(" not in store_source
    assert "def save_outline(" not in store_source
    assert "def regenerate_outline(" not in store_source
    assert "def confirm_outline(" not in store_source
    assert "def start_fill_generation(" not in store_source
    assert "def update_fill_generation_state(" not in store_source
    assert "def fail_fill_generation(" not in store_source
    assert "def save_fill_generation_result(" not in store_source
    assert "def get_template_fallback(" not in store_source
    assert "outline_nodes_from_directory_toc" not in store_source
    assert "f\"目录生成完成，已输出 {len(nodes)} 个一级章节。\"" not in store_source


def test_draft_generation_uses_workspace_specific_modules() -> None:
    generation_source = Path("app/services/bid_generation_flow.py").read_text(encoding="utf-8")
    tech_assembly_source = Path("app/services/tech_assembly.py").read_text(encoding="utf-8")
    technical_draft_source = Path("app/services/technical_draft_generation.py").read_text(encoding="utf-8")

    assert not Path("app/services/draft_generation.py").exists()
    assert "app.services.draft_generation" not in generation_source
    assert "app.services.business_draft_generation" in generation_source
    assert "app.services.technical_draft_generation" in generation_source
    assert "from app.services.bid_type import" in generation_source
    assert "normalize_bid_type" not in generation_source
    assert 'if bid_type == "商务标"' not in generation_source
    assert "store.get_project(" not in generation_source
    assert "_draft_generator_for_bid_type" in generation_source
    assert "技术标生成标书仅支持技术标项目" in tech_assembly_source
    assert "from app.services.store import store" not in technical_draft_source
    assert "normalize_bid_type" not in technical_draft_source
    assert "get_workspace_project_runtime_state(" in technical_draft_source


def test_business_and_technical_routes_import_workspace_flow_services() -> None:
    business_route_source = Path("app/api/routes/business.py").read_text(encoding="utf-8")
    technical_route_source = Path("app/api/routes/technical.py").read_text(encoding="utf-8")
    old_flow_path = Path("app/services/bid_flow_service.py")
    business_directory_source = Path("app/services/business_directory_service.py").read_text(encoding="utf-8")
    technical_directory_source = Path("app/services/technical_directory_service.py").read_text(encoding="utf-8")
    business_generation_source = Path("app/services/business_generation_service.py").read_text(encoding="utf-8")
    technical_generation_source = Path("app/services/technical_generation_service.py").read_text(encoding="utf-8")
    business_document_source = Path("app/services/business_document_service.py").read_text(encoding="utf-8")
    technical_document_source = Path("app/services/technical_document_service.py").read_text(encoding="utf-8")

    assert not old_flow_path.exists()
    assert "app.services.bid_flow_service import" not in business_route_source
    assert "app.services.bid_flow_service import" not in technical_route_source
    assert "app.services.business_directory_service" in business_route_source
    assert "app.services.business_generation_service" in business_route_source
    assert "app.services.business_document_service" in business_route_source
    assert "app.services.technical_directory_service" in technical_route_source
    assert "app.services.technical_generation_service" in technical_route_source
    assert "app.services.technical_document_service" in technical_route_source
    assert "/document/business-format" in business_route_source
    assert "/document/technical-format" in technical_route_source
    assert "app.services.bid_directory_flow" in business_directory_source
    assert "app.services.bid_directory_flow" in technical_directory_source
    assert "app.services.bid_generation_flow" in business_generation_source
    assert "app.services.bid_generation_flow" in technical_generation_source
    assert "app.services.bid_document_flow" in business_document_source
    assert "app.services.bid_document_flow" in technical_document_source
    assert "class BusinessDocumentService" in business_document_source
    assert "class TechnicalDocumentService" in technical_document_source


def test_project_delete_uses_workspace_material_store_facades() -> None:
    store.reset_for_tests()
    business_project_id = store.create_project(
        {"name": "商务标删除项目素材测试", "customerName": "测试业主", "bidType": "商务标"}
    )["id"]
    technical_project_id = store.create_project(
        {"name": "技术标删除项目素材测试", "customerName": "测试业主", "bidType": "技术标"}
    )["id"]
    business_deleted: list[str] = []
    technical_deleted: list[str] = []

    async def fake_business_delete(path: str, *, expected_project_id: str = "") -> dict[str, object]:
        assert expected_project_id == business_project_id
        business_deleted.append(path)
        return {"message": "business deleted", "folderPath": path}

    async def fake_technical_delete(path: str, *, expected_project_id: str = "") -> dict[str, object]:
        assert expected_project_id == technical_project_id
        technical_deleted.append(path)
        return {"message": "technical deleted", "folderPath": path}

    with patch(
        "app.services.business_material_store.business_material_store.raw_cleanup_project_folder",
        side_effect=fake_business_delete,
    ), patch(
        "app.services.technical_material_store.technical_material_store.raw_cleanup_project_folder",
        side_effect=fake_technical_delete,
    ):
        store.delete_project(business_project_id)
        store.delete_project(technical_project_id)

    assert business_deleted == [f"商务标/项目素材/{business_project_id}"]
    assert technical_deleted == ["技术标/项目定制/技术标删除项目素材测试"]


def test_project_material_cleanup_facades_only_accept_project_roots() -> None:
    from app.services.business_material_store import business_material_store
    from app.services.technical_material_store import technical_material_store

    business_calls: list[dict[str, str]] = []
    technical_calls: list[dict[str, str]] = []

    async def fake_business_cleanup(path: str, *, bid_type: str) -> dict[str, object]:
        business_calls.append({"path": path, "bidType": bid_type})
        return {"message": "business cleanup", "folderPath": path}

    async def fake_technical_cleanup(path: str, *, bid_type: str) -> dict[str, object]:
        technical_calls.append({"path": path, "bidType": bid_type})
        return {"message": "technical cleanup", "folderPath": path}

    with patch("app.services.business_material_store.material_store.raw_cleanup_project_folder", side_effect=fake_business_cleanup):
        payload = asyncio.run(business_material_store.raw_cleanup_project_folder("商务标/项目素材/BIZ-001"))
    assert payload["folderPath"] == "商务标/项目素材/BIZ-001"
    assert business_calls == [{"path": "商务标/项目素材/BIZ-001", "bidType": "商务标"}]

    with patch("app.services.technical_material_store.material_store.raw_cleanup_project_folder", side_effect=fake_technical_cleanup):
        payload = asyncio.run(technical_material_store.raw_cleanup_project_folder("技术标/项目素材/TECH-001"))
    assert payload["folderPath"] == "技术标/项目素材/TECH-001"
    assert technical_calls == [{"path": "技术标/项目素材/TECH-001", "bidType": "技术标"}]

    for invalid_path in ("商务标/通用素材", "商务标/项目素材", "商务标/项目素材/BIZ-001/项目商务响应文件"):
        try:
            asyncio.run(business_material_store.raw_cleanup_project_folder(invalid_path))
        except PeripheralError as exc:
            assert exc.code == "PROJECT_MATERIAL_PATH_REQUIRED"
        else:
            raise AssertionError(f"expected PeripheralError for {invalid_path}")

    for invalid_path in ("技术标/通用素材", "技术标/项目素材", "技术标/项目素材/TECH-001/子目录"):
        try:
            asyncio.run(technical_material_store.raw_cleanup_project_folder(invalid_path))
        except PeripheralError as exc:
            assert exc.code == "PROJECT_MATERIAL_PATH_REQUIRED"
        else:
            raise AssertionError(f"expected PeripheralError for {invalid_path}")


def test_bid_project_state_rules_are_outside_store() -> None:
    try:
        create_project_state("PRJ-MISSING-BID-TYPE", {"name": "缺标类项目"})
    except ValueError:
        pass
    else:
        raise AssertionError("create_project_state should require explicit bidType")

    project = create_project_state(
        "PRJ-BIZ-STATE",
        {
            "name": "商务项目状态测试",
            "customerName": "测试业主",
            "bidType": "商务标",
            "reviewDecision": "unknown",
            "appendixSourceMatrixPath": "/data/documents/_config/initial.xlsx",
        },
    )
    participating_project = create_project_state(
        "PRJ-BIZ-PARTICIPATE",
        {
            "name": "商务参与项目",
            "customerName": "测试业主",
            "bidType": "商务标",
            "reviewDecision": "participate",
        },
    )
    update_project_state(
        project,
        "PRJ-BIZ-STATE",
        {
            "projectCode": "BIZ-STATE-001",
            "deadline": "2026-06-30",
            "reviewDecision": "abandon",
            "reviewComment": "暂不参与",
            "appendixSourceMatrixPath": "/data/documents/_config/technical_appendix_source_matrix.xlsx",
            "technicalAppendixSourceMatrix": {"path": "/data/documents/_config/technical_appendix_source_matrix.xlsx"},
        },
    )
    try:
        update_project_state(project, "PRJ-BIZ-STATE", {"bidType": ""})
    except ValueError:
        pass
    else:
        raise AssertionError("update_project_state should reject missing bidType")
    normalize_project_identity_state(project)
    fallback_before = normalize_template_fallback_state(project)
    update_template_fallback_state(project, {"enabled": False, "sourceId": "business-template"})
    project["templateFileRecords"] = [{"name": "项目模板.docx"}]
    file_records, template_records = project_parse_input_records("PRJ-BIZ-STATE", project)
    fallback_context = project_template_fallback_context("PRJ-BIZ-STATE", project)
    stage_payload = update_stage_state(project, 3, {"status": "active"})
    stages_payload = project_stages_state(project)
    list_payload = project_list_state([project], bid_type="商务标", page=1, page_size=10)
    participate_list_payload = project_list_state(
        [project, participating_project],
        bid_type="商务标",
        review_decision="participate",
        page=1,
        page_size=10,
    )
    summary = project_summary_state(project)
    detail = project_detail_state(project)
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    state_source = Path("app/services/bid_project_state.py").read_text(encoding="utf-8")

    assert normalize_review_decision("bad-value") == "pending"
    assert project["bidType"] == "商务标"
    assert project["fill_state"]["tasks"][1]["label"] == "调用商务标正文拼装 skill"
    assert project["document_state"]["fileName"] == "商务项目状态测试_正文.docx"
    assert project["business_gap_state"]["recognitionStatus"] == "idle"
    assert project["projectCode"] == "BIZ-STATE-001"
    assert project["endDate"] == "2026-06-30"
    assert project["reviewDecision"] == "abandon"
    assert project["reviewComment"] == "暂不参与"
    assert project["appendixSourceMatrixPath"] == "/data/documents/_config/technical_appendix_source_matrix.xlsx"
    assert project["identity"]["projectCode"] == "BIZ-STATE-001"
    assert fallback_before == {"enabled": True, "sourceId": "system-default"}
    assert project["templateFallback"] == {"enabled": False, "sourceId": "business-template"}
    assert file_records == []
    assert template_records == [{"name": "项目模板.docx"}]
    assert fallback_context == {
        "projectId": "PRJ-BIZ-STATE",
        "bidType": "商务标",
        "enabled": False,
        "sourceId": "business-template",
        "hasProjectTemplate": True,
    }
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["id"] == "PRJ-BIZ-STATE"
    assert participate_list_payload["total"] == 1
    assert participate_list_payload["items"][0]["id"] == "PRJ-BIZ-PARTICIPATE"
    assert [stage["name"] for stage in stages_payload] == ["模板与目录", "审核目录", "素材匹配", "共创导出"]
    assert stage_payload["stageLabel"] == "素材匹配"
    assert summary["stageLabel"] == "审核终止"
    assert summary["reviewDecisionLabel"] == "不参与"
    assert detail["templateFallback"] == {"enabled": False, "sourceId": "business-template"}
    assert detail["appendixSourceMatrixPath"] == "/data/documents/_config/technical_appendix_source_matrix.xlsx"
    assert detail["technicalAppendixSourceMatrix"] == {
        "path": "/data/documents/_config/technical_appendix_source_matrix.xlsx"
    }
    assert "from app.services.bid_project_state import" in store_source
    assert "create_project_state(project_id, data)" in store_source
    assert "update_project_state(project, project_id, data)" in store_source
    assert "delete_project_side_effects(project_id, project)" in store_source
    assert "return project_detail_state(project)" in store_source
    assert "project_list_state(" in store_source
    assert "def create_project_state" in state_source
    assert "def update_project_state" in state_source
    assert "def project_summary_state" in state_source
    assert "def project_list_state" in state_source
    assert "def project_stages_state" in state_source
    assert "def project_detail_state" in state_source
    assert "def project_parse_input_records" in state_source
    assert "def project_template_fallback_context" in state_source
    assert "def project_template_fallback_payload" in state_source
    assert "def update_stage_state" in state_source
    assert "def delete_project_material_folder" in state_source
    assert "def create_project_state" not in store_source
    assert "build_project_identity(project)" not in store_source
    assert "project_turbine_model(project)" not in store_source
    assert "def _summary" not in store_source
    assert "def _normalize_template_fallback" not in store_source
    assert "def template_fallback_context(" not in store_source
    assert "def update_template_fallback(" not in store_source
    assert "items.sort(key=lambda item: item[\"updatedAt\"], reverse=True)" not in store_source
    assert "from app.services.project_stage_flow import" not in store_source
    assert "project_progress_stages(project)" not in store_source
    assert "from app.services.template_store" not in store_source
    assert "resolve_fallback_bid_template_file_sync" not in store_source
    assert "asyncio.run(" not in store_source
    assert '"business_gap_state": {' not in store_source
    assert "promote_parse_artifacts_to_workspace" not in store_source


def test_bid_project_persistence_is_outside_store() -> None:
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    repository_source = Path("app/services/bid_project_repository.py").read_text(encoding="utf-8")

    assert "from app.services.bid_project_repository import ProjectStateRepository" in store_source
    assert "ProjectStateRepository(self._storage_backend)" in store_source
    assert "import psycopg" not in store_source
    assert "from psycopg" not in store_source
    assert "Jsonb(" not in store_source
    assert "CREATE TABLE IF NOT EXISTS projects" not in store_source
    assert "SELECT id, payload FROM projects" not in store_source
    assert "INSERT INTO projects" not in store_source
    assert "DELETE FROM projects" not in store_source
    assert "class ProjectStateRepository" in repository_source
    assert "import psycopg" in repository_source
    assert "Jsonb(" in repository_source
    assert "CREATE TABLE IF NOT EXISTS projects" in repository_source
    assert "SELECT id, payload FROM projects" in repository_source
    assert "INSERT INTO projects" in repository_source
    assert "DELETE FROM projects" in repository_source


def test_technical_appendix_source_matrix_uses_default_documents_config(tmp_path, monkeypatch) -> None:
    from app.core.config import settings

    config_dir = tmp_path / "_config"
    config_dir.mkdir(parents=True)
    matrix_path = config_dir / "technical_appendix_source_matrix.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "来源矩阵"
    sheet.append(["客户", "表格", "项目定制", "标准文件", "其他"])
    sheet.append(["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""])
    workbook.save(matrix_path)

    override_path = tmp_path / "override.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["客户", "表格", "项目定制", "标准文件", "其他"])
    sheet.append(["华能", "附表D.1-D.6", "功率曲线", "", ""])
    workbook.save(override_path)

    monkeypatch.setattr(settings, "documents_dir", tmp_path)

    default_matrix = load_appendix_source_matrix_for_project({"customerName": "华能集团"})
    assert default_matrix["path"] == str(matrix_path)
    assert default_matrix["rows"][0]["customer"] == "华能"
    assert default_matrix["rows"][0]["standardSources"] == ["机型参数表"]

    project_matrix = load_appendix_source_matrix_for_project(
        {
            "customerName": "华能集团",
            "appendixSourceMatrixPath": str(override_path),
        }
    )
    assert project_matrix["path"] == str(override_path)
    assert project_matrix["rows"][0]["projectSources"] == ["功率曲线"]


def test_services_use_public_project_state_mutation_api() -> None:
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    workspace_access_source = Path("app/services/workspace_project_access.py").read_text(encoding="utf-8")
    service_sources = {
        path: path.read_text(encoding="utf-8")
        for path in Path("app/services").glob("*.py")
        if path.name != "store.py"
    }
    private_callers = [
        str(path)
        for path, source in service_sources.items()
        if "store._require(" in source or "store._persist_project(" in source
    ]

    assert private_callers == []
    assert "def require_project_for_update" in store_source
    assert "def persist_project_state" in store_source
    assert "store.require_project_for_update" in workspace_access_source
    assert "store.persist_project_state" in workspace_access_source
    assert "require_workspace_project_for_update(" in service_sources[Path("app/services/business_gap_repository.py")]
    assert "persist_workspace_project_state(" in service_sources[Path("app/services/business_gap_repository.py")]
    assert "require_workspace_project_for_update(" in service_sources[Path("app/services/technical_gap_repository.py")]
    assert "persist_workspace_project_state(" in service_sources[Path("app/services/technical_gap_repository.py")]
    assert "def require_any_workspace_project_for_update" in workspace_access_source
    assert "require_any_workspace_project_for_update(" in service_sources[Path("app/services/ocr_service.py")]
    assert "persist_workspace_project_state(" in service_sources[Path("app/services/ocr_service.py")]
    assert "from app.services.store import store" not in service_sources[Path("app/services/ocr_service.py")]
    assert "persist_workspace_project_state(" in service_sources[Path("app/services/business_assembly.py")]
    assert "store.persist_project_state" not in service_sources[Path("app/services/business_assembly.py")]


def test_workspace_project_access_owns_bid_type_guards() -> None:
    access_source = Path("app/services/workspace_project_access.py").read_text(encoding="utf-8")
    business_repository_source = Path("app/services/business_gap_repository.py").read_text(encoding="utf-8")
    technical_repository_source = Path("app/services/technical_gap_repository.py").read_text(encoding="utf-8")
    technical_draft_source = Path("app/services/technical_draft_generation.py").read_text(encoding="utf-8")
    business_assembly_source = Path("app/services/business_assembly.py").read_text(encoding="utf-8")
    tech_assembly_source = Path("app/services/tech_assembly.py").read_text(encoding="utf-8")
    technical_document_format_source = Path("app/services/technical_document_format.py").read_text(encoding="utf-8")
    document_flow_source = Path("app/services/bid_document_flow.py").read_text(encoding="utf-8")
    directory_flow_source = Path("app/services/bid_directory_flow.py").read_text(encoding="utf-8")
    business_parse_assets_source = Path("app/services/business_parse_assets.py").read_text(encoding="utf-8")
    project_service_source = Path("app/services/bid_project_service.py").read_text(encoding="utf-8")
    parse_service_source = Path("app/services/bid_parse_service.py").read_text(encoding="utf-8")
    business_document_editing_source = Path("app/services/business_document_editing.py").read_text(encoding="utf-8")
    business_document_service_source = Path("app/services/business_document_service.py").read_text(encoding="utf-8")
    technical_document_service_source = Path("app/services/technical_document_service.py").read_text(encoding="utf-8")
    business_gap_planning_source = Path("app/services/business_gap_planning.py").read_text(encoding="utf-8")
    outline_generation_source = Path("app/services/outline_generation.py").read_text(encoding="utf-8")
    redis_worker_source = Path("app/workers/redis_worker.py").read_text(encoding="utf-8")

    assert "def ensure_workspace_project_type" in access_source
    assert "require_bid_type" in access_source
    assert "normalize_bid_type" not in access_source
    assert "store.get_project_runtime_state" in access_source
    assert "store.require_project_for_update" in access_source
    assert "normalize_bid_type" not in business_repository_source
    assert "normalize_bid_type" not in technical_repository_source
    assert "from app.services.store import store" not in business_repository_source
    assert "from app.services.store import store" not in technical_repository_source
    assert "from app.services.store import store" not in technical_draft_source
    assert "store.get_project(" not in technical_draft_source
    assert "from app.services.store import store" not in business_assembly_source
    assert "store.get_outline_state(project_id)" not in business_assembly_source
    assert "store.save_fill_generation_result(" not in business_assembly_source
    assert "store.get_document_state(project_id)" not in business_assembly_source
    assert "require_workspace_project_for_update(" in business_assembly_source
    assert "save_fill_generation_result_state(" in business_assembly_source
    assert "persist_workspace_project_state(" in business_assembly_source
    assert "from app.services.store import store" not in tech_assembly_source
    assert "store.get_project(" not in tech_assembly_source
    assert "store.get_outline_state(project_id)" not in tech_assembly_source
    assert "store.get_parse_storage(project_id)" not in tech_assembly_source
    assert "store.get_parse_inputs(project_id)" not in tech_assembly_source
    assert "store.save_fill_generation_result(" not in tech_assembly_source
    assert "store.get_directory_state(project_id)" not in tech_assembly_source
    assert "project_parse_input_records(" in tech_assembly_source
    assert "require_workspace_project_for_update(" in tech_assembly_source
    assert "save_fill_generation_result_state(" in tech_assembly_source
    assert "persist_workspace_project_state(" in tech_assembly_source
    assert "normalize_bid_type" not in technical_document_format_source
    assert "from app.services.store import store" not in technical_document_format_source
    assert "normalize_bid_type" not in business_parse_assets_source
    assert "store.get_project_runtime_state(project_id)" not in technical_document_format_source
    assert "store.get_document_state(project_id)" not in technical_document_format_source
    assert "store.get_outline_state(project_id)" not in technical_document_format_source
    assert "store.get_parse_storage(project_id)" not in technical_document_format_source
    assert "store.get_project(project_id)" not in business_parse_assets_source
    assert "from app.services.store import store" not in business_parse_assets_source
    assert "store.get_parse_result(project_id)" not in business_parse_assets_source
    assert "store.get_parse_storage(project_id)" not in business_parse_assets_source
    assert "store.update_parse_result(project_id" not in business_parse_assets_source
    assert "get_workspace_project_runtime_state(" in technical_document_format_source
    assert "get_workspace_project_runtime_state(" in business_parse_assets_source
    assert "require_workspace_project_for_update(" in business_parse_assets_source
    assert "update_parse_result_state(" in business_parse_assets_source
    assert "persist_workspace_project_state(" in business_parse_assets_source
    assert "normalize_bid_type" not in project_service_source
    assert "from app.services.store import store" not in project_service_source
    assert "store.get_project_runtime_state(project_id)" not in project_service_source
    assert "store.list_projects(" not in project_service_source
    assert "store.create_project(" not in project_service_source
    assert "store.get_project(project_id)" not in project_service_source
    assert "store.update_project(" not in project_service_source
    assert "store.delete_project" not in project_service_source
    assert "store.template_fallback_context(" not in project_service_source
    assert "store.update_template_fallback(" not in project_service_source
    assert "store.get_parse_progress(" not in project_service_source
    assert "store.get_stages(" not in project_service_source
    assert "store.update_stage(" not in project_service_source
    assert "get_workspace_project_runtime_state(" in project_service_source
    assert "list_workspace_projects(" in project_service_source
    assert "create_workspace_project(" in project_service_source
    assert "update_workspace_project(" in project_service_source
    assert "update_workspace_project_stage(" in project_service_source
    assert "workspace_template_fallback_context(" in project_service_source
    assert "normalize_bid_type" not in parse_service_source
    assert "from app.services.store import store" not in parse_service_source
    assert "store.get_project(project_id)" not in parse_service_source
    assert "store.get_parse_result(project_id)" not in parse_service_source
    assert "store.get_parse_progress(project_id)" not in parse_service_source
    assert "store.get_parse_inputs(project_id" not in parse_service_source
    assert "store.start_parse_progress(project_id)" not in parse_service_source
    assert "store.update_parse_progress(" not in parse_service_source
    assert "store.complete_parse(" not in parse_service_source
    assert "store.update_template_files(project_id" not in parse_service_source
    assert "self.project_service.bid_type" in parse_service_source
    assert "require_workspace_project_for_update(" in parse_service_source
    assert "persist_workspace_project_state(" in parse_service_source
    assert "project_parse_input_records(" in parse_service_source
    assert "complete_parse_state(" in parse_service_source
    assert "update_parse_progress_state(" in parse_service_source
    assert "update_template_files_state(" in parse_service_source
    assert "normalize_bid_type" not in business_document_editing_source
    assert "from app.services.store import store" not in business_document_editing_source
    assert "store.get_project_runtime_state(project_id)" not in business_document_editing_source
    assert "store.get_project(project_id)" not in business_document_editing_source
    assert "store.get_document_state(project_id)" not in business_document_editing_source
    assert "get_workspace_project_runtime_state(" in business_document_editing_source
    assert "normalize_bid_type" not in business_document_service_source
    assert "from app.services.store import store" not in business_document_service_source
    assert "store.get_document_state(project_id)" not in business_document_service_source
    assert "store.get_fill_state(project_id)" not in business_document_service_source
    assert "store.force_save_document(project_id)" not in business_document_service_source
    assert "store.apply_business_document_format(project_id, result)" not in business_document_service_source
    assert "require_workspace_project_for_update(" in business_document_service_source
    assert "persist_workspace_project_state(" in business_document_service_source
    assert "force_save_document_state(project_state, project_id)" in business_document_service_source
    assert "apply_business_document_format_to_project(project_state, result)" in business_document_service_source
    assert "from app.services.store import store" not in technical_document_service_source
    assert "store.apply_technical_document_format(project_id, result)" not in technical_document_service_source
    assert "require_workspace_project_for_update(" in technical_document_service_source
    assert "persist_workspace_project_state(" in technical_document_service_source
    assert "apply_technical_document_format_to_project(project_state, result)" in technical_document_service_source
    assert "from app.services.store import store" not in document_flow_source
    assert "store.get_document_state(project_id)" not in document_flow_source
    assert "store.save_document_content(project_id, content)" not in document_flow_source
    assert "store.force_save_document(project_id)" not in document_flow_source
    assert "store.get_final_document(project_id)" not in document_flow_source
    assert "require_workspace_project_for_update(" in document_flow_source
    assert "persist_workspace_project_state(" in document_flow_source
    assert "save_document_content_state(project, project_id, content)" in document_flow_source
    assert "force_save_document_state(project, project_id)" in document_flow_source
    assert "final_document_state(project)" in document_flow_source
    assert "from app.services.store import store" not in directory_flow_source
    assert "store.get_directory_state(project_id)" not in directory_flow_source
    assert "store.update_directory_generation_state(" not in directory_flow_source
    assert "store.fail_directory_generation(" not in directory_flow_source
    assert "store.get_parse_inputs(project_id" not in directory_flow_source
    assert "store.start_directory_generation(project_id)" not in directory_flow_source
    assert "store.get_outline_state(project_id)" not in directory_flow_source
    assert "store.save_outline(project_id" not in directory_flow_source
    assert "store.regenerate_outline(project_id)" not in directory_flow_source
    assert "store.confirm_outline(project_id)" not in directory_flow_source
    assert "require_workspace_project_for_update(" in directory_flow_source
    assert "require_any_workspace_project_for_update(" in directory_flow_source
    assert "persist_workspace_project_state(" in directory_flow_source
    assert "project_parse_input_records(" in directory_flow_source
    assert "directory_state_with_rule_evidence(" in directory_flow_source
    assert "start_directory_generation_state(project)" in directory_flow_source
    assert "update_directory_generation_state(project" in directory_flow_source
    assert "fail_directory_generation_state(project" in directory_flow_source
    assert "save_outline_state(project" in directory_flow_source
    assert "regenerate_outline_state(project)" in directory_flow_source
    assert "confirm_outline_state(project)" in directory_flow_source
    assert "normalize_bid_type" not in business_gap_planning_source
    assert "ensure_workspace_project_type(" in business_gap_planning_source
    assert "store.get_project(project_id)" not in outline_generation_source
    assert "from app.services.store import store" not in outline_generation_source
    assert "store.get_parse_storage(project_id)" not in outline_generation_source
    assert "store.get_parse_inputs(project_id)" not in outline_generation_source
    assert "store.save_generated_outline(" not in outline_generation_source
    assert "get_any_workspace_project_runtime_state(" in outline_generation_source
    assert "project_parse_input_records(" in outline_generation_source
    assert "require_any_workspace_project_for_update(" in outline_generation_source
    assert "save_generated_outline_state(" in outline_generation_source
    assert "persist_workspace_project_state(" in outline_generation_source
    assert "from app.services.store import store" not in redis_worker_source
    assert "store.get_directory_state(project_id)" not in redis_worker_source
    assert "store.get_fill_state(project_id)" not in redis_worker_source
    assert "or TECHNICAL_BID_TYPE" not in redis_worker_source
    assert "require_bid_type(" in redis_worker_source
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    assert "def get_directory_state(" not in store_source
    assert "def get_outline_state(" not in store_source
    assert "def start_directory_generation(" not in store_source
    assert "def update_directory_generation_state(" not in store_source
    assert "def fail_directory_generation(" not in store_source
    assert "def save_generated_outline(" not in store_source
    assert "def save_outline(" not in store_source
    assert "def regenerate_outline(" not in store_source
    assert "def confirm_outline(" not in store_source
    assert "def get_fill_state(" not in store_source
    assert "get_any_workspace_project_runtime_state(" in redis_worker_source


def test_project_parse_input_records_recovers_tender_uploads_from_disk(tmp_path) -> None:
    from app.core.config import settings

    original_uploads_dir = settings.uploads_dir
    try:
        settings.uploads_dir = tmp_path / "uploads"
        project_id = "PRJ-RECOVER-UPLOADS"
        tender_dir = settings.uploads_dir / project_id / "tender"
        tender_dir.mkdir(parents=True)
        source = tender_dir / "tender-1-deadbeef.pdf"
        source.write_bytes(b"%PDF-1.4\n")
        project = create_project_state(
            project_id,
            {"name": "恢复上传记录项目", "customerName": "测试业主", "bidType": "商务标"},
        )
        project["fileRecords"] = []

        tender_records, template_records = project_parse_input_records(project_id, project, include_fallback=False)

        assert template_records == []
        assert len(tender_records) == 1
        assert tender_records[0]["id"] == "TEN-1"
        assert tender_records[0]["name"] == source.name
        assert tender_records[0]["stored_name"] == source.name
        assert tender_records[0]["path"] == str(source)
        assert tender_records[0]["size_bytes"] == source.stat().st_size
        assert tender_records[0]["content_type"] == "application/pdf"
    finally:
        settings.uploads_dir = original_uploads_dir


def test_bid_type_rules_have_single_source_of_truth() -> None:
    from app.services.bid_type import (
        BUSINESS_BID_TYPE,
        GENERAL_BID_TYPE,
        TECHNICAL_BID_TYPE,
        is_business_bid_type,
        is_technical_bid_type,
        normalize_bid_type,
        require_bid_type,
    )
    from app.services.identity import build_project_identity, build_project_material_scope, classify_material_path, material_identity

    bid_type_source = Path("app/services/bid_type.py").read_text(encoding="utf-8")
    parse_profiles_source = Path("app/services/parse_profiles.py").read_text(encoding="utf-8")
    identity_source = Path("app/services/identity.py").read_text(encoding="utf-8")
    store_source = Path("app/services/store.py").read_text(encoding="utf-8")
    business_route_source = Path("app/api/routes/business.py").read_text(encoding="utf-8")
    sources_using_bid_type = {
        "workspace_project_access": Path("app/services/workspace_project_access.py").read_text(encoding="utf-8"),
        "bid_project_state": Path("app/services/bid_project_state.py").read_text(encoding="utf-8"),
        "bid_runtime_state": Path("app/services/bid_runtime_state.py").read_text(encoding="utf-8"),
        "workspace_artifacts": Path("app/services/workspace_artifacts.py").read_text(encoding="utf-8"),
        "project_fact_materials": Path("app/services/project_fact_materials.py").read_text(encoding="utf-8"),
        "project_stage_flow": Path("app/services/project_stage_flow.py").read_text(encoding="utf-8"),
        "bid_generation_flow": Path("app/services/bid_generation_flow.py").read_text(encoding="utf-8"),
        "technical_draft_generation": Path("app/services/technical_draft_generation.py").read_text(encoding="utf-8"),
        "bid_fill_state": Path("app/services/bid_fill_state.py").read_text(encoding="utf-8"),
        "outline_generation": Path("app/services/outline_generation.py").read_text(encoding="utf-8"),
        "parsing": Path("app/services/parsing.py").read_text(encoding="utf-8"),
        "business_assembly": Path("app/services/business_assembly.py").read_text(encoding="utf-8"),
        "business_document_editing": Path("app/services/business_document_editing.py").read_text(encoding="utf-8"),
        "technical_document_format": Path("app/services/technical_document_format.py").read_text(encoding="utf-8"),
        "business_audit_service": Path("app/services/business_audit_service.py").read_text(encoding="utf-8"),
        "technical_audit_service": Path("app/services/technical_audit_service.py").read_text(encoding="utf-8"),
        "business_document_service": Path("app/services/business_document_service.py").read_text(encoding="utf-8"),
        "business_parse_assets": Path("app/services/business_parse_assets.py").read_text(encoding="utf-8"),
        "business_gap_domain": Path("app/services/business_gap_domain.py").read_text(encoding="utf-8"),
        "business_gap_planning": Path("app/services/business_gap_planning.py").read_text(encoding="utf-8"),
        "business_gap_repository": Path("app/services/business_gap_repository.py").read_text(encoding="utf-8"),
        "technical_gap_repository": Path("app/services/technical_gap_repository.py").read_text(encoding="utf-8"),
        "technical_gap_service": Path("app/services/technical_gap_service.py").read_text(encoding="utf-8"),
        "technical_gap_planner": Path("app/services/technical_gap_planner.py").read_text(encoding="utf-8"),
        "technical_gap_review": Path("app/services/technical_gap_review.py").read_text(encoding="utf-8"),
        "technical_gap_state": Path("app/services/technical_gap_state.py").read_text(encoding="utf-8"),
        "technical_gap_fact_table": Path("app/services/technical_gap_fact_table.py").read_text(encoding="utf-8"),
        "business_gap_service": Path("app/services/business_gap_service.py").read_text(encoding="utf-8"),
        "bid_project_service": Path("app/services/bid_project_service.py").read_text(encoding="utf-8"),
        "business_material_store": Path("app/services/business_material_store.py").read_text(encoding="utf-8"),
        "technical_material_store": Path("app/services/technical_material_store.py").read_text(encoding="utf-8"),
        "material_folder_scope": Path("app/services/material_folder_scope.py").read_text(encoding="utf-8"),
        "material_folder_maintenance": Path("app/services/material_folder_maintenance.py").read_text(encoding="utf-8"),
        "material_raw_folder_operations": Path("app/services/material_raw_folder_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_taxonomy": Path("app/services/material_taxonomy.py").read_text(encoding="utf-8"),
        "material_identity_options": Path("app/services/material_identity_options.py").read_text(encoding="utf-8"),
        "material_update_metadata": Path("app/services/material_update_metadata.py").read_text(encoding="utf-8"),
        "material_upload_metadata": Path("app/services/material_upload_metadata.py").read_text(encoding="utf-8"),
        "material_upload_operations": Path("app/services/material_upload_operations.py").read_text(encoding="utf-8"),
        "material_store": Path("app/services/material_store.py").read_text(encoding="utf-8"),
        "peripheral": Path("app/services/peripheral.py").read_text(encoding="utf-8"),
        "template_store": Path("app/services/template_store.py").read_text(encoding="utf-8"),
        "tech_assembly": Path("app/services/tech_assembly.py").read_text(encoding="utf-8"),
        "business_material_splitter": Path("app/services/business_material_splitter.py").read_text(encoding="utf-8"),
        "bid_outline_state": Path("app/services/bid_outline_state.py").read_text(encoding="utf-8"),
        "material_wiki_scope": Path("app/services/material_wiki_scope.py").read_text(encoding="utf-8"),
        "material_upload_target": Path("app/services/material_upload_target.py").read_text(encoding="utf-8"),
        "technical_turbine_material_options": Path("app/services/technical_turbine_material_options.py").read_text(
            encoding="utf-8"
        ),
        "dashboard_service": Path("app/services/dashboard_service.py").read_text(encoding="utf-8"),
        "wiki_generation": Path("app/services/business_wiki_generation.py").read_text(encoding="utf-8"),
    }

    assert normalize_bid_type("商务响应文件") == BUSINESS_BID_TYPE
    assert normalize_bid_type("技术方案") == TECHNICAL_BID_TYPE
    assert normalize_bid_type(GENERAL_BID_TYPE) == GENERAL_BID_TYPE
    assert normalize_bid_type("unknown") == ""
    assert normalize_bid_type("unknown", BUSINESS_BID_TYPE) == BUSINESS_BID_TYPE
    assert require_bid_type("商务响应文件") == BUSINESS_BID_TYPE
    assert require_bid_type("技术方案") == TECHNICAL_BID_TYPE
    try:
        require_bid_type("")
    except ValueError:
        pass
    else:
        raise AssertionError("require_bid_type should reject missing bid type")
    try:
        build_project_identity({"id": "PRJ-NO-BID-TYPE", "name": "缺标类项目"})
    except ValueError:
        pass
    else:
        raise AssertionError("build_project_identity should require explicit bidType")
    try:
        build_project_material_scope({"id": "PRJ-NO-BID-TYPE", "name": "缺标类项目"})
    except ValueError:
        pass
    else:
        raise AssertionError("build_project_material_scope should require explicit bidType")
    try:
        classify_material_path("项目素材/LEGACY-001", "")
    except ValueError:
        pass
    else:
        raise AssertionError("classify_material_path should require an explicit fallback bid type")
    try:
        material_identity(material_tier="standard", bid_type="")
    except ValueError:
        pass
    else:
        raise AssertionError("material_identity should require explicit bidType")
    assert is_business_bid_type("商务标项目") is True
    assert is_technical_bid_type("技术标项目") is True
    assert is_technical_bid_type("unknown") is False
    assert "def normalize_bid_type" in bid_type_source
    assert "default: str = TECHNICAL_BID_TYPE" not in bid_type_source
    assert "def require_bid_type" in bid_type_source
    assert "def normalize_bid_type" not in parse_profiles_source
    assert "def normalize_bid_type" not in identity_source
    assert "return \"商务标\" if \"商务\" in value else \"技术标\"" not in parse_profiles_source
    assert "return text if text in BID_TYPES else default" not in identity_source
    assert "from app.services.bid_type import BUSINESS_BID_TYPE" in business_route_source
    assert 'BUSINESS_BID_TYPE = "商务标"' not in business_route_source
    assert "default_bid_type: str = TECHNICAL_BID_TYPE" not in identity_source
    assert "bid_type: Any = TECHNICAL_BID_TYPE" not in identity_source
    assert "normalize_bid_type(project.get(\"bidType\"), TECHNICAL_BID_TYPE)" not in identity_source
    assert "normalize_bid_type(identity.get(\"bidType\") or project.get(\"bidType\"), TECHNICAL_BID_TYPE)" not in identity_source
    assert "from app.services.bid_type import" in parse_profiles_source
    assert "from app.services.bid_type import" in identity_source
    for source_name, source in sources_using_bid_type.items():
        if source_name in {"material_store", "material_upload_operations", "workspace_artifacts", "dashboard_service"}:
            assert "from app.services.bid_type import" not in source
        else:
            assert "from app.services.bid_type import" in source
        assert "from app.services.parse_profiles import normalize_bid_type" not in source
        assert 'BUSINESS_BID_TYPE = "商务标"' not in source
        assert 'TECHNICAL_BID_TYPE = "技术标"' not in source
        assert "from app.services.business_material_store import BUSINESS_BID_TYPE" not in source
        assert "from app.services.technical_material_store import TECHNICAL_BID_TYPE" not in source
        assert "from app.services.business_gap_repository import (\n    BUSINESS_BID_TYPE" not in source
    wiki_generation_source = sources_using_bid_type["wiki_generation"]
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in wiki_generation_source
    assert 'bid_type == "商务标"' not in wiki_generation_source
    assert 'bid_type == "技术标"' not in wiki_generation_source
    assert 'material.get("bidType") == "商务标"' not in wiki_generation_source
    assert 'material_bid_type == "商务标"' not in wiki_generation_source
    material_taxonomy_source = sources_using_bid_type["material_taxonomy"]
    assert 'bid_type == "技术标"' not in material_taxonomy_source
    assert 'parts[0] == "技术标"' not in material_taxonomy_source
    assert 'parts[0] == "商务标"' not in material_taxonomy_source
    assert 'base_path = "商务标/通用素材"' not in material_taxonomy_source
    assert 'str(ext.get("bidType") or "") == "商务标"' not in sources_using_bid_type["material_update_metadata"]
    assert 'bid_type: str = "技术标"' not in sources_using_bid_type["material_upload_operations"]
    assert 'bid_type: str = "技术标"' not in sources_using_bid_type["material_store"]
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type["material_store"]
    for source_name in [
        "material_raw_folder_operations",
        "material_folder_maintenance",
        "material_upload_operations",
        "material_upload_target",
        "material_upload_metadata",
    ]:
        assert "bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type[source_name]
        assert "requested_bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type[source_name]
    assert 'bid_type: str = "技术标"' not in sources_using_bid_type["peripheral"]
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type["peripheral"]
    assert 'bid_type: str = "技术标"' not in sources_using_bid_type["template_store"]
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type["template_store"]
    assert 'bid_type: str = "技术标"' not in sources_using_bid_type["parsing"]
    assert 'bid_type: str = "商务标"' not in sources_using_bid_type["parsing"]
    assert "bid_type: str = BUSINESS_BID_TYPE" not in sources_using_bid_type["parsing"]
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type["parsing"]
    assert 'bid_type="技术标"' not in sources_using_bid_type["technical_draft_generation"]
    assert 'bid_type="技术标"' not in sources_using_bid_type["tech_assembly"]
    assert 'bid_type="商务标"' not in sources_using_bid_type["business_assembly"]
    assert '"bidType": "商务标"' not in sources_using_bid_type["business_assembly"]
    assert 'bid_type="商务标"' not in sources_using_bid_type["business_document_editing"]
    assert 'return "商务标"' not in sources_using_bid_type["business_document_editing"]
    assert 'bid_type="技术标"' not in sources_using_bid_type["technical_document_format"]
    assert 'bid_type="商务标"' not in sources_using_bid_type["business_gap_planning"]
    assert '"bidType": "商务标"' not in sources_using_bid_type["business_gap_planning"]
    assert 'f"商务标/项目素材' not in sources_using_bid_type["business_gap_domain"]
    assert 'f"商务标/项目素材' not in sources_using_bid_type["business_gap_service"]
    assert 'f"商务标/项目素材' not in sources_using_bid_type["business_parse_assets"]
    assert 'f"技术标/项目素材' not in sources_using_bid_type["technical_gap_service"]
    assert "project_material_root_path(BUSINESS_BID_TYPE" in sources_using_bid_type["business_gap_domain"]
    assert "project_material_root_path(BUSINESS_BID_TYPE" in sources_using_bid_type["business_parse_assets"]
    assert "project_material_root_path(TECHNICAL_BID_TYPE" in sources_using_bid_type["technical_gap_service"]
    assert 'project.get("bidType") or "商务标"' not in sources_using_bid_type["business_gap_service"]
    assert 'project.get("bidType") or BUSINESS_BID_TYPE' not in sources_using_bid_type["business_gap_service"]
    assert 'bid_type="商务标"' not in sources_using_bid_type["bid_project_service"]
    assert 'bid_type="技术标"' not in sources_using_bid_type["bid_project_service"]
    assert "or self.bid_type" not in sources_using_bid_type["bid_project_service"]
    assert "from app.services.store import store" not in sources_using_bid_type["dashboard_service"]
    assert "store.list_projects(" not in sources_using_bid_type["dashboard_service"]
    assert "technical_project_service.list(page_size=50)" in sources_using_bid_type["dashboard_service"]
    assert "business_project_service.list(page_size=50)" in sources_using_bid_type["dashboard_service"]
    assert 'bid_type="技术标"' not in sources_using_bid_type["dashboard_service"]
    assert 'bid_type="商务标"' not in sources_using_bid_type["dashboard_service"]
    assert 'bid_label: str = "商务标"' not in sources_using_bid_type["business_document_service"]
    assert 'project.get("bidType") or "商务标"' not in sources_using_bid_type["business_document_service"]
    assert 'project.get("bidType") or BUSINESS_BID_TYPE' not in sources_using_bid_type["business_document_service"]
    assert 'project.get("bidType") or "技术标"' not in store_source
    assert 'data.get("bidType") or "技术标"' not in sources_using_bid_type["bid_project_state"]
    assert 'project.get("bidType") or "技术标"' not in sources_using_bid_type["bid_project_state"]
    assert 'project.get("bidType") or "技术标"' not in sources_using_bid_type["bid_runtime_state"]
    assert "or TECHNICAL_BID_TYPE" not in sources_using_bid_type["bid_project_state"]
    assert "or TECHNICAL_BID_TYPE" not in sources_using_bid_type["bid_runtime_state"]
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type["bid_generation_flow"]
    for source_name in [
        "bid_fill_state",
        "material_identity_options",
        "outline_generation",
        "tech_assembly",
        "technical_gap_planner",
        "technical_gap_review",
        "technical_gap_state",
    ]:
        assert 'or "技术标"' not in sources_using_bid_type[source_name]
        assert '"bidType": "技术标"' not in sources_using_bid_type[source_name]
        assert "or TECHNICAL_BID_TYPE" not in sources_using_bid_type[source_name]
    assert 'or "投标文件"' not in sources_using_bid_type["outline_generation"]
    assert 'manifest.get("bidType") or BUSINESS_BID_TYPE' not in sources_using_bid_type["outline_generation"]
    assert "item.get('bidType') or '技术标'" not in sources_using_bid_type["tech_assembly"]
    assert 'or "投标文件"' not in sources_using_bid_type["tech_assembly"]
    assert "or TECHNICAL_BID_TYPE" not in sources_using_bid_type["material_identity_options"]
    assert "or TECHNICAL_BID_TYPE" not in sources_using_bid_type["material_upload_metadata"]
    assert "or folder.bid_type or TECHNICAL_BID_TYPE" not in sources_using_bid_type["material_folder_maintenance"]
    assert "default: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type["material_folder_scope"]
    assert "classify_material_path(normalized, TECHNICAL_BID_TYPE)" not in sources_using_bid_type["material_folder_scope"]
    assert "else TECHNICAL_BID_TYPE" not in sources_using_bid_type["material_upload_target"]
    assert "or TECHNICAL_BID_TYPE" not in sources_using_bid_type["technical_turbine_material_options"]
    assert 'Any = "技术标"' not in sources_using_bid_type["workspace_artifacts"]
    assert 'profile_or_bid_type: Any = "技术标"' not in sources_using_bid_type["workspace_artifacts"]
    assert 'resolve_parse_profile(str(value or "技术标"))' not in sources_using_bid_type["workspace_artifacts"]
    assert "from app.services.bid_type import TECHNICAL_BID_TYPE" not in sources_using_bid_type["workspace_artifacts"]
    assert "value: Any = TECHNICAL_BID_TYPE" not in sources_using_bid_type["workspace_artifacts"]
    assert "bid_type: Any = TECHNICAL_BID_TYPE" not in sources_using_bid_type["workspace_artifacts"]
    assert "profile_or_bid_type: Any = TECHNICAL_BID_TYPE" not in sources_using_bid_type["workspace_artifacts"]
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in sources_using_bid_type["workspace_artifacts"]
    assert '!= "商务标"' not in sources_using_bid_type["business_material_splitter"]
    assert 'parts[0] == "商务标"' not in sources_using_bid_type["business_material_splitter"]
    assert '!= "商务标"' not in sources_using_bid_type["bid_outline_state"]
    implicit_normalize_callers: list[str] = []
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name != "normalize_bid_type":
                continue
            if path.as_posix() == "app/services/bid_type.py":
                continue
            if len(node.args) < 2 and not any(keyword.arg == "default" for keyword in node.keywords):
                implicit_normalize_callers.append(f"{path}:{node.lineno}")
    assert implicit_normalize_callers == []


def test_store_does_not_bypass_workspace_material_facades() -> None:
    source = Path("app/services/store.py").read_text(encoding="utf-8")
    project_state_source = Path("app/services/bid_project_state.py").read_text(encoding="utf-8")

    assert "from app.services.material_store import material_store" not in source
    assert not re.search(r"(?<![A-Za-z_])material_store\.", source)
    assert "business_material_store.raw_delete_folder" not in source
    assert "technical_material_store.raw_delete_folder" not in source
    assert "business_material_store.raw_cleanup_project_folder" in project_state_source
    assert "technical_material_store.raw_cleanup_project_folder" in project_state_source


def test_business_parse_assets_upload_uses_business_material_store() -> None:
    project = {
        "id": "PRJ-BIZ-PARSE-ASSET",
        "bidType": "商务标",
        "name": "商务解析资产同步测试",
        "customerName": "测试业主",
        "projectCode": "BIZ-2026-001",
    }
    calls: list[dict[str, object]] = []

    async def fake_raw_upload(**kwargs):
        calls.append(kwargs)
        return {
            "message": "uploaded",
            "items": [
                {
                    "id": "RAW-BIZ-001",
                    "name": "商务评分标准.docx",
                    "folderPath": kwargs["target_path"],
                    "bidType": "商务标",
                }
            ],
        }

    with patch(
        "app.services.business_parse_assets.business_material_store.raw_upload",
        side_effect=fake_raw_upload,
    ):
        payload = asyncio.run(
            business_parse_assets_module._upload_business_material_files(
                project,
                target_folder="项目商务响应文件",
                files=[{"name": "商务评分标准.docx", "data": b"docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}],
            )
        )

    assert payload["items"][0]["bidType"] == "商务标"
    assert len(calls) == 1
    assert calls[0]["target_path"] == "商务标/项目素材/PRJ-BIZ-PARSE-ASSET/项目商务响应文件"
    assert calls[0]["project_id"] == "PRJ-BIZ-PARSE-ASSET"
    assert calls[0]["project_code"] == "BIZ-2026-001"
    assert calls[0]["project_name"] == "商务解析资产同步测试"
    assert calls[0]["material_tier"] == "project"
    assert str(calls[0]["customer_id"]).startswith("CUST-")
    assert calls[0]["customer_name"] == "测试业主"
    assert calls[0]["on_conflict"] == "version"
    assert calls[0]["files"] == [
        {
            "name": "商务评分标准.docx",
            "data": b"docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    ]


def test_business_parse_assets_do_not_import_material_store_singleton() -> None:
    source = Path("app/services/business_parse_assets.py").read_text(encoding="utf-8")

    assert "from app.services.business_material_store import business_material_store" in source
    assert "from app.services.material_store import material_store" not in source
    assert not re.search(r"(?<![A-Za-z_])material_store\.raw_upload", source)
    assert "business_material_store.raw_upload" in source


def test_business_material_splitter_upload_uses_business_material_store() -> None:
    source = Path("app/services/business_material_splitter.py").read_text(encoding="utf-8")

    assert "from app.services.material_store import material_store" not in source
    assert not re.search(r"(?<![A-Za-z_])material_store\.raw_upload", source)
    assert "business_material_store.raw_upload" in source


def test_wiki_generation_import_uses_workspace_material_stores() -> None:
    business_source = Path("app/services/business_wiki_generation.py").read_text(encoding="utf-8")
    technical_source = Path("app/services/technical_wiki_generation.py").read_text(encoding="utf-8")

    for source in (business_source, technical_source):
        assert "from app.services.material_store import material_store" not in source
        assert not re.search(r"(?<![A-Za-z_])material_store\.import_generated_wiki_blueprint", source)

    assert "business_material_store.import_generated_wiki_blueprint" in business_source
    assert "technical_material_store.import_generated_wiki_blueprint" in technical_source


def test_wiki_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    scope_source = Path("app/services/material_wiki_scope.py").read_text(encoding="utf-8")
    tree_source = Path("app/services/material_wiki_tree.py").read_text(encoding="utf-8")
    import_source = Path("app/services/material_wiki_import.py").read_text(encoding="utf-8")

    assert "def _bid_type_for_wiki_root" not in material_source
    assert "title.startswith(f\"{normalized_bid_type}Wiki\")" not in material_source
    assert "wiki_root_visible_for_bid_type" not in material_source
    assert "wiki_root_visible_for_bid_type" in tree_source
    assert "wiki_root_bid_type" not in material_source
    assert "wiki_root_bid_type" in import_source
    assert "def wiki_root_visible_for_bid_type" in scope_source
    assert "def wiki_root_bid_type" in scope_source


def test_raw_folder_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    folder_scope_source = Path("app/services/material_folder_scope.py").read_text(encoding="utf-8")
    folder_maintenance_source = Path("app/services/material_folder_maintenance.py").read_text(encoding="utf-8")
    folder_operations_source = Path("app/services/material_raw_folder_operations.py").read_text(encoding="utf-8")
    lifecycle_source = Path("app/services/material_raw_lifecycle_operations.py").read_text(encoding="utf-8")

    assert "RAW_MATERIAL_ROOTS" not in material_source
    assert "TECHNICAL_TIER_FOLDERS" not in material_source
    assert "BUSINESS_TIER_FOLDERS" not in material_source
    assert "BUSINESS_STANDARD_SUBFOLDERS" not in material_source
    assert "BUSINESS_CUSTOMIZED_SUBFOLDERS" not in material_source
    assert "canonical_technical_material_path" not in material_source
    assert not re.search(r"(?<!material_)bid_type_sort_order", material_source)
    assert "canonical_raw_folder_metadata" not in material_source
    assert "raw_material_tier_folder_specs" not in material_source
    assert "business_standard_subfolder_specs" not in material_source
    assert "business_customized_subfolder_specs" not in material_source
    assert "business_customized_child_tier_for_parent_folder_path" not in material_source
    assert "project_material_root_path" not in material_source
    assert "projectId 不能为空。" not in material_source
    assert "migrate_legacy_technical_folders(" not in material_source
    assert "bootstrap_project_material_folder(" not in material_source
    assert "ensure_business_standard_subfolders(" not in material_source
    assert "ensure_business_customized_children_for_created_folder(" not in material_source
    assert "def _ensure_material_target_folder" not in material_source
    assert "def _infer_material_tier_from_folder" not in material_source
    assert "def raw_permissions" not in material_source
    assert "build_raw_material_permissions" not in material_source
    assert "技术标素材" not in material_source
    assert "商务标素材" not in material_source
    assert "RawFolderDeletion" not in material_source
    assert "RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS" not in material_source
    assert "def ensure_raw_material_roots" not in material_source
    assert "def ensure_folder_path" not in material_source
    assert "def canonical_raw_folder_metadata" in folder_scope_source
    assert "def raw_material_tier_folder_specs" in folder_scope_source
    assert "def business_standard_subfolder_specs" in folder_scope_source
    assert "def business_customized_subfolder_specs" in folder_scope_source
    assert "def build_raw_material_permissions" in folder_scope_source
    assert "def infer_material_tier_from_raw_folder" in folder_scope_source
    assert "def ensure_business_standard_subfolders" in folder_maintenance_source
    assert "def ensure_business_customized_subfolders" in folder_maintenance_source
    assert "def ensure_business_customized_children_for_created_folder" in folder_maintenance_source
    assert "def backfill_existing_business_customized_subfolders" in folder_maintenance_source
    assert "def migrate_legacy_technical_folders" in folder_maintenance_source
    assert "def ensure_material_target_folder" in folder_maintenance_source
    assert "def bootstrap_project_material_folder" in folder_maintenance_source
    assert "business_standard_subfolder_specs" in folder_maintenance_source
    assert "business_customized_subfolder_specs" in folder_maintenance_source
    assert "ensure_business_customized_children_for_created_folder(" in lifecycle_source
    assert "business_customized_child_tier_for_parent_folder_path" in folder_maintenance_source
    assert "canonical_technical_material_path" in folder_maintenance_source
    assert "客户素材必须填写客户名称。" in folder_maintenance_source
    assert "projectId 不能为空。" in folder_maintenance_source
    assert "class RawFolderOperations" in folder_operations_source
    assert "def ensure_raw_material_roots" in folder_operations_source
    assert "def deleted_default_folder_paths" in folder_operations_source
    assert "def mark_default_folder_deleted" in folder_operations_source
    assert "def clear_default_folder_deletion" in folder_operations_source
    assert "def ensure_canonical_folder" in folder_operations_source
    assert "def ensure_folder_path" in folder_operations_source
    assert "def ensure_nested_folder" in folder_operations_source
    assert "RawFolderDeletion" in folder_operations_source
    assert "RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS" in folder_operations_source
    assert "canonical_raw_folder_metadata" in folder_operations_source
    assert "raw_material_tier_folder_specs" in folder_operations_source
    assert "migrate_legacy_technical_folders(" in folder_operations_source
    assert "bootstrap_project_material_folder(" in folder_operations_source


def test_material_runtime_tables_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    runtime_source = Path("app/services/material_runtime_tables.py").read_text(encoding="utf-8")
    template_source = Path("app/services/template_store.py").read_text(encoding="utf-8")
    settings_source = Path("app/services/system_settings.py").read_text(encoding="utf-8")
    audit_source = Path("app/services/audit_service.py").read_text(encoding="utf-8")
    auth_source = Path("app/services/auth_service.py").read_text(encoding="utf-8")
    ocr_source = Path("app/services/ocr_service.py").read_text(encoding="utf-8")
    business_gap_planning_source = Path("app/services/business_gap_planning.py").read_text(encoding="utf-8")

    assert "MaterialRuntimeTables" not in material_source
    assert "ensure_material_runtime_tables" in material_source
    assert "async def ensure_material_runtime_tables" not in material_source
    assert "_ensure_runtime_tables" not in material_source
    assert "CREATE TABLE IF NOT EXISTS raw_folder_deletions" not in material_source
    assert "CREATE TABLE IF NOT EXISTS wiki_attachments" not in material_source
    assert "CREATE TABLE IF NOT EXISTS template_assets" not in material_source
    assert "CREATE TABLE IF NOT EXISTS system_users" not in material_source
    assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS meta JSONB" not in material_source
    assert "CREATE TABLE IF NOT EXISTS ocr_candidates" not in material_source
    assert "class MaterialRuntimeTables" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS raw_folder_deletions" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS wiki_attachments" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS template_assets" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS system_users" in runtime_source
    assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS meta JSONB" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS ocr_candidates" in runtime_source
    assert "async def ensure_material_runtime_tables" in runtime_source
    for source in [
        template_source,
        settings_source,
        audit_source,
        auth_source,
        ocr_source,
        business_gap_planning_source,
    ]:
        assert "from app.services.material_runtime_tables import ensure_material_runtime_tables" in source
        assert "from app.services.material_store import ensure_material_runtime_tables" not in source


def test_performance_items_runtime_schema_keeps_partner_name() -> None:
    from app.services.material_runtime_tables import MaterialRuntimeTables

    class SqlCaptureSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: Any) -> None:
            self.statements.append(str(statement))

    session = SqlCaptureSession()
    asyncio.run(MaterialRuntimeTables().ensure(session))

    create_statement = next(
        statement
        for statement in session.statements
        if "CREATE TABLE IF NOT EXISTS performance_items (" in statement
    )
    assert "partner_name VARCHAR(300)" in create_statement
    assert (
        "ALTER TABLE performance_items ADD COLUMN IF NOT EXISTS partner_name VARCHAR(300)"
        in session.statements
    )


def test_material_runtime_tables_repairs_duplicate_folder_paths_before_unique_index() -> None:
    from app.services.material_runtime_tables import MaterialRuntimeTables

    class SqlCaptureSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: Any) -> None:
            self.statements.append(str(statement))

    session = SqlCaptureSession()
    asyncio.run(MaterialRuntimeTables().ensure(session))

    migration_statement = next(
        statement
        for statement in session.statements
        if "CREATE UNIQUE INDEX idx_raw_folders_path" in statement
    )
    file_relink = migration_statement.index("UPDATE raw_files AS target")
    child_relink = migration_statement.index("UPDATE raw_folders AS child")
    duplicate_delete = migration_statement.index("DELETE FROM raw_folders AS target")
    unique_index = migration_statement.index("CREATE UNIQUE INDEX idx_raw_folders_path")

    assert "pg_advisory_xact_lock" in migration_statement
    assert "MIN(id) OVER (PARTITION BY path)" in migration_statement
    assert file_relink < child_relink < duplicate_delete < unique_index


def test_material_file_display_helpers_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    file_source = Path("app/services/file_utils.py").read_text(encoding="utf-8")
    template_source = Path("app/services/template_store.py").read_text(encoding="utf-8")
    settings_source = Path("app/services/system_settings.py").read_text(encoding="utf-8")
    parse_assets_source = Path("app/services/business_parse_assets.py").read_text(encoding="utf-8")
    splitter_source = Path("app/services/business_material_splitter.py").read_text(encoding="utf-8")

    assert safe_segment(" 客户/A 项目.docx ", "fallback.docx") == "客户-A 项目.docx"
    assert format_size_label(7) == "7 B"
    assert format_size_label(1536) == "1.5 KB"
    assert format_size_label(2 * 1024 * 1024) == "2.00 MB"
    assert "def safe_segment" not in material_source
    assert "def size_label" not in material_source
    assert "def now_display" not in material_source
    assert "from app.services.material_store import ensure_material_runtime_tables, size_label" not in template_source
    assert "from app.services.material_store import ensure_material_runtime_tables, safe_segment, size_label" not in settings_source
    assert "from app.services.material_store import safe_segment" not in parse_assets_source
    assert "from app.services.material_store import safe_segment" not in splitter_source
    assert "def safe_segment" in file_source
    assert "def format_size_label" in file_source
    assert "def now_display" in file_source
    assert "from app.services.file_utils import format_size_label as size_label" in template_source
    assert "from app.services.file_utils import format_size_label as size_label" in settings_source
    assert "from app.services.file_utils import safe_segment" in parse_assets_source
    assert "from app.services.file_utils import safe_segment" in splitter_source


def test_material_store_is_thin_operation_facade() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")

    blocked_snippets = [
        "from sqlalchemy",
        "from app.models.materials import",
        "from app.services.minio_client import minio_client",
        "async with async_session",
        "session.execute",
        "select(",
        "session.execute(insert(",
        "session.execute(update(",
        "session.execute(delete(",
        "minio_client.",
        "RawFile(",
        "RawFile.",
        "RawFolder(",
        "RawFolder.",
        "WikiNode",
        "WikiDoc",
        "WikiAttachment",
        "CREATE TABLE",
        "ALTER TABLE",
        "Jsonb",
        "psycopg",
    ]
    for snippet in blocked_snippets:
        assert snippet not in material_source

    expected_operation_calls = [
        "raw_tree_operation(",
        "identity_options_operation(",
        "raw_files_operation(",
        "upload_raw_files(",
        "update_raw_file(",
        "raw_download_file_operation(",
        "wiki_list_operation(",
        "create_wiki_node(",
        "upload_wiki_attachment(",
        "import_generated_wiki_blueprint_operation(",
        "move_raw_file(",
        "move_raw_folder(",
    ]
    for snippet in expected_operation_calls:
        assert snippet in material_source


def test_raw_tree_display_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_raw_tree_operations.py").read_text(encoding="utf-8")
    tree_source = Path("app/services/material_raw_tree.py").read_text(encoding="utf-8")

    assert "raw_tree_operation(" in material_source
    assert "build_raw_tree_payload" not in material_source
    assert "select(RawFile)" not in material_source
    assert "order_by(RawFolder.sort_order, RawFolder.id)" not in material_source
    assert "subtree_file_count" not in material_source
    assert '"directFileCount": direct_file_count' not in material_source
    assert "def raw_tree_operation" in operations_source
    assert "build_raw_tree_payload" in operations_source
    assert "select(RawFile)" in operations_source
    assert "order_by(RawFolder.sort_order, RawFolder.id)" in operations_source
    assert "def build_raw_tree_payload" in tree_source
    assert "subtree_file_count" in tree_source
    assert '"directFileCount": direct_file_count' in tree_source


def test_raw_move_metadata_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    move_source = Path("app/services/material_move_metadata.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_move_operations.py").read_text(encoding="utf-8")

    assert "move_raw_file(" in material_source
    assert "move_raw_folder(" in material_source
    assert "build_raw_move_file_ext_fields" not in material_source
    assert "build_raw_move_folder_file_ext_fields" not in material_source
    assert "build_raw_move_file_ext_fields" in operations_source
    assert "build_raw_move_folder_file_ext_fields" in operations_source
    assert "def move_raw_file" in operations_source
    assert "def move_raw_folder" in operations_source
    assert "folder_id_to_new_path" not in material_source
    assert "folder.path.removeprefix(source.path)" not in material_source
    assert "目标路径存在同名文件" in operations_source
    assert "folder_id_to_new_path" in operations_source
    assert "folder.path.removeprefix(source.path)" in operations_source
    assert '"lastAction": "move-folder"' not in material_source
    assert '"lastAction": "version"' not in material_source
    assert '"lastAction": "move"' not in material_source
    assert '"materialTierLabel": MATERIAL_TIER_LABELS.get' not in material_source
    assert "def build_raw_move_file_ext_fields" in move_source
    assert "def build_raw_move_folder_file_ext_fields" in move_source
    assert "RAW_MOVE_FILE_ACTION" in move_source


def test_raw_folder_move_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    folder_scope_source = Path("app/services/material_folder_scope.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_move_operations.py").read_text(encoding="utf-8")

    assert "is_raw_folder_move_protected_path" not in material_source
    assert "is_raw_folder_move_descendant_target" not in material_source
    assert "is_raw_folder_move_protected_path" in operations_source
    assert "is_raw_folder_move_descendant_target" in operations_source
    assert "bid_type: str" in operations_source
    assert "raw_folder_matches_bid_type(source, bid_type)" in operations_source
    assert "raw_folder_matches_bid_type(target_parent, bid_type)" in operations_source
    assert '"RAW_FOLDER_SCOPE"' in operations_source
    assert 'protected_paths = {"技术标", "商务标"}' not in material_source
    assert 'source_path in protected_paths' not in material_source
    assert "def is_raw_folder_move_protected_path" in folder_scope_source
    assert "def is_raw_folder_move_descendant_target" in folder_scope_source


def test_wiki_node_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    wiki_scope_source = Path("app/services/material_wiki_scope.py").read_text(encoding="utf-8")
    node_source = Path("app/services/material_wiki_node_operations.py").read_text(encoding="utf-8")

    assert "wiki_node_bid_types" not in material_source
    assert "wiki_node_bid_types" in node_source
    assert '[bid_type] if bid_type in {"技术标", "商务标"} else ["通用"]' not in material_source
    assert "def wiki_node_bid_types" in wiki_scope_source
    assert "DEFAULT_WIKI_APPLICABLE_TYPE = GENERAL_BID_TYPE" in wiki_scope_source


def test_wiki_tree_display_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    list_source = Path("app/services/material_wiki_list_operations.py").read_text(encoding="utf-8")
    tree_source = Path("app/services/material_wiki_tree.py").read_text(encoding="utf-8")

    assert "wiki_list_operation(" in material_source
    assert "build_wiki_tree_context" not in material_source
    assert "WikiNode" not in material_source
    assert "WikiDoc" not in material_source
    assert "WikiAttachment" not in material_source
    assert "selectedNode" not in material_source
    assert "tagOptions" not in material_source
    assert "collect_visible" not in material_source
    assert '"icon": "folder" if has_children else "article"' not in material_source
    assert "def wiki_list_operation" in list_source
    assert "build_wiki_tree_context" in list_source
    assert "WikiNode" in list_source
    assert "WikiDoc" in list_source
    assert "WikiAttachment" in list_source
    assert "selectedNode" in list_source
    assert "tagOptions" in list_source
    assert "def build_wiki_tree_context" in tree_source
    assert "collect_visible" in tree_source
    assert '"icon": "folder" if has_children else "article"' in tree_source


def test_wiki_node_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    node_source = Path("app/services/material_wiki_node_operations.py").read_text(encoding="utf-8")

    assert "create_wiki_node(" in material_source
    assert "update_wiki_node(" in material_source
    assert "delete_wiki_node(" in material_source
    assert "refresh_wiki_summary(" in material_source
    assert "move_wiki_node(" in material_source
    assert "新建节点，尚未生成摘要。" not in material_source
    assert "请在此补充节点内容。" not in material_source
    assert "node_depths" not in material_source
    assert "def collect(current: WikiNode" not in material_source
    assert "source.parent_id = new_parent_id" not in material_source
    assert "目标节点不存在。" not in material_source
    assert "def create_wiki_node" in node_source
    assert "def update_wiki_node" in node_source
    assert "def delete_wiki_node" in node_source
    assert "def refresh_wiki_summary" in node_source
    assert "def move_wiki_node" in node_source
    assert "新建节点，尚未生成摘要。" in node_source
    assert "请在此补充节点内容。" in node_source
    assert "node_depths" in node_source
    assert "def collect(current: WikiNode" in node_source
    assert "source.parent_id = new_parent_id" in node_source
    assert "目标节点不存在。" in node_source


def test_wiki_attachment_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    list_source = Path("app/services/material_wiki_list_operations.py").read_text(encoding="utf-8")
    attachment_source = Path("app/services/material_wiki_attachment_operations.py").read_text(encoding="utf-8")

    assert "upload_wiki_attachment(" in material_source
    assert "download_wiki_attachment_content(" in material_source
    assert "delete_wiki_attachment(" in material_source
    assert "wiki_download_attachment_content(self, attachment_id: str) ->" not in material_source
    assert "wiki_download_attachment_content(self, attachment_id: str, bid_type: str)" in material_source
    assert "wiki_attachment_to_dict(" not in material_source
    assert "def _wiki_attachment_key" not in material_source
    assert "def _wiki_attachment_to_dict" not in material_source
    assert "def _purge_wiki_attachment_object" not in material_source
    assert "WIKI_ATTACHMENT_NAME_REQUIRED" not in material_source
    assert "附件文件名不能为空。" not in material_source
    assert "stream.seek(0, 2)" not in material_source
    assert "minio_client.put_object_stream(bucket, key, stream" not in material_source
    assert "wiki_attachment_to_dict(" in list_source
    assert "def upload_wiki_attachment" in attachment_source
    assert "def download_wiki_attachment_content" in attachment_source
    assert "def delete_wiki_attachment" in attachment_source
    assert "def wiki_doc_matches_bid_type" in attachment_source
    assert "WIKI_ATTACHMENT_SCOPE" in attachment_source
    assert "def wiki_attachment_to_dict" in attachment_source
    assert "def purge_wiki_attachment_object" in attachment_source
    assert "def wiki_attachment_key" in attachment_source
    assert "WIKI_ATTACHMENT_NAME_REQUIRED" in attachment_source
    assert "附件文件名不能为空。" in attachment_source
    assert "stream.seek(0, 2)" in attachment_source
    assert "minio_client.put_object_stream(bucket, key, stream" in attachment_source


def test_wiki_import_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    import_source = Path("app/services/material_wiki_import.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_wiki_import_operations.py").read_text(encoding="utf-8")

    assert "import_generated_wiki_blueprint_operation(" in material_source
    assert "import_generated_wiki_blueprint(" in material_source
    assert "bid_type: str" in material_source
    assert "build_generated_wiki_root_spec" not in material_source
    assert "normalize_wiki_import_mode" not in material_source
    assert "AUTO_WIKI_DOC_SUMMARY" not in material_source
    assert "purge_wiki_root" not in material_source
    assert "purge_generated_children" not in material_source
    assert "duplicate_root" not in material_source
    assert "这是系统自动生成的分标类 Wiki 根节点" not in material_source
    assert "Wiki 已重新生成并覆盖" not in material_source
    assert "VALID_WIKI_IMPORT_MODES" not in material_source
    assert "def build_generated_wiki_root_spec" in import_source
    assert "def generated_wiki_import_message" in import_source
    assert "VALID_WIKI_IMPORT_MODES" in import_source
    assert "def import_generated_wiki_blueprint_operation" in operations_source
    assert "build_generated_wiki_root_spec" in operations_source
    assert "normalize_wiki_import_mode" in operations_source
    assert "normalize_wiki_bid_type" in operations_source
    assert "WIKI_IMPORT_SCOPE" in operations_source
    assert "WIKI_IMPORT_BID_TYPE_REQUIRED" in operations_source
    assert "AUTO_WIKI_DOC_SUMMARY" in operations_source
    assert "purge_wiki_root" in operations_source
    assert "sync_children_to_specs" in operations_source
    assert "purge_generated_children" not in operations_source
    assert "duplicate_root" in operations_source
    assert "PLATFORM_WIKI_SECTION_TITLES" in operations_source


def test_raw_update_metadata_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    update_source = Path("app/services/material_update_metadata.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_raw_update_operations.py").read_text(encoding="utf-8")

    assert "update_raw_file(" in material_source
    assert "build_raw_update_file_ext_fields" not in material_source
    assert "RAW_FILE_FOLDER_MISSING" not in material_source
    assert "RAW_FILE_NAME_REQUIRED" not in material_source
    assert "目标目录存在同名文件。" not in material_source
    assert "minio_client.copy_object" not in material_source
    assert "重命名成功" not in material_source
    assert '"businessMaterialKindLabel": BUSINESS_MATERIAL_KIND_LABELS.get' not in material_source
    assert '"lastAction": "update"' not in material_source
    assert "def update_raw_file" in operations_source
    assert "build_raw_update_file_ext_fields" in operations_source
    assert "RAW_FILE_FOLDER_MISSING" in operations_source
    assert "RAW_FILE_NAME_REQUIRED" in operations_source
    assert "目标目录存在同名文件。" in operations_source
    assert "minio_client.copy_object" in operations_source
    assert "重命名成功" in operations_source
    assert "def build_raw_update_file_ext_fields" in update_source
    assert '"lastAction": "update"' in update_source


def test_material_identity_options_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    identity_source = Path("app/services/material_identity_options.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_identity_options_operations.py").read_text(encoding="utf-8")

    assert "identity_options_operation(" in material_source
    assert "build_material_identity_options" not in material_source
    assert "def add_customer" not in material_source
    assert "def add_project" not in material_source
    assert "canonical_customer" not in material_source
    assert "build_project_identity" not in material_source
    assert "SELECT id, payload FROM projects" not in material_source
    assert "def identity_options_operation" in operations_source
    assert "build_material_identity_options" in operations_source
    assert "SELECT id, payload FROM projects" in operations_source
    assert "def build_material_identity_options" in identity_source
    assert "canonical_customer" in identity_source
    assert "build_project_identity" in identity_source


def test_raw_file_filter_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    filter_source = Path("app/services/material_raw_file_filter.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_raw_file_operations.py").read_text(encoding="utf-8")

    assert "raw_files_operation(" in material_source
    assert "build_raw_files_payload" not in material_source
    assert "project_matches" not in material_source
    assert "customer_matches" not in material_source
    assert "raw_file_matches_scope" not in material_source
    assert "selectinload(RawFile.folder)" not in material_source
    assert "RawFolder.path.like" not in material_source
    assert "RawFile.name.ilike" not in material_source
    assert "desc(RawFile.updated_at)" not in material_source
    assert "def build_raw_files_payload" in filter_source
    assert "def raw_file_matches_scope" in filter_source
    assert "project_matches" in filter_source
    assert "customer_matches" in filter_source
    assert "def raw_files_operation" in operations_source
    assert "build_raw_files_payload" in operations_source
    assert "selectinload(RawFile.folder)" in operations_source
    assert "RawFolder.path.like" in operations_source
    assert "RawFile.name.ilike" in operations_source
    assert "desc(RawFile.updated_at)" in operations_source


def test_material_scope_helpers_require_explicit_bid_type() -> None:
    scoped_sources = {
        "material_identity_options.py": Path("app/services/material_identity_options.py").read_text(encoding="utf-8"),
        "material_identity_options_operations.py": Path(
            "app/services/material_identity_options_operations.py"
        ).read_text(encoding="utf-8"),
        "material_raw_file_filter.py": Path("app/services/material_raw_file_filter.py").read_text(encoding="utf-8"),
        "material_raw_file_operations.py": Path("app/services/material_raw_file_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_raw_tree.py": Path("app/services/material_raw_tree.py").read_text(encoding="utf-8"),
        "material_raw_tree_operations.py": Path("app/services/material_raw_tree_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_wiki_scope.py": Path("app/services/material_wiki_scope.py").read_text(encoding="utf-8"),
        "material_wiki_tree.py": Path("app/services/material_wiki_tree.py").read_text(encoding="utf-8"),
        "material_wiki_list_operations.py": Path("app/services/material_wiki_list_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_move_metadata.py": Path("app/services/material_move_metadata.py").read_text(encoding="utf-8"),
        "material_raw_access_operations.py": Path("app/services/material_raw_access_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_raw_lifecycle_operations.py": Path("app/services/material_raw_lifecycle_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_raw_update_operations.py": Path("app/services/material_raw_update_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_move_operations.py": Path("app/services/material_move_operations.py").read_text(encoding="utf-8"),
        "material_store.py": Path("app/services/material_store.py").read_text(encoding="utf-8"),
    }

    for source in scoped_sources.values():
        assert 'bid_type: str = ""' not in source
    assert 'item_bid_type: str = ""' not in scoped_sources["material_identity_options.py"]
    assert 'destination_bid_type: str = ""' not in scoped_sources["material_move_metadata.py"]
    assert "async def raw_tree(self) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_tree(self, *, bid_type: str)" in scoped_sources["material_store.py"]
    assert "raw_tree=lambda: self.raw_tree(bid_type=bid_type)" in scoped_sources["material_store.py"]
    assert "async def raw_create_folder(self, parent_path: str, folder_name: str, *, bid_type: str)" in scoped_sources[
        "material_store.py"
    ]
    assert "async def raw_delete_folder(self, path: str, *, bid_type: str)" in scoped_sources["material_store.py"]
    assert (
        "async def raw_move_folder(self, source_path: str, target_parent_path: str, *, bid_type: str)"
        in scoped_sources["material_store.py"]
    )
    assert "async def raw_delete_file(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_delete_file(self, file_id: str, *, bid_type: str)" in scoped_sources["material_store.py"]
    assert "async def raw_download_file(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_download_content(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_download_cleaned_content(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "raw_file_matches_bid_type" in scoped_sources["material_raw_access_operations.py"]
    assert "raw_file_matches_bid_type" in scoped_sources["material_raw_lifecycle_operations.py"]
    assert "raw_file_matches_bid_type" in scoped_sources["material_raw_update_operations.py"]
    assert "raw_folder_matches_bid_type(parent, bid_type)" in scoped_sources["material_raw_lifecycle_operations.py"]
    assert "raw_folder_matches_bid_type(folder, bid_type)" in scoped_sources["material_raw_lifecycle_operations.py"]
    assert "raw_folder_matches_bid_type" in scoped_sources["material_move_operations.py"]
    assert "raw_folder_matches_bid_type(source, bid_type)" in scoped_sources["material_move_operations.py"]
    assert "raw_folder_matches_bid_type(target_parent, bid_type)" in scoped_sources["material_move_operations.py"]


def test_raw_upload_target_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    target_source = Path("app/services/material_upload_target.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_upload_operations.py").read_text(encoding="utf-8")

    assert "upload_raw_files(" in material_source
    assert "build_raw_upload_target_plan" not in material_source
    assert "resolve_raw_upload_canonical_target" not in material_source
    assert "build_raw_upload_target_plan" in operations_source
    assert "resolve_raw_upload_canonical_target" in operations_source
    assert "classify_material_path" not in material_source
    assert "target_parts = [part for part in target_path.split" not in material_source
    assert "def build_raw_upload_target_plan" in target_source
    assert "def resolve_raw_upload_canonical_target" in target_source
    assert "classify_material_path" in target_source


def test_raw_upload_action_metadata_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    metadata_source = Path("app/services/material_upload_metadata.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_upload_operations.py").read_text(encoding="utf-8")

    assert "upload_raw_files(" in material_source
    assert "build_raw_upload_record_ext_fields" not in material_source
    assert "build_raw_upload_existing_ext_fields" not in material_source
    assert "build_raw_upload_record_ext_fields" in operations_source
    assert "build_raw_upload_existing_ext_fields" in operations_source
    assert "RAW_UPLOAD_CONFLICT_ACTIONS" not in material_source
    assert "RAW_UPLOAD_CONFLICT_ACTIONS" in operations_source
    assert "def upload_raw_files" in operations_source
    assert "RAW_UPLOAD_FILES_REQUIRED" not in material_source
    assert "RAW_UPLOAD_FILES_REQUIRED" in operations_source
    assert "RAW_FILE_TYPE_NOT_ALLOWED" not in material_source
    assert "RAW_FILE_TYPE_NOT_ALLOWED" in operations_source
    assert "file_stream.seek(0, 2)" not in material_source
    assert "file_stream.seek(0, 2)" in operations_source
    assert "build_raw_upload_ext_fields" in operations_source
    assert '"lastAction": "upload"' not in material_source
    assert 'ext["lastAction"] = on_conflict' not in material_source
    assert '"lastOperator": "当前用户"' not in material_source
    assert "RAW_UPLOAD_CONFLICT_ACTIONS" in metadata_source
    assert "def build_raw_upload_record_ext_fields" in metadata_source
    assert "def build_raw_upload_existing_ext_fields" in metadata_source


def test_raw_access_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    access_source = Path("app/services/material_raw_access_operations.py").read_text(encoding="utf-8")

    assert "raw_download_file_operation(" in material_source
    assert "raw_download_content_operation(" in material_source
    assert "raw_cleaned_preview_operation(" in material_source
    assert "raw_download_cleaned_content_operation(" in material_source
    assert "raw_download_cleaned_file_operation(" not in material_source
    assert "def raw_download_cleaned_file(" not in material_source
    assert "def _cleaned_object_key" not in material_source
    assert "hashlib.sha1" not in material_source
    assert "PurePosixPath" not in material_source
    assert "quote(cleaned_file_name)" not in material_source
    assert "RAW_CLEANED_PREVIEW_UNAVAILABLE" not in material_source
    assert "documentKey" not in material_source
    assert "browserFileUrl" not in material_source
    assert "cleaned/content" not in material_source
    assert "def raw_download_file_operation" in access_source
    assert "def raw_download_content_operation" in access_source
    assert "def raw_cleaned_preview_operation" in access_source
    assert "def raw_download_cleaned_content_operation" in access_source
    assert "def raw_download_cleaned_file_operation" not in access_source
    assert "hashlib.sha1" in access_source
    assert "PurePosixPath" in access_source
    assert "quote(cleaned_file_name)" in access_source
    assert "RAW_CLEANED_PREVIEW_UNAVAILABLE" in access_source
    assert "documentKey" in access_source
    assert "browserFileUrl" in access_source
    assert "cleaned/content" in access_source


def test_raw_lifecycle_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    lifecycle_source = Path("app/services/material_raw_lifecycle_operations.py").read_text(encoding="utf-8")

    assert "create_raw_folder(" in material_source
    assert "delete_raw_folder(" in material_source
    assert "delete_raw_file(" in material_source
    assert "retry_clean_raw_file(" not in material_source
    assert "def raw_retry_clean_file(" not in material_source
    assert "RAW_FOLDER_NAME_REQUIRED" not in material_source
    assert "文件夹名称不能为空。" not in material_source
    assert "文件夹创建成功。" not in material_source
    assert "RAW_FOLDER_EXISTS" not in material_source
    assert "parent_path.strip" not in material_source
    assert "RAW_FOLDER_DELETE_PROTECTED" not in material_source
    assert "文件夹删除成功，共删除" not in material_source
    assert "deletedFileCount" not in material_source
    assert "RawFolder.path.startswith" not in material_source
    assert "await self._mark_default_folder_deleted(session, folder_path)" not in material_source
    assert "RAW_FILE_NOT_CLEANABLE" not in material_source
    assert "cleanUpdatedAt" not in material_source
    assert "已重新触发素材清洗。" not in material_source
    assert '"message": "删除成功"' not in material_source
    assert "payload = item.to_dict()" not in material_source
    assert "def create_raw_folder" in lifecycle_source
    assert "def delete_raw_folder" in lifecycle_source
    assert "def delete_raw_file" in lifecycle_source
    assert "def retry_clean_raw_file" not in lifecycle_source
    assert "RAW_FOLDER_NAME_REQUIRED" in lifecycle_source
    assert "文件夹名称不能为空。" in lifecycle_source
    assert "文件夹创建成功。" in lifecycle_source
    assert "RAW_FOLDER_EXISTS" in lifecycle_source
    assert "parent_path_text.strip" in lifecycle_source
    assert "raw_folder_matches_bid_type(parent, bid_type)" in lifecycle_source
    assert "RAW_FOLDER_DELETE_PROTECTED" in lifecycle_source
    assert "raw_folder_matches_bid_type(folder, bid_type)" in lifecycle_source
    assert '"RAW_FOLDER_SCOPE"' in lifecycle_source
    assert "文件夹删除成功，共删除" in lifecycle_source
    assert "deletedFileCount" in lifecycle_source
    assert "RawFolder.path.startswith" in lifecycle_source
    assert "mark_default_folder_deleted(session, folder_path)" in lifecycle_source
    assert "RAW_FILE_NOT_CLEANABLE" not in lifecycle_source
    assert "cleanUpdatedAt" not in lifecycle_source
    assert "已重新触发素材清洗。" not in lifecycle_source
    assert "purge_raw_file_objects(session, item)" in lifecycle_source
    assert '"message": "删除成功"' in lifecycle_source


def test_raw_file_object_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    object_source = Path("app/services/material_raw_object_operations.py").read_text(encoding="utf-8")

    assert "archive_raw_file_version" in material_source
    assert "purge_raw_file_objects" in material_source
    assert "remove_cleaned_object_from_ext" in material_source
    assert "enqueue_cleaning_job" in material_source
    assert "def _archive_raw_file_version" not in material_source
    assert "def _purge_raw_file_objects" not in material_source
    assert "def _remove_cleaned_object_from_ext" not in material_source
    assert "def _enqueue_cleaning_job" not in material_source
    assert "def _raw_object_key" not in material_source
    assert "RawFileVersion(" not in material_source
    assert "select(RawFileVersion)" not in material_source
    assert "minio_client.remove_object" not in material_source
    assert "enqueue_generation_job" not in material_source
    assert "Failed to remove cleaned material object" not in material_source
    assert "Failed to enqueue material cleaning job" not in material_source
    assert "def archive_raw_file_version" in object_source
    assert "def purge_raw_file_objects" in object_source
    assert "def remove_cleaned_object_from_ext" in object_source
    assert "def enqueue_cleaning_job" in object_source
    assert "def raw_object_key" in object_source
    assert "RawFileVersion(" in object_source
    assert "select(RawFileVersion)" in object_source
    assert "minio_client.remove_object" in object_source
    assert "enqueue_generation_job" in object_source
    assert "Failed to remove cleaned material object" in object_source
    assert "Failed to enqueue material cleaning job" in object_source


def test_legacy_structured_material_store_api_is_removed() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")

    assert not Path("app/services/material_structured_operations.py").exists()
    assert "material_structured_operations" not in material_source
    assert "def structured_list(" not in material_source
    assert "def structured_template(" not in material_source
    assert "def structured_create(" not in material_source
    assert "def structured_delete(" not in material_source
    assert "def structured_update(" not in material_source
    assert "def structured_import_preview(" not in material_source
    assert "def structured_confirm_import(" not in material_source
    assert "def structured_import_excel(" not in material_source
    assert "StructuredTable" not in material_source
    assert "StructuredRow" not in material_source
    assert "STRUCTURED_TABLE_INVALID" not in material_source
    assert "STRUCTURED_MATERIAL_NOT_FOUND" not in material_source
    assert "导入模板.xlsx" not in material_source
    assert "待导入模板.xlsx" not in material_source
    assert "Imported" not in material_source
    assert "Deleted" not in material_source
    assert "Updated" not in material_source


def test_legacy_peripheral_structured_material_api_is_removed() -> None:
    peripheral_source = Path("app/services/peripheral.py").read_text(encoding="utf-8")
    template_source = Path("app/services/template_store.py").read_text(encoding="utf-8")

    assert "_structured_items" not in peripheral_source
    assert "_structured_table_options" not in peripheral_source
    assert "_structured_import_history" not in peripheral_source
    assert "_structured_latest_receipt" not in peripheral_source
    assert "def structured_list(" not in peripheral_source
    assert "def structured_template(" not in peripheral_source
    assert "def structured_preview_import(" not in peripheral_source
    assert "def structured_confirm_import(" not in peripheral_source
    assert "def structured_create(" not in peripheral_source
    assert "def structured_update(" not in peripheral_source
    assert "def structured_delete(" not in peripheral_source
    assert "def structured_import_excel(" not in peripheral_source
    assert "materials_structured" not in peripheral_source
    assert "导入结构化素材" not in peripheral_source
    assert "STRUCTURED_MATERIAL_NOT_FOUND" not in peripheral_source
    assert "peripheral_store._structured_table_options" not in template_source
    assert "DEFAULT_EXCEL_TEMPLATE_TABLE_OPTIONS" in template_source
    assert "_excel_table_options" in peripheral_source


def test_turbine_options_are_technical_material_boundary() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    technical_source = Path("app/services/technical_material_store.py").read_text(encoding="utf-8")

    assert "def turbine_model_options" not in material_source
    assert "extract_turbine_model_options_from_xlsx_bytes" not in material_source
    assert "material_model_fit" not in material_source
    assert "normalize_project_turbine_model" not in material_source
    assert "list_technical_turbine_model_options" in technical_source
    assert "material_model_fit" in technical_source
    assert "material_store.turbine_model_options" not in technical_source


def test_technical_raw_files_owns_turbine_model_filtering() -> None:
    async def fake_raw_files(**kwargs):
        assert "turbine_model" not in kwargs
        return {
            "items": [
                {
                    "id": "RAW-MATCH",
                    "name": "EW10.0-220下置 技术参数.docx",
                    "folderPath": "技术标/通用素材",
                },
                {
                    "id": "RAW-CONFLICT",
                    "name": "EW10.0-230上置 技术参数.docx",
                    "folderPath": "技术标/通用素材",
                },
                {
                    "id": "RAW-GENERIC",
                    "name": "通用技术说明.docx",
                    "folderPath": "技术标/通用素材",
                },
            ],
            "total": 3,
            "page": kwargs["page"],
            "pageSize": kwargs["page_size"],
        }

    with patch("app.services.technical_material_store.material_store.raw_files", side_effect=fake_raw_files):
        payload = asyncio.run(
            technical_material_store.raw_files(
                folder_path="技术标/通用素材",
                turbine_model={"model": "EW10.0-220下置"},
                page=1,
                page_size=20,
            )
        )

    assert payload["total"] == 2
    assert [item["id"] for item in payload["items"]] == ["RAW-MATCH", "RAW-GENERIC"]


def test_project_fact_material_download_uses_workspace_material_stores() -> None:
    source = Path("app/services/project_fact_materials.py").read_text(encoding="utf-8")

    assert "from app.services.material_store import material_store" not in source
    assert "business_material_store" in source
    assert "technical_material_store" in source
    assert not re.search(r"(?<![A-Za-z_])material_store\.raw_download", source)


def test_project_fact_material_download_supports_performance_package(tmp_path) -> None:
    from app.services.project_fact_materials import prepare_project_fact_material_files

    async def fake_download_item_attachment(category_id: str, item_id: str, attachment_id: str) -> dict[str, str]:
        assert category_id == "PERCAT-0011"
        assert item_id == "PERITEM-0268"
        assert attachment_id == "PERITEMATT-0118"
        return {
            "fileName": "001-华电新疆喀什_合同.docx",
            "bucket": "mock-bucket",
            "key": "performance-categories/PERCAT-0011/item-contracts/PERITEM-0268/doc.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def fake_download_file(bucket: str, key: str, target_path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"performance-package-docx")

    material_index = [
        {
            "id": "PERITEM-0268",
            "materialId": "PERITEM-0268",
            "categoryId": "PERCAT-0011",
            "name": "华电新疆喀什 2x66 万千瓦",
            "sourceType": "performance_package",
            "candidateType": "performance_item",
            "attachments": [{"id": "PERITEMATT-0118", "itemId": "PERITEM-0268", "categoryId": "PERCAT-0011"}],
        }
    ]

    with patch(
        "app.services.performance_material_resolver.performance_package_service.download_item_attachment",
        side_effect=fake_download_item_attachment,
    ), patch(
        "app.services.project_fact_materials.business_material_store.raw_download_content",
        side_effect=AssertionError("performance package must not use raw material downloads"),
    ), patch(
        "app.services.project_fact_materials.business_material_store.raw_download_cleaned_content",
        side_effect=AssertionError("performance package must not use raw cleaned material downloads"),
    ), patch(
        "app.services.project_fact_materials.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        prepared = prepare_project_fact_material_files(material_index, tmp_path, bid_type="商务标")

    assert prepared[0]["sourceKind"] == "performance_package_item"
    assert prepared[0]["fileName"] == "PERITEM-0268-001-华电新疆喀什_合同.docx"
    assert Path(prepared[0]["path"]).exists()


def test_ocr_routes_are_workspace_scoped() -> None:
    router_source = Path("app/api/router.py").read_text(encoding="utf-8")
    business_source = Path("app/api/routes/business.py").read_text(encoding="utf-8")
    technical_source = Path("app/api/routes/technical.py").read_text(encoding="utf-8")
    ocr_source = Path("app/services/ocr_service.py").read_text(encoding="utf-8")
    bid_ocr_source = Path("app/services/bid_ocr_service.py").read_text(encoding="utf-8")

    assert "ocr" not in router_source
    assert "/api/business/projects/{project_id}/ocr/tasks" in business_source
    assert "/api/technical/projects/{project_id}/ocr/tasks" in technical_source
    assert "business_ocr_service" in business_source
    assert "technical_ocr_service" in technical_source
    assert "self.project_service.ensure_project(project_id)" in bid_ocr_source
    assert "require_any_workspace_project_for_update(" in ocr_source
    assert "from app.services.store import store" not in ocr_source


def test_technical_manual_upload_action_stays_in_technical_actions(tmp_path) -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-UPLOAD",
                    "section": "技术方案",
                    "title": "补充技术说明",
                    "status": "needs_input",
                    "decision": "material_required",
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )
    project = store._require(project_id)

    with patch.object(
        technical_gap_actions_module,
        "technical_workspace_dir",
        return_value=tmp_path / "technical-workspace",
    ):
        payload = technical_gap_actions_module.register_technical_manual_gap_upload(
            project,
            "TG-UPLOAD",
            {
                "files": [{"name": "补充技术说明.txt", "text": "这里是技术标人工补充内容。"}],
                "operator": "技术用户",
            },
            browser_base_url="http://testserver",
            onlyoffice_base_url="http://onlyoffice",
        )

    artifact = payload["artifact"]
    assert payload["item"]["status"] == "resolved"
    assert artifact["source"] == "manual_upload"
    assert artifact["operator"] == "技术用户"
    assert artifact["fileName"].endswith(".docx")
    assert Path(artifact["path"]).exists()
    assert artifact["onlyoffice"]["browserFileUrl"].startswith("http://testserver/api/technical/")


def test_technical_existing_material_action_uses_technical_material_store(tmp_path) -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-MAT",
                    "section": "技术方案",
                    "title": "引用技术素材",
                    "status": "needs_input",
                    "decision": "material_required",
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )
    project = store._require(project_id)

    async def fake_raw_download(material_id: str) -> dict[str, str]:
        assert material_id == "RAW-TECH-001"
        return {
            "bucket": "mock-bucket",
            "key": "technical/RAW-TECH-001-original.docx",
            "fileName": "技术素材原件.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    async def fake_cleaned_download(material_id: str) -> dict[str, str]:
        assert material_id == "RAW-TECH-001"
        return {
            "bucket": "mock-bucket",
            "key": "technical/RAW-TECH-001.docx",
            "fileName": "技术素材.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def fake_download_file(bucket: str, key: str, target_path: Path) -> None:
        assert bucket == "mock-bucket"
        if key == "technical/RAW-TECH-001-original.docx":
            target_path.with_suffix(f"{target_path.suffix}.download").write_bytes(b"partial")
            raise RuntimeError("raw object missing")
        assert key == "technical/RAW-TECH-001.docx"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"technical-material-docx")

    with patch.object(
        technical_gap_actions_module,
        "technical_workspace_dir",
        return_value=tmp_path / "technical-workspace",
    ), patch.object(
        technical_gap_actions_module.technical_material_store,
        "raw_download_cleaned_content",
        side_effect=fake_cleaned_download,
    ), patch.object(
        technical_gap_actions_module.technical_material_store,
        "raw_download_content",
        side_effect=fake_raw_download,
    ), patch.object(
        technical_gap_actions_module.minio_client,
        "download_file",
        side_effect=fake_download_file,
    ):
        prepared = asyncio.run(
            technical_gap_actions_module.prepare_technical_existing_gap_material_files(
                project,
                "TG-MAT",
                {
                    "materials": [
                        {
                            "materialId": "RAW-TECH-001",
                            "materialName": "技术素材.docx",
                            "folderPath": "技术标/通用素材",
                            "materialTier": "standard",
                        }
                    ]
                },
            )
        )
        payload = technical_gap_actions_module.register_technical_existing_gap_material(
            project,
            "TG-MAT",
            {"operator": "技术用户"},
            prepared,
            browser_base_url="http://testserver",
        )

    artifact = payload["artifact"]
    assert prepared[0]["sourceKind"] == "cleaned"
    assert Path(prepared[0]["path"]).exists()
    assert payload["item"]["status"] == "resolved"
    assert artifact["source"] == "material_library"
    assert artifact["materialId"] == "RAW-TECH-001"
    assert artifact["operator"] == "技术用户"
    assert artifact["onlyoffice"]["browserFileUrl"].startswith("http://testserver/api/technical/")


def test_technical_ai_fill_action_stays_in_technical_ai_fill_module(tmp_path) -> None:
    project_id = _seed_technical_gap_project(
        {
            "scopeBoundary": {"readableScopes": []},
            "materialIndex": [],
            "items": [
                {
                    "id": "TG-AI",
                    "section": "技术方案",
                    "title": "技术参数响应",
                    "status": "needs_input",
                    "decision": "fill_required",
                    "usage": "table_fill",
                    "appendixTasks": [
                        {
                            "id": "BLANK-TABLE",
                            "title": "技术参数表",
                            "availableParseFields": [
                                {
                                    "id": "FIELD-001",
                                    "label": "项目名称",
                                    "value": "技术标服务拆分测试项目",
                                }
                            ],
                        }
                    ],
                    "fillTasks": [
                        {
                            "id": "FILL-TABLE",
                            "skill": "bid-tech-table-filler",
                            "status": "pending",
                            "blankSource": {"id": "BLANK-TABLE", "title": "技术参数表"},
                        }
                    ],
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1, "fillableTaskCount": 1},
        }
    )
    project = store._require(project_id)
    project["gap_state"]["projectFactTable"] = {
        "status": "confirmed",
        "fields": [{"label": "项目名称", "value": "技术标服务拆分测试项目", "status": "confirmed"}],
    }

    def fake_table_runner(manifest_path: Path) -> dict[str, object]:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        output_path = Path(manifest["outputFile"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"technical-ai-filled-docx")
        assert manifest["schemaVersion"] == "bid-tech-table-fill-v1"
        assert manifest["projectFactTable"]["status"] == "confirmed"
        return {
            "schema_version": "bid-tech-table-fill-v1",
            "outputFile": str(output_path),
            "unfilledFields": [],
            "evidenceRefs": [{"fieldId": "FIELD-001", "source": "projectFactTable"}],
            "fillReport": {
                "targetFieldCount": 1,
                "filledFieldCount": 1,
                "unfilledFieldCount": 0,
                "semanticCheckCount": 1,
                "semanticFailedCount": 0,
                "semanticValidationRate": 1,
            },
        }

    with patch.object(
        technical_gap_ai_fill_module,
        "technical_workspace_dir",
        return_value=tmp_path / "technical-workspace",
    ), patch.object(
        technical_gap_ai_fill_module,
        "run_technical_table_filler_skill",
        side_effect=fake_table_runner,
    ):
        payload = technical_gap_actions_module.run_technical_ai_fill_for_gap(
            project,
            "TG-AI",
            {"fillTaskId": "FILL-TABLE", "operator": "技术用户"},
            browser_base_url="http://testserver",
        )

    artifact = payload["artifact"]
    assert payload["item"]["status"] == "resolved"
    assert payload["item"]["fillTasks"][0]["status"] == "completed"
    assert artifact["source"] == "ai_fill"
    assert artifact["skill"] == "bid-tech-table-filler"
    assert artifact["operator"] == "技术用户"
    assert artifact["qualityReport"]["status"] == "passed"
    assert Path(artifact["path"]).exists()
    assert artifact["onlyoffice"]["browserFileUrl"].startswith("http://testserver/api/technical/")


def test_technical_gap_fact_table_lookup_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    record = store._require(project_id)
    record["gap_state"]["projectFactTable"] = {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "fields": [{"label": "项目名称", "value": "技术标服务拆分测试项目"}],
        "summary": {"totalCount": 1},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.get_gap_fact_table",
        side_effect=AssertionError("technical_gap_service must not delegate fact lookup back to store"),
        create=True,
    ):
        payload = asyncio.run(technical_gap_service.facts(project_id))

    assert payload["schemaVersion"] == PROJECT_FACT_TABLE_SCHEMA_VERSION
    assert payload["fields"][0]["label"] == "项目名称"


def test_technical_gap_build_facts_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    built_table = {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [{"label": "招标编号", "value": "TECH-001"}],
        "summary": {"totalCount": 1},
    }

    with patch(
        "app.services.store.store.build_gap_fact_table",
        side_effect=AssertionError("technical_gap_service must not delegate fact build back to store"),
        create=True,
    ), patch(
        "app.services.store.store._build_project_fact_table",
        side_effect=AssertionError("technical_gap_service must use fact table helper for fact building"),
        create=True,
    ), patch(
        "app.services.technical_gap_service.build_project_fact_table",
        return_value=built_table,
    ), patch(
        "app.services.technical_gap_service.require_technical_gap_project_for_update",
        wraps=require_technical_gap_project_for_update,
    ) as require_project, patch(
        "app.services.technical_gap_service.persist_technical_gap_project",
        wraps=persist_technical_gap_project,
    ) as persist_project:
        payload = asyncio.run(technical_gap_service.build_facts(project_id))

    assert payload["fields"][0]["label"] == "招标编号"
    require_project.assert_called_once_with(project_id)
    persist_project.assert_called_once()
    assert store._require(project_id)["gap_state"]["projectFactTable"]["fields"][0]["value"] == "TECH-001"


def test_technical_gap_save_facts_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    record = store._require(project_id)
    record["gap_state"]["projectFactTable"] = {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [],
        "summary": {"totalCount": 0},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.save_gap_fact_table",
        side_effect=AssertionError("technical_gap_service must not delegate fact save back to store"),
        create=True,
    ), patch(
        "app.services.store.store._normalize_project_fact_field",
        side_effect=AssertionError("technical_gap_service must use fact table helper for fact normalization"),
        create=True,
    ), patch(
        "app.services.store.store._summarize_project_fact_fields",
        side_effect=AssertionError("technical_gap_service must use fact table helper for fact summaries"),
        create=True,
    ):
        payload = asyncio.run(
            technical_gap_service.save_facts(
                project_id,
                {
                    "fields": [{"label": "投标机型", "value": "WTG-1", "required": True}],
                    "confirm": True,
                    "operator": "技术用户",
                },
            )
        )

    assert payload["status"] == "confirmed"
    assert payload["confirmedBy"] == "技术用户"
    assert payload["fields"][0]["status"] == "confirmed"
    assert store._require(project_id)["gap_state"]["projectFactTable"]["status"] == "confirmed"


def test_technical_gap_detection_stays_out_of_store_private_helpers() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    plan = {
        "items": [
            {
                "id": "TG-1",
                "section": "技术方案",
                "title": "总体方案",
                "status": "needs_input",
                "priority": "high",
                "decision": "material_required",
            }
        ],
        "summary": {"totalTocItems": 1},
    }

    with patch(
        "app.services.store.store.run_gap_detection",
        side_effect=AssertionError("technical_gap_service must not delegate gap detection back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ), patch(
        "app.services.store.store._legacy_gap_items_from_plan",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.legacy_technical_gap_items_from_plan"),
    ), patch(
        "app.services.store.store._build_gap_detection_payload",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.build_technical_gap_detection_payload"),
    ), patch(
        "app.services.store.store._default_review_document_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.default_technical_review_document_state"),
    ), patch(
        "app.services.technical_gap_service.build_technical_gap_plan_for_project",
        return_value=plan,
    ):
        payload = technical_gap_service.run_detection(project_id)

    assert payload["message"] == "缺口识别完成，共识别 1 个目录项。"
    assert store._require(project_id)["gap_state"]["items"][0]["id"] == "TG-1"


def test_technical_gap_filling_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-1",
                    "section": "技术方案",
                    "title": "总体方案",
                    "status": "needs_input",
                    "decision": "material_required",
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )

    with patch(
        "app.services.store.store.get_gap_filling",
        side_effect=AssertionError("technical_gap_service must not delegate gap filling back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ), patch(
        "app.services.store.store._refresh_gap_plan_artifact_urls",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.refresh_technical_gap_plan_artifact_urls"),
    ):
        payload = asyncio.run(technical_gap_service.gaps(project_id, _DummyRequest()))

    assert payload["status"] == "ready"
    assert payload["gapPlan"]["items"][0]["id"] == "TG-1"


def test_technical_gap_update_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-1",
                    "section": "技术方案",
                    "title": "总体方案",
                    "status": "needs_input",
                    "decision": "material_required",
                    "reviewNotes": [],
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )

    with patch(
        "app.services.store.store.update_gap_item",
        side_effect=AssertionError("technical_gap_service must not delegate gap updates back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ), patch(
        "app.services.store.store._find_gap_item",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.find_technical_gap_item"),
    ), patch(
        "app.services.store.store._find_gap_plan_item",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.find_technical_gap_plan_item"),
    ), patch(
        "app.services.store.store._default_review_document_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.default_technical_review_document_state"),
    ):
        payload = asyncio.run(
            technical_gap_service.update_gap(
                project_id,
                "TG-1",
                {"status": "skipped", "reason": "技术标单独确认"},
            )
        )

    assert payload["item"]["status"] == "skipped"
    assert store._require(project_id)["gap_state"]["plan"]["items"][0]["status"] == "ignored"


def test_technical_gap_review_submit_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-1",
                    "section": "技术方案",
                    "title": "总体方案",
                    "status": "ignored",
                    "decision": "material_required",
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )

    with patch(
        "app.services.store.store.submit_gap_review",
        side_effect=AssertionError("technical_gap_service must not delegate review submit back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ):
        payload = asyncio.run(technical_gap_service.submit_review(project_id))

    assert payload["payload"]["submittedForReview"] is True
    assert store._require(project_id)["gap_state"]["submittedForReview"] is True


def test_business_gap_selectable_materials_stays_in_business_service() -> None:
    project = {
        "id": "PRJ-BIZ-SCOPE",
        "bidType": "商务标",
        "business_gap_state": {"recognitionStatus": "completed"},
    }
    picker = {
        "templateIndex": [],
        "materialIndex": [
            {
                "id": "RAW-BIZ-0001",
                "name": "商务资质证书.pdf",
                "folderPath": "商务标/通用素材/资质合规库",
                "materialTier": "standard",
            }
        ],
        "evidenceSegments": [],
        "materialScope": {"paths": ["商务标/通用素材"]},
    }

    with patch("app.services.workspace_project_access.store.get_project_runtime_state", return_value=project), patch(
        "app.services.store.store._ensure_business_gap_state",
        side_effect=AssertionError("business_gap_service must use business_gap_state.ensure_business_gap_state"),
        create=True,
    ), patch(
        "app.services.business_gap_service.build_business_gap_material_picker_index",
        return_value=picker,
    ), patch(
        "app.services.store.store.list_business_gap_selectable_materials",
        side_effect=AssertionError("business_gap_service must not delegate selectable materials back to store"),
        create=True,
    ):
        payload = business_gap_service.selectable_materials("PRJ-BIZ-SCOPE", keyword="资质")

    assert payload["bidType"] == "商务标"
    assert payload["items"][0]["materialId"] == "RAW-BIZ-0001"


def test_business_gap_payload_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "承诺函",
                    "taskType": "attachment",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.get_business_gap_filling",
        side_effect=AssertionError("business_gap_service must not delegate gap payload back to store"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_template_candidates",
        side_effect=AssertionError("business_gap_service must use business_gap_refresh for template refresh"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_material_kind_labels",
        side_effect=AssertionError("business_gap_service must use business_gap_refresh for material kind refresh"),
        create=True,
    ):
        payload = business_gap_service.gaps(project_id, _DummyRequest())

    assert payload["status"] == "completed"
    assert payload["source"]["bidType"] == "商务标"
    assert payload["tasks"][0]["id"] == "BTASK-001"


def test_business_gap_run_detection_stays_in_business_service() -> None:
    store.reset_for_tests()
    project = store.create_project({"name": "商务标缺口识别测试项目", "customerName": "测试业主", "bidType": "商务标"})
    project_id = project["id"]
    record = store._require(project_id)
    record["outline_state"]["reviewStatus"] = "confirmed"
    store._persist_project(record)
    built_plan = {
        "schemaVersion": "bid-business-gap-plan-v1",
        "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
        "tasks": [
            {
                "id": "BTASK-001",
                "title": "投标函",
                "status": "needs_input",
                "decision": "material_required",
            }
        ],
        "moduleGroups": [],
        "planFile": "/tmp/business_gap_plan.json",
    }

    with patch(
        "app.services.store.store.run_business_gap_detection",
        side_effect=AssertionError("business_gap_service must not delegate detection back to store"),
        create=True,
    ), patch(
        "app.services.business_gap_service.build_business_gap_plan_for_project",
        return_value=built_plan,
    ), patch(
        "app.services.business_gap_service.persist_business_gap_project",
        wraps=persist_business_gap_project,
    ) as persist_project:
        payload = business_gap_service.run_detection(project_id)

    assert payload["status"] == "completed"
    assert payload["summary"]["taskCount"] == 1
    assert payload["plan"]["integrity"]["status"] == "blocked"
    assert payload["message"] == "商务标缺口计划生成完成，共 1 个任务。"
    persist_project.assert_called_once()
    stored_state = store._require(project_id)["business_gap_state"]
    assert stored_state["recognitionStatus"] == "completed"
    assert stored_state["planFile"] == "/tmp/business_gap_plan.json"
    assert store._require(project_id)["gap_state"]["recognitionStatus"] == "idle"


def test_business_gap_fact_table_lookup_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "fields": [{"label": "项目名称", "value": "商务标服务拆分测试项目"}],
        "summary": {"totalCount": 1},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.get_business_gap_fact_table",
        side_effect=AssertionError("business_gap_service must not delegate fact lookup back to store"),
        create=True,
    ):
        payload = business_gap_service.facts(project_id)

    assert payload["schemaVersion"] == BUSINESS_FACT_TABLE_SCHEMA_VERSION
    assert payload["fields"][0]["label"] == "项目名称"


def test_business_gap_empty_fact_table_stays_in_fact_table_helper() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store._empty_project_fact_table",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for empty facts"),
        create=True,
    ):
        payload = business_gap_service.facts(project_id)

    assert payload["schemaVersion"] == BUSINESS_FACT_TABLE_SCHEMA_VERSION
    assert payload["status"] == "empty"
    assert payload["summary"]["totalCount"] == 0


def test_business_gap_build_facts_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    built_table = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [{"label": "招标编号", "value": "BIZ-001"}],
        "summary": {"totalCount": 1},
    }

    with patch(
        "app.services.store.store.build_business_gap_fact_table",
        side_effect=AssertionError("business_gap_service must not delegate fact build back to store"),
        create=True,
    ), patch(
        "app.services.store.store._build_project_fact_table",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact building"),
        create=True,
    ), patch(
        "app.services.business_gap_service.build_project_fact_table",
        return_value=built_table,
    ), patch(
        "app.services.business_gap_service.require_business_gap_project_for_update",
        wraps=require_business_gap_project_for_update,
    ) as require_project, patch(
        "app.services.business_gap_service.persist_business_gap_project",
        wraps=persist_business_gap_project,
    ) as persist_project:
        payload = asyncio.run(business_gap_service.build_facts(project_id))

    assert payload["fields"][0]["label"] == "招标编号"
    require_project.assert_called_once_with(project_id)
    persist_project.assert_called_once()
    assert store._require(project_id)["business_gap_state"]["projectFactTable"]["fields"][0]["value"] == "BIZ-001"


def test_business_gap_save_facts_allows_user_add_and_delete_fields() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [
            {"label": "招标项目名称", "value": "", "status": "missing"},
            {"label": "招标编号", "value": "", "status": "missing"},
        ],
        "summary": {"totalCount": 2},
    }
    store._persist_project(record)

    payload = asyncio.run(
        business_gap_service.save_facts(
            project_id,
            {
                "fields": [
                    {"label": "项目名称", "value": "商务标服务拆分测试项目"},
                    {"label": "投标人", "value": "测试投标单位"},
                    {"label": "自定义联系人", "value": "张三"},
                ],
                "confirm": False,
                "operator": "测试用户",
            },
        )
    )

    labels = {field["label"]: field for field in payload["fields"]}
    assert len(payload["fields"]) == 3
    assert payload["fields"][0]["label"] == "招标项目名称"
    assert labels["招标项目名称"]["value"] == "商务标服务拆分测试项目"
    assert labels["投标人"]["value"] == "测试投标单位"
    assert labels["自定义联系人"]["category"] == "人工补充事实"
    assert labels["自定义联系人"]["sourceMode"] == "manual"
    assert "招标编号" not in labels
    assert "项目名称" not in labels


def test_business_fact_table_ignores_empty_turbine_model_dict_and_signature_party_noise() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {
        "id": "PRJ-BIZ-FACT-NOISE",
        "name": "真实样本事实表降噪测试",
        "customerName": "京能集团",
        "bidType": "商务标",
        "turbineModel": {
            "model": "",
            "platform": "",
            "layout": "",
            "status": "manual",
            "aliases": [],
        },
        "parse_result": {
            "status": "completed",
            "structured": {
                "projectFactFields": [
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "山西漳山发电有限责任公司 （盖单位章",
                        "confidence": 0.95,
                    },
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "将在收到异议之日起 3 日内作出答复，作出答复前，将暂停招标投标活动",
                        "confidence": 0.96,
                    },
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "收到澄清后12小时内,逾期未在规定时间内确认的，招标人一律视为已收到",
                        "confidence": 0.97,
                    },
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "在本章第 4.2.1 项规定的投标截止时间(开标时间),通过中国华能集团有限公司电子商务平台公开开标",
                        "confidence": 0.98,
                    },
                ]
            },
        },
    }

    table = build_project_fact_table(project, {"plan": {}})
    labels = {field["label"]: field for field in table["fields"]}
    # 盖章装饰剥离后封面招标人是可信值；句子型噪声仍被拒绝
    assert labels["招标人"]["value"] == "山西漳山发电有限责任公司"
    assert labels["风机型号"]["value"] == ""


def test_business_fact_table_accepts_party_name_with_seal_decoration() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {
        "id": "PRJ-BIZ-FACT-SEAL",
        "name": "盖章尾巴清洗测试",
        "customerName": "京能集团",
        "bidType": "商务标",
        "parse_result": {
            "status": "completed",
            "structured": {
                "projectFactFields": [
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "山西漳山发电有限责任公司 （盖单位章",
                        "confidence": 0.95,
                    }
                ]
            },
        },
    }
    gap_state = {
        "plan": {},
        "projectFactTable": {
            "schemaVersion": "bid-project-fact-table-v1",
            "fields": [
                {
                    "label": "招标人",
                    "value": "京能集团",
                    "status": "candidate",
                    "sourceRefs": [{"type": "project", "field": "customerName", "title": "招标人"}],
                }
            ],
        },
    }

    table = build_project_fact_table(project, gap_state)
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["招标人"]["value"] == "山西漳山发电有限责任公司"


def test_business_fact_table_drops_placeholder_values_on_rebuild() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {
        "id": "PRJ-BIZ-FACT-PLACEHOLDER",
        "name": "占位符清洗测试",
        "bidType": "商务标",
        "parse_result": {
            "status": "completed",
            "structured": {
                "projectFactFields": [
                    {
                        "fieldKey": "projectName",
                        "label": "项目名称",
                        "value": "（项目名称）",
                        "confidence": 0.9,
                    }
                ]
            },
        },
    }
    gap_state = {
        "plan": {},
        "projectFactTable": {
            "schemaVersion": "bid-project-fact-table-v1",
            "fields": [
                {
                    "label": "招标项目名称",
                    "value": "（项目名称）",
                    "status": "candidate",
                    "confidence": 0.86,
                },
                {
                    "label": "招标编号",
                    "value": "ZBA272600801",
                    "status": "candidate",
                    "confidence": 0.9,
                },
            ],
        },
    }

    table = build_project_fact_table(project, gap_state)
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["招标项目名称"]["value"] == "占位符清洗测试"
    assert labels["招标编号"]["value"] == "ZBA272600801"


def test_business_fact_table_uses_shared_bidder_profile() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {"id": "PRJ-BIDDER-PROFILE", "name": "档案测试项目", "bidType": "商务标"}
    with patch(
        "app.services.business_gap_fact_table.load_business_bidder_facts_sync",
        return_value={"投标人地址": "上海市闵行区东川路555号", "投标人电话": "021-00000000"},
    ):
        table = build_project_fact_table(project, {"plan": {}})
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["投标人地址"]["value"] == "上海市闵行区东川路555号"
    assert labels["投标人地址"]["sourceRefs"][0]["type"] == "bidderProfile"
    assert labels["投标人电话"]["value"] == "021-00000000"
    assert labels["投标人"]["value"] == "上海电气风电集团股份有限公司"


def test_business_fact_table_profile_refreshes_unconfirmed_fixed_candidates() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {"id": "PRJ-BIDDER-PROFILE-2", "name": "档案刷新测试", "bidType": "商务标"}
    gap_state = {
        "plan": {},
        "projectFactTable": {
            "schemaVersion": "bid-project-fact-table-v1",
            "fields": [
                {"label": "投标人地址", "value": "旧地址", "status": "candidate"},
                {
                    "label": "投标人电话",
                    "value": "010-11111111",
                    "status": "confirmed",
                    "confirmedAt": "2026-06-01T00:00:00+00:00",
                    "confirmedBy": "人工",
                },
            ],
        },
    }
    with patch(
        "app.services.business_gap_fact_table.load_business_bidder_facts_sync",
        return_value={"投标人地址": "上海市浦东新区新地址1号", "投标人电话": "021-22222222"},
    ):
        table = build_project_fact_table(project, gap_state)
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["投标人地址"]["value"] == "上海市浦东新区新地址1号"
    assert labels["投标人电话"]["value"] == "010-11111111"


def test_business_gap_save_facts_persists_fixed_fields_to_bidder_profile() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    captured: dict[str, object] = {}

    async def fake_store(values, *, updated_by=""):
        captured["values"] = dict(values)
        captured["updated_by"] = updated_by
        return dict(values)

    with patch("app.services.business_gap_service.store_business_bidder_facts", side_effect=fake_store):
        asyncio.run(
            business_gap_service.save_facts(
                project_id,
                {
                    "fields": [
                        {"label": "投标人地址", "value": "上海市闵行区东川路555号"},
                        {"label": "招标项目名称", "value": "某风电项目"},
                        {"label": "自定义联系人", "value": "张三"},
                    ],
                    "confirm": False,
                    "operator": "测试用户",
                },
            )
        )

    assert captured["values"] == {"投标人地址": "上海市闵行区东川路555号"}
    assert captured["updated_by"] == "测试用户"


def test_drop_unconfirmed_generated_artifacts_supersedes_same_target() -> None:
    from app.services.business_gap_service import _drop_unconfirmed_generated_artifacts

    task = {
        "resolvedArtifacts": [
            {"artifactType": "parse_appendix_template", "confirmed": True, "fileName": "APPX-0001.docx"},
            {
                "artifactType": "business_table_fill",
                "confirmed": False,
                "fileName": "投标函-AI填写.docx",
                "target": {"fileName": "投标函.docx"},
            },
            {
                "artifactType": "business_table_fill",
                "confirmed": True,
                "fileName": "投标函-AI填写-旧确认.docx",
                "target": {"fileName": "投标函.docx"},
            },
            {
                "artifactType": "business_table_fill",
                "confirmed": False,
                "fileName": "其他表-AI填写.docx",
                "target": {"fileName": "其他表.docx"},
            },
        ]
    }
    _drop_unconfirmed_generated_artifacts(task, artifact_type="business_table_fill", target_file_name="投标函.docx")
    names = [item["fileName"] for item in task["resolvedArtifacts"]]
    # 同目标未确认的被替换；已确认的与其他目标的保留
    assert "投标函-AI填写.docx" not in names
    assert "投标函-AI填写-旧确认.docx" in names
    assert "其他表-AI填写.docx" in names
    assert "APPX-0001.docx" in names


def test_confirm_generated_artifact_converges_task_to_single_output() -> None:
    from app.services.business_gap_service import (
        _converge_task_to_final_artifact,
        _restore_task_reference_artifacts,
    )

    final = {"artifactId": "BART-1-TBL-2", "artifactType": "business_table_fill", "sourceMode": "generated_by_business_table_fill", "confirmed": True}
    task = {
        "resolvedArtifacts": [
            {"artifactId": "APPX-0001", "artifactType": "parse_appendix_template", "sourceMode": "parsed_from_tender_attachment_template", "confirmed": True},
            {"artifactId": "SEL-1", "artifactType": "selected_material", "sourceMode": "selected_from_business_material_library", "materialUsage": "fill_template", "confirmed": True},
            {"artifactId": "BART-1-TBL-1", "artifactType": "business_table_fill", "sourceMode": "generated_by_business_table_fill", "confirmed": False},
            final,
            {"artifactId": "UP-1", "artifactType": "manual_supplement", "sourceMode": "uploaded_in_business_s3", "confirmed": True},
        ]
    }

    _converge_task_to_final_artifact(task, final)
    resolved_ids = [item["artifactId"] for item in task["resolvedArtifacts"]]
    reference_ids = [item["artifactId"] for item in task["referenceArtifacts"]]
    # 终局产物 + 人工上传留在装配列表；底稿与填写参考素材挪入过程参考；旧生成产物删除
    assert resolved_ids == ["BART-1-TBL-2", "UP-1"]
    assert set(reference_ids) == {"APPX-0001", "SEL-1"}
    assert task["finalArtifactId"] == "BART-1-TBL-2"

    _restore_task_reference_artifacts(task)
    restored_ids = {item["artifactId"] for item in task["resolvedArtifacts"]}
    assert {"BART-1-TBL-2", "UP-1", "APPX-0001", "SEL-1"} <= restored_ids
    assert task["referenceArtifacts"] == []
    assert task["finalArtifactId"] == ""


def test_business_assembly_fact_table_stays_in_fact_table_helper(tmp_path) -> None:
    from app.services import business_assembly

    source = Path("app/services/business_assembly.py").read_text(encoding="utf-8")
    built_table = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": "PRJ-BIZ-ASSEMBLY",
        "status": "draft",
        "fields": [{"label": "项目名称", "value": "商务标装配测试"}],
        "summary": {"totalCount": 1},
    }

    assert "from app.services.store import store" not in source
    with patch(
        "app.services.business_assembly.build_project_fact_table",
        return_value=built_table,
    ):
        path = business_assembly._prepare_project_fact_table(
            {"id": "PRJ-BIZ-ASSEMBLY", "bidType": "商务标"},
            {},
            tmp_path,
        )

    assert json.loads(path.read_text(encoding="utf-8"))["fields"][0]["value"] == "商务标装配测试"


def test_business_gap_save_facts_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [],
        "summary": {"totalCount": 0},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.save_business_gap_fact_table",
        side_effect=AssertionError("business_gap_service must not delegate fact save back to store"),
        create=True,
    ), patch(
        "app.services.store.store._normalize_project_fact_field",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact normalization"),
        create=True,
    ), patch(
        "app.services.store.store._summarize_project_fact_fields",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact summaries"),
        create=True,
    ):
        payload = asyncio.run(
            business_gap_service.save_facts(
                project_id,
                {
                    "fields": [
                        {
                            "label": "投标人",
                            "value": "测试投标单位",
                            "required": True,
                            "confidence": 0.9,
                        }
                    ],
                    "confirm": True,
                    "operator": "测试用户",
                },
            )
        )

    assert payload["status"] == "confirmed"
    assert payload["confirmedBy"] == "测试用户"
    labels = {field["label"]: field for field in payload["fields"]}
    assert len(payload["fields"]) == 1
    assert labels["投标人"]["status"] == "confirmed"
    assert labels["投标人"]["value"] == "测试投标单位"
    assert store._require(project_id)["business_gap_state"]["projectFactTable"]["status"] == "confirmed"


def test_business_gap_update_task_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "可忽略事项",
                    "taskType": "attachment",
                    "decision": "review_required",
                    "status": "review_required",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.update_business_gap_task",
        side_effect=AssertionError("business_gap_service must not delegate task updates back to store"),
        create=True,
    ):
        payload = business_gap_service.update_task(project_id, "BTASK-001", {"status": "ignored", "notes": "无需响应"})

    assert payload["task"]["status"] == "ignored"
    assert payload["task"]["handlingMode"] == "ignored"
    assert payload["plan"]["tocRefs"][0]["status"] == "ready"


def test_business_gap_update_task_template_refresh_stays_in_refresh_helper() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "投标函",
                    "taskType": "form",
                    "decision": "fill_required",
                    "status": "needs_input",
                    "moduleKey": "base_documents_guarantees",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.update_business_gap_task",
        side_effect=AssertionError("business_gap_service must not delegate task updates back to store"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_template_candidates",
        side_effect=AssertionError("business_gap_service must use business_gap_refresh for template refresh"),
        create=True,
    ), patch(
        "app.services.business_gap_service.refresh_template_candidates",
        return_value=True,
    ) as refresh:
        payload = business_gap_service.update_task(project_id, "BTASK-001", {"assemblyMode": "template_fill_docx"})

    refresh.assert_called_once()
    assert payload["task"]["assemblyMode"] == "template_fill_docx"


def test_business_gap_refresh_material_kind_labels_updates_task_records() -> None:
    from app.services.business_gap_refresh import refresh_material_kind_labels

    project = {"id": "PRJ-BIZ-REFRESH", "name": "商务刷新测试", "bidType": "商务标"}
    state = {
        "plan": {
            "tasks": [
                {
                    "id": "BTASK-001",
                    "handlingMode": "manual_select",
                    "candidateMaterials": [{"materialId": "BMAT-001"}],
                    "selectedMaterialRefs": [{"materialId": "BMAT-001"}],
                    "resolvedArtifacts": [{"materialId": "BMAT-001"}],
                }
            ]
        }
    }

    with patch(
        "app.services.business_gap_refresh.build_business_gap_material_picker_index",
        return_value={
            "materialIndex": [
                {
                    "id": "BMAT-001",
                    "businessMaterialKind": "fixed",
                    "businessMaterialKindLabel": "固定素材",
                }
            ]
        },
    ):
        changed = refresh_material_kind_labels(project, state)

    task = state["plan"]["tasks"][0]
    assert changed is True
    assert task["candidateMaterials"][0]["businessMaterialKind"] == "fixed"
    assert task["selectedMaterialRefs"][0]["businessMaterialKindLabel"] == "固定素材"
    assert task["resolvedArtifacts"][0]["businessMaterialKind"] == "fixed"
    assert task["handlingMode"] == "fixed_material"


def test_business_gap_task_state_helpers_stay_in_domain_layer() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material", "manual_upload_required"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store._update_business_gap_toc_ref_statuses",
        side_effect=AssertionError("business_gap_service must use business_gap_domain for toc status updates"),
        create=True,
    ), patch(
        "app.services.store.store._recompute_business_gap_task_after_artifact_change",
        side_effect=AssertionError("business_gap_service must use business_gap_domain for task recompute"),
        create=True,
    ), patch(
        "app.services.store.store._apply_business_task_artifact_intent",
        side_effect=AssertionError("business_gap_service must use business_gap_domain for artifact intent"),
        create=True,
    ), patch(
        "app.services.store.store._finalize_business_gap_plan_update",
        side_effect=AssertionError("business_gap_service must use business_gap_state for plan finalization"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_urls_for_result",
        side_effect=AssertionError("business_gap_service must use business_gap_planning URL refresh directly"),
        create=True,
    ):
        manual_payload = business_gap_service.create_manual_task(
            project_id,
            "TOC-1",
            {"title": "本章节补充说明材料"},
        )
        update_payload = business_gap_service.update_task(
            project_id,
            "BTASK-001",
            {"assemblyMode": "template_fill_docx"},
        )
        upload_payload = business_gap_service.upload_artifact(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            {
                "files": [
                    {
                        "name": "补充承诺函.pdf",
                        "mimeType": "application/pdf",
                        "data": "data:application/pdf;base64," + b64encode(b"%PDF-business-domain").decode("ascii"),
                    }
                ]
            },
        )

    assert manual_payload["task"]["id"].startswith("BTASK-MANUAL-")
    assert update_payload["task"]["fillPlan"]["mode"] == "template_fill_docx"
    assert upload_payload["task"]["status"] == "ready"
    assert upload_payload["artifact"]["sourceMode"] == "uploaded_in_business_s3"


def test_business_gap_upload_artifact_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material", "manual_upload_required"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.upload_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact upload back to store"),
        create=True,
    ):
        payload = business_gap_service.upload_artifact(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            {
                "files": [
                    {
                        "name": "补充承诺函.pdf",
                        "mimeType": "application/pdf",
                        "data": "data:application/pdf;base64," + b64encode(b"%PDF-business-upload").decode("ascii"),
                    }
                ]
            },
        )

    assert payload["task"]["status"] == "ready"
    assert payload["task"]["handlingMode"] == "manual_upload"
    assert payload["artifact"]["sourceMode"] == "uploaded_in_business_s3"
    assert "business-workspace/gaps/uploads" in Path(payload["artifact"]["filePath"]).as_posix()


def test_business_gap_upload_artifact_files_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material", "manual_upload_required"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.upload_business_gap_artifact_bytes",
        side_effect=AssertionError("business_gap_service must not delegate artifact file upload back to store"),
        create=True,
    ):
        payload = business_gap_service.upload_artifact_files(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            [{"name": "补充承诺函.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "rawBytes": b"docx"}],
            operator="测试用户",
        )

    assert payload["task"]["status"] == "ready"
    assert payload["artifact"]["operator"] == "测试用户"
    assert payload["artifact"]["sourceMode"] == "uploaded_in_business_s3"


def test_business_gap_sync_artifact_to_material_stays_in_business_service(tmp_path) -> None:
    artifact_path = tmp_path / "补充承诺函.pdf"
    artifact_path.write_bytes(b"%PDF-business-sync")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "ready"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "ready",
                    "status": "ready",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-SYNC",
                            "fileName": artifact_path.name,
                            "filePath": str(artifact_path),
                            "sourceMode": "uploaded_in_business_s3",
                            "materialSyncStatus": "not_synced",
                            "mimeType": "application/pdf",
                        }
                    ],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    async def fake_raw_upload(**kwargs):
        assert "bid_type" not in kwargs
        assert kwargs["target_path"].startswith(f"商务标/项目素材/{project_id}/")
        assert kwargs["material_tier"] == "project"
        return {
            "items": [
                {
                    "id": "RAW-SYNC-001",
                    "name": "补充承诺函.pdf",
                    "folderPath": kwargs["target_path"],
                    "bidType": "商务标",
                    "materialTier": "project",
                    "projectId": project_id,
                }
            ]
        }

    with patch(
        "app.services.store.store.sync_business_gap_artifact_to_material_library",
        side_effect=AssertionError("business_gap_service must not delegate material sync back to store"),
        create=True,
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_upload",
        side_effect=fake_raw_upload,
    ):
        payload = asyncio.run(
            business_gap_service.sync_artifact_to_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {"artifactId": "ART-SYNC"},
            )
        )

    assert payload["artifact"]["materialSyncStatus"] == "synced_to_project_material"
    assert payload["artifact"]["wikiSyncStatus"] == "wiki_rebuild_required"
    assert payload["material"]["bidType"] == "商务标"
    assert payload["wikiRebuildRequired"] is True


def test_business_gap_ai_draft_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "投标函",
                    "taskType": "form",
                    "decision": "ai_draft_required",
                    "status": "needs_input",
                    "assigneeMode": "ai_draft",
                    "moduleKey": "base_documents_guarantees",
                    "assemblyMode": "ai_draft",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["ai_draft_required"],
                }
            ],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "confirmed",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [
            {"label": "项目名称", "value": "商务标服务拆分测试项目", "status": "confirmed"},
            {"label": "招标编号", "value": "BIZ-001", "status": "confirmed"},
            {"label": "投标人", "value": "测试投标单位", "status": "confirmed"},
        ],
        "summary": {"totalCount": 3, "confirmedCount": 3},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.run_business_gap_ai_draft",
        side_effect=AssertionError("business_gap_service must not delegate AI draft back to store"),
        create=True,
    ), patch(
        "app.services.store.store._fact_table_value_map",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact value maps"),
        create=True,
    ), patch(
        "app.services.store.store._write_business_ai_draft_docx",
        side_effect=AssertionError("business_gap_service must use business_gap_ai_draft for docx generation"),
        create=True,
    ):
        payload = asyncio.run(
            business_gap_service.ai_draft(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {"operator": "测试用户"},
            )
        )

    assert payload["task"]["status"] == "review_required"
    assert payload["artifact"]["sourceMode"] == "generated_by_business_s3_ai_draft"
    assert payload["artifact"]["operator"] == "测试用户"
    assert payload["artifact"]["factTableStatus"] == "confirmed"


def test_business_gap_table_fill_stays_in_business_service(tmp_path) -> None:
    target_path = tmp_path / "投标函模板.docx"
    target_path.write_bytes(b"fake-docx-template")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "投标函",
                    "taskType": "table",
                    "decision": "fill_required",
                    "status": "needs_input",
                    "moduleKey": "structured_response_tables",
                    "assemblyMode": "template_fill_docx",
                    "materialUsage": "fill_table",
                    "templateCandidates": [
                        {
                            "templateId": "TPL-001",
                            "templateName": "投标函模板.docx",
                            "fileName": target_path.name,
                            "filePath": str(target_path),
                            "assemblyMode": "template_fill_docx",
                            "materialUsage": "fill_table",
                            "sourceMode": "project_uploaded_bid_template",
                        }
                    ],
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "confirmed",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [{"label": "项目名称", "value": "商务标服务拆分测试项目", "status": "confirmed"}],
        "summary": {"totalCount": 1, "confirmedCount": 1},
    }
    store._persist_project(record)

    def fake_runner(manifest_path: Path) -> dict[str, object]:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        assert manifest["target"]["templateId"] == "TPL-001"
        output_path = Path(manifest["outputFile"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"filled-docx")
        return {
            "schemaVersion": "bid-business-table-fill-v1",
            "outputFile": str(output_path),
            "fillReport": {"filledFieldCount": 1},
            "unfilledFields": [],
            "evidenceRefs": [],
        }

    with patch(
        "app.services.store.store.run_business_gap_table_fill",
        side_effect=AssertionError("business_gap_service must not delegate table fill back to store"),
        create=True,
    ), patch(
        "app.services.store.store._fact_table_value_map",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact value maps"),
        create=True,
    ), patch(
        "app.services.store.store._business_table_fill_source_materials",
        side_effect=AssertionError("business_gap_service must use business_gap_table_fill for source materials"),
        create=True,
    ), patch(
        "app.services.store.store._prepare_business_table_fill_target",
        side_effect=AssertionError("business_gap_service must use business_gap_table_fill for target prep"),
        create=True,
    ), patch(
        "app.services.store.store._prepare_business_table_fill_sources",
        side_effect=AssertionError("business_gap_service must use business_gap_table_fill for source prep"),
        create=True,
    ), patch(
        "app.services.business_gap_service.run_business_table_fill_skill",
        side_effect=fake_runner,
    ):
        payload = asyncio.run(
            business_gap_service.table_fill(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {"target": {"templateId": "TPL-001"}, "operator": "测试用户"},
            )
        )

    assert payload["task"]["status"] == "review_required"
    assert payload["task"]["handlingMode"] == "ai_table_fill"
    assert payload["artifact"]["sourceMode"] == "generated_by_business_table_fill"
    assert payload["artifact"]["operator"] == "测试用户"


def test_business_table_fill_source_prep_uses_business_material_store(tmp_path) -> None:
    from app.services.business_gap_table_fill import prepare_business_table_fill_sources

    async def fake_cleaned_download(material_id: str) -> dict[str, object]:
        assert material_id == "BMAT-001"
        return {
            "bucket": "bucket",
            "key": "business/BMAT-001.docx",
            "fileName": "商务素材.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def fake_download_file(bucket: str, key: str, target_path: Path) -> None:
        assert bucket == "bucket"
        assert key == "business/BMAT-001.docx"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"business-material")

    with patch(
        "app.services.business_gap_table_fill.business_material_store.raw_download_cleaned_content",
        side_effect=fake_cleaned_download,
    ), patch(
        "app.services.business_gap_table_fill.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        prepared = prepare_business_table_fill_sources(
            [{"id": "BMAT-001", "materialName": "商务素材.docx"}],
            tmp_path,
        )

    assert prepared[0]["sourceKind"] == "cleaned"
    assert Path(prepared[0]["path"]).exists()


def test_business_gap_create_manual_task_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "number": "1.1", "title": "补充说明", "taskIds": [], "status": "empty"}],
            "tasks": [],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.create_business_gap_manual_task",
        side_effect=AssertionError("business_gap_service must not delegate manual task creation back to store"),
        create=True,
    ):
        payload = business_gap_service.create_manual_task(project_id, "TOC-1", {"title": "本章节补充说明材料"})

    assert payload["task"]["sourceType"] == "manual_user"
    assert payload["task"]["tocTarget"]["nodeId"] == "TOC-1"
    assert payload["task"]["status"] == "needs_input"
    assert payload["task"]["id"] in payload["plan"]["tocRefs"][0]["taskIds"]


def test_business_gap_confirm_artifact_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "review_required"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "待确认承诺函",
                    "taskType": "attachment",
                    "decision": "review_required",
                    "status": "review_required",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-001",
                            "fileName": "承诺函.docx",
                            "confirmed": False,
                            "reviewStatus": "pending_review",
                        }
                    ],
                    "riskFlags": ["missing_material", "parser_generated_unconfirmed"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.confirm_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact confirmation back to store"),
        create=True,
    ):
        payload = business_gap_service.confirm_artifact(project_id, "BTASK-001", {"artifactId": "ART-001"})

    assert payload["task"]["status"] == "ready"
    assert payload["artifact"]["confirmed"] is True
    assert payload["artifact"]["reviewStatus"] == "approved"
    assert "missing_material" not in payload["task"]["riskFlags"]


def test_business_gap_remove_artifact_stays_in_business_service(tmp_path) -> None:
    artifact_path = tmp_path / "补料.pdf"
    artifact_path.write_bytes(b"%PDF-manual-upload")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "ready"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工补料",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "ready",
                    "status": "ready",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [{"materialId": "RAW-BIZ-001"}],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-REMOVE",
                            "fileName": artifact_path.name,
                            "filePath": str(artifact_path),
                            "sourceMode": "selected_from_business_material_library",
                            "materialId": "RAW-BIZ-001",
                            "materialSyncStatus": "not_synced",
                            "confirmed": True,
                        }
                    ],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.remove_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact removal back to store"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_urls_for_result",
        side_effect=AssertionError("business_gap_service must use business_gap_planning URL refresh directly"),
        create=True,
    ):
        payload = business_gap_service.remove_artifact(project_id, "BTASK-001", "ART-REMOVE", _DummyRequest())

    assert payload["artifact"]["artifactId"] == "ART-REMOVE"
    assert payload["task"]["resolvedArtifacts"] == []
    assert payload["task"]["selectedMaterialRefs"] == []
    assert not artifact_path.exists()


def test_business_gap_select_material_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "资质文件", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "资质证书",
                    "taskType": "certificate",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "qualification_compliance_certificates",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    async def fake_download_content(material_id: str) -> dict[str, str]:
        return {
            "fileId": material_id,
            "fileName": "商务资质证书.pdf",
            "bucket": "mock-bucket",
            "key": "mock-key",
            "mimeType": "application/pdf",
        }

    def fake_download_file(bucket: str, key: str, target_path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"%PDF-business-material")

    with patch(
        "app.services.store.store.select_business_gap_material",
        side_effect=AssertionError("business_gap_service must not delegate material selection back to store"),
        create=True,
    ), patch(
        "app.services.store.store._record_business_material_feedback",
        side_effect=AssertionError("business_gap_service must use business_gap_state for material feedback"),
        create=True,
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_cleaned_content",
        side_effect=RuntimeError("no cleaned content in this test"),
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_content",
        side_effect=fake_download_content,
    ), patch(
        "app.services.business_gap_service.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        payload = asyncio.run(
            business_gap_service.select_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {
                    "materials": [
                        {
                            "materialId": "RAW-BIZ-001",
                            "materialName": "商务资质证书.pdf",
                            "folderPath": "商务标/通用素材/资质合规库",
                            "materialTier": "standard",
                            "businessMaterialKind": "fixed",
                            "businessMaterialKindLabel": "固定素材",
                        }
                    ]
                },
            )
        )

    assert payload["task"]["status"] == "ready"
    assert payload["task"]["handlingMode"] == "fixed_material"
    assert payload["selectedMaterialRefs"][0]["materialId"] == "RAW-BIZ-001"
    assert payload["artifact"]["sourceMode"] == "selected_from_business_material_library"
    assert payload["artifact"]["businessMaterialKind"] == "fixed"
    feedback = store._require(project_id)["business_gap_state"]["materialFeedback"]
    assert feedback[0]["materialId"] == "RAW-BIZ-001"


def test_business_gap_select_performance_package_uses_performance_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "业绩情况表", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "近年类似项目业绩表",
                    "taskType": "performance",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "performance_cooperation_support",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    async def fake_download_item_attachment(category_id: str, item_id: str, attachment_id: str) -> dict[str, str]:
        assert category_id == "PERCAT-0011"
        assert item_id == "PERITEM-0268"
        assert attachment_id == "PERITEMATT-0118"
        return {
            "fileName": "001-华电新疆喀什_合同.docx",
            "bucket": "mock-bucket",
            "key": "performance-categories/PERCAT-0011/item-contracts/PERITEM-0268/doc.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def fake_download_file(bucket: str, key: str, target_path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"performance-package-docx")

    with patch(
        "app.services.performance_material_resolver.performance_package_service.download_item_attachment",
        side_effect=fake_download_item_attachment,
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_cleaned_content",
        side_effect=AssertionError("performance package must not use raw cleaned material downloads"),
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_content",
        side_effect=AssertionError("performance package must not use raw material downloads"),
    ), patch(
        "app.services.business_gap_service.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        payload = asyncio.run(
            business_gap_service.select_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {
                    "materials": [
                        {
                            "materialId": "PERITEM-0268",
                            "categoryId": "PERCAT-0011",
                            "materialName": "华电新疆喀什 2x66 万千瓦",
                            "folderPath": "业绩库/陆上6MW业绩",
                            "materialTier": "standard",
                            "businessMaterialKind": "performance",
                            "businessMaterialKindLabel": "共用业绩",
                            "sourceType": "performance_package",
                            "candidateType": "performance_item",
                            "attachments": [
                                {
                                    "id": "PERITEMATT-0118",
                                    "categoryId": "PERCAT-0011",
                                    "itemId": "PERITEM-0268",
                                    "attachmentType": "contract_item",
                                    "fileName": "001-华电新疆喀什_合同.docx",
                                }
                            ],
                        }
                    ]
                },
            )
        )

    assert payload["task"]["status"] == "ready"
    assert payload["selectedMaterialRefs"][0]["sourceType"] == "performance_package"
    assert payload["artifact"]["materialSourceType"] == "performance_package"
    assert payload["artifact"]["sourceKind"] == "performance_package_item"
    assert payload["artifact"]["sourceType"] == "performance_package"
    assert "华电新疆喀什_合同" in payload["artifact"]["fileName"]
    assert payload["artifact"]["fileName"].endswith(".docx")


def test_business_gap_select_non_fixed_material_counts_as_manual_supplement() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "资质文件", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "资质证书",
                    "taskType": "certificate",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "qualification_compliance_certificates",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    async def fake_download_content(material_id: str) -> dict[str, str]:
        return {
            "fileId": material_id,
            "fileName": "商务补充材料.pdf",
            "bucket": "mock-bucket",
            "key": "mock-key",
            "mimeType": "application/pdf",
        }

    def fake_download_file(bucket: str, key: str, target_path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"%PDF-business-material")

    with patch(
        "app.services.business_gap_service.business_material_store.raw_download_cleaned_content",
        side_effect=RuntimeError("no cleaned content in this test"),
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_content",
        side_effect=fake_download_content,
    ), patch(
        "app.services.business_gap_service.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        payload = asyncio.run(
            business_gap_service.select_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {
                    "materials": [
                        {
                            "materialId": "RAW-BIZ-OTHER",
                            "materialName": "商务补充材料.pdf",
                            "folderPath": "商务标/通用素材/其他材料",
                            "materialTier": "standard",
                            "businessMaterialKind": "other",
                            "businessMaterialKindLabel": "其他",
                            "handlingMode": "manual_select",
                        }
                    ],
                    "handlingMode": "manual_select",
                },
            )
        )

    assert payload["task"]["status"] == "ready"
    assert payload["task"]["handlingMode"] == "manual_upload"
    assert payload["artifact"]["sourceMode"] == "selected_from_business_material_library"
    assert payload["artifact"]["businessMaterialKind"] == "other"


def test_business_gap_select_template_stays_in_business_service(tmp_path) -> None:
    template_path = tmp_path / "投标函模板.docx"
    template_path.write_bytes(b"fake-docx-template")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "投标函",
                    "taskType": "form",
                    "decision": "fill_required",
                    "status": "needs_input",
                    "moduleKey": "base_documents_guarantees",
                    "assemblyMode": "template_fill_docx",
                    "candidateMaterials": [],
                    "templateCandidates": [
                        {
                            "templateId": "TPL-001",
                            "templateName": "投标函模板.docx",
                            "filePath": str(template_path),
                            "sourceMode": "project_uploaded_bid_template",
                        }
                    ],
                    "resolvedArtifacts": [],
                    "riskFlags": ["template_missing_for_fill"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.select_business_gap_template",
        side_effect=AssertionError("business_gap_service must not delegate template selection back to store"),
        create=True,
    ):
        payload = business_gap_service.select_template(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            {"template": {"templateId": "TPL-001"}},
        )

    assert payload["task"]["status"] == "ready"
    assert payload["artifact"]["templateId"] == "TPL-001"
    assert payload["artifact"]["sourceMode"] == "project_uploaded_bid_template"
    assert "business-workspace/gaps/selected-templates" in Path(payload["artifact"]["filePath"]).as_posix()


def test_business_gap_artifact_lookup_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "ready"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "承诺函",
                    "taskType": "attachment",
                    "decision": "ready",
                    "status": "ready",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-LOOKUP",
                            "fileName": "承诺函.docx",
                            "filePath": "/tmp/承诺函.docx",
                            "sourceMode": "uploaded_in_business_s3",
                        }
                    ],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.get_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact lookup back to store"),
        create=True,
    ):
        payload = business_gap_service.artifact(project_id, "ART-LOOKUP")

    assert payload["artifactId"] == "ART-LOOKUP"
    assert payload["sourceMode"] == "uploaded_in_business_s3"
