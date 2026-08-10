"""缺口清单导出：逐项的组装判定必须和 tech_assembly 真正的挑选规则同口径。

磁盘上的 s4 快照停在识别那一刻，排查「这一章为什么没进正文」只能看库里的当前状态。
"""
from __future__ import annotations

from unittest import mock

import pytest

from app.services import technical_gap_service as service_module

PASSED_QUALITY = {"status": "passed"}


def _artifact(artifact_id: str, source: str = "ai_fill", **extra) -> dict:
    return {
        "id": artifact_id,
        "source": source,
        "fileName": f"{artifact_id}.docx",
        "path": f"/data/{artifact_id}.docx",
        **extra,
    }


def _export(*items: dict) -> dict:
    project = {"id": "PRJ-EXPORT", "bidType": "technical"}
    gap_state = {"recognitionStatus": "completed", "plan": {"items": list(items)}}
    with mock.patch.object(service_module, "get_technical_gap_project_runtime_state", return_value=project), \
         mock.patch.object(service_module, "ensure_technical_gap_state", return_value=gap_state):
        return service_module.TechnicalGapService().export_plan("PRJ-EXPORT")


def _entry(payload: dict, gap_id: str) -> dict:
    return next(entry for entry in payload["items"] if entry["id"] == gap_id)


def test_ai_artifact_pending_review_is_reported_as_blocked() -> None:
    # 用户实际撞上的那一类：填了、产物在，但质检没过又没人复核，组装静默跳过
    payload = _export(
        {
            "id": "GAP-0010",
            "title": "投标关键数据一览表",
            "resolvedArtifacts": [
                _artifact("ART-1", qualityReport={"status": "needs_review", "unfilledPlaceholderCount": 13})
            ],
        }
    )

    entry = _entry(payload, "GAP-0010")
    assert entry["willAssemble"] is False
    assert "未放行" in entry["reason"]
    assert "13 项未填字段" in entry["sources"][0]["blockedBy"]
    assert payload["summary"]["blockedByReview"] == 1
    assert [item["id"] for item in payload["blockedItems"]] == ["GAP-0010"]


def test_human_confirmed_artifact_assembles() -> None:
    payload = _export(
        {
            "id": "GAP-0011",
            "resolvedArtifacts": [
                _artifact("ART-2", qualityGate="human_confirmed", qualityReport={"status": "needs_review"})
            ],
        }
    )

    entry = _entry(payload, "GAP-0011")
    assert entry["willAssemble"] is True
    assert entry["sources"][0]["accepted"] is True


def test_manual_material_selection_assembles_without_quality_gate() -> None:
    # 人工选的成稿素材不是 AI 产物，不受质检门槛限制
    payload = _export({"id": "GAP-0012", "resolvedArtifacts": [_artifact("ART-3", source="material_library")]})

    assert _entry(payload, "GAP-0012")["willAssemble"] is True


def test_fill_template_selection_waits_for_filling() -> None:
    payload = _export(
        {"id": "GAP-0013", "resolvedArtifacts": [_artifact("ART-4", source="material_library", s7Ready=False)]}
    )

    entry = _entry(payload, "GAP-0013")
    assert entry["willAssemble"] is False
    assert "未就绪" in entry["sources"][0]["blockedBy"]


def test_auto_matched_materials_assemble_without_confirmation() -> None:
    # 自动匹配的素材不过就绪闸，直接进组装（产品口径，与 tech_assembly 一致）
    payload = _export({"id": "GAP-0014", "matchedMaterials": [{"id": "MAT-1", "name": "整章素材.docx"}]})

    entry = _entry(payload, "GAP-0014")
    assert entry["willAssemble"] is True
    assert entry["sources"][0]["kind"] == "matchedMaterial"


def test_resolved_artifacts_shadow_auto_matched_materials() -> None:
    # 有产物就只认产物：产物未放行时不会回落到自动匹配素材
    payload = _export(
        {
            "id": "GAP-0015",
            "resolvedArtifacts": [_artifact("ART-5", qualityReport={"status": "needs_review"})],
            "matchedMaterials": [{"id": "MAT-2", "name": "备选.docx"}],
        }
    )

    entry = _entry(payload, "GAP-0015")
    assert entry["willAssemble"] is False
    assert [source["kind"] for source in entry["sources"]] == ["resolvedArtifact"]


def test_title_only_and_parent_covered_items_are_skipped() -> None:
    payload = _export(
        {"id": "GAP-P", "titleOnly": True},
        {"id": "GAP-C", "coverageRole": "covered_by_parent", "coveredByParent": "GAP-OTHER"},
        {
            "id": "GAP-C2",
            "coverageRole": "covered_by_parent",
            "coveredByParent": "GAP-P",
            "matchedMaterials": [{"id": "MAT-3", "name": "子节素材.docx"}],
        },
    )

    assert _entry(payload, "GAP-P")["willAssemble"] is False
    covered = _entry(payload, "GAP-C")
    assert covered["willAssemble"] is False
    assert "父章" in covered["reason"]
    # 覆盖源被改成「仅保留标题」后子节重新自己上场，与组装侧的豁免一致
    assert _entry(payload, "GAP-C2")["willAssemble"] is True


def test_item_without_any_source_is_reported_as_empty() -> None:
    payload = _export({"id": "GAP-0016"})

    entry = _entry(payload, "GAP-0016")
    assert entry["willAssemble"] is False
    assert entry["reason"] == "没有任何可用素材"
    assert payload["summary"] == {
        "totalItems": 1,
        "willAssemble": 0,
        "skipped": 1,
        "blockedByReview": 0,
    }
