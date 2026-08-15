from __future__ import annotations

"""技术标事实表维护 Skill（方案 B，T5/T6）测试：manifest 组装、回收状态流转、脚本简报、API 链路。"""

import copy
import json
import re
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
from app.services.job_queue import EnqueueResult
from app.services.store import store
from app.services.technical_fact_curate_job import _now_iso, run_fact_curate_job
from app.services.technical_fact_field_specs import fillable_specs, load_specs
from app.services.technical_gap_fact_table import (
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_NOT_APPLICABLE,
    FACT_STATUS_UNEXTRACTED,
)

SCRIPT_PATH = (
    BASE_DIR / "opencode" / "skills" / "bid-tech-fact-curator" / "scripts" / "run_from_manifest.py"
)
SKILL_DIR = BASE_DIR / "opencode" / "skills" / "bid-tech-fact-curator"

# Skill 文档里 `action: "值"` / `"action": "值"` 形式声明的 action，即它教 agent 回传什么。
# 只认冒号赋值形式：`{type, action, evidence}` 这类结构说明里的 action 不带值，不该被算进来。
_DOC_ACTION_RE = re.compile(r"action[\"'`]?\s*[:：]\s*[\"'`]?([a-z][a-z\s|-]*)")


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
    for meta in ("specKey", "specSeq", "sourceKind", "status", "label", "value", "unit"):
        assert meta in field
    # 两件事分桶：unextracted+tender→fill，有值的非只读字段→fix。
    # 平台输入（投标机型）进 fix 不进 fill——它要接受核对（实测 AI 从这类字段抓出过
    # 「台数 6 台 vs 招标要求 60 台」），只是落表时不覆盖值、走冲突通道。
    assert manifest["targets"] == {
        "fill": ["招标单机容量出口端mw"],
        "fix": ["年平均风速", "电量承诺函版本", "投标机型"],
    }
    assert manifest["briefFile"].endswith("fact_curate_brief.json")
    assert manifest["outputFile"].endswith("fact_curate_suggestions.json")


def test_skill_docs_only_teach_legal_actions() -> None:
    """SKILL 文档教的 action 必须都在 CURATE_ACTIONS 里。

    文档是 prompt 不是编译期契约：教 agent 回传一个后端不认的 action，建议会被判非法、
    连 evidence 一起丢弃，而且静默无告警。曾经出过这个问题——铁律 7 教「拿不准就给
    `action: "confirm"`」，但 confirm 从来不是合法值，最需要人工裁决的跨项目素材建议
    因此全被丢掉。这里把文档与代码钉在一起，再犯就直接红。
    """
    taught: set[str] = set()
    for doc in (SKILL_DIR / "SKILL.md", SKILL_DIR / "references" / "rules.md"):
        for raw in _DOC_ACTION_RE.findall(doc.read_text(encoding="utf-8")):
            taught.update(part.strip() for part in raw.split("|") if part.strip())

    assert taught, "两份文档都没声明 action，正则或文档结构变了，这个守卫已失效"
    illegal = taught - curator.CURATE_ACTIONS
    assert not illegal, f"文档教了非法 action {sorted(illegal)}；合法值只有 {sorted(curator.CURATE_ACTIONS)}"


# 三态收敛（产品裁决 2026-08-10）后废弃的状态名，文档里再出现就是过时描述。
_RETIRED_FACT_STATUSES = ("extracted", "pending_confirmation", "missing_source", "conflict")


def test_skill_docs_do_not_teach_retired_field_statuses() -> None:
    """SKILL 文档里的状态名必须跟得上三态收敛。

    上一个用例守 action，不守 status，所以这个坑漏了过去：七态收敛成三态时代码改了、
    文档没改，SKILL.md 一边说 fix 桶装的是 extracted 字段，一边说「confirmed 字段
    不会出现在任何桶里，不要为它产出建议」——而 _curate_targets 里 fix 桶装的**正是**
    confirmed 字段。一个听话的 agent 会把整个 fix 桶跳过，脏数据清洗静默空转，报告里
    只表现为 counts.fixed 一直是 0，不会有任何告警。
    """
    for doc in (SKILL_DIR / "SKILL.md", SKILL_DIR / "references" / "rules.md"):
        text = doc.read_text(encoding="utf-8")
        for retired in _RETIRED_FACT_STATUSES:
            # unextracted 是合法状态且以 extracted 结尾，靠左右边界把它排除掉
            hit = re.search(rf"(?<![0-9A-Za-z_]){retired}(?![0-9A-Za-z_])", text)
            assert hit is None, f"{doc.name} 仍在教已废弃的字段状态 {retired!r}"

    # 防守卫空转：文档必须仍然在讲这三态，否则上面的断言等于没跑
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for status in (FACT_STATUS_UNEXTRACTED, FACT_STATUS_CONFIRMED, FACT_STATUS_NOT_APPLICABLE):
        assert status in skill_text, f"SKILL.md 不再提及合法状态 {status}，这个守卫已失效"


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
    """补抽范围：招标/素材/证书/来源未指定的未提取字段都进 fill 桶；模板/平台/自动生成类不填。"""
    fields = [
        {"key": "f-tender", "status": "unextracted", "sourceKind": "tender"},
        {"key": "f-material", "status": "unextracted", "sourceKind": "material"},
        {"key": "f-cert", "status": "unextracted", "sourceKind": "cert"},
        # 清单来源列写「/」：来源未指定但仍需取值，必须交给 AI 在素材范围内找
        {"key": "f-unspecified", "status": "unextracted", "sourceKind": "unspecified"},
        {"key": "x-platform", "status": "unextracted", "sourceKind": "platform"},
        {"key": "x-derived", "status": "unextracted", "sourceKind": "derived"},
        {"key": "x-template", "status": "unextracted", "sourceKind": "template"},
    ]

    targets = curator._curate_targets(fields)

    assert targets["fill"] == ["f-tender", "f-material", "f-cert", "f-unspecified"]


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
    # 三态：4 条里 3 条有值即可用，1 条无值待人工填
    assert summary["specConfirmedCount"] == 3
    assert summary["specUnfilledCount"] == 1
    assert summary["specConfirmedCount"] + summary["specUnfilledCount"] == summary["specBuiltTotal"]


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


