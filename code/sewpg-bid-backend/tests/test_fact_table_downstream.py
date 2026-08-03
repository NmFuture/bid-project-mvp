from __future__ import annotations

"""技术标项目事实表下游对接测试：S2 manifest 注入（A1）与素材索引机型过滤（A2）。"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from docx import Document

from app.core.config import settings
from app.services.outline_generation import (
    _prepare_toc_skill_workspace,
    _publish_toc_skill_workspace,
    project_facts_for_manifest,
)
from app.services.technical_gap_planner import (
    _allowed_technical_material_index,
    _fact_table_turbine_model,
    _filter_material_index_by_fact_table,
)


@pytest.fixture()
def workspace_dirs(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "documents_dir", tmp_path / "documents")
    monkeypatch.setattr(settings, "parsed_dir", tmp_path / "parsed")
    settings.ensure_dirs()
    return tmp_path


def _write_docx(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)


def _fact_table() -> dict:
    return {
        "schemaVersion": "bid-project-fact-table-v2",
        "fields": [
            {"label": "投标机型", "value": "EW10.0-220", "status": "confirmed"},
            {"label": "项目名称", "value": "翁牛特旗120万千瓦风电项目", "status": "extracted"},
            {"label": "函件签署日期", "value": "2026年07月23日", "status": "pending_confirmation"},
            {"label": "单机功率曲线考核阈值", "value": "", "status": "unextracted"},
            {"label": "冲突字段", "value": "版本A", "status": "conflict"},
        ],
    }


def _prepare_workspace(workspace_dirs: Path, project: dict) -> dict:
    tender_path = settings.uploads_dir / "P-FACT" / "tender" / "招标文件.docx"
    template_path = settings.uploads_dir / "P-FACT" / "template" / "投标文件-正文.docx"
    _write_docx(tender_path, ["第一章 采购需求", "投标人应提供实施方案。"])
    _write_docx(template_path, ["第一章 投标响应概述", "第二章 实施方案"])
    return _prepare_toc_skill_workspace(
        project_id="P-FACT",
        project=project,
        parse_storage={"combinedTextPath": ""},
        tender_file_records=[{"id": "TEN-1", "name": "招标文件.docx", "path": str(tender_path)}],
        template_file_records=[{"id": "TPL-1", "name": "投标文件-正文.docx", "path": str(template_path)}],
    )


def _base_project() -> dict:
    return {
        "id": "P-FACT",
        "projectCode": "CODE-FACT",
        "name": "事实表对接项目",
        "bidType": "技术标",
        "turbineModel": {"model": "EW10.0-220"},
        "gap_state": {"projectFactTable": _fact_table()},
    }


def test_manifest_injects_project_facts_and_turbine_model(workspace_dirs) -> None:
    workspace = _prepare_workspace(workspace_dirs, _base_project())

    manifest = json.loads((Path(workspace["stagingWorkDir"]) / "s2_input.json").read_text(encoding="utf-8"))
    assert manifest["turbineModel"]["model"] == "EW10.0-220"
    assert manifest["projectFacts"] == {
        "投标机型": "EW10.0-220",
        "项目名称": "翁牛特旗120万千瓦风电项目",
        "函件签署日期": "2026年07月23日",
    }


def test_manifest_omits_facts_and_turbine_model_when_missing(workspace_dirs) -> None:
    project = _base_project()
    project.pop("gap_state")
    project.pop("turbineModel")
    workspace = _prepare_workspace(workspace_dirs, project)

    manifest = json.loads((Path(workspace["stagingWorkDir"]) / "s2_input.json").read_text(encoding="utf-8"))
    assert "projectFacts" not in manifest
    assert "turbineModel" not in manifest


def test_project_facts_for_manifest_only_takes_valued_trusted_statuses() -> None:
    facts = project_facts_for_manifest(_base_project())
    assert "单机功率曲线考核阈值" not in facts  # 无值
    assert "冲突字段" not in facts  # conflict 不注入
    assert facts["投标机型"] == "EW10.0-220"


def test_trusted_manifest_snapshot_covers_injected_keys(workspace_dirs) -> None:
    workspace = _prepare_workspace(workspace_dirs, _base_project())

    # _publish 的可信校验是 current == _trustedManifest：注入键必须在快照内
    current = json.loads((Path(workspace["stagingWorkDir"]) / "s2_input.json").read_text(encoding="utf-8"))
    assert current == workspace["_trustedManifest"]

    # 发布流程不因新键报错，且发布后 manifest 保留 projectFacts / turbineModel
    publish_info = _publish_toc_skill_workspace(workspace, {"status": "completed"})
    published_manifest = json.loads(Path(publish_info["manifestPath"]).read_text(encoding="utf-8"))
    assert published_manifest["projectFacts"]["投标机型"] == "EW10.0-220"
    assert published_manifest["turbineModel"]["model"] == "EW10.0-220"


def test_publish_still_rejects_agent_modified_manifest(workspace_dirs) -> None:
    workspace = _prepare_workspace(workspace_dirs, _base_project())
    manifest_path = Path(workspace["stagingWorkDir"]) / "s2_input.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["projectFacts"] = {"投标机型": "被篡改"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="manifest.*被修改"):
        _publish_toc_skill_workspace(workspace, {"status": "completed"})


def _material_scope() -> dict:
    return {
        "bidType": "技术标",
        "readableScopes": [{"path": "技术标/通用素材", "materialTier": "standard"}],
    }


def _fake_material_items() -> list[dict]:
    return [
        {"id": "RAW-OTHER", "name": "EW5.0-200 运维方案.docx", "folderPath": "技术标/通用素材", "materialTier": "standard"},
        {"id": "RAW-MATCH", "name": "EW10.0-220 运维方案.docx", "folderPath": "技术标/通用素材", "materialTier": "standard"},
        {"id": "RAW-GENERIC", "name": "通用运维方案.docx", "folderPath": "技术标/通用素材", "materialTier": "standard"},
        {"id": "RAW-CUST-GENERIC", "name": "客户通用服务承诺.docx", "folderPath": "技术标/客户定制/华能", "materialTier": "customer"},
    ]


def _run_allowed_index(gap_state, turbine_model=None) -> list[dict]:
    async def fake_raw_files(**kwargs):
        return {"items": [dict(item) for item in _fake_material_items()], "total": 4}

    with patch("app.services.technical_gap_planner.technical_material_store.raw_files", side_effect=fake_raw_files):
        return _allowed_technical_material_index(_material_scope(), turbine_model or {}, gap_state=gap_state)


def test_material_index_tightened_by_fact_table_turbine_model() -> None:
    gap_state = {"projectFactTable": _fact_table()}
    items = _run_allowed_index(gap_state)
    # 标准档严格 match 才保留（generic 剔除）；客户档保留机型无关素材
    assert [item["id"] for item in items] == ["RAW-MATCH", "RAW-CUST-GENERIC"]


def test_material_index_unchanged_without_fact_table() -> None:
    all_ids = ["RAW-OTHER", "RAW-MATCH", "RAW-GENERIC", "RAW-CUST-GENERIC"]
    assert [item["id"] for item in _run_allowed_index(None)] == all_ids
    assert [item["id"] for item in _run_allowed_index({})] == all_ids
    gap_state = {"projectFactTable": {"fields": [{"label": "投标机型", "value": "", "status": "unextracted"}]}}
    assert [item["id"] for item in _run_allowed_index(gap_state)] == all_ids


def test_material_index_not_tightened_when_fact_model_matches_project_model() -> None:
    gap_state = {"projectFactTable": _fact_table()}
    items = _run_allowed_index(gap_state, turbine_model={"model": "EW10.0-220"})
    assert [item["id"] for item in items] == ["RAW-MATCH", "RAW-CUST-GENERIC"]


def test_filter_material_index_by_fact_table_unit() -> None:
    items = _fake_material_items()
    assert _filter_material_index_by_fact_table(items, None) == items
    assert _filter_material_index_by_fact_table(items, {}) == items

    gap_state = {"projectFactTable": _fact_table()}
    filtered = _filter_material_index_by_fact_table(items, gap_state)
    assert [item["id"] for item in filtered] == ["RAW-MATCH", "RAW-CUST-GENERIC"]


def test_fact_table_turbine_model_reads_value_and_tolerates_missing() -> None:
    assert _fact_table_turbine_model({"projectFactTable": _fact_table()})["model"] == "EW10.0-220"
    assert _fact_table_turbine_model(None) == {}
    assert _fact_table_turbine_model({}) == {}
    assert _fact_table_turbine_model({"projectFactTable": {"fields": [{"label": "投标机型", "value": ""}]}}) == {}
