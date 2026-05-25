from __future__ import annotations

import copy
from typing import Any

from app.services.bid_type import require_bid_type
from app.services.bid_runtime_state import now_iso
from app.services.technical_gap_domain import check_technical_gap_integrity
from app.services.technical_gap_state import ensure_technical_review_document_state


def summarize_technical_review(gap_state: dict[str, Any]) -> dict[str, int]:
    items = list(gap_state["items"])
    return {
        "total": len(items),
        "resolvedCount": sum(1 for item in items if item["status"] == "resolved"),
        "skippedCount": sum(1 for item in items if item["status"] == "skipped"),
        "pendingCount": sum(1 for item in items if item["status"] not in {"resolved", "skipped"}),
    }


def build_technical_review_payload(project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
    bid_type = require_bid_type(
        project.get("bidType"),
        error_message="技术标复查必须显式传入技术标项目。",
    )
    latest_submission_by_missing_id: dict[str, dict[str, Any]] = {}
    for submission in gap_state["submissions"]:
        missing_id = str(submission.get("missingId") or "")
        if missing_id and missing_id not in latest_submission_by_missing_id:
            latest_submission_by_missing_id[missing_id] = submission

    items = []
    for item in gap_state["items"]:
        items.append(
            {
                "id": item["id"],
                "section": item["section"],
                "title": item["title"],
                "bidType": item.get("bidType") or bid_type,
                "status": item["status"],
                "resolvedSource": item.get("resolvedSource") or "",
                "skipReason": item.get("skipReason") or "",
                "resolvedAt": item.get("resolvedAt") or "",
                "priority": item.get("priority") or "low",
                "submission": copy.deepcopy(latest_submission_by_missing_id.get(item["id"])),
            }
        )

    review_state = ensure_technical_review_document_state(project)
    return {
        "status": "ready" if gap_state["submittedForReview"] else "idle",
        "confirmed": bool(gap_state["reviewConfirmed"]),
        "reviewedAt": gap_state["reviewedAt"] or "",
        "summary": summarize_technical_review(gap_state),
        "items": items,
        "source": {
            "fromStage": "缺口处理",
            "projectId": project["id"],
            "projectName": project["name"],
        },
        "parse": {
            "status": review_state["parseStatus"],
            "parsedAt": review_state["parsedAt"],
            "fileName": review_state["fileName"],
        },
    }


def technical_review_source_file_name(gap_state: dict[str, Any]) -> str:
    for item in gap_state["items"]:
        if item.get("status") == "resolved" and item.get("resolvedSource"):
            return str(item["resolvedSource"])
    return "缺口处理结果.docx"


def build_technical_review_document_content(project: dict[str, Any], gap_state: dict[str, Any]) -> str:
    resolved_items = [item for item in gap_state["items"] if item["status"] == "resolved"]
    skipped_items = [item for item in gap_state["items"] if item["status"] == "skipped"]
    lines = [
        f"# {project['name']}（缺口处理确认预览）",
        "",
        "该文档由缺口处理提交确认后自动生成，用于生成标书前预览。",
        "",
        f"- 已补录：{len(resolved_items)} 项",
        f"- 未补录：{len(skipped_items)} 项",
        "",
        "## 已补录素材",
    ]
    if not resolved_items:
        lines.append("- 无")
    else:
        for index, item in enumerate(resolved_items, start=1):
            lines.append(f"{index}. {item['title']}（{item['section']}）")
            lines.append(f"   - 来源：{item.get('resolvedSource') or '已补录'}")

    lines.extend(["", "## 未补录素材"])
    if not skipped_items:
        lines.append("- 无")
    else:
        for index, item in enumerate(skipped_items, start=1):
            lines.append(f"{index}. {item['title']}（{item['section']}）")
            lines.append(f"   - 原因：{item.get('skipReason') or '未填写'}")
    return "\n".join(lines)


def prepare_technical_review_document(project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
    if not gap_state["submittedForReview"]:
        raise ValueError("请先在缺口处理页提交确认后再生成预览文档。")

    pending = [item for item in gap_state["items"] if item["status"] not in {"resolved", "skipped"}]
    if pending:
        raise ValueError(f"仍有 {len(pending)} 项素材未处理，暂不可生成预览文档。")

    review_state = ensure_technical_review_document_state(project)
    parsed_at = now_iso()
    review_state.update(
        {
            "parseStatus": "completed",
            "parsedAt": parsed_at,
            "sourceFileName": technical_review_source_file_name(gap_state),
            "fileName": f"{project['name']}_缺口处理确认预览.docx",
            "fileType": "docx",
            "content": build_technical_review_document_content(project, gap_state),
            "lastSavedAt": parsed_at,
            "version": 1,
            "documentKey": f"{project['id']}-s6-v1",
        }
    )
    project["updatedAt"] = parsed_at
    return {
        "message": "缺口处理确认预览已生成，可继续生成标书。",
        "payload": copy.deepcopy(review_state),
    }


def save_technical_review_document_content(project: dict[str, Any], content: str) -> dict[str, Any]:
    review_state = ensure_technical_review_document_state(project)
    next_version = int(review_state.get("version") or 1) + 1
    review_state.update(
        {
            "parseStatus": "completed",
            "content": content,
            "version": next_version,
            "lastSavedAt": now_iso(),
            "documentKey": f"{project['id']}-s6-v{next_version}",
        }
    )
    project["updatedAt"] = review_state["lastSavedAt"]
    return copy.deepcopy(review_state)


def force_save_technical_review_document(project: dict[str, Any]) -> dict[str, Any]:
    review_state = ensure_technical_review_document_state(project)
    next_version = int(review_state.get("version") or 1) + 1
    review_state.update(
        {
            "parseStatus": "completed",
            "version": next_version,
            "lastSavedAt": now_iso(),
            "documentKey": f"{project['id']}-s6-v{next_version}",
        }
    )
    project["updatedAt"] = review_state["lastSavedAt"]
    return copy.deepcopy(review_state)


def confirm_technical_review(project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
    if not gap_state["submittedForReview"]:
        raise ValueError("请先在缺口处理页提交确认后再执行确认。")

    integrity = check_technical_gap_integrity(gap_state.get("plan") or {})
    gap_state["integrity"] = integrity
    if integrity["status"] != "passed":
        raise ValueError(f"仍有 {integrity['blockingCount']} 项缺口未解决，暂不可确认审核。")

    gap_state["reviewConfirmed"] = True
    gap_state["reviewedAt"] = now_iso()
    project["updatedAt"] = gap_state["reviewedAt"]
    return {
        "message": "缺口处理已确认，可进入标书生成。",
        "reviewStatus": "confirmed",
        "payload": build_technical_review_payload(project, gap_state),
    }
