import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
import app.services.technical_gap_service as technical_gap_service_module
import app.services.technical_gap_actions as technical_gap_actions_module
import app.services.technical_gap_ai_fill as technical_gap_ai_fill_module
from app.services.technical_coverage import build_technical_coverage
from app.services.technical_gap_planner import _allowed_technical_material_index
from app.services.technical_gap_review import (
    build_technical_review_document_content,
    build_technical_review_payload,
    confirm_technical_review,
    force_save_technical_review_document,
    prepare_technical_review_document,
    save_technical_review_document_content,
    technical_review_source_file_name,
)
from app.services.technical_gap_state import ensure_technical_review_document_state
from app.services.technical_material_store import technical_material_store


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
                    "name": "EW10.0-220 技术方案.docx",
                    "folderPath": "技术标/标准文件/EW10.0-220上置",
                    "materialTier": "standard",
                    "cleanStatus": "cleaned",
                    "hasCleanedWord": True,
                    "cleanedFileName": "EW10.0-220 技术方案.docx",
                },
                {
                    "id": "RAW-TECH-0002",
                    "name": "技术方案.docx",
                    "folderPath": "技术标/标准文件/EW6.0-200上置",
                    "materialTier": "standard",
                },
                {
                    "id": "RAW-TECH-0003",
                    "name": "通用技术方案.docx",
                    "folderPath": "技术标/标准文件",
                    "materialTier": "standard",
                },
            ],
            "total": 3,
        }

    material_scope = {
        "bidType": "技术标",
        "readableScopes": [
            {
                "path": "技术标/标准文件",
                "materialTier": "standard",
            }
        ],
    }

    with patch("app.services.technical_gap_planner.technical_material_store.raw_files", side_effect=fake_raw_files) as raw_files:
        items = _allowed_technical_material_index(material_scope, {"model": "EW10.0-220上置"})

    assert raw_files.call_count == 1
    # 标准文件池严格 1:1 限定选中机型：其他机型（conflict）与机型无关（generic）都不进池
    assert [item["id"] for item in items] == ["RAW-TECH-0001"]


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
                    },
                    {
                        "id": "RAW-PROJECT-APPENDIX",
                        "name": "附表B.5 培训内容和计划表.docx",
                        "folderPath": "技术标/项目定制/项目全名/附表",
                        "materialTier": "project",
                    },
                    {
                        "id": "RAW-CLIENT-INPUT",
                        "name": "附表C.8 升降机.docx",
                        "folderPath": "技术标/项目定制/项目全名/技术附表输入文件",
                        "materialTier": "project",
                    },
                ],
                "total": 3,
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

    # 项目定制/附表（空副表约定目录）不进正文素材池；
    # 技术附表输入文件（甲方已填附表）保留在索引里，供附表查表替换。
    assert [item["id"] for item in items] == ["RAW-STANDARD", "RAW-CUSTOMER", "RAW-PROJECT", "RAW-CLIENT-INPUT"]
    # 标准文件层按机型目录查询（素材库标准文件目录以机型命名），客户/项目层查各自根。
    assert raw_files.call_args_list[0].kwargs["folder_path"] == "技术标/标准文件/EW10.0-220上置"
    assert raw_files.call_args_list[0].kwargs["turbine_model"]["model"] == "EW10.0-220上置"
    assert raw_files.call_args_list[1].kwargs["folder_path"] == "技术标/客户定制"
    assert raw_files.call_args_list[1].kwargs["customer_name"] == "华能集团"
    assert raw_files.call_args_list[2].kwargs["folder_path"] == "技术标/项目定制"
    assert raw_files.call_args_list[2].kwargs["project_id"] == "MATPRJ-001"


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
    assert "OpencodeEngine" not in document_source
    assert "BusinessDocumentService" not in document_source
    assert "app.services.business_assembly" in business_document_source
    assert "app.services.business_document_editing" in business_document_source
    assert "OpencodeEngine" in business_document_source
    assert "apply_technical_document_format_preset" not in business_document_source
    assert "TECH_FORMAT_PRESETS" not in business_document_source
    assert "app.services.technical_document_format" in technical_document_source
    assert "apply_technical_document_format_preset" in technical_document_source
    assert "app.services.business_assembly" not in technical_document_source
    assert "app.services.business_document_editing" not in technical_document_source
    assert "OpencodeEngine" not in technical_document_source


def test_technical_chat_is_owned_by_technical_chat_service() -> None:
    technical_document_source = Path("app/services/technical_document_service.py").read_text(encoding="utf-8")
    technical_chat_source = Path("app/services/technical_chat_service.py").read_text(encoding="utf-8")
    technical_route_source = Path("app/api/routes/technical.py").read_text(encoding="utf-8")

    assert "OpencodeEngine" not in technical_document_source
    assert "OpencodeEngine" in technical_chat_source
    assert "app.services.technical_chat_service" in technical_route_source
    assert "technical_chat_service.chat" in technical_route_source


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