def test_manifest_materials_carry_path_only_when_materialized(workspace_dirs, monkeypatch) -> None:
    """已落地素材带 path；未落地的仍进清单不带 path，由 skill 按 materialFetch 现取。"""
    material_file = workspace_dirs / "material.docx"
    material_file.write_text("占位", encoding="utf-8")
    monkeypatch.setattr(
        curator,
        "project_fact_material_index",
        lambda project, gap_state, **_: [
            {"id": "RAW-1", "name": "已落地", "folderPath": "技术标/项目定制", "materialTier": "project"},
            {"id": "RAW-2", "name": "未落地", "folderPath": "技术标/标准文件", "materialTier": "standard"},
        ],
    )
    monkeypatch.setattr(
        curator,
        "project_fact_material_cached_path",
        lambda cache_dir, material_id: material_file if material_id == "RAW-1" else None,
    )

    manifest, _ = curator.build_fact_curator_manifest(_project(), {"projectFactTable": _table()}, {})

    assert [item["id"] for item in manifest["materials"]] == ["RAW-1", "RAW-2"]
    assert manifest["materials"][0]["path"] == str(material_file)
    assert "path" not in manifest["materials"][1]
    assert "{materialId}" in manifest["materialFetch"]["url"]


# ---------------------------------------------------------------- 回收状态流转


def _apply(suggestions: list[dict], table: dict | None = None) -> tuple[dict, dict]:
    return curator.apply_fact_curator_suggestions(
        table or _table(), suggestions, operator="测试用户", saved_at="2026-07-26T01:00:00Z"
    )


def test_fill_suggestion_lands_as_usable_value() -> None:
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
    assert field["status"] == "confirmed"
    ref = field["sourceRefs"][-1]
    assert ref["type"] == "factCurator"
    assert ref["action"] == "fill"
    assert ref["confidence"] == 0.92
    assert report["filled"] == ["招标单机容量出口端mw"]
    # 4 条字段全部有值：本轮补上的 + 原有 3 条
    assert table["summary"]["confirmedCount"] == 4


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
    assert field["status"] == "confirmed"
    assert field["alternatives"][0]["value"] == old_value
    assert field["sourceRefs"][-1]["type"] == "factCurator"
    assert report["fixed"] == ["年平均风速"]


def test_confirm_advice_action_is_rejected() -> None:
    """confirm-advice 已废弃：即使 agent 回传该 action 也不落表，只记 ignored。"""
    table, report = _apply(
        [
            {
                "fieldKey": "电量承诺函版本",
                "suggestedValue": "V3 考核值",
                "unit": "",
                "evidence": "承诺函原文口径为 V2 保证值",
                "confidence": 0.66,
                "action": "confirm-advice",
            }
        ]
    )

    field = table["fields"][2]
    assert field["value"] == "V2 保证值"
    assert report["ignored"] == [
        {"fieldKey": "电量承诺函版本", "reason": "非法 action：confirm-advice"}
    ]


def test_platform_field_not_overwritten_but_conflict_recorded() -> None:
    """平台输入的值 AI 不许覆盖，但分歧要留痕、要能被看见。

    以前是静默 skippedConfirmed：AI 发现不对也没人知道。实测 AI 在这类字段上抓出过
    「机组台数 6 台 vs 招标要求 60 台」——那个错会一路抄进标书，不能不管；但也不能让
    AI 直接改人选的东西。折中是值保持人选的，候选进 alternatives、原因进 notes、
    打 hasConflict 供页面标红，由人裁决。
    """
    table, report = _apply(
        [
            {
                "fieldKey": "投标机型",
                "suggestedValue": "EW5.0-200",
                "unit": "",
                "evidence": "招标文件表14 要求 EW5.0-200",
                "confidence": 0.99,
                "action": "fix",
            }
        ]
    )
    field = table["fields"][3]
    # 值一个字都不动
    assert field["value"] == "EW10.0-220"
    assert field["status"] == "confirmed"
    # 不给平台字段挂 factCurator 来源——值不是它写的，挂了会让人以为这是 AI 填的
    assert all(ref.get("type") != "factCurator" for ref in field["sourceRefs"])
    # 但分歧要留下来
    assert field["hasConflict"] is True
    assert [item["value"] for item in field["alternatives"]] == ["EW5.0-200"]
    assert "EW5.0-200" in field["notes"] and "招标文件表14" in field["notes"]
    assert report["conflicts"] == [
        {
            "fieldKey": "投标机型",
            "label": "投标机型",
            "currentValue": "EW10.0-220",
            "suggestedValue": "EW5.0-200",
            "evidence": "招标文件表14 要求 EW5.0-200",
            "confidence": 0.99,
        }
    ]
    assert report["counts"]["conflicts"] == 1
    # 表内原有 3 条有值字段计数不变
    assert table["summary"]["confirmedCount"] == 3


