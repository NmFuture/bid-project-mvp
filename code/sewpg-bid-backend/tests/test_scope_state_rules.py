import ast
import json
from pathlib import Path
from openpyxl import Workbook
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
from app.services.bid_runtime_state import (
    ensure_project_runtime_states,
    outline_nodes_from_toc_items,
    recover_parse_result,
)
from app.services.technical_appendix_source_matrix import load_appendix_source_matrix_for_project


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
    # peripheral 已收敛为 PeripheralError/now_day（deadcode-01），不再使用 bid_type
    peripheral_source = Path("app/services/peripheral.py").read_text(encoding="utf-8")
    assert 'bid_type: str = "技术标"' not in peripheral_source
    assert "bid_type: str = TECHNICAL_BID_TYPE" not in peripheral_source
    assert "from app.services.bid_type import" not in peripheral_source
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
