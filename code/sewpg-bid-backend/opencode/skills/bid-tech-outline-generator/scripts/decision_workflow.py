from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import outline_composer


STATE_SCHEMA = "technical-outline-decision-state.v1"
STATE_FILE_NAME = "outline_decision_state.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _state_path(work_dir: Path) -> Path:
    return work_dir / STATE_FILE_NAME


def _new_state(fingerprint: str) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA,
        "input_fingerprint": fingerprint,
        "template_decisions": {},
        "additions": [],
        "active_batch": {"token": "", "target_ids": []},
    }


def _load_state(work_dir: Path, fingerprint: str) -> dict[str, Any]:
    path = _state_path(work_dir)
    if not path.is_file():
        state = _new_state(fingerprint)
        _write_json(path, state)
        return state
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"outline decision state is invalid: {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA:
        raise SystemExit(f"outline decision state schema is invalid: {path}")
    if state.get("input_fingerprint") != fingerprint:
        state = _new_state(fingerprint)
        _write_json(path, state)
    return state


def _annotated_items(structure: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    annotated = outline_composer.annotate_template_structure(structure)
    items = [
        item
        for item in annotated.get("items") or []
        if isinstance(item, dict) and int(item.get("level") or 1) <= 3
    ]
    return annotated, items


def _batch_token(fingerprint: str, target_ids: list[str]) -> str:
    payload = json.dumps(
        {"input_fingerprint": fingerprint, "target_ids": target_ids},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def next_decision_batch(
    work_dir: Path,
    structure: dict[str, Any],
    *,
    max_items: int = 50,
    comparison_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if max_items < 1 or max_items > 50:
        raise SystemExit("decision-next max_items must be between 1 and 50")
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint)
    active_ids = list((state.get("active_batch") or {}).get("target_ids") or [])
    if active_ids:
        target_ids = active_ids
    else:
        decided = set((state.get("template_decisions") or {}).keys())
        target_ids = [
            str(item["template_id"])
            for item in items
            if str(item["template_id"]) not in decided
        ][:max_items]
    by_id = {str(item["template_id"]): item for item in items}
    if not target_ids:
        return {
            "schema_version": STATE_SCHEMA,
            "batch_token": "",
            "items": [],
            "decided_count": len(state.get("template_decisions") or {}),
            "remaining_count": 0,
            "complete": True,
        }
    token = _batch_token(fingerprint, target_ids)
    state["active_batch"] = {"token": token, "target_ids": target_ids}
    _write_json(_state_path(work_dir), state)
    return {
        "schema_version": STATE_SCHEMA,
        "batch_token": token,
        "comparison_context": comparison_context or {
            "schema_version": "outline-comparison-context.v1",
            "heading_count": 0,
            "files": [],
        },
        "items": [
            {
                "target_id": target_id,
                "parent_id": by_id[target_id].get("parent_id"),
                "number": str(by_id[target_id].get("number") or ""),
                "title": str(by_id[target_id].get("title") or ""),
                "level": int(by_id[target_id].get("level") or 1),
            }
            for target_id in target_ids
        ],
        "decided_count": len(state.get("template_decisions") or {}),
        "remaining_count": len(items) - len(state.get("template_decisions") or {}),
        "complete": False,
    }


def submit_decision_batch(
    work_dir: Path,
    structure: dict[str, Any],
    payload: dict[str, Any],
    *,
    appendix_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint)
    active = state.get("active_batch") or {}
    expected_ids = list(active.get("target_ids") or [])
    token = str(payload.get("batch_token") or "")
    if not expected_ids or token != str(active.get("token") or ""):
        raise SystemExit("decision-batch must use the current decision-next batch_token")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise SystemExit("decision-batch items must be a list")
    actual_ids = [
        str(item.get("target_id") or "")
        for item in raw_items
        if isinstance(item, dict)
    ]
    if actual_ids != expected_ids or len(raw_items) != len(expected_ids):
        raise SystemExit("decision-batch items must exactly match the current decision-next batch")
    decisions = state.setdefault("template_decisions", {})
    for index, item in enumerate(raw_items):
        decision = str(item.get("decision") or "").strip()
        target_id = actual_ids[index]
        if decision == "retain":
            if set(item) != {"target_id", "decision"}:
                raise SystemExit(f"decision-batch items[{index}] retain has unsupported fields")
            decisions[target_id] = {"target_id": target_id, "decision": "retain"}
            continue
        if decision != "suggest_delete":
            raise SystemExit(
                f"decision-batch items[{index}].decision must be retain or suggest_delete"
            )
        reason = str(item.get("reason") or "").strip()
        if not reason:
            raise SystemExit(f"decision-batch items[{index}].reason is required")
        normalized = {
            "target_id": target_id,
            "decision": "suggest_delete",
            "reason": reason,
        }
        if "tender_basis" in item:
            normalized["tender_basis"] = deepcopy(item["tender_basis"])
        decisions[target_id] = normalized

    additions = payload.get("additions") or []
    if not isinstance(additions, list):
        raise SystemExit("decision-batch additions must be a list")
    existing_ids = {
        str(item.get("node_id") or "") for item in state.get("additions") or []
    }
    appendices_by_id = {
        str(item.get("appendix_id") or ""): item
        for item in appendix_items or []
        if isinstance(item, dict) and str(item.get("appendix_id") or "")
    }
    for index, addition in enumerate(additions):
        if not isinstance(addition, dict):
            raise SystemExit(f"decision-batch additions[{index}] must be an object")
        node_id = str(addition.get("node_id") or "").strip()
        reason = str(addition.get("reason") or "").strip()
        if not node_id or node_id in existing_ids:
            raise SystemExit(
                f"decision-batch additions[{index}].node_id is missing or duplicate"
            )
        if not reason:
            raise SystemExit(f"decision-batch additions[{index}].reason is required")
        appendix_id = str(addition.get("appendix_id") or "").strip()
        if appendix_id:
            appendix = appendices_by_id.get(appendix_id)
            if appendix is None:
                raise SystemExit(
                    f"decision-batch additions[{index}].appendix_id is unknown: {appendix_id}"
                )
            unsupported = set(addition) - {
                "node_id",
                "parent_id",
                "appendix_id",
                "reason",
                "tender_basis",
            }
            if unsupported:
                raise SystemExit(
                    f"decision-batch additions[{index}] appendix has unsupported fields"
                )
            number = str(appendix.get("number") or "")
            title = str(appendix.get("title") or "")
        else:
            number = str(addition.get("number") or "")
            title = str(addition.get("title") or "")
        change = {
            "operation": "add",
            "node_id": node_id,
            "parent_id": addition.get("parent_id"),
            "number": number,
            "title": title,
            "suggestion_action": "建议增加",
            "suggestion_reason": reason,
        }
        if "tender_basis" in addition:
            change["tender_basis"] = deepcopy(addition["tender_basis"])
        state.setdefault("additions", []).append(change)
        existing_ids.add(node_id)

    state["active_batch"] = {"token": "", "target_ids": []}
    _write_json(_state_path(work_dir), state)
    decided_count = len(decisions)
    return {
        "schema_version": STATE_SCHEMA,
        "decided_count": decided_count,
        "remaining_count": len(items) - decided_count,
        "addition_count": len(state.get("additions") or []),
    }


def finalize_decisions(
    work_dir: Path,
    structure: dict[str, Any],
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint)
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("current decision-next batch has not been submitted")
    decisions_by_id = state.get("template_decisions") or {}
    missing = [
        str(item["template_id"])
        for item in items
        if str(item["template_id"]) not in decisions_by_id
    ]
    if missing:
        raise SystemExit("template decisions missing: " + ", ".join(missing[:20]))
    decisions = {
        "schema_version": outline_composer.DECISIONS_SCHEMA,
        "input_fingerprint": fingerprint,
        "template_decisions": [decisions_by_id[str(item["template_id"])] for item in items],
        "changes": state.get("additions") or [],
    }
    try:
        return outline_composer.submit_decisions(
            work_dir=work_dir,
            structure=structure,
            decisions=decisions,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