def test_platform_field_agreeing_with_ai_is_not_a_conflict() -> None:
    """AI 查证结果与人选的一致：不标红、不留痕，免得满屏假冲突。"""
    table, report = _apply(
        [
            {
                "fieldKey": "投标机型",
                "suggestedValue": "EW10.0-220",
                "unit": "",
                "evidence": "招标文件与素材一致",
                "confidence": 0.95,
                "action": "fix",
            }
        ]
    )
    field = table["fields"][3]
    assert field["value"] == "EW10.0-220"
    assert not field.get("hasConflict")
    assert report["conflicts"] == []
    assert report["skippedConfirmed"] == ["投标机型"]


def test_platform_field_stays_out_of_fill_bucket() -> None:
    """平台字段没值是人还没填，AI 不替人做主——只进 fix，不进 fill。"""
    fields = [
        {"key": "空的平台字段", "status": "unextracted", "value": "", "platformAuthored": True},
        {"key": "有值的平台字段", "status": "confirmed", "value": "钢塔", "platformAuthored": True},
    ]

    targets = curator._curate_targets(fields)

    assert targets["fill"] == []
    assert targets["fix"] == ["有值的平台字段"]


def test_platform_field_recognized_without_spec_source_kind() -> None:
    """靠建表时打的 platformAuthored 标记认，不依赖清单来源列。

    实测 PRJ-0004 的 61 个字段里 sourceKind=platform 的一个都没有：投标机型的来源列
    写的是「项目定制…」被归成 material，机组台数、基础形式连 specKey 都是空的。
    只看 sourceKind 的话这道保护等于没有。
    """
    assert curator._is_platform_authored_field({"sourceKind": "material", "platformAuthored": True})
    assert curator._is_platform_authored_field({"sourceKind": "", "platformAuthored": True})
    # 清单确实标了平台输入的也认
    assert curator._is_platform_authored_field({"sourceKind": "platform"})
    # 从素材抽出来的不是平台字段
    assert not curator._is_platform_authored_field(
        {"sourceKind": "material", "sourceRefs": [{"type": "materialFact", "materialId": "RAW-1"}]}
    )
    # 关键回归：挂着 projectTurbineModel 来源但平台没填值的，不算平台字段——
    # 那圈字段不论平台值空不空都会挂这个标记，拿它当判据会把 AI 的正确修正锁死
    assert not curator._is_platform_authored_field(
        {"sourceKind": "material", "sourceRefs": [{"type": "projectTurbineModel", "field": "hubHeightM"}]}
    )


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
        targets={"fill": ["招标单机容量出口端mw"], "fix": []},
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
    assert by_key["spec-090"]["status"] == "confirmed"
    assert by_key["极端工况-Mx（kNm）"]["value"] == "12500"
    assert by_key["极端工况-Mx（kNm）"]["status"] == "confirmed"
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
    assert table["fields"][0]["status"] == "confirmed"
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
        "targets": {"fill": ["招标单机容量出口端mw"], "fix": ["年平均风速"]},
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
    assert summary["counts"] == {"fill": 1, "fix": 1}
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
        # 页面改格子时前端会挂 manualEdit 来源，整表保存原样落库；curator 据此跳过人工值
        marked_fields = [
            {
                **field,
                "sourceRefs": [
                    {"type": "manualEdit", "title": "人工修改", "field": field.get("label") or ""},
                    *(field.get("sourceRefs") or []),
                ],
            }
            if field["id"] == confirmed_target["id"] else field
            for field in fields
        ]
        save_response = self.client.put(
            f"/api/technical/projects/{project_id}/gaps/facts",
            json={"fields": marked_fields, "operator": "测试用户"},
        )
        self.assertEqual(save_response.status_code, 200, save_response.text)

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
            # 故意每批都全量回传，模拟 agent 越界——本用例要测的正是那道硬门禁：
            # 「项目名称」人工改过、不在任何一批的 targets 里，agent 仍回传时必须被挡下。
            # 并行后同一条越界建议会被每批各记一次，靠报告合并时的去重保证计数不虚高。
            Path(manifest["outputFile"]).write_text(
                json.dumps({"schema": "bid-tech-fact-curate-v1", "suggestions": suggestions}, ensure_ascii=False),
                encoding="utf-8",
            )
            return {"schema": "bid-tech-fact-curate-v1", "suggestionsPath": manifest["outputFile"]}

        # curate 已任务化：接口只负责提交，执行体由 worker 调用，这里直接跑执行体
        with patch.object(curator, "run_technical_fact_curator_skill", side_effect=fake_skill):
            run_fact_curate_job(project_id, {"operator": "测试用户"})

        status_payload = self.client.get(
            f"/api/technical/projects/{project_id}/gaps/facts/curate"
        ).json()
        self.assertEqual(status_payload["factCurateState"]["status"], "succeeded")
        report = status_payload["curateReport"]
        self.assertEqual(report["filled"], [fill_target["key"]])
        self.assertEqual(report["skippedConfirmed"], [confirmed_target["key"]])
        # message 按 report 实际计数给出，不空喊"已置为待人工确认"
        self.assertIn("补抽 1 条", status_payload["message"])
        self.assertIn("已确认跳过 1 条", status_payload["message"])

        table = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        by_key = {field["key"]: field for field in table["fields"]}
        filled = by_key[fill_target["key"]]
        self.assertEqual(filled["value"], "按招标文件要求")
        self.assertEqual(filled["status"], "confirmed")
        self.assertEqual(filled["sourceRefs"][-1]["type"], "factCurator")
        confirmed = by_key[confirmed_target["key"]]
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["value"], confirmed_target["value"])

    def test_fill_only_skips_rebuild_and_keeps_previous_ai_values(self) -> None:
        """「AI补空」跳过重建，上一轮 AI 填的值必须还在。

        重建时只有人工写过的值跨轮存活，AI 填的一律重算——这正是「整轮重来」丢结论的
        原因。实测同样输入两轮抓到的东西并不相同（一轮 4 条修正、一轮 6 条，只有 4 条
        重叠），重建抹掉的就是真发现。补空模式必须绕开它。
        """
        project_id = self._create_project()
        self.assertEqual(
            self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build").status_code, 200
        )
        # 造一个上一轮 AI 填出来的值（挂 factCurator 来源，不是人工值）
        project = store._require(project_id)
        table = project["gap_state"]["projectFactTable"]
        ai_field = next(f for f in table["fields"] if not str(f.get("value") or "").strip())
        ai_field["value"] = "上一轮 AI 填的值"
        ai_field["status"] = "confirmed"
        ai_field["sourceRefs"] = [{"type": "factCurator", "action": "fill", "evidence": "上一轮证据"}]
        store._persist_project(project)

        def fake_run(project_snapshot, gap_state_snapshot, data, *, on_phase=None, on_progress=None):
            self.assertTrue(data.get("fillOnly"), "补空模式必须把 fillOnly 传到 curator")
            return copy.deepcopy(gap_state_snapshot["projectFactTable"]), {
                "counts": {"filled": 0},
                "ignored": [],
                "touchedKeys": [],
            }

        with (
            patch(
                "app.services.technical_gap_fact_table.build_project_fact_table"
            ) as rebuild,
            patch(
                "app.services.technical_fact_curator.run_fact_curator_for_project",
                side_effect=fake_run,
            ),
        ):
            run_fact_curate_job(project_id, {"operator": "测试用户", "fillOnly": True})
            rebuild.assert_not_called()

        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        kept = next(f for f in after["fields"] if f["id"] == ai_field["id"])
        self.assertEqual(kept["value"], "上一轮 AI 填的值")
        state = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts/curate").json()
        self.assertEqual(state["factCurateState"]["status"], "succeeded")
        # 补空不跑 fix 桶，文案不能报「修正 0 条」——那会让人以为查过没问题
        self.assertIn("AI补空完成", state["factCurateState"]["message"])
        self.assertNotIn("修正", state["factCurateState"]["message"])

    def test_curate_endpoint_submits_background_job(self) -> None:
        """接口只提交任务：立即返回 queued，执行体不在请求里跑；进行中重复提交被拒。"""
        project_id = self._create_project()
        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)

        # 真实入队会同时拿到队列锁，两者必须一起 mock：只 mock 入队的话，僵尸判定
        # （jobId 在但锁没了 = worker 死了）会把刚提交的任务当成死的，锁形同虚设
        locked = {"value": False}

        def fake_enqueue(job_type, target_project_id, payload):
            locked["value"] = True
            return EnqueueResult(queued=True, job_id="JOB-CURATE-1")

        with (
            patch(
                "app.services.technical_fact_curate_job.enqueue_generation_job",
                side_effect=fake_enqueue,
            ),
            patch(
                "app.services.technical_fact_curate_job.is_generation_locked",
                side_effect=lambda *args, **kwargs: locked["value"],
            ),
            patch.object(curator, "run_technical_fact_curator_skill") as skill,
        ):
            response = self.client.post(
                f"/api/technical/projects/{project_id}/gaps/facts/curate", json={}
            )
            self.assertEqual(response.status_code, 200, response.text)
            state = response.json()["factCurateState"]
            self.assertEqual(state["status"], "queued")
            self.assertEqual(state["jobId"], "JOB-CURATE-1")
            skill.assert_not_called()

            # 任务未结束时重复提交直接拒绝，避免两轮结果互相覆盖
            conflict = self.client.post(
                f"/api/technical/projects/{project_id}/gaps/facts/curate", json={}
            )
            self.assertEqual(conflict.status_code, 409, conflict.text)

            # 保存与重建现在归同一把锁管：三步都在任务里跑，中途放任何一步进来都会
            # 改表、让正在跑的那一轮失去前提（旧实现只锁 curate，实测 16 分钟白跑）
            save_conflict = self.client.put(
                f"/api/technical/projects/{project_id}/gaps/facts",
                json={"fields": [], "operator": "测试用户"},
            )
            self.assertEqual(save_conflict.status_code, 409, save_conflict.text)
            build_conflict = self.client.post(
                f"/api/technical/projects/{project_id}/gaps/facts/build"
            )
            self.assertEqual(build_conflict.status_code, 409, build_conflict.text)
            # 正文填写读事实表来填 Word，这时候读到的是重建到一半的表
            body_fill_conflict = self.client.post(
                f"/api/technical/projects/{project_id}/gaps/body-fill", json={}
            )
            self.assertEqual(body_fill_conflict.status_code, 409, body_fill_conflict.text)

    def test_zombie_curate_state_does_not_lock_out_save_and_build(self) -> None:
        """worker 被杀留下的 running 状态不能永久锁死页面。

        没有这道判断，保存和刷新会跟着一起卡住，只能改库才能恢复——三个接口共用一把锁
        之后，僵尸状态的代价比只锁 curate 时大得多。
        """
        project_id = self._create_project()
        self.assertEqual(
            self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build").status_code, 200
        )
        project = store._require(project_id)
        project["gap_state"]["factCurateState"] = {
            "status": "running",
            "jobId": "JOB-DEAD",
            "phase": "AI 分析素材",
            "message": "",
            "startedAt": "2026-07-30T00:00:00Z",
        }
        store._persist_project(project)

        # jobId 在但队列锁没了 = worker 死了：放行
        with patch("app.services.technical_fact_curate_job.is_generation_locked", return_value=False):
            save_response = self.client.put(
                f"/api/technical/projects/{project_id}/gaps/facts",
                json={"fields": [], "operator": "测试用户"},
            )
            self.assertEqual(save_response.status_code, 200, save_response.text)

    def test_local_executor_run_is_not_mistaken_for_zombie(self) -> None:
        """Redis 不可用时任务走本地执行器，没有队列锁可查——不能因此把它当成僵尸。

        只照抄「锁没了就是僵尸」会让本地路径下每个在跑的任务都被判死，这把锁等于没加。
        """
        project_id = self._create_project()
        self.assertEqual(
            self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build").status_code, 200
        )
        project = store._require(project_id)
        project["gap_state"]["factCurateState"] = {
            "status": "running",
            "jobId": "",  # 本地执行器：从来没进过 Redis 队列
            "phase": "AI 分析素材",
            "message": "",
            "startedAt": _now_iso(),
        }
        store._persist_project(project)

        with patch("app.services.technical_fact_curate_job.is_generation_locked", return_value=False):
            save_response = self.client.put(
                f"/api/technical/projects/{project_id}/gaps/facts",
                json={"fields": [], "operator": "测试用户"},
            )
            self.assertEqual(save_response.status_code, 409, save_response.text)

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
            with self.assertRaises(RuntimeError):
                run_fact_curate_job(project_id, {"operator": "测试用户"})

        # 失败原因如实回写状态，供前端轮询展示
        status_payload = self.client.get(
            f"/api/technical/projects/{project_id}/gaps/facts/curate"
        ).json()
        self.assertEqual(status_payload["factCurateState"]["status"], "failed")
        self.assertIn("mock", status_payload["factCurateState"]["message"])
        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        # opencode 抛错时表不被污染：字段值与状态逐项一致
        self.assertEqual(
            [(field["key"], field["value"], field["status"]) for field in after["fields"]],
            [(field["key"], field["value"], field["status"]) for field in before["fields"]],
        )

    def test_curate_keeps_concurrent_manual_edit_and_still_lands_the_rest(self) -> None:
        """期间被人工改过的字段让位，其余照落——整轮不再作废。

        旧实现是整表快照比对，表被动过一个字节就抛异常整轮不保存，实测让一次 16 分钟的
        运行全部白跑。现在按字段合并：只有被人工接手的那个字段跳过，并在 dropped 里带原因。
        """
        project_id = self._create_project()
        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)
        fields = build_response.json()["fields"]
        edited = fields[0]
        # 对照字段必须是 AI 可写的：平台输入/模板占位/自动生成本来就在只读门禁里，
        # 拿它做对照会分不清「被人工挡住」和「本来就不许 AI 碰」
        untouched_by_human = next(
            field
            for field in fields
            if field["key"] != edited["key"] and field.get("sourceKind") not in {"template", "platform", "derived"}
        )

        def fake_run(project_snapshot, gap_state_snapshot, data, *, on_phase=None, on_progress=None):
            # AI 跑的这段时间里，人在页面上改了第一个字段（真实路径会带 manualEdit 标记）
            latest = store._require(project_id)
            latest_table = latest["gap_state"]["projectFactTable"]
            latest_table["fields"][0]["value"] = "人工运行中修改"
            latest_table["fields"][0]["sourceRefs"] = [
                {"type": "manualEdit", "title": "人工修改", "field": edited.get("label") or ""}
            ]
            latest_table["updatedAt"] = "2026-07-30T12:00:00Z"
            store._persist_project(latest)

            # AI 基于开跑时的旧快照，两个字段都写了值
            result = copy.deepcopy(gap_state_snapshot["projectFactTable"])
            by_key = {field["key"]: field for field in result["fields"]}
            by_key[edited["key"]]["value"] = "AI 旧快照结果"
            by_key[untouched_by_human["key"]]["value"] = "AI 正常结果"
            by_key[untouched_by_human["key"]]["status"] = "confirmed"
            return result, {
                "counts": {"filled": 2},
                "ignored": [],
                "touchedKeys": [edited["key"], untouched_by_human["key"]],
            }

        with patch(
            "app.services.technical_fact_curator.run_fact_curator_for_project",
            side_effect=fake_run,
        ):
            run_fact_curate_job(project_id, {"operator": "测试用户"})

        status_payload = self.client.get(
            f"/api/technical/projects/{project_id}/gaps/facts/curate"
        ).json()
        self.assertEqual(status_payload["factCurateState"]["status"], "succeeded")
        dropped = status_payload["curateReport"]["dropped"]
        self.assertEqual([item["fieldKey"] for item in dropped], [edited["key"]])
        self.assertIn("人工", dropped[0]["reason"])
        # 未覆盖的条数要出现在给用户看的文案里，不能静默少写
        self.assertIn("1 条", status_payload["factCurateState"]["message"])

        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        by_key = {field["key"]: field for field in after["fields"]}
        self.assertEqual(by_key[edited["key"]]["value"], "人工运行中修改")
        self.assertEqual(by_key[untouched_by_human["key"]]["value"], "AI 正常结果")

    def test_curate_drops_field_that_vanished_from_latest_table(self) -> None:
        """期间换过清单、字段已不在最新表里：跳过并带原因，不静默丢也不整轮失败。"""
        project_id = self._create_project()
        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)
        gone = build_response.json()["fields"][0]

        def fake_run(project_snapshot, gap_state_snapshot, data, *, on_phase=None, on_progress=None):
            latest = store._require(project_id)
            latest_table = latest["gap_state"]["projectFactTable"]
            latest_table["fields"] = [
                field for field in latest_table["fields"] if field["key"] != gone["key"]
            ]
            store._persist_project(latest)

            result = copy.deepcopy(gap_state_snapshot["projectFactTable"])
            for field in result["fields"]:
                if field["key"] == gone["key"]:
                    field["value"] = "AI 给这个已消失字段的值"
            return result, {"counts": {"filled": 1}, "ignored": [], "touchedKeys": [gone["key"]]}

        with patch(
            "app.services.technical_fact_curator.run_fact_curator_for_project",
            side_effect=fake_run,
        ):
            run_fact_curate_job(project_id, {"operator": "测试用户"})

        status_payload = self.client.get(
            f"/api/technical/projects/{project_id}/gaps/facts/curate"
        ).json()
        self.assertEqual(status_payload["factCurateState"]["status"], "succeeded")
        dropped = status_payload["curateReport"]["dropped"]
        self.assertEqual([item["fieldKey"] for item in dropped], [gone["key"]])
        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        self.assertNotIn(gone["key"], {field["key"] for field in after["fields"]})


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
    """把清单里的素材都当作 build 阶段已落地，manifest 直接带上本地路径。"""

    def fake_cached_path(cache_dir: Path, material_id: str) -> Path:
        path = workspace_dirs / f"material-{material_id}.docx"
        path.write_text("占位", encoding="utf-8")
        return path

    monkeypatch.setattr(curator, "project_fact_material_cached_path", fake_cached_path)


