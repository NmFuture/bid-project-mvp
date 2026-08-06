from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from urllib.parse import quote


def technical_outline_number_and_title(
    node: dict[str, Any],
    fallback_number: str,
) -> tuple[str, str]:
    """统一 S4/S7 的确认目录编号与纯标题，避免素材关联键在阶段间漂移。"""
    number = ""
    for key in ("tocNumber", "toc_number", "number"):
        candidate = str(node.get(key) or "").strip()
        if candidate:
            number = candidate
            break
    number = number or fallback_number

    title = str(node.get("title") or node.get("name") or "").strip()
    if number and title.startswith(number):
        suffix = title[len(number) :]
        compact_number_prefix = number.endswith(("章", "节", "、", "）", ")"))
        if not suffix or suffix[:1].isspace() or suffix[:1] in "：:、.-" or compact_number_prefix:
            title = suffix.strip(" ：:、.-") or title
    return number, title


def technical_gap_artifact_is_s7_ready(artifact: dict[str, Any]) -> bool:
    # active=False 表示已被撤销/取代的非活动产物（保留审计），一律不进 S7。
    if artifact.get("active", True) is False:
        return False
    if artifact.get("s7Ready", True) is False:
        return False
    if str(artifact.get("source") or "") != "ai_fill":
        return True
    if str(artifact.get("qualityGate") or "") == "human_confirmed":
        return True
    quality_report = artifact.get("qualityReport") if isinstance(artifact.get("qualityReport"), dict) else {}
    return str(quality_report.get("status") or "") == "passed"


def recompute_technical_gap_decisions(plan: dict[str, Any]) -> int:
    """决策终审：候选素材不等于决策，对齐商务标 recompute_task_states 的两层架构。

    build_gap_plan 产出的 decision 是「初判」；这里是每次都会重跑的「终审」，按优先级：
    1. 人工上传、人工选材等非 AI 可合并产物 → decision=ready，可替代 AI 填写任务。
    2. 有未放行的 AI resolvedArtifacts → decision=review_required，必须先验收或人工确认。
    3. 还有未完成的 fillTasks（附表或正文「待填写」模板）→ decision=fill_required。
    4. 所有任务完成且存在可合并 AI 产物 → decision=ready。
    5. 初判是 fill_required 但没有未完成 fillTasks、只有 candidateMaterials（字面候选/主题弱
       关联召回，纯供人工挑选）→ 改判 review_required（此前只在 schema 占位、从未真正赋值）。
    6. 其余（ready/structural/material_required 等）保持初判结果不变——尤其是「已经匹配到现成
       素材」的 ready 态，就算带着 candidateMaterials 当备选，也不能被这条终审规则误伤。

    返回被改写 decision 的条目数。
    """
    changed = 0
    for item in plan.get("items") or []:
        if not isinstance(item, dict):
            continue
        resolved_artifacts = [a for a in (item.get("resolvedArtifacts") or []) if isinstance(a, dict)]
        ready_non_ai_artifacts = [
            artifact
            for artifact in resolved_artifacts
            if str(artifact.get("source") or "") != "ai_fill"
            and technical_gap_artifact_is_s7_ready(artifact)
        ]
        if ready_non_ai_artifacts:
            if item.get("decision") != "ready" or item.get("status") != "resolved":
                item["decision"] = "ready"
                item["status"] = "resolved"
                changed += 1
            continue

        unready_ai_artifacts = [
            artifact
            for artifact in resolved_artifacts
            if str(artifact.get("source") or "") == "ai_fill"
            and not technical_gap_artifact_is_s7_ready(artifact)
        ]
        if unready_ai_artifacts:
            if item.get("decision") != "review_required" or item.get("status") != "needs_input":
                item["decision"] = "review_required"
                item["status"] = "needs_input"
                changed += 1
            continue

        pending_fill_tasks = [
            task for task in (item.get("fillTasks") or [])
            if isinstance(task, dict) and str(task.get("status") or "pending") != "completed"
        ]
        if pending_fill_tasks:
            if item.get("decision") != "fill_required" or item.get("status") == "resolved":
                item["decision"] = "fill_required"
                item["status"] = "needs_input"
                changed += 1
            continue

        merge_ready_artifacts = [a for a in resolved_artifacts if technical_gap_artifact_is_s7_ready(a)]
        if merge_ready_artifacts:
            if item.get("decision") != "ready" or item.get("status") != "resolved":
                item["decision"] = "ready"
                item["status"] = "resolved"
                changed += 1
            continue

        if str(item.get("decision") or "") != "fill_required":
            continue  # ready/material_required/structural 等初判结果不参与终审改写

        candidate_materials = [m for m in (item.get("candidateMaterials") or []) if isinstance(m, dict)]
        if candidate_materials and item.get("decision") != "review_required":
            item["decision"] = "review_required"
            item["status"] = "needs_input"
            changed += 1

    return changed


