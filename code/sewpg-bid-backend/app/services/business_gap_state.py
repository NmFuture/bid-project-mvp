from __future__ import annotations

import copy
import hashlib
from typing import Any

from app.services.bid_runtime_state import now_iso
from app.services.business_gap_domain import update_toc_ref_statuses
from app.services.business_gap_planning import summarize_business_gap_plan


def ensure_business_gap_state(project: dict[str, Any]) -> dict[str, Any]:
    state = project.get("business_gap_state")
    if not isinstance(state, dict):
        state = {}
        project["business_gap_state"] = state
    state.setdefault("recognitionStatus", "idle")
    state.setdefault("recognizedAt", "")
    state.setdefault("submittedForReview", False)
    state.setdefault("reviewConfirmed", False)
    state.setdefault("reviewedAt", "")
    state.setdefault("plan", {})
    state.setdefault("planFile", "")
    state.setdefault("integrity", {})
    state.setdefault("projectFactTable", {})
    return state


def business_gap_integrity(plan: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        task
        for task in (plan.get("tasks") if isinstance(plan.get("tasks"), list) else [])
        if isinstance(task, dict)
    ]
    blocking = [
        {
            "id": str(task.get("id") or ""),
            "title": str(task.get("title") or ""),
            "status": str(task.get("status") or ""),
            "decision": str(task.get("decision") or ""),
        }
        for task in tasks
        if str(task.get("status") or "") in {"needs_input", "filling", "review_required"}
    ]
    return {
        "status": "passed" if not blocking else "blocked",
        "checkedAt": now_iso(),
        "blockingCount": len(blocking),
        "blockingTasks": blocking,
        "summary": summarize_business_gap_plan(plan),
    }


def finalize_business_gap_plan_update(
    project: dict[str, Any],
    business_gap_state: dict[str, Any],
    plan: dict[str, Any],
    *,
    updated_at: str,
) -> None:
    plan["updatedAt"] = updated_at
    update_toc_ref_statuses(plan)
    plan["summary"] = summarize_business_gap_plan(plan)
    business_gap_state["plan"] = plan
    business_gap_state["submittedForReview"] = False
    business_gap_state["reviewConfirmed"] = False
    business_gap_state["reviewedAt"] = ""
    business_gap_state["integrity"] = business_gap_integrity(plan)
    plan["integrity"] = copy.deepcopy(business_gap_state["integrity"])
    project["updatedAt"] = updated_at


def record_business_gap_detection_result(
    project: dict[str, Any],
    business_gap_state: dict[str, Any],
    plan: dict[str, Any],
    *,
    recognized_at: str,
) -> None:
    plan["summary"] = summarize_business_gap_plan(plan)
    business_gap_state.update(
        {
            "recognitionStatus": "completed",
            "recognizedAt": recognized_at,
            "submittedForReview": False,
            "reviewConfirmed": False,
            "reviewedAt": "",
            "plan": plan,
            "planFile": str(plan.get("planFile") or ""),
            "integrity": business_gap_integrity(plan),
        }
    )
    plan["integrity"] = copy.deepcopy(business_gap_state["integrity"])
    project["updatedAt"] = recognized_at


def record_business_material_feedback(
    business_gap_state: dict[str, Any],
    task: dict[str, Any],
    artifacts: list[dict[str, Any]],
    *,
    operator: str,
    selected_at: str,
) -> None:
    entries = business_gap_state.setdefault("materialFeedback", [])
    if not isinstance(entries, list):
        entries = []
        business_gap_state["materialFeedback"] = entries
    existing_keys = {
        str(item.get("feedbackKey") or "")
        for item in entries
        if isinstance(item, dict) and str(item.get("feedbackKey") or "")
    }
    task_title = str(task.get("title") or "")
    toc_target = task.get("tocTarget") if isinstance(task.get("tocTarget"), dict) else {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        material_id = str(artifact.get("materialId") or "").strip()
        segment_id = str(artifact.get("evidenceSegmentId") or "").strip()
        if not material_id:
            continue
        feedback_key = business_material_feedback_key(task, material_id, segment_id)
        if feedback_key in existing_keys:
            continue
        existing_keys.add(feedback_key)
        entries.append(
            {
                "schemaVersion": "bid-business-material-feedback-item-v1",
                "feedbackKey": feedback_key,
                "taskId": str(task.get("id") or ""),
                "taskKey": str(task.get("taskKey") or ""),
                "taskTitle": task_title,
                "moduleKey": str(task.get("moduleKey") or ""),
                "taskType": str(task.get("taskType") or ""),
                "assemblyMode": str(task.get("assemblyMode") or artifact.get("assemblyMode") or ""),
                "materialUsage": str(task.get("materialUsage") or artifact.get("materialUsage") or ""),
                "tocNodeId": str(toc_target.get("nodeId") or ""),
                "tocNumber": str(toc_target.get("number") or ""),
                "tocTitle": str(toc_target.get("title") or ""),
                "materialId": material_id,
                "materialName": str(artifact.get("materialName") or artifact.get("fileName") or ""),
                "folderPath": str(artifact.get("folderPath") or ""),
                "materialTier": str(artifact.get("materialTier") or ""),
                "wikiCardId": str(artifact.get("wikiCardId") or ""),
                "evidenceSegmentId": segment_id,
                "evidenceSegmentTitle": str(artifact.get("evidenceSegmentTitle") or ""),
                "evidenceSummary": str(artifact.get("evidenceSummary") or ""),
                "selectedAt": selected_at,
                "operator": operator or "当前用户",
                "source": "business_s3_manual_selection",
            }
        )
    business_gap_state["materialFeedback"] = entries[-300:]


def business_material_feedback_key(task: dict[str, Any], material_id: str, segment_id: str) -> str:
    raw = "|".join(
        [
            str(task.get("moduleKey") or ""),
            str(task.get("taskType") or ""),
            str(task.get("title") or ""),
            str(material_id or ""),
            str(segment_id or ""),
        ]
    )
    return "biz-feedback-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