def test_manifest_materials_annotated_with_class_home_project(workspace_dirs, monkeypatch) -> None:
    monkeypatch.setattr(
        curator,
        "project_fact_material_index",
        lambda project, gap_state, **_: [
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
        lambda project, gap_state, **_: [
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
        lambda project, gap_state, **_: [
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
    # 落表状态：有值即可用；notes 追加跨项目来源标注
    assert field["status"] == "confirmed"
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


def test_conflict_flag_survives_save_round_trip() -> None:
    """冲突标记要扛过保存往返，否则一保存就没了、冲突等于没报过。

    alternatives 和 notes 本来就在 normalize 的保留名单里，hasConflict 原先不在——
    页面标红一保存就消失，人再也看不到 AI 报过什么。
    """
    from app.services.technical_gap_fact_table import normalize_project_fact_field

    conflicted = normalize_project_fact_field(
        {
            "label": "机组台数",
            "value": "6",
            "hasConflict": True,
            "alternatives": [{"value": "60", "source": {"type": "factCurator", "evidence": "招标表14"}}],
            "notes": "AI 查证与项目信息不一致：建议「60」",
            "sourceRefs": [{"type": "projectTurbineModel", "field": "turbineCount"}],
        },
        index=1,
        confirm=False,
        operator="测试用户",
        saved_at="2026-08-15T00:00:00Z",
    )
    assert conflicted["hasConflict"] is True
    assert [item["value"] for item in conflicted["alternatives"]] == ["60"]
    assert "60" in conflicted["notes"]

    # 人裁决过之后前端置 False，这个 False 同样要回写，不能被当成"没这个键"丢掉
    resolved = normalize_project_fact_field(
        {**conflicted, "value": "60", "hasConflict": False},
        index=1,
        confirm=False,
        operator="测试用户",
        saved_at="2026-08-15T00:00:00Z",
    )
    assert resolved["hasConflict"] is False


def test_fill_only_targets_leave_fix_bucket_empty() -> None:
    """「AI补空」只补没值的字段，已有的值一律不碰。"""
    fields = [
        {"key": "空的", "status": "unextracted", "value": "", "sourceKind": "tender"},
        {"key": "有值的", "status": "confirmed", "value": "7.20", "sourceKind": "material"},
    ]

    assert curator._curate_targets(fields) == {"fill": ["空的"], "fix": ["有值的"]}
    assert curator._curate_targets(fields, fill_only=True) == {"fill": ["空的"], "fix": []}


def test_no_targets_short_circuits_without_opening_a_session(workspace_dirs, monkeypatch) -> None:
    """没有目标字段就别开会话——白等一轮是 8 分钟。

    「AI补空」在表已经填满时最容易撞上这种情况。
    """
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    filled = [
        {**field, "value": "已有值", "status": "confirmed"} if not field.get("value") else field
        for field in _fields()
    ]
    gap_state = {"projectFactTable": _table(filled)}

    with patch.object(curator, "run_technical_fact_curator_skill") as skill:
        table, report = curator.run_fact_curator_for_project(
            _project(), gap_state, {"fillOnly": True}
        )

    skill.assert_not_called()
    assert report["counts"]["filled"] == 0
    assert report["suggestionCount"] == 0
    # 表原样返回，不因为空跑就把值动了
    assert [f["value"] for f in table["fields"]] == [f["value"] for f in filled]


def test_platform_authored_only_when_the_person_actually_filled_it() -> None:
    """平台没填值的字段不算平台输入，AI 该直接改。

    实测 PRJ-0004：hubHeightM / ratedPowerKw / rotorDiameterM 平台侧全是空的，值其实
    抽自素材。但这一圈字段不论平台值空不空都会挂 projectTurbineModel 来源标记，拿它
    当判据就会把它们一起圈进保护区——结果 AI 把「轮毂高度」从跨列串行脏值「池建昌」
    改成 125 的正确修正被降级成"建议"，脏值反倒被锁死在表里。
    """
    from app.services.technical_gap_fact_table import build_project_fact_table

    project = {
        "id": "PRJ-PARTIAL",
        "name": "只填了一部分机型参数的项目",
        # 人只选了机型和台数，轮毂高度/单机容量/叶轮直径都没填
        "turbineModel": {"model": "EW10.0-220上置", "turbineCount": "60"},
    }
    table = build_project_fact_table(project, {})
    by_label = {str(f.get("label") or ""): f for f in table.get("fields") or []}

    for filled in ("投标机型", "机组台数"):
        field = by_label.get(filled)
        assert field is not None, f"缺字段 {filled}：{sorted(by_label)[:10]}"
        assert curator._is_platform_authored_field(field), f"{filled} 人填过，应受保护"

    for blank in ("轮毂高度", "单机容量", "叶轮直径"):
        field = by_label.get(blank)
        if field is None:
            continue
        assert not curator._is_platform_authored_field(field), (
            f"{blank} 平台侧没填值，值抽自素材，AI 必须能直接改而不是只给建议"
        )


def test_platform_authored_flag_survives_save_round_trip() -> None:
    """标记要扛过保存往返，否则保存一次保护就没了。"""
    from app.services.technical_gap_fact_table import normalize_project_fact_field

    saved = normalize_project_fact_field(
        {"label": "机组台数", "value": "60", "platformAuthored": True},
        index=1,
        confirm=False,
        operator="测试用户",
        saved_at="2026-08-15T00:00:00Z",
    )
    assert saved["platformAuthored"] is True
    assert curator._is_platform_authored_field(saved)


# ---------------------------------------------------------------- 并行分批


def test_split_targets_balances_instead_of_following_material_class() -> None:
    """只按 materialClass 切会被最大那批卡死，批大小要按并发算出来。

    实测 59 个目标字段的类别分布是 tender 25 / wind_resource 20 / none 7 / cert 3 /
    未指定 2 / production_base 2，前两类占 76%。整轮耗时 = 最慢那批，所以大类必须再拆。
    """
    dist = {"tender": 25, "wind_resource": 20, "none": 7, "cert": 3, "": 2, "production_base": 2}
    fields, keys = [], []
    for index, (cls, count) in enumerate(dist.items()):
        for seq in range(count):
            key = f"{index}-{seq}"
            fields.append({"key": key, "materialClass": cls})
            keys.append(key)

    batches = curator.split_curate_targets({"fill": keys, "fix": []}, fields, max_batches=8)
    sizes = [len(b["fill"]) + len(b["fix"]) for b in batches]

    assert sum(sizes) == len(keys), "切分丢字段了"
    assert len(batches) <= 8
    # 最大批不超过总量的两成——纯按类别切时它是 42%
    assert max(sizes) / sum(sizes) < 0.2, f"批次不均衡：{sizes}"


def test_split_targets_batch_count_does_not_track_field_count() -> None:
    """清单换大版时批数不能跟着线性涨，否则波次翻倍反而更慢。"""
    def batches_for(total: int) -> int:
        fields = [{"key": f"k{i}", "materialClass": "tender"} for i in range(total)]
        keys = [f["key"] for f in fields]
        return len(curator.split_curate_targets({"fill": keys, "fix": []}, fields, max_batches=8))

    assert batches_for(59) <= 8
    assert batches_for(150) <= 8
    assert batches_for(400) <= 8
    # 字段少于批数上限时不切碎批——每个会话的固定开销是实打实的
    assert batches_for(5) <= 2
    assert batches_for(1) == 1


def test_batch_manifest_keeps_full_field_roster_but_trims_non_targets(workspace_dirs, monkeypatch) -> None:
    """切分只切 targets，可见字段仍是全表——交叉印证靠的就是同时看到别的字段。

    实测 agent 分得清「招标场址要求安全等级」和「机型认证安全等级」、分得清「功率曲线
    取值的湍流度」和「认证 Iref」，前提是这些字段在同一份 manifest 里。
    """
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    gap_state = {"projectFactTable": _table()}
    batch = {"fill": ["招标单机容量出口端mw"], "fix": []}

    manifest, _ = curator.build_fact_curator_manifest(
        _project(), gap_state, {}, targets_override=batch
    )

    fields = manifest["projectFactTable"]["fields"]
    assert len(fields) == 4, "全表字段都要在，只有 targets 被切"
    assert manifest["targets"] == batch

    by_key = {f["key"]: f for f in fields}
    target = by_key["招标单机容量出口端mw"]
    # 目标字段给全键位，空值也留成空串（SKILL 输入契约声明「value：当前值，可空」）
    for contract_key in ("label", "value", "unit", "status", "sourceKind", "specKey", "materialClass"):
        assert contract_key in target, f"目标字段缺契约键 {contract_key}"
    # 非目标只留「叫什么、什么值」，不带 sourceRefs/notes 那些 agent 用不上的
    context = by_key["投标机型"]
    assert set(context) <= {"key", "label", "value", "unit"}, f"上下文字段没精简：{sorted(context)}"


def test_one_batch_failure_keeps_the_other_batches_results(workspace_dirs, monkeypatch) -> None:
    """一批挂了不能带走别批已经拿到的结果——这正是增量落表的意义。"""
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    monkeypatch.setattr(settings, "fact_curate_concurrency", 2)
    gap_state = {"projectFactTable": _table()}
    import threading

    # 并发下 append 与 len 之间有竞态，两个线程会同时读到 2，谁都不失败——用锁取号
    lock = threading.Lock()
    seen: list[Path] = []

    def flaky_skill(manifest_path: Path) -> dict:
        with lock:
            seen.append(manifest_path)
            call_no = len(seen)
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if call_no == 1:
            raise RuntimeError("第一批 mock 失败")
        keys = set(manifest["targets"]["fill"]) | set(manifest["targets"]["fix"])
        mine = [
            {
                "fieldKey": key,
                "suggestedValue": "并行填的值",
                "unit": "",
                "evidence": "mock 证据",
                "confidence": 0.8,
                "action": "fill" if key in set(manifest["targets"]["fill"]) else "fix",
            }
            for key in keys
        ]
        Path(manifest["outputFile"]).write_text(
            json.dumps({"schema": "bid-tech-fact-curate-v1", "suggestions": mine}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"schema": "bid-tech-fact-curate-v1", "suggestionsPath": manifest["outputFile"]}

    with patch.object(curator, "run_technical_fact_curator_skill", side_effect=flaky_skill):
        table, report = curator.run_fact_curator_for_project(_project(), gap_state, {})

    assert len(report["batchErrors"]) == 1
    assert "第一批 mock 失败" in report["batchErrors"][0]["message"]
    assert report["batchDone"] == report["batchTotal"]
    # 没失败那几批的结果照样落了表
    assert report["counts"]["filled"] + report["counts"]["fixed"] > 0
    assert any(str(f.get("value") or "") == "并行填的值" for f in table["fields"])


def test_all_batches_failing_raises_instead_of_reporting_empty(workspace_dirs, monkeypatch) -> None:
    """全批失败要如实报错：报「跑完了但一条建议都没有」跟「查了没找到」分不开。"""
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    gap_state = {"projectFactTable": _table()}

    with patch.object(
        curator, "run_technical_fact_curator_skill", side_effect=RuntimeError("opencode 全挂")
    ):
        with pytest.raises(RuntimeError, match="均失败"):
            curator.run_fact_curator_for_project(_project(), gap_state, {})


def test_progress_reports_running_batches_not_just_completed(workspace_dirs, monkeypatch) -> None:
    """开跑就要报进度，不能只在批完成时报。

    实测单批要 4 分半，只在完成时报的话头几分钟进度纹丝不动，用户看着像卡死。
    进行中的批数也要报——前端靠它画「N 批进行中」那段脉冲。
    """
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    monkeypatch.setattr(settings, "fact_curate_concurrency", 2)
    gap_state = {"projectFactTable": _table()}
    seen: list[dict] = []

    def fake_skill(manifest_path: Path) -> dict:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        Path(manifest["outputFile"]).write_text(
            json.dumps({"schema": "bid-tech-fact-curate-v1", "suggestions": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"schema": "bid-tech-fact-curate-v1", "suggestionsPath": manifest["outputFile"]}

    with patch.object(curator, "run_technical_fact_curator_skill", side_effect=fake_skill):
        _, report = curator.run_fact_curator_for_project(
            _project(), gap_state, {}, on_progress=seen.append
        )

    assert seen, "一次进度都没报"
    total = report["batchTotal"]
    assert all(item["batchTotal"] == total for item in seen)
    # 有过「还没完成任何一批但已经有批在跑」的时刻——这正是进度条能立刻动起来的依据
    assert any(item["batchDone"] == 0 and item["batchRunning"] > 0 for item in seen), seen
    # 收尾时全部完成、没有残留的进行中
    assert seen[-1]["batchDone"] == total
    assert seen[-1]["batchRunning"] == 0


def test_progress_failure_does_not_break_the_run(workspace_dirs, monkeypatch) -> None:
    """进度上报炸了不该带走整轮结果——它只是给人看的。"""
    monkeypatch.setattr(curator, "_curator_materials", lambda project, gap_state: [])
    gap_state = {"projectFactTable": _table()}

    def fake_skill(manifest_path: Path) -> dict:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        Path(manifest["outputFile"]).write_text(
            json.dumps({"schema": "bid-tech-fact-curate-v1", "suggestions": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"schema": "bid-tech-fact-curate-v1", "suggestionsPath": manifest["outputFile"]}

    def boom(_payload: dict) -> None:
        raise RuntimeError("进度写库炸了")

    with patch.object(curator, "run_technical_fact_curator_skill", side_effect=fake_skill):
        table, report = curator.run_fact_curator_for_project(
            _project(), gap_state, {}, on_progress=boom
        )

    assert report["batchDone"] == report["batchTotal"]
    assert table["fields"]
