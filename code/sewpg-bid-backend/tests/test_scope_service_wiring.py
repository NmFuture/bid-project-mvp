import asyncio
import re
from pathlib import Path
from unittest.mock import patch
import app.services.business_parse_assets as business_parse_assets_module
from app.services.store import store
from app.services.peripheral import PeripheralError


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
    # 技术标写回走带并发校验的公开 API：后台填写 worker 与页面操作会并发写同一项目，
    # 无条件覆盖会静默吞掉对方的改动。
    assert (
        "persist_workspace_project_state_checked("
        in service_sources[Path("app/services/technical_gap_repository.py")]
    )
    assert "def require_any_workspace_project_for_update" in workspace_access_source
    assert "require_any_workspace_project_for_update(" in service_sources[Path("app/services/ocr_service.py")]
    # 只改自己那几页的模块走按字段写回：整份覆盖会把别人这期间写入的页顶回旧值
    assert "persist_workspace_project_fields(" in service_sources[Path("app/services/ocr_service.py")]
    assert "from app.services.store import store" not in service_sources[Path("app/services/ocr_service.py")]
    assert "persist_workspace_project_fields(" in service_sources[Path("app/services/business_assembly.py")]
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
    assert "persist_workspace_project_fields(" in business_assembly_source
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
    assert "persist_workspace_project_fields(" in tech_assembly_source
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
    assert "persist_workspace_project_fields(" in business_parse_assets_source
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
    assert "persist_workspace_project_fields(" in parse_service_source
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
    assert "force_save_document_state(project, project_id" in document_flow_source
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
    assert "persist_workspace_project_fields(" in directory_flow_source
    assert "project_parse_input_records(" in directory_flow_source
    assert "directory_state_with_rule_evidence(" in directory_flow_source
    assert "start_directory_generation_state(project)" in directory_flow_source
    assert "update_directory_generation_state(project" in directory_flow_source
    assert "fail_directory_generation_state(project" in directory_flow_source
    assert "save_outline_state(project" in directory_flow_source
    assert 'return await self.run_generation(project_id, {"regenerateOutline": True})' in directory_flow_source
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


def test_customer_registry_covers_material_library_folder_names() -> None:
    """客户注册表的规范名必须能对上素材库客户目录名，否则按客户取素材会落空。

    客户/项目档的第 3 级目录是身份目录（material_folder_scope.py 注释），目录名
    即 customerName。2026-08-07 5090 实测素材库客户目录为「华能集团」「国电投」，
    而注册表当时只有华能，且建项目弹窗的硬编码清单写的是「国家电投」——两边对
    不上时 customer_matches 无法命中，用户选了客户却取不到任何素材。
    """
    from app.services.identity import canonical_customer

    # 素材库实有目录名必须能解析出与自身一致的规范名
    for folder_name in ("华能集团", "国电投"):
        resolved = canonical_customer(folder_name)
        assert resolved["customerCanonicalName"] == folder_name, (
            f"素材库目录 {folder_name} 未能解析为同名规范客户"
        )
        assert resolved["customerId"], f"{folder_name} 缺少 customerId"

    # 历史/别名写法必须归一到同一个客户，避免老数据失联
    spic_ids = {
        canonical_customer(name)["customerId"]
        for name in ("国电投", "国家电投", "国家电力投资", "中电投")
    }
    assert spic_ids == {"CUST-SPIC"}, f"国电投别名未归一：{spic_ids}"

    huaneng_ids = {
        canonical_customer(name)["customerId"]
        for name in ("华能", "华能集团", "中国华能")
    }
    assert huaneng_ids == {"CUST-HUANENG"}, f"华能别名未归一：{huaneng_ids}"
