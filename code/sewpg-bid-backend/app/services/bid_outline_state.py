from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.bid_runtime_state import (
    build_directory_event,
    build_directory_opencode_output,
    count_outline_nodes,
    default_outline_nodes,
    now_iso,
    outline_nodes_from_directory_toc,
    recover_directory_state,
    recover_outline_state,
)
from app.services.project_stage_flow import apply_confirmed_outline_stage


def complete_directory_generation_state(project: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    generated_at = now_iso()
    nodes = default_outline_nodes(str(project.get("name") or ""))
    payload = {
        "status": "completed",
        "percentage": 100,
        "summary": "目录生成完成。",
        "generatedAt": generated_at,
        "output": {
            "fileName": f"{project['name']}_目录.docx",
            "fileType": "docx",
            "chapterCount": len(nodes),
        },
        "opencodeOutput": build_directory_opencode_output(),
        "ruleEvidence": {},
        "events": [
            build_directory_event("目录生成完成。", level="success", step="done", at=generated_at),
        ],
        "tasks": [
            {"id": "task-1", "label": "准备目录输入", "status": "done"},
            {"id": "task-2", "label": "Opencode 生成目录", "status": "done"},
            {"id": "task-3", "label": "保存目录结果", "status": "done"},
        ],
    }
    project["directory_state"] = payload
    project["outline_state"] = {
        "outlineVersion": 1,
        "reviewStatus": "draft",
        "generatedAt": generated_at,
        "summary": {"totalNodeCount": count_outline_nodes(nodes)},
        "nodes": nodes,
    }
    project["updatedAt"] = generated_at
    return copy.deepcopy(payload)


def start_directory_generation_state(project: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "status": "running",
        "percentage": 5,
        "summary": "已开始生成目录，正在准备招标文件与投标模板候选。",
        "generatedAt": "",
        "output": None,
        "opencodeOutput": build_directory_opencode_output(),
        "ruleEvidence": {},
        "events": [
            build_directory_event(
                "已开始生成目录任务，正在准备招标文件与投标模板候选。",
                step="bootstrap",
            ),
        ],
        "tasks": [
            {"id": "task-1", "label": "准备目录输入", "status": "running"},
            {"id": "task-2", "label": "Opencode 生成目录", "status": "pending"},
            {"id": "task-3", "label": "保存目录结果", "status": "pending"},
        ],
    }
    project["directory_state"] = payload
    project["updatedAt"] = now_iso()
    return copy.deepcopy(payload)


def update_directory_generation_state(
    project: dict[str, Any],
    *,
    percentage: int | None = None,
    summary: str | None = None,
    tasks: list[dict[str, Any]] | None = None,
    status: str | None = None,
    event_message: str | None = None,
    event_level: str = "info",
    event_step: str = "general",
    opencode_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = copy.deepcopy(project.get("directory_state") or recover_directory_state(project))
    if percentage is not None:
        current["percentage"] = max(0, min(100, int(percentage)))
    if summary is not None:
        current["summary"] = summary
    if tasks is not None:
        current["tasks"] = copy.deepcopy(tasks)
    if status is not None:
        current["status"] = status
    if opencode_output is not None:
        merged_output = build_directory_opencode_output()
        merged_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
        merged_output.update(copy.deepcopy(opencode_output))
        merged_output["parts"] = copy.deepcopy(merged_output.get("parts") or [])[-20:]
        current["opencodeOutput"] = merged_output
    if event_message:
        events = list(current.get("events") or [])
        events.append(
            build_directory_event(
                event_message,
                level=event_level,
                step=event_step,
            )
        )
        current["events"] = events[-20:]
    project["directory_state"] = current
    project["updatedAt"] = now_iso()
    return copy.deepcopy(current)


def fail_directory_generation_state(
    project: dict[str, Any],
    *,
    message: str,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = copy.deepcopy(project.get("directory_state") or recover_directory_state(project))
    current["status"] = "failed"
    current["summary"] = message
    current_output = build_directory_opencode_output()
    current_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
    if (
        current_output.get("status") != "idle"
        or current_output.get("sessionId")
        or current_output.get("providerId")
        or current_output.get("modelId")
        or current_output.get("parts")
    ):
        current_output["status"] = "failed"
    current["opencodeOutput"] = current_output
    if tasks is not None:
        current["tasks"] = copy.deepcopy(tasks)
    events = list(current.get("events") or [])
    events.append(build_directory_event(message, level="error", step="failed"))
    current["events"] = events[-20:]
    project["directory_state"] = current
    project["updatedAt"] = now_iso()
    return copy.deepcopy(current)


def save_generated_outline_state(
    project: dict[str, Any],
    *,
    nodes: list[dict[str, Any]],
    generated_at: str,
    summary: str,
    opencode_output: dict[str, Any] | None = None,
    rule_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_state = copy.deepcopy(project.get("directory_state") or {})
    current_events = list(copy.deepcopy(current_state.get("events") or []))
    current_output = build_directory_opencode_output()
    current_output.update(copy.deepcopy(current_state.get("opencodeOutput") or {}))
    if opencode_output is not None:
        current_output.update(copy.deepcopy(opencode_output))
    current_output["parts"] = copy.deepcopy(current_output.get("parts") or [])[-20:]
    current_events.append(
        build_directory_event(
            f"目录生成完成，已输出 {len(nodes)} 个一级章节。",
            level="success",
            step="done",
            at=generated_at,
        )
    )
    payload = {
        "status": "completed",
        "percentage": 100,
        "summary": summary,
        "generatedAt": generated_at,
        "output": {
            "fileName": f"{project['name']}_目录.docx",
            "fileType": "docx",
            "chapterCount": len(nodes),
        },
        "opencodeOutput": current_output,
        "ruleEvidence": copy.deepcopy(rule_evidence or current_state.get("ruleEvidence") or {}),
        "events": current_events[-20:],
        "tasks": [
            {"id": "task-1", "label": "准备目录输入", "status": "done"},
            {"id": "task-2", "label": "Opencode 生成目录", "status": "done"},
            {"id": "task-3", "label": "保存目录结果", "status": "done"},
        ],
    }
    project["directory_state"] = payload
    current_outline = project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {}
    project["outline_state"] = {
        "outlineVersion": int(current_outline.get("outlineVersion") or 0) + 1,
        "reviewStatus": "draft",
        "generatedAt": generated_at,
        "summary": {"totalNodeCount": count_outline_nodes(nodes)},
        "nodes": copy.deepcopy(nodes),
    }
    project["updatedAt"] = generated_at
    return copy.deepcopy(payload)


def directory_state_with_rule_evidence(project: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(project["directory_state"])
    if not isinstance(state.get("ruleEvidence"), dict) or not state.get("ruleEvidence"):
        evidence = load_directory_rule_evidence(state)
        if evidence:
            state["ruleEvidence"] = evidence
    return state


def load_directory_rule_evidence(state: dict[str, Any]) -> dict[str, Any]:
    opencode_output = state.get("opencodeOutput") if isinstance(state.get("opencodeOutput"), dict) else {}
    evidence_path = Path(str(opencode_output.get("evidencePath") or "")).expanduser()
    if not str(evidence_path).strip() or not evidence_path.exists():
        return {}
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(evidence, dict):
        return {}
    decisions = evidence.get("decisions") if isinstance(evidence.get("decisions"), list) else []
    if evidence.get("schema_version") == "bid-toc-evidence-v2":
        action_counts: dict[str, int] = {}
        for item in decisions:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            if action:
                action_counts[action] = action_counts.get(action, 0) + 1
        return {
            "schemaVersion": "bid-toc-evidence-v2",
            "engine": str(evidence.get("engine") or ""),
            "ruleVersion": str(evidence.get("ruleVersion") or evidence.get("rule_version") or ""),
            "decisionCount": len(decisions),
            "reviewCount": sum(
                1
                for item in decisions
                if isinstance(item, dict) and bool(item.get("review_required") or item.get("reviewRequired"))
            ),
            "actionCounts": action_counts,
        }
    candidates = evidence.get("tenderCandidates") if isinstance(evidence.get("tenderCandidates"), list) else []
    template_outline = evidence.get("templateOutline") if isinstance(evidence.get("templateOutline"), list) else []
    item_sources = evidence.get("itemSources") if isinstance(evidence.get("itemSources"), list) else []
    decision_limit = 80
    return {
        "schemaVersion": str(evidence.get("schema_version") or ""),
        "engine": str(evidence.get("engine") or ""),
        "ruleVersion": str(evidence.get("ruleVersion") or evidence.get("rule_version") or ""),
        "ruleConfig": copy.deepcopy(evidence.get("ruleConfig") if isinstance(evidence.get("ruleConfig"), dict) else {}),
        "templateOutlineCount": len(template_outline),
        "tenderCandidateCount": len(candidates),
        "itemSources": [
            copy.deepcopy(item)
            for item in item_sources
            if isinstance(item, dict)
        ][:decision_limit],
        "itemSourceCount": len(item_sources),
        "decisionCount": len(decisions),
        "decisions": [
            copy.deepcopy(item)
            for item in decisions
            if isinstance(item, dict)
        ][:decision_limit],
    }


def save_outline_state(project: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    current = copy.deepcopy(project.get("outline_state") or recover_outline_state(project))
    current["outlineVersion"] = int(current.get("outlineVersion") or 1) + 1
    current["reviewStatus"] = "draft"
    current["summary"] = {"totalNodeCount": count_outline_nodes(nodes)}
    current["nodes"] = copy.deepcopy(nodes)
    project["outline_state"] = current
    project["updatedAt"] = now_iso()
    return copy.deepcopy(current)


def regenerate_outline_state(project: dict[str, Any]) -> dict[str, Any]:
    nodes = regenerated_outline_nodes(project)
    current_outline = project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {}
    generated_at = now_iso()
    project["outline_state"] = {
        "outlineVersion": int(current_outline.get("outlineVersion") or 1) + 1,
        "reviewStatus": "draft",
        "generatedAt": generated_at,
        "summary": {"totalNodeCount": count_outline_nodes(nodes)},
        "nodes": nodes,
    }
    project["updatedAt"] = generated_at
    return copy.deepcopy(project["outline_state"])


def regenerated_outline_nodes(project: dict[str, Any]) -> list[dict[str, Any]]:
    if str(project.get("bidType") or "").strip() != BUSINESS_BID_TYPE:
        return default_outline_nodes(str(project.get("name") or ""))
    nodes = outline_nodes_from_directory_toc(project)
    return nodes or copy.deepcopy(project.get("outline_state", {}).get("nodes") or [])


def confirm_outline_state(project: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(project.get("outline_state"), dict):
        project["outline_state"] = recover_outline_state(project)
    project["outline_state"]["reviewStatus"] = "confirmed"
    apply_confirmed_outline_stage(project)
    project["updatedAt"] = now_iso()
    return {
        "message": "目录已确认",
        "outlineVersion": project["outline_state"]["outlineVersion"],
        "reviewStatus": "confirmed",
    }
