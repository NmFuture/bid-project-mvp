from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from urllib.parse import quote


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
