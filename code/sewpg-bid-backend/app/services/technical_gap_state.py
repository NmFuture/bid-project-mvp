from __future__ import annotations

from typing import Any

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.technical_gap_domain import check_technical_gap_integrity
from app.services.technical_gap_planner import normalize_technical_gap_plan_fill_task_skills


def ensure_technical_gap_state(project: dict[str, Any]) -> dict[str, Any]:
    gap_state = project.get("gap_state")
    if not isinstance(gap_state, dict):
        gap_state = {}
        project["gap_state"] = gap_state
    gap_state.setdefault("recognitionStatus", "idle")
    gap_state.setdefault("recognizedAt", "")
    gap_state.setdefault("submittedForReview", False)
    gap_state.setdefault("reviewConfirmed", False)
    gap_state.setdefault("reviewedAt", "")
    gap_state.setdefault("items", [])
    gap_state.setdefault("submissions", [])
    gap_state.setdefault("plan", {})
    gap_state.setdefault("planFile", "")
    gap_state.setdefault("integrity", {})
    gap_state.setdefault("projectFactTable", {})
    return gap_state


def repair_technical_gap_state_fill_task_skills(gap_state: dict[str, Any]) -> bool:
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    repaired = normalize_technical_gap_plan_fill_task_skills(plan)
    if not repaired:
        return False
    gap_state["plan"] = plan
    gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
    gap_state["integrity"] = check_technical_gap_integrity(plan)
    plan["integrity"] = gap_state["integrity"]
    return True


def legacy_technical_gap_items_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, item in enumerate(plan.get("items") or [], start=1):
        status = str(item.get("status") or "")
        if status in {"matched", "structural"}:
            continue
        items.append(
            {
                "id": str(item.get("id") or f"GAP-{index}"),
                "section": str(item.get("section") or ""),
                "title": str(item.get("title") or ""),
                "desc": str(item.get("gapReason") or "请补充该目录项所需素材。"),
                "priority": str(item.get("priority") or "medium"),
                "bidType": TECHNICAL_BID_TYPE,
                "status": "resolved" if status == "resolved" else "skipped" if status == "ignored" else "pending",
                "skipReason": str(item.get("skipReason") or ""),
                "resolvedSource": str(item.get("resolvedSource") or ""),
                "resolvedAt": str(item.get("resolvedAt") or ""),
                "latestUploadAt": str(item.get("latestUploadAt") or ""),
                "latestSubmissionId": str(item.get("latestSubmissionId") or ""),
            }
        )
    return items


def default_technical_review_document_state(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "parseStatus": "idle",
        "parsedAt": "",
        "documentId": f"REV-DOC-{project['id']}",
        "sourceFileName": "",
        "fileName": f"{project['name']}_缺口处理确认预览.docx",
        "fileType": "docx",
        "content": "",
        "lastSavedAt": "",
        "version": 1,
        "documentKey": f"{project['id']}-s6-v1",
    }


def ensure_technical_review_document_state(project: dict[str, Any]) -> dict[str, Any]:
    state = project.get("review_document_state")
    if not isinstance(state, dict):
        state = {}
        project["review_document_state"] = state
    defaults = default_technical_review_document_state(project)
    for key, value in defaults.items():
        state.setdefault(key, value)
    return state