def summarize_technical_gap_plan(plan: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in plan.get("items") or [] if isinstance(item, dict)]
    decision_counts: dict[str, int] = {}
    for item in items:
        decision = str(item.get("decision") or "")
        if decision:
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
    return {
        "totalTocItems": len(items),
        "matchedCount": sum(1 for item in items if item.get("status") == "matched"),
        "missingCount": sum(1 for item in items if item.get("status") in {"missing", "needs_input"}),
        "resolvedCount": sum(1 for item in items if item.get("status") == "resolved"),
        "ignoredCount": sum(1 for item in items if item.get("status") == "ignored"),
        "structuralCount": sum(1 for item in items if item.get("status") == "structural"),
        "fillableTaskCount": sum(len(item.get("fillTasks") or []) for item in items),
        "blockingCount": sum(1 for item in items if item.get("status") in {"missing", "needs_input", "filling"}),
        "readyCount": decision_counts.get("ready", 0),
        "fillRequiredCount": decision_counts.get("fill_required", 0),
        "materialRequiredCount": decision_counts.get("material_required", 0),
        "reviewRequiredCount": decision_counts.get("review_required", 0),
        "appendixTaskCount": sum(len(item.get("appendixTasks") or []) for item in items),
    }


def check_technical_gap_integrity(plan: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_technical_gap_plan(plan)
    blocking_items = [
        {
            "id": str(item.get("id") or ""),
            "number": str(item.get("number") or ""),
            "title": str(item.get("title") or ""),
            "status": str(item.get("status") or ""),
        }
        for item in plan.get("items") or []
        if str(item.get("status") or "") in {"missing", "needs_input", "filling"}
    ]
    return {
        "status": "passed" if not blocking_items else "blocked",
        "checkedAt": _now_iso(),
        "blockingCount": len(blocking_items),
        "blockingItems": blocking_items,
        "summary": summary,
    }


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def technical_gap_artifact_onlyoffice_payload(
    *,
    project_id: str,
    artifact_id: str,
    file_name: str,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> dict[str, Any]:
    file_url = f"/api/technical/projects/{project_id}/gaps/artifacts/{artifact_id}/content/{quote(file_name)}"
    browser_url = f"{browser_base_url.rstrip('/')}{file_url}" if browser_base_url else file_url
    document_server_url = (
        f"{onlyoffice_base_url.rstrip('/')}{file_url}"
        if onlyoffice_base_url
        else browser_url
    )
    return {
        "status": "ready",
        "mode": "view",
        "fileUrl": document_server_url,
        "browserFileUrl": browser_url,
        "documentServerFileUrl": document_server_url,
        "documentKey": f"{project_id}-{artifact_id}",
        "title": file_name,
    }


def build_technical_gap_detection_payload(project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
    items = copy.deepcopy(gap_state["items"])
    gap_plan = copy.deepcopy(gap_state.get("plan") or {})
    plan_summary = gap_plan.get("summary") if isinstance(gap_plan.get("summary"), dict) else {}
    high_priority_count = sum(1 for item in items if item.get("priority") == "high")
    medium_priority_count = sum(1 for item in items if item.get("priority") == "medium")
    low_priority_count = max(0, len(items) - high_priority_count - medium_priority_count)
    return {
        "status": gap_state["recognitionStatus"],
        "recognizedAt": gap_state["recognizedAt"],
        "summary": {
            "totalMissing": len(items),
            "totalTocItems": int(plan_summary.get("totalTocItems") or 0),
            "matchedCount": int(plan_summary.get("matchedCount") or 0),
            "missingCount": int(plan_summary.get("missingCount") or len(items)),
            "resolvedCount": int(plan_summary.get("resolvedCount") or 0),
            "fillableTaskCount": int(plan_summary.get("fillableTaskCount") or 0),
            "highPriorityCount": high_priority_count,
            "mediumPriorityCount": medium_priority_count,
            "lowPriorityCount": low_priority_count,
        },
        "items": items,
        "gapPlan": gap_plan,
        "integrity": copy.deepcopy(gap_state.get("integrity") or {}),
        "source": {
            "fromStage": "缺口处理",
            "projectId": project["id"],
            "projectName": project["name"],
        },
    }


def refresh_technical_gap_plan_artifact_urls(
    project_id: str,
    gap_plan: dict[str, Any],
    *,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> None:
    if not isinstance(gap_plan, dict):
        return
    for item in gap_plan.get("items") or []:
        if not isinstance(item, dict):
            continue
        for artifact in item.get("resolvedArtifacts") or []:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("id") or "")
            file_name = str(artifact.get("fileName") or Path(str(artifact.get("path") or "")).name)
            if not artifact_id or not file_name:
                continue
            artifact["onlyoffice"] = {
                **(artifact.get("onlyoffice") if isinstance(artifact.get("onlyoffice"), dict) else {}),
                **technical_gap_artifact_onlyoffice_payload(
                    project_id=project_id,
                    artifact_id=artifact_id,
                    file_name=file_name,
                    browser_base_url=browser_base_url,
                    onlyoffice_base_url=onlyoffice_base_url,
                ),
            }


def find_technical_gap_item(gap_state: dict[str, Any], gap_id: str) -> dict[str, Any]:
    for item in gap_state["items"]:
        if item.get("id") == gap_id:
            return item
    raise KeyError(gap_id)


def find_technical_gap_plan_item(gap_state: dict[str, Any], gap_id: str) -> dict[str, Any] | None:
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    for item in plan.get("items") or []:
        if str(item.get("id") or "") == gap_id:
            return item
    return None


def aggregate_technical_gap_fill_quality(
    results: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    reports = [result.get("qualityReport") for result in results if isinstance(result.get("qualityReport"), dict)]
    if not reports:
        return {
            "status": "failed" if errors else "empty",
            "coverageRate": 0.0,
            "correctnessRate": 0.0,
            "completenessRate": 0.0,
            "thresholds": {"coverageRate": 0.85, "correctnessRate": 0.85, "completenessRate": 0.85},
        }
    expected = sum(int(report.get("expectedFieldCount") or 0) for report in reports)
    filled = sum(int(report.get("filledFieldCount") or 0) for report in reports)
    unfilled = sum(int(report.get("unfilledFieldCount") or 0) for report in reports)
    evidence = sum(int(report.get("evidenceRefCount") or 0) for report in reports)
    if expected > 0:
        coverage = filled / expected
        correctness = min(1.0, evidence / max(1, filled)) if filled else 0.0
        completeness = max(0.0, (expected - unfilled) / expected)
    else:
        coverage = sum(float(report.get("coverageRate") or 0) for report in reports) / len(reports)
        correctness = sum(float(report.get("correctnessRate") or 0) for report in reports) / len(reports)
        completeness = sum(float(report.get("completenessRate") or 0) for report in reports) / len(reports)
    thresholds = {"coverageRate": 0.85, "correctnessRate": 0.85, "completenessRate": 0.85}
    passed = (
        not errors
        and coverage >= thresholds["coverageRate"]
        and correctness >= thresholds["correctnessRate"]
        and completeness >= thresholds["completenessRate"]
    )
    return {
        "status": "passed" if passed else "needs_review",
        "coverageRate": round(coverage, 4),
        "correctnessRate": round(correctness, 4),
        "completenessRate": round(completeness, 4),
        "expectedFieldCount": expected,
        "filledFieldCount": filled,
        "unfilledFieldCount": unfilled,
        "evidenceRefCount": evidence,
        "taskCount": len(reports),
        "passedTaskCount": sum(1 for report in reports if report.get("status") == "passed"),
        "needsReviewTaskCount": sum(1 for report in reports if report.get("status") != "passed"),
        "thresholds": thresholds,
    }
