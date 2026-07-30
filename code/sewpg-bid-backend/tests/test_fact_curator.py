from __future__ import annotations

"""技术标事实表维护 Skill（方案 B，T5/T6）测试：manifest 组装、回收状态流转、脚本简报、API 链路。"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import BASE_DIR, settings
from app.services import technical_fact_curator as curator
from app.services.store import store
from app.services.technical_fact_field_specs import fillable_specs, load_specs

SCRIPT_PATH = (
    BASE_DIR / "opencode" / "skills" / "bid-tech-fact-curator" / "scripts" / "run_from_manifest.py"
)


def _test_fact_specs() -> dict:
    """build_facts 门控 seed：测试绕过实时表上传，直接注入全局字段清单作为项目 specs。"""
    return {
        "fileName": "测试实时表.xlsx",
        "uploadedAt": "2026-07-27T00:00:00",
        "specs": copy.deepcopy(fillable_specs()),
    }


@pytest.fixture()
def workspace_dirs(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "documents_dir", tmp_path / "documents")
    monkeypatch.setattr(settings, "parsed_dir", tmp_path / "parsed")
    settings.ensure_dirs()
    return tmp_path


def _fields() -> list[dict]:
    return [
        {
            "id": "FACT-0001",
            "key": "招标单机容量出口端mw",
            "label": "招标单机容量（出口端，MW）",
            "value": "",
            "unit": "",
            "status": "unextracted",
            "sourceKind": "tender",
            "needsConfirmation": False,
            "specKey": "T-010",
            "specSeq": 10,
            "sourceRefs": [],
            "notes": "",
        },
        {
            "id": "FACT-0002",
            "key": "年平均风速",
            "label": "参考高度处年平均风速（m/s）",
            "value": "7.36/6.86/7.20 风电场保证年上网电量(MWh)",
            "unit": "m/s",
            "status": "extracted",
            "sourceKind": "material",
            "needsConfirmation": False,
            "specKey": "T-021",
            "specSeq": 21,
            "sourceRefs": [{"type": "materialFact", "materialId": "RAW-1"}],
            "notes": "",
        },
        {
            "id": "FACT-0003",
            "key": "电量承诺函版本",
            "label": "发电小时数/电量承诺函版本",
            "value": "V2 保证值",
            "unit": "",
            "status": "pending_confirmation",
            "sourceKind": "tender",
            "needsConfirmation": True,
            "specKey": "T-030",
            "specSeq": 30,
            "sourceRefs": [],
            "notes": "",
        },
        {
            "id": "FACT-0004",
            "key": "投标机型",
            "label": "投标机型",
            "value": "EW10.0-220",
            "unit": "",
            "status": "confirmed",
            "sourceKind": "platform",
            "needsConfirmation": False,
            "specKey": "T-001",
            "specSeq": 1,
            "sourceRefs": [{"type": "projectTurbineModel", "field": "model"}],
            "notes": "",
        },
    ]


def _table(fields: list[dict] | None = None, status: str = "draft") -> dict:
    fields = fields if fields is not None else _fields()
    return {
        "schemaVersion": "bid-project-fact-table-v2",
        "projectId": "P-CUR",
        "status": status,
        "builtAt": "2026-07-26T00:00:00Z",
        "updatedAt": "2026-07-26T00:00:00Z",
        "confirmedAt": "",
        "confirmedBy": "",
        "fields": fields,
        "summary": {},
    }


def _project() -> dict:
    return {
        "id": "P-CUR",
        "name": "事实表维护测试项目",
        "turbineModel": {"model": "EW10.0-220"},
    }


# ---------------------------------------------------------------- manifest 组装


def test_manifest_targets_buckets(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    gap_state = {"projectFactTable": _table()}

    manifest, manifest_path = curator.build_fact_curator_manifest(_project(), gap_state, {})

    assert manifest_path.is_file()
    assert manifest["schemaVersion"] == "bid-tech-fact-curate-v1"
    # 全量字段带 spec 元数据注入
    assert len(manifest["projectFactTable"]["fields"]) == 4
    field = manifest["projectFactTable"]["fields"][0]
    for meta in ("specKey", "specSeq", "sourceKind", "status", "label", "value", "unit", "needsConfirmation"):
        assert meta in field
    # 三件事分桶：unextracted+tender→fill，extracted→fix，needsConfirmation 非 confirmed→confirmAdvice
    assert manifest["targets"] == {
        "fill": ["招标单机容量出口端mw"],
        "fix": ["年平均风速"],
        "confirmAdvice": ["电量承诺函版本"],
    }
    assert manifest["briefFile"].endswith("fact_curate_brief.json")
    assert manifest["outputFile"].endswith("fact_curate_suggestions.json")


def test_manifest_uses_isolated_run_directory(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    gap_state = {"projectFactTable": _table()}

    first, first_path = curator.build_fact_curator_manifest(_project(), gap_state, {})
    second, second_path = curator.build_fact_curator_manifest(_project(), gap_state, {})

    assert first_path.parent != second_path.parent
    assert Path(first["briefFile"]).parent == first_path.parent
    assert Path(first["outputFile"]).parent == first_path.parent
    assert Path(second["briefFile"]).parent == second_path.parent
    assert Path(second["outputFile"]).parent == second_path.parent


def test_curate_targets_fill_covers_material_and_cert() -> None:
    """补抽范围：招标/素材/证书类未提取字段都进 fill 桶；模板/平台/自动生成类不填。"""
    fields = [
        {"key": "f-tender", "status": "unextracted", "sourceKind": "tender"},
        {"key": "f-material", "status": "unextracted", "sourceKind": "material"},
        {"key": "f-cert", "status": "unextracted", "sourceKind": "cert"},
        {"key": "x-platform", "status": "unextracted", "sourceKind": "platform"},
        {"key": "x-derived", "status": "unextracted", "sourceKind": "derived"},
        {"key": "x-template", "status": "unextracted", "sourceKind": "template"},
    ]

    targets = curator._curate_targets(fields)

    assert targets["fill"] == ["f-tender", "f-material", "f-cert"]


def test_apply_summary_preserves_project_spec_total_and_tracks_built_progress() -> None:
    """Curator 刷新 summary 时不得把项目规则总数改成当前已构建骨架行数。"""
    source_table = _table()
    source_table["summary"] = {"specTotal": 10}
    table, _ = curator.apply_fact_curator_suggestions(
        source_table, [], operator="测试", saved_at="2026-07-27T00:00:00Z"
    )

    summary = table["summary"]
    # 项目规则共 10 条，当前表只构建出 4 条；两个口径不能混用。
    assert summary["specTotal"] == 10
    assert summary["specBuiltTotal"] == 4
    assert summary["specConfirmedCount"] == 1
    assert summary["specPendingConfirmationCount"] == 1
    assert summary["specUnfilledCount"] == 1
    assert summary["specFilledUnconfirmedCount"] == 1
    assert (
        summary["specConfirmedCount"]
        + summary["specPendingConfirmationCount"]
        + summary["specUnfilledCount"]
        + summary["specFilledUnconfirmedCount"]
        == summary["specBuiltTotal"]
    )


def test_manifest_tender_sources_only_existing(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    combined = settings.documents_dir / "P-CUR" / "technical-workspace" / "parse" / "combined.txt"
    combined.parent.mkdir(parents=True, exist_ok=True)
    combined.write_text("招标文件全文：单机容量不小于10MW。", encoding="utf-8")
    project = {
        **_project(),
        "parse_storage": {
            "combinedTextPath": str(combined),
            "structuredResultPath": str(combined.parent / "不存在.json"),
        },
    }

    manifest, _ = curator.build_fact_curator_manifest(project, {"projectFactTable": _table()}, {})

    kinds = [source["kind"] for source in manifest["tenderSources"]]
    assert kinds == ["combinedText"]
    assert manifest["tenderSources"][0]["path"] == str(combined)


def test_manifest_materials_filtered_by_local_path(workspace_dirs, monkeypatch) -> None:
    material_file = workspace_dirs / "material.docx"
    material_file.write_text("占位", encoding="utf-8")
    monkeypatch.setattr(
        curator,
        "project_fact_material_index",
        lambda project, gap_state: [{"id": "RAW-1", "name": "有路径"}, {"id": "RAW-2", "name": "无路径"}],
    )
    monkeypatch.setattr(
        curator,
        "prepare_project_fact_materials",
        lambda project, materials: [
            {"id": "RAW-1", "name": "有路径", "path": str(material_file), "folderPath": "技术标/项目定制", "materialTier": "project"},
            {"id": "RAW-2", "name": "无路径", "path": str(workspace_dirs / "不存在.docx")},
        ],
    )

    manifest, _ = curator.build_fact_curator_manifest(_project(), {"projectFactTable": _table()}, {})

    assert [item["id"] for item in manifest["materials"]] == ["RAW-1"]
    assert manifest["materials"][0]["path"] == str(material_file)


# ---------------------------------------------------------------- 回收状态流转


def _apply(suggestions: list[dict], table: dict | None = None) -> tuple[dict, dict]:
    return curator.apply_fact_curator_suggestions(
        table or _table(), suggestions, operator="测试用户", saved_at="2026-07-26T01:00:00Z"
    )


def test_fill_suggestion_becomes_pending_confirmation() -> None:
    table, report = _apply(
        [
            {
                "fieldKey": "招标单机容量出口端mw",
                "suggestedValue": "10",
                "unit": "MW",
                "evidence": "招标公告：单机容量不小于10MW",
                "confidence": 0.92,
                "action": "fill",
            }
        ]
    )
    field = table["fields"][0]
    assert field["value"] == "10"
    assert field["unit"] == "MW"
    assert field["status"] == "pending_confirmation"
    ref = field["sourceRefs"][-1]
    assert ref["type"] == "factCurator"
    assert ref["action"] == "fill"
    assert ref["confidence"] == 0.92
    assert report["filled"] == ["招标单机容量出口端mw"]
    assert table["summary"]["pendingConfirmationCount"] == 2  # 本字段 + 原 FACT-0003


def test_fix_suggestion_replaces_value_and_keeps_old_in_alternatives() -> None:
    old_value = _fields()[1]["value"]
    table, report = _apply(
        [
            {
                "fieldKey": "年平均风速",
                "suggestedValue": "7.36",
                "unit": "m/s",
                "evidence": "原值为跨列串行，首列 7.36 为本字段值",
                "confidence": 0.78,
                "action": "fix",
            }
        ]
    )
    field = table["fields"][1]
    assert field["value"] == "7.36"
    assert field["status"] == "pending_confirmation"
    assert field["alternatives"][0]["value"] == old_value
    assert field["sourceRefs"][-1]["type"] == "factCurator"
    assert report["fixed"] == ["年平均风速"]


def test_confirm_advice_keeps_existing_value() -> None:
    table, report = _apply(
        [
            {
                "fieldKey": "电量承诺函版本",
                "suggestedValue": "V3 考核值",
                "unit": "",
                "evidence": "承诺函原文口径为 V2 保证值，现值一致",
                "confidence": 0.66,
                "action": "confirm-advice",
            }
        ]
    )
    field = table["fields"][2]
    assert field["value"] == "V2 保证值"  # 有值口径建议不改值
    assert field["status"] == "pending_confirmation"
    assert field["sourceRefs"][-1]["type"] == "factCurator"
    assert field["sourceRefs"][-1]["action"] == "confirm-advice"
    assert report["advised"] == ["电量承诺函版本"]


def test_confirm_advice_with_empty_suggested_value_keeps_evidence() -> None:
    table, report = _apply(
        [
            {
                "fieldKey": "电量承诺函版本",
                "suggestedValue": "",
                "unit": "",
                "evidence": "现值 V2 保证值与承诺函原文口径一致",
                "confidence": 0.88,
                "action": "confirm-advice",
            }
        ]
    )

    field = table["fields"][2]
    assert field["value"] == "V2 保证值"
    assert field["status"] == "pending_confirmation"
    assert field["sourceRefs"][-1]["evidence"] == "现值 V2 保证值与承诺函原文口径一致"
    assert field["updatedBy"] == "测试用户"
    assert report["advised"] == ["电量承诺函版本"]
    assert report["ignored"] == []


def test_confirmed_field_never_overwritten() -> None:
    table, report = _apply(
        [
            {
                "fieldKey": "投标机型",
                "suggestedValue": "EW5.0-200",
                "unit": "",
                "evidence": "试图覆盖已确认字段",
                "confidence": 0.99,
                "action": "fix",
            }
        ]
    )
    field = table["fields"][3]
    assert field["value"] == "EW10.0-220"
    assert field["status"] == "confirmed"
    assert all(ref.get("type") != "factCurator" for ref in field["sourceRefs"])
    assert report["skippedConfirmed"] == ["投标机型"]
    # 表级 summary 也不因 AI 建议出现 confirmed 以外的变化
    assert table["summary"]["confirmedCount"] == 1


def test_not_found_keeps_unextracted_and_writes_notes() -> None:
    table, report = _apply(
        [
            {
                "fieldKey": "招标单机容量出口端mw",
                "suggestedValue": "",
                "unit": "",
                "evidence": "检索招标文件全文未出现单机容量要求",
                "confidence": 0.0,
                "action": "fill",
            }
        ]
    )
    field = table["fields"][0]
    assert field["status"] == "unextracted"
    assert field["value"] == ""
    assert "未找到值" in field["notes"]
    assert "未出现单机容量要求" in field["notes"]
    assert report["notFound"] == ["招标单机容量出口端mw"]


def test_unknown_field_key_ignored_and_never_confirmed_by_curator() -> None:
    table, report = _apply(
        [
            {
                "fieldKey": "不存在的字段",
                "suggestedValue": "1",
                "unit": "",
                "evidence": "",
                "confidence": 0.5,
                "action": "fill",
            }
        ]
    )
    assert report["ignored"] == [{"fieldKey": "不存在的字段", "reason": "fieldKey 与事实表字段不匹配"}]
    # curator 绝不写 confirmed
    assert all(field["status"] != "confirmed" or field["key"] == "投标机型" for field in table["fields"])
    assert table["status"] == "draft"


def test_invalid_action_ignored_with_reason_not_downgraded() -> None:
    table, report = _apply(
        [
            {
                "fieldKey": "招标单机容量出口端mw",
                "suggestedValue": "10",
                "unit": "MW",
                "evidence": "招标公告：单机容量不小于10MW",
                "confidence": 0.9,
                "action": "overwrite",  # 非法 action：不得静默降级为 fill
            }
        ]
    )
    field = table["fields"][0]
    assert field["status"] == "unextracted"  # 字段不被污染
    assert field["value"] == ""
    assert report["filled"] == []
    assert report["ignored"] == [{"fieldKey": "招标单机容量出口端mw", "reason": "非法 action：overwrite"}]


def test_action_must_match_manifest_target_bucket() -> None:
    table, report = curator.apply_fact_curator_suggestions(
        _table(),
        [
            {
                "fieldKey": "招标单机容量出口端mw",
                "suggestedValue": "10",
                "unit": "MW",
                "evidence": "招标公告：单机容量不小于10MW",
                "confidence": 0.9,
                "action": "fix",
            }
        ],
        operator="测试用户",
        saved_at="2026-07-26T01:00:00Z",
        targets={"fill": ["招标单机容量出口端mw"], "fix": [], "confirmAdvice": []},
    )

    assert table["fields"][0]["value"] == ""
    assert table["fields"][0]["status"] == "unextracted"
    assert report["ignored"] == [
        {"fieldKey": "招标单机容量出口端mw", "reason": "action fix 与本轮目标桶不匹配"}
    ]


def test_real_world_key_forms_matched_by_normalization() -> None:
    """PRJ-0007 实测回归：agent 回传的别名/大小写/骨架键形态都要能落表。"""
    fields = [
        {
            "id": "FACT-0090",
            "key": "spec-090",  # 骨架键：label 归一键被占用时的兜底形态
            "label": "单台机组平均可利用率保证值（%）",
            "value": "",
            "unit": "",
            "status": "unextracted",
            "sourceKind": "tender",
            "needsConfirmation": False,
            "specKey": "T-090",
            "specSeq": 90,
            "sourceRefs": [],
            "notes": "",
        },
        {
            "id": "FACT-0042",
            "key": "极端工况-Mx（kNm）",  # 历史构建遗留的大小写混合 key
            "label": "极端工况-Mx（kNm）",
            "value": "",
            "unit": "",
            "status": "unextracted",
            "sourceKind": "tender",
            "needsConfirmation": False,
            "specKey": "T-042",
            "specSeq": 42,
            "sourceRefs": [],
            "notes": "",
        },
    ]
    table, report = _apply(
        [
            {  # agent 意译成别名：经 fact_label_key(label) 归一后命中 spec-090 骨架
                "fieldKey": "单台可利用率",
                "suggestedValue": "97",
                "unit": "%",
                "evidence": "招标文件：单台机组年平均可利用率≥97%",
                "confidence": 0.85,
                "action": "fill",
            },
            {  # agent 回传小写形：命中混合大小写 key
                "fieldKey": "极端工况-mx（knm）",
                "suggestedValue": "12500",
                "unit": "kNm",
                "evidence": "技术规范书极端工况表",
                "confidence": 0.7,
                "action": "fill",
            },
        ],
        table=_table(fields),
    )
    by_key = {field["key"]: field for field in table["fields"]}
    assert by_key["spec-090"]["value"] == "97"
    assert by_key["spec-090"]["status"] == "pending_confirmation"
    assert by_key["极端工况-Mx（kNm）"]["value"] == "12500"
    assert by_key["极端工况-Mx（kNm）"]["status"] == "pending_confirmation"
    assert sorted(report["filled"]) == ["单台可利用率", "极端工况-mx（knm）"]
    assert report["ignored"] == []

    # 骨架键原样 echo 也能精确命中
    table2, report2 = _apply(
        [
            {
                "fieldKey": "spec-090",
                "suggestedValue": "",
                "unit": "",
                "evidence": "招标文件全文未出现可利用率要求",
                "confidence": 0.0,
                "action": "fill",
            }
        ],
        table=_table(fields),
    )
    field = table2["fields"][0]
    assert field["status"] == "unextracted"
    assert "未找到值" in field["notes"]
    assert report2["notFound"] == ["spec-090"]


def test_confirmed_table_downgraded_when_new_pending_field() -> None:
    fields = _fields()
    for field in fields:
        if field["key"] == "招标单机容量出口端mw":
            field["status"] = "missing_source"  # 终态之一，表级可 confirmed
    table, _ = _apply(
        [
            {
                "fieldKey": "招标单机容量出口端mw",
                "suggestedValue": "10",
                "unit": "MW",
                "evidence": "招标公告：单机容量不小于10MW",
                "confidence": 0.9,
                "action": "fill",
            }
        ],
        table=_table(fields, status="confirmed"),
    )
    assert table["fields"][0]["status"] == "pending_confirmation"
    assert table["status"] == "draft"  # 出现新的非终态字段，表级降回 draft 待人工
    assert table["confirmedAt"] == ""


# ---------------------------------------------------------------- 建议回收解析


def test_load_suggestions_prefers_output_file(workspace_dirs, monkeypatch) -> None:
    output = workspace_dirs / "suggestions.json"
    output.write_text(
        json.dumps(
            {
                "schema": "bid-tech-fact-curate-v1",
                "suggestions": [
                    {"fieldKey": "A", "suggestedValue": "1", "action": "fill", "confidence": 1.5},
                    {"fieldKey": "", "suggestedValue": "x"},  # 无 fieldKey 被丢弃
                    "非字典条目",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    suggestions = curator.load_fact_curator_suggestions(
        {"suggestions": [{"fieldKey": "INLINE", "suggestedValue": "2"}]},
        {"outputFile": str(output)},
    )
    assert suggestions == [
        {"fieldKey": "A", "suggestedValue": "1", "unit": "", "evidence": "", "confidence": 1.0, "action": "fill"}
    ]


def test_load_suggestions_falls_back_to_inline(workspace_dirs) -> None:
    suggestions = curator.load_fact_curator_suggestions(
        {"suggestions": [{"fieldKey": "INLINE", "suggestedValue": "2", "action": "fix"}]},
        {"outputFile": str(workspace_dirs / "不存在.json")},
    )
    assert suggestions[0]["fieldKey"] == "INLINE"
    assert suggestions[0]["action"] == "fix"


def test_run_skill_supervises_factcurate_without_early_return(tmp_path, monkeypatch) -> None:
    """factcurate 只传 early_tool_command 做轮询 idle 监管，不传等待文件：
    建议文件由 LLM 多轮迭代写出（先草稿后填值），提前返回会回收草稿并孤儿化会话。"""
    manifest_path = tmp_path / "fact_curate_input.json"
    manifest_path.write_text(
        json.dumps({"schemaVersion": "bid-tech-fact-curate-v1", "outputFile": str(tmp_path / "out.json")}, ensure_ascii=False),
        encoding="utf-8",
    )
    calls: dict = {}

    class FakeClient:
        def run_bid_tech_fact_curator_with_trace(self, prompt: str, **kwargs) -> dict:
            calls.update(kwargs)
            return {"schema": "bid-tech-fact-curate-v1"}

    monkeypatch.setattr(curator, "OpencodeClient", lambda: FakeClient())

    curator.run_technical_fact_curator_skill(manifest_path)

    assert calls["early_tool_command"] == "factcurate"
    assert "early_tool_wait_file" not in calls


def test_run_clears_stale_suggestions_before_skill(workspace_dirs, monkeypatch) -> None:
    """上一轮残留的 suggestions 必须先清掉：会话未能写出新文件时，残留 outputFile
    会被当作本轮结果回收（表现为建议数与上次完全相同）。"""
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    gap_state = {"projectFactTable": _table()}
    run_dir = curator._curator_work_dir(_project()) / "run-stale-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(curator, "_curator_run_dir", lambda project: run_dir)
    stale_output = run_dir / "fact_curate_suggestions.json"
    stale_output.write_text(json.dumps({"suggestions": [{"fieldKey": "STALE"}]}), encoding="utf-8")
    seen: dict = {}

    def fake_skill(manifest_path):
        seen["output_existed_at_skill_start"] = stale_output.exists()
        return {"schema": "bid-tech-fact-curate-v1", "suggestions": [], "opencodeOutput": {}}

    monkeypatch.setattr(curator, "run_technical_fact_curator_skill", fake_skill)

    curator.run_fact_curator_for_project(_project(), gap_state, {})

    assert seen["output_existed_at_skill_start"] is False


# ---------------------------------------------------------------- skill 脚本简报


def test_brief_script_flags_dirty_value_and_finds_snippets(tmp_path) -> None:
    combined = tmp_path / "combined.txt"
    combined.write_text("招标文件全文：招标单机容量（出口端）不小于10MW，塔筒型式见技术规范书。", encoding="utf-8")
    brief_file = tmp_path / "brief.json"
    manifest = {
        "schemaVersion": "bid-tech-fact-curate-v1",
        "projectId": "P-CUR",
        "projectFactTable": {"fields": _fields()},
        "targets": {"fill": ["招标单机容量出口端mw"], "fix": ["年平均风速"], "confirmAdvice": []},
        "tenderSources": [{"kind": "combinedText", "path": str(combined)}],
        "materials": [],
        "briefFile": str(brief_file),
        "outputFile": str(tmp_path / "suggestions.json"),
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--manifest", str(manifest_path), "--response", "summary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["schema"] == "bid-tech-fact-curate-v1"
    assert summary["counts"] == {"fill": 1, "fix": 1, "confirmAdvice": 0}
    assert "年平均风速" in summary["flaggedFields"]

    brief = json.loads(brief_file.read_text(encoding="utf-8"))
    by_key = {field["fieldKey"]: field for field in brief["fields"]}
    # 串行脏数据被机械标记
    assert "serial-text" in by_key["年平均风速"]["flags"]
    # fill 字段从招标文件全文检索到候选片段
    snippets = by_key["招标单机容量出口端mw"]["snippets"]
    assert snippets and "单机容量" in snippets[0]["text"]


# ---------------------------------------------------------------- API 链路（mock opencode）


class FactCurateApiTests(unittest.TestCase):
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

    def _create_project(self) -> str:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": "事实表维护API测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        project_id = response.json()["id"]
        project = store._require(project_id)
        project["identity"] = {"owner": "测试业主", "customerName": "测试业主"}
        project["gap_state"] = {
            "recognitionStatus": "completed",
            "recognizedAt": "2026-07-26T00:00:00",
            "submittedForReview": False,
            "reviewConfirmed": False,
            "reviewedAt": "",
            "items": [],
            "submissions": [],
            "plan": {},
            "planFile": "",
            "integrity": {},
            "projectFactTable": {},
            "factSpecs": _test_fact_specs(),
        }
        store._persist_project(project)
        return project_id

    def test_curate_endpoint_applies_suggestions(self) -> None:
        project_id = self._create_project()
        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)
        fields = build_response.json()["fields"]

        fill_target = next(
            field for field in fields
            if field.get("status") == "unextracted" and field.get("sourceKind") == "tender"
        )
        confirmed_target = next(field for field in fields if str(field.get("value") or "").strip())
        patch_response = self.client.patch(
            f"/api/technical/projects/{project_id}/gaps/facts/{confirmed_target['id']}",
            json={"operator": "测试用户"},
        )
        self.assertEqual(patch_response.status_code, 200, patch_response.text)

        suggestions = [
            {
                "fieldKey": fill_target["key"],
                "suggestedValue": "按招标文件要求",
                "unit": "",
                "evidence": "mock 证据",
                "confidence": 0.8,
                "action": "fill",
            },
            {
                "fieldKey": confirmed_target["key"],
                "suggestedValue": "试图覆盖",
                "unit": "",
                "evidence": "mock 证据",
                "confidence": 0.9,
                "action": "fix",
            },
        ]

        def fake_skill(manifest_path: Path) -> dict:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            Path(manifest["outputFile"]).write_text(
                json.dumps({"schema": "bid-tech-fact-curate-v1", "suggestions": suggestions}, ensure_ascii=False),
                encoding="utf-8",
            )
            return {"schema": "bid-tech-fact-curate-v1", "suggestionsPath": manifest["outputFile"]}

        with patch.object(curator, "run_technical_fact_curator_skill", side_effect=fake_skill):
            response = self.client.post(
                f"/api/technical/projects/{project_id}/gaps/facts/curate",
                json={"operator": "测试用户"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        report = payload["curateReport"]
        self.assertEqual(report["filled"], [fill_target["key"]])
        self.assertEqual(report["skippedConfirmed"], [confirmed_target["key"]])
        # message 按 report 实际计数给出，不空喊"已置为待人工确认"
        self.assertIn("补抽 1 条", payload["message"])
        self.assertIn("已确认跳过 1 条", payload["message"])

        table = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        by_key = {field["key"]: field for field in table["fields"]}
        filled = by_key[fill_target["key"]]
        self.assertEqual(filled["value"], "按招标文件要求")
        self.assertEqual(filled["status"], "pending_confirmation")
        self.assertEqual(filled["sourceRefs"][-1]["type"], "factCurator")
        confirmed = by_key[confirmed_target["key"]]
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["value"], confirmed_target["value"])

    def test_curate_endpoint_requires_completed_recognition(self) -> None:
        project_id = self._create_project()
        project = store._require(project_id)
        project["gap_state"]["recognitionStatus"] = "pending"
        store._persist_project(project)

        response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/curate", json={})
        self.assertEqual(response.status_code, 400, response.text)

    def test_curate_endpoint_opencode_failure_returns_400_and_table_untouched(self) -> None:
        project_id = self._create_project()
        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)
        before = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()

        with patch.object(
            curator,
            "run_technical_fact_curator_skill",
            side_effect=RuntimeError("futurecode 创建 session 失败：mock"),
        ):
            response = self.client.post(
                f"/api/technical/projects/{project_id}/gaps/facts/curate",
                json={"operator": "测试用户"},
            )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("mock", response.json()["detail"])
        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        # opencode 抛错时表不被污染：字段值与状态逐项一致
        self.assertEqual(
            [(field["key"], field["value"], field["status"]) for field in after["fields"]],
            [(field["key"], field["value"], field["status"]) for field in before["fields"]],
        )

    def test_curate_endpoint_does_not_overwrite_concurrent_manual_edit(self) -> None:
        project_id = self._create_project()
        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)
        target = build_response.json()["fields"][0]

        def fake_run(project_snapshot, gap_state_snapshot, data):
            latest = store._require(project_id)
            latest_table = latest["gap_state"]["projectFactTable"]
            latest_table["fields"][0]["value"] = "人工运行中修改"
            latest_table["fields"][0]["status"] = "extracted"
            latest_table["updatedAt"] = "2026-07-30T12:00:00Z"
            store._persist_project(latest)

            stale_result = copy.deepcopy(gap_state_snapshot["projectFactTable"])
            stale_result["fields"][0]["value"] = "AI 旧快照结果"
            return stale_result, {"counts": {}, "ignored": []}

        with patch(
            "app.services.technical_gap_service.run_fact_curator_for_project",
            side_effect=fake_run,
        ):
            response = self.client.post(
                f"/api/technical/projects/{project_id}/gaps/facts/curate",
                json={"operator": "测试用户"},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("本次结果未覆盖保存", response.json()["detail"])
        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        by_id = {field["id"]: field for field in after["fields"]}
        self.assertEqual(by_id[target["id"]]["value"], "人工运行中修改")


# ---------------------------------------------------------------- T3 定向增强


def test_manifest_fields_carry_reference_file_and_material_class(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    spec = next(
        item
        for item in load_specs()
        if "风资源" in str(item.get("referenceFile") or "") and "\n" not in str(item.get("referenceFile") or "")
    )
    fields = _fields()
    fields[0]["specKey"] = str(spec.get("key") or "")
    fields[0]["specSeq"] = 0
    fields[1]["specKey"] = "不存在的spec键"
    fields[1]["specSeq"] = int(spec.get("seq") or 0)  # specKey 匹配不上按 specSeq 兜底
    fields[2]["specKey"] = "不存在的spec键"
    fields[2]["specSeq"] = 0

    manifest, _ = curator.build_fact_curator_manifest(_project(), {"projectFactTable": _table(fields)}, {})

    manifest_fields = manifest["projectFactTable"]["fields"]
    assert manifest_fields[0]["referenceFile"] == str(spec.get("referenceFile") or "")
    assert manifest_fields[0]["materialClass"] == "wind_resource"
    assert manifest_fields[1]["referenceFile"] == str(spec.get("referenceFile") or "")
    assert manifest_fields[1]["materialClass"] == "wind_resource"
    # 关联不上 spec 的字段给空串，不臆造
    assert manifest_fields[2]["referenceFile"] == ""
    assert manifest_fields[2]["materialClass"] == ""


def _stub_prepare(workspace_dirs: Path, monkeypatch) -> None:
    def fake_prepare(project: dict, materials: list[dict]) -> list[dict]:
        prepared = []
        for index, material in enumerate(materials):
            path = workspace_dirs / f"material-{material.get('id') or index}.docx"
            path.write_text("占位", encoding="utf-8")
            prepared.append({**material, "path": str(path)})
        return prepared

    monkeypatch.setattr(curator, "prepare_project_fact_materials", fake_prepare)


def test_manifest_materials_annotated_with_class_home_project(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(
        curator,
        "project_fact_material_index",
        lambda project, gap_state: [
            {"id": "RAW-OWN", "name": "塔架与基础工程量.xlsx", "folderPath": "技术标/项目定制/事实表维护测试项目"},
        ],
    )
    # 无缺失类别：不注入跨项目候选
    monkeypatch.setattr(
        curator,
        "build_fact_material_check",
        lambda project, gap_state: {"classes": [], "summary": {"missingClasses": [], "affectedFieldCount": 0}},
    )
    _stub_prepare(workspace_dirs, monkeypatch)

    manifest, _ = curator.build_fact_curator_manifest(_project(), {"projectFactTable": _table()}, {})

    assert len(manifest["materials"]) == 1
    material = manifest["materials"][0]
    assert material["materialClass"] == "tower_quantity"
    assert material["homeProject"] == "事实表维护测试项目"
    assert material["crossProject"] is False


def test_manifest_injects_cross_project_candidates_for_missing_classes(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(
        curator,
        "project_fact_material_index",
        lambda project, gap_state: [
            {"id": "RAW-OWN", "name": "塔架与基础工程量.xlsx", "folderPath": "技术标/项目定制/事实表维护测试项目"},
        ],
    )
    monkeypatch.setattr(
        curator,
        "build_fact_material_check",
        lambda project, gap_state: {
            "classes": [
                {"class": "tower_quantity", "missing": False, "crossProjectCandidates": []},
                {
                    "class": "wind_resource",
                    "missing": True,
                    "crossProjectCandidates": [
                        {
                            "id": f"RAW-X{i}",
                            "name": f"乙项目风资源报告{i}.docx",
                            "folderPath": "技术标/项目定制/乙项目",
                            "homeProject": "乙项目",
                        }
                        for i in range(4)
                    ],
                },
            ],
            "summary": {"missingClasses": ["wind_resource"], "affectedFieldCount": 26},
        },
    )
    _stub_prepare(workspace_dirs, monkeypatch)

    manifest, _ = curator.build_fact_curator_manifest(_project(), {"projectFactTable": _table()}, {})

    materials = manifest["materials"]
    # 本项目素材在前，缺失类别候选每类最多 3 份注入在后
    assert [item["id"] for item in materials] == ["RAW-OWN", "RAW-X0", "RAW-X1", "RAW-X2"]
    own, *injected = materials
    assert own["crossProject"] is False
    for material in injected:
        assert material["crossProject"] is True
        assert material["homeProject"] == "乙项目"
        assert material["materialClass"] == "wind_resource"
        assert material["path"]  # 走 prepare_project_fact_materials 落地为本地可读文件


def test_cross_project_candidates_yield_to_own_materials(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(curator, "_CURATOR_MATERIAL_LIMIT", 2)
    monkeypatch.setattr(
        curator,
        "project_fact_material_index",
        lambda project, gap_state: [
            {"id": "RAW-OWN1", "name": "塔架工程量.xlsx", "folderPath": "技术标/项目定制/事实表维护测试项目"},
            {"id": "RAW-OWN2", "name": "基础弯矩表.xlsx", "folderPath": "技术标/项目定制/事实表维护测试项目"},
        ],
    )

    def no_scan(project: dict, gap_state: dict) -> dict:
        raise AssertionError("本项目素材已占满额度，不应再查跨项目候选")

    monkeypatch.setattr(curator, "build_fact_material_check", no_scan)
    _stub_prepare(workspace_dirs, monkeypatch)

    manifest, _ = curator.build_fact_curator_manifest(_project(), {"projectFactTable": _table()}, {})

    assert [item["id"] for item in manifest["materials"]] == ["RAW-OWN1", "RAW-OWN2"]


def test_blank_templates_do_not_block_cross_project_candidates(workspace_dirs, monkeypatch) -> None:
    """回归（PRJ-0007）：项目目录里全是「待填写」空白模板时，模板被索引过滤、
    _CURATOR_MATERIAL_LIMIT 额度释放，缺失类别的跨项目候选能注入 manifest。"""
    from app.services import technical_gap_fact_table as fact_table_module

    # curator 侧接回真实索引（索引内部扫描用桩替代），验证模板在源头被过滤
    monkeypatch.setattr(curator, "project_fact_material_index", fact_table_module.project_fact_material_index)
    monkeypatch.setattr(
        fact_table_module,
        "build_project_material_scope",
        lambda project: {
            "readableScopes": [{"materialTier": "project", "path": "技术标/项目定制/事实表维护测试项目"}]
        },
    )
    templates = [
        {
            "id": f"RAW-TPL{i}",
            "name": f"待填写-附表{i}.docx",
            "folderPath": "技术标/项目定制/事实表维护测试项目",
            "materialTier": "project",
        }
        for i in range(50)  # 超过 _CURATOR_MATERIAL_LIMIT，修复前会占满额度
    ]
    monkeypatch.setattr(fact_table_module, "run_async_material_files", lambda **kwargs: {"items": templates})
    monkeypatch.setattr(
        curator,
        "build_fact_material_check",
        lambda project, gap_state: {
            "classes": [
                {
                    "class": "wind_resource",
                    "missing": True,
                    "crossProjectCandidates": [
                        {
                            "id": "RAW-X0",
                            "name": "乙项目风资源报告.docx",
                            "folderPath": "技术标/项目定制/乙项目",
                            "homeProject": "乙项目",
                        }
                    ],
                },
            ],
            "summary": {"missingClasses": ["wind_resource"], "affectedFieldCount": 26},
        },
    )
    _stub_prepare(workspace_dirs, monkeypatch)

    manifest, _ = curator.build_fact_curator_manifest(_project(), {"projectFactTable": _table()}, {})

    # 模板不进 manifest，缺失类别候选正常注入
    assert [item["id"] for item in manifest["materials"]] == ["RAW-X0"]
    assert manifest["materials"][0]["crossProject"] is True


def test_cross_project_evidence_appends_source_note() -> None:
    cross_materials = [
        {"id": "RAW-X0", "name": "乙项目风资源报告.docx", "homeProject": "乙项目", "crossProject": True}
    ]
    table, report = curator.apply_fact_curator_suggestions(
        _table(),
        [
            {
                "fieldKey": "招标单机容量出口端mw",
                "suggestedValue": "10",
                "unit": "MW",
                "evidence": "RAW-X0 乙项目风资源报告.docx 表2：单机容量10MW",
                "confidence": 0.8,
                "action": "fill",
            }
        ],
        operator="测试用户",
        saved_at="2026-07-26T01:00:00Z",
        cross_materials=cross_materials,
    )
    field = table["fields"][0]
    # 落表状态规则不变：一律 pending_confirmation；notes 追加跨项目来源标注
    assert field["status"] == "pending_confirmation"
    assert "跨项目来源：乙项目/乙项目风资源报告.docx" in field["notes"]
    assert report["filled"] == ["招标单机容量出口端mw"]

    # 未引用跨项目素材的 evidence 不加标注
    table2, _ = curator.apply_fact_curator_suggestions(
        _table(),
        [
            {
                "fieldKey": "招标单机容量出口端mw",
                "suggestedValue": "10",
                "unit": "MW",
                "evidence": "招标文件招标公告：单机容量不小于10MW",
                "confidence": 0.9,
                "action": "fill",
            }
        ],
        operator="测试用户",
        saved_at="2026-07-26T01:00:00Z",
        cross_materials=cross_materials,
    )
    assert "跨项目来源" not in table2["fields"][0]["notes"]


if __name__ == "__main__":
    unittest.main()
