from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_outline

VALID_REQUIRED_STATUS = {"必要", "可选", "待确认"}


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outline(
    *,
    history_path: str | Path,
    source_candidates_path: str | Path,
    decisions_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    history = load_json(history_path)
    source_candidates = load_json(source_candidates_path)
    decisions = load_json(decisions_path)
    sections, deferred_items = build_sections(history, source_candidates, decisions)
    outline = {
        "schema_version": "business_bid_outline.v1",
        "document_name": str(decisions.get("document_name") or history.get("document_name") or "商务标目录"),
        "outline_source": {
            "section_title": "历史商务标目录与当前招标文件候选",
            "source_text": str(history.get("document_name") or "history_bid_outline_inputs.json"),
            "confidence": "medium",
            "source_type": "history_bid_headings",
            "history_document_name": str(history.get("document_name") or ""),
            "summary": "opencode 完成语义判断；outline_authoring_helper 仅按显式决策和候选 ID 机械写回。",
        },
        "context": {
            "authoring_helper": {
                "role": "mechanical_writer",
                "history_bid_outline_inputs": str(history_path),
                "source_text_candidates": str(source_candidates_path),
                "decisions": str(decisions_path),
                "deferred_items": deferred_items,
            },
            "source_text_candidates_summary": source_candidates.get("summary") or {},
        },
        "sections": sections,
        "review_items": normalize_review_items(decisions.get("review_items") or [], sections),
    }
    errors = validate_outline.validate(outline)
    if errors:
        raise ValueError("outline validation failed: " + "; ".join(errors))
    write_json(output_path, outline)
    return {
        "output": str(output_path),
        "section_count": sum(1 for _section in iter_sections(sections)),
        "review_item_count": len(outline["review_items"]),
    }


def build_sections(
    history: dict[str, Any],
    source_candidates: dict[str, Any],
    decisions: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_items = source_candidates.get("items") if isinstance(source_candidates.get("items"), list) else []
    history_records = history_records_from_inputs(history)
    item_by_id = {str(item.get("id")): item for item in candidate_items if item.get("id")}
    item_by_source_id = {
        str(item.get("candidate_source_id")): item
        for item in candidate_items
        if item.get("candidate_source_id")
    }
    for item in candidate_items:
        normalized = normalized_source_id(item.get("id"))
        if normalized:
            item_by_source_id.setdefault(normalized, item)

    decision_records = decisions.get("sections") if isinstance(decisions.get("sections"), list) else []
    validate_bulk_defer_reason_contract(decision_records)
    decision_by_key: dict[str, dict[str, Any]] = {}
    for decision in decision_records:
        if not isinstance(decision, dict):
            continue
        for key in decision_keys(decision):
            decision_by_key.setdefault(key, decision)

    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    deferred_items: list[dict[str, Any]] = []
    for index, history_record in enumerate(history_records, start=1):
        level = int(history_record.get("level") or 1)
        source_id = str(history_record.get("candidate_id") or f"hist-cand-{index:03d}")
        item_id = str(history_record.get("outline_item_id") or f"BIZ-FALLBACK-{index:04d}")
        item = (
            item_by_source_id.get(source_id)
            or item_by_id.get(item_id)
            or item_by_source_id.get(normalized_source_id(source_id))
            or {}
        )
        item_id = str(item.get("id") or item_id)
        decision = find_decision(decision_by_key, item_id, source_id)
        if decision is None:
            raise ValueError(f"missing opencode decision for {item_id} / {source_id}")
        action = str(decision.get("action") or "keep").strip().lower()
        validate_action_status_contract(item_id, action, decision)
        validate_defer_reason_contract(item_id, action, decision, item)
        if action in {"defer", "omit", "skip"}:
            while stack and int(stack[-1].get("level") or 1) >= level:
                stack.pop()
            deferred_items.append(
                {
                    "id": item_id,
                    "candidate_source_id": source_id,
                    "title": str(history_record.get("title") or item.get("title") or ""),
                    "action": action,
                    "reason": str(decision.get("reason") or ""),
                }
            )
            continue
        section = build_section(history_record, item, decision, item_id, source_id)
        while stack and int(stack[-1].get("level") or 1) >= int(section.get("level") or 1):
            stack.pop()
        if stack:
            stack[-1].setdefault("children", []).append(section)
        else:
            roots.append(section)
        stack.append(section)
    return roots, deferred_items


def history_records_from_inputs(history: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = history.get("outline_candidates") if isinstance(history.get("outline_candidates"), list) else []
    records: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        title = str(candidate.get("title_hint") or candidate.get("title") or "").strip()
        if not title:
            continue
        record = dict(candidate)
        record["candidate_id"] = str(candidate.get("candidate_id") or f"hist-cand-{index:03d}")
        record["outline_item_id"] = str(candidate.get("outline_item_id") or f"BIZ-FALLBACK-{index:04d}")
        record["title"] = title
        record["level"] = max(1, min(int(candidate.get("level") or 1), 6))
        records.append(record)
    return records


def decision_keys(decision: dict[str, Any]) -> list[str]:
    keys = []
    for field in ("id", "source_candidate_item_id", "candidate_source_id"):
        value = str(decision.get(field) or "").strip()
        if value:
            keys.append(value)
            normalized = normalized_source_id(value)
            if normalized:
                keys.append(normalized)
    return keys


def find_decision(
    decision_by_key: dict[str, dict[str, Any]],
    item_id: str,
    source_id: str,
) -> dict[str, Any] | None:
    for key in (item_id, source_id, normalized_source_id(item_id), normalized_source_id(source_id)):
        if key and key in decision_by_key:
            return decision_by_key[key]
    return None


def normalized_source_id(value: Any) -> str:
    text = str(value or "")
    if not re.match(r"^(hist-cand|BIZ-FALLBACK)-\d+$", text):
        return ""
    match = re.search(r"(\d+)$", text)
    if not match:
        return ""
    return f"hist-cand-{int(match.group(1)):03d}"


def build_section(
    history_record: dict[str, Any],
    item: dict[str, Any],
    decision: dict[str, Any],
    item_id: str,
    source_id: str,
) -> dict[str, Any]:
    selected = select_candidate(item, decision)
    required_status = str(decision.get("required_status") or "").strip()
    if required_status not in VALID_REQUIRED_STATUS:
        raise ValueError(f"{item_id}: required_status must be one of 必要/可选/待确认")
    validate_evidence_status_contract(item_id, selected, required_status)
    source_text = str(selected.get("source_text") or history_record.get("source_text") or history_record.get("title") or "")
    reason = str(decision.get("reason") or selected.get("match_reason") or "")
    if not reason:
        raise ValueError(f"{item_id}: reason is required")
    source_ref = selected.get("source_ref") if isinstance(selected.get("source_ref"), dict) else {}
    section = {
        "id": item_id,
        "candidate_source_id": source_id,
        "source_candidate_item_id": item_id,
        "selected_candidate_id": str(selected.get("candidate_id") or ""),
        "title": str(decision.get("title") or history_record.get("title") or item.get("title") or ""),
        "number": section_number(history_record.get("number")),
        "level": int(history_record.get("level") or 1),
        "required_status": required_status,
        "source_text": source_text,
        "source_refs": [tender_source_ref(selected)] if source_ref or selected.get("scope") != "history_fallback" else [],
        "evidence_scope": str(selected.get("scope") or "history_fallback"),
        "evidence_strength": str(selected.get("evidence_strength") or "fallback"),
        "evidence_category": str(selected.get("evidence_category") or ""),
        "reason": reason,
        "children": [],
    }
    return section


def validate_evidence_status_contract(item_id: str, selected: dict[str, Any], required_status: str) -> None:
    evidence_scope = str(selected.get("scope") or "history_fallback").strip()
    evidence_strength = str(selected.get("evidence_strength") or "fallback").strip()
    if (
        evidence_scope == "history_fallback"
        and evidence_strength == "fallback"
        and required_status == "必要"
    ):
        raise ValueError(
            f"{item_id}: history_fallback/fallback evidence cannot be marked 必要; "
            "rewrite the opencode decision as 待确认 or select current tender evidence"
        )


def validate_action_status_contract(item_id: str, action: str, decision: dict[str, Any]) -> None:
    required_status = str(decision.get("required_status") or "").strip()
    if action in {"defer", "omit", "skip"} and required_status == "必要":
        raise ValueError(
            f"{item_id}: action={action} 不能标为“必要”; "
            "keep it as a directory node with current tender evidence, or defer it as body material"
        )


def validate_defer_reason_contract(
    item_id: str,
    action: str,
    decision: dict[str, Any],
    item: dict[str, Any],
) -> None:
    if action not in {"defer", "omit", "skip"}:
        return
    reason = str(decision.get("reason") or "").strip()
    candidates = item.get("candidates") if isinstance(item.get("candidates"), list) else []
    selected = select_candidate(item, decision) if candidates else {}
    evidence_scope = str(selected.get("scope") or "history_fallback").strip()
    evidence_strength = str(selected.get("evidence_strength") or "fallback").strip()
    has_defer_basis = any(
        marker in reason
        for marker in (
            "正文素材",
            "素材库",
            "后续组装",
            "附件明细",
            "明显不适用",
            "不适用于当前项目",
            "已被",
            "覆盖",
        )
    )
    only_missing_evidence = (
        evidence_scope == "history_fallback"
        and evidence_strength == "fallback"
        and any(marker in reason for marker in ("未找到", "找不到", "fallback", "证据不足", "不可信"))
    )
    if only_missing_evidence and not has_defer_basis:
        raise ValueError(
            f"{item_id}: defer reason must explain 正文素材/素材库组装、不适用或被覆盖; "
            "missing current evidence or history fallback alone is not a defer reason"
        )


def validate_bulk_defer_reason_contract(decision_records: list[Any]) -> None:
    reason_counts: dict[str, int] = {}
    total_deferred = 0
    for decision in decision_records:
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "keep").strip().lower()
        if action not in {"defer", "omit", "skip"}:
            continue
        total_deferred += 1
        reason = normalize_reason(decision.get("reason"))
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    if total_deferred < 20:
        return
    repeated_reason = max(reason_counts.values(), default=0)
    if repeated_reason >= 20 and repeated_reason / total_deferred >= 0.8:
        raise ValueError(
            "bulk defer decisions reuse one template reason; "
            "rewrite opencode decisions with item-specific defer basis or keep history items as 待确认"
        )


def normalize_reason(value: Any) -> str:
    return " ".join(str(value or "").split())


def select_candidate(item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    candidates = item.get("candidates") if isinstance(item.get("candidates"), list) else []
    selected_id = str(decision.get("selected_candidate_id") or decision.get("candidate_id") or "").strip()
    if selected_id:
        for candidate in candidates:
            if str(candidate.get("candidate_id") or "") == selected_id:
                return candidate
        raise ValueError(f"{item.get('id')}: selected candidate not found: {selected_id}")
    if candidates:
        return candidates[0]
    return {
        "candidate_id": "",
        "source_text": str(item.get("source_text") or item.get("title") or ""),
        "scope": "history_fallback",
        "evidence_strength": "fallback",
        "evidence_category": "material_proof",
        "match_reason": "未在 source_text_candidates.json 中找到候选，由 helper 保留历史文本。",
    }


def tender_source_ref(candidate: dict[str, Any]) -> dict[str, Any]:
    ref = candidate.get("source_ref") if isinstance(candidate.get("source_ref"), dict) else {}
    source_text = str(candidate.get("source_text") or "")
    return {
        "type": "tender",
        "role": "basis",
        "fileId": str(ref.get("file_id") or ref.get("fileId") or ""),
        "fileName": str(ref.get("source_file") or ref.get("fileName") or ""),
        "paragraphIndex": ref.get("paragraph_index"),
        "blockId": ref.get("block_id"),
        "tableId": ref.get("table_id"),
        "rowIndex": ref.get("row_index"),
        "colIndex": ref.get("col_index"),
        "searchText": source_text,
        "rawText": source_text,
        "basisText": source_text,
        "reason": str(candidate.get("match_reason") or ""),
        "source_ref": ref,
    }


def section_number(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_review_items(items: list[Any], sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    section_ids = {str(section.get("id")) for section in iter_sections(sections)}
    result = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        required_status = str(item.get("required_status") or "待确认")
        if required_status not in VALID_REQUIRED_STATUS:
            required_status = "待确认"
        suggested = item.get("suggested_section_id")
        if suggested is not None and str(suggested) not in section_ids:
            suggested = None
        result.append(
            {
                "id": str(item.get("id") or f"REVIEW-{index:04d}"),
                "message": str(item.get("message") or ""),
                "source_text": str(item.get("source_text") or ""),
                "suggested_section_id": suggested,
                "required_status": required_status,
                "severity": str(item.get("severity") or "warning"),
            }
        )
    return result


def iter_sections(sections: list[dict[str, Any]]):
    for section in sections or []:
        yield section
        yield from iter_sections(section.get("children", []) or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Mechanically write final business outline from opencode decisions.")
    parser.add_argument("--history", default="history_bid_outline_inputs.json")
    parser.add_argument("--source-candidates", default="source_text_candidates.json")
    parser.add_argument("--decisions", default="outline_authoring_decisions.json")
    parser.add_argument("--output", default="outline.json")
    args = parser.parse_args()
    result = write_outline(
        history_path=args.history,
        source_candidates_path=args.source_candidates,
        decisions_path=args.decisions,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
