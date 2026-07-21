from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import outline_composer


STATE_SCHEMA = "technical-outline-decision-state.v2"
LEGACY_STATE_SCHEMA = "technical-outline-decision-state.v1"
STATE_FILE_NAME = "outline_decision_state.json"
CONTEXT_SCHEMA = "outline-decision-context.v1"
DEFAULT_CONTEXT_MAX_CHARS = 12000
MAX_CONTEXT_MAX_CHARS = 20000


def _payload_digest(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _state_path(work_dir: Path) -> Path:
    return work_dir / STATE_FILE_NAME


def _binding_value(binding: dict[str, str] | None, key: str) -> str:
    return str((binding or {}).get(key) or "").strip()


def _empty_active_batch() -> dict[str, Any]:
    return {
        "token": "",
        "target_ids": [],
        "context_digest": "",
        "context_next_cursor": "",
        "context_complete": False,
    }


def _new_state(
    fingerprint: str,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA,
        "input_fingerprint": fingerprint,
        "tender_inputs_digest": _binding_value(workflow_binding, "tenderInputsDigest"),
        "headings_state_digest": _binding_value(workflow_binding, "headingsStateDigest"),
        "template_decisions": {},
        "additions": [],
        "active_batch": _empty_active_batch(),
        "finalized_decisions_digest": "",
    }


def _load_state(
    work_dir: Path,
    fingerprint: str,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    path = _state_path(work_dir)
    if not path.is_file():
        state = _new_state(fingerprint, workflow_binding)
        _write_json(path, state)
        return state
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"outline decision state is invalid: {path}: {exc}") from exc
    if isinstance(state, dict) and state.get("schema_version") == LEGACY_STATE_SCHEMA:
        raise SystemExit("目录决策协议已升级，请重新生成目录")
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA:
        raise SystemExit(f"outline decision state schema is invalid: {path}")
    if state.get("input_fingerprint") != fingerprint:
        state = _new_state(fingerprint, workflow_binding)
        _write_json(path, state)
        return state
    if workflow_binding:
        expected_tender = _binding_value(workflow_binding, "tenderInputsDigest")
        expected_headings = _binding_value(workflow_binding, "headingsStateDigest")
        if (
            str(state.get("tender_inputs_digest") or "") != expected_tender
            or str(state.get("headings_state_digest") or "") != expected_headings
        ):
            has_progress = bool(
                state.get("template_decisions")
                or state.get("additions")
                or (state.get("active_batch") or {}).get("target_ids")
            )
            if has_progress:
                raise SystemExit("outline decision state does not match the current tender/headings inputs")
            state = _new_state(fingerprint, workflow_binding)
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


def _batch_token(
    fingerprint: str,
    target_ids: list[str],
    context_digest: str,
    workflow_binding: dict[str, str] | None = None,
) -> str:
    payload = json.dumps(
        {
            "input_fingerprint": fingerprint,
            "tender_inputs_digest": _binding_value(workflow_binding, "tenderInputsDigest"),
            "headings_state_digest": _binding_value(workflow_binding, "headingsStateDigest"),
            "target_ids": target_ids,
            "context_digest": context_digest,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_context_files(
    comparison_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for raw_file in (comparison_context or {}).get("files") or []:
        if not isinstance(raw_file, dict):
            continue
        file_id = str(raw_file.get("file_id") or "").strip()
        items = []
        for raw_item in raw_file.get("items") or []:
            if not isinstance(raw_item, dict):
                continue
            items.append(
                {
                    "evidence_id": str(raw_item.get("evidence_id") or "").strip(),
                    "level": int(raw_item.get("level") or 0),
                    "text": str(raw_item.get("text") or "").strip(),
                }
            )
        if file_id and items:
            files.append({"file_id": file_id, "items": items})
    return files


def _context_digest(
    files: list[dict[str, Any]],
    workflow_binding: dict[str, str] | None,
) -> str:
    return _payload_digest(
        {
            "headings_state_digest": _binding_value(
                workflow_binding,
                "headingsStateDigest",
            ),
            "files": files,
        }
    )


def _page_files(entries: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for file_id, item in entries:
        if not files or files[-1]["file_id"] != file_id:
            files.append({"file_id": file_id, "items": []})
        files[-1]["items"].append(item)
    return files


def _context_page(
    files: list[dict[str, Any]],
    digest: str,
    *,
    cursor: int,
    max_chars: int,
) -> dict[str, Any]:
    entries = [
        (str(file_entry["file_id"]), deepcopy(item))
        for file_entry in files
        for item in file_entry["items"]
    ]
    selected: list[tuple[str, dict[str, Any]]] = []
    next_index = cursor

    def payload(candidate: list[tuple[str, dict[str, Any]]], end: int) -> dict[str, Any]:
        complete = end >= len(entries)
        return {
            "schema_version": CONTEXT_SCHEMA,
            "digest": digest,
            "heading_count": len(entries),
            "cursor": str(cursor),
            "next_cursor": "" if complete else str(end),
            "complete": complete,
            "files": _page_files(candidate),
        }

    while next_index < len(entries):
        candidate = [*selected, entries[next_index]]
        candidate_payload = payload(candidate, next_index + 1)
        compact_size = len(
            json.dumps(
                candidate_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        if compact_size > max_chars:
            break
        selected = candidate
        next_index += 1

    if not selected and next_index < len(entries):
        raise SystemExit(
            "单条招标目录上下文超过 decision-context --max-chars，"
            "请提高 --max-chars 后重试"
        )
    return payload(selected, next_index)


def next_decision_context_page(
    work_dir: Path,
    structure: dict[str, Any],
    batch_token: str,
    *,
    cursor: str = "0",
    max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    comparison_context: dict[str, Any] | None = None,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    if max_chars < 1000 or max_chars > MAX_CONTEXT_MAX_CHARS:
        raise SystemExit("decision-context --max-chars must be between 1000 and 20000")
    cursor_text = str(cursor).strip()
    if not cursor_text.isdigit():
        raise SystemExit("decision-context --cursor must be a non-negative integer")
    normalized_cursor = str(int(cursor_text))

    annotated, _ = _annotated_items(structure)
    state = _load_state(work_dir, annotated["input_fingerprint"], workflow_binding)
    active = state.get("active_batch") or {}
    if not active.get("target_ids") or batch_token != str(active.get("token") or ""):
        raise SystemExit(
            "decision-context batch_token must match the current decision-next batch_token"
        )
    expected_cursor = str(active.get("context_next_cursor") or "")
    if active.get("context_complete"):
        raise SystemExit("decision-context for the current batch is already complete")
    if normalized_cursor != expected_cursor:
        raise SystemExit(
            f"decision-context cursor must match the current cursor: {expected_cursor}"
        )

    files = _normalized_context_files(comparison_context)
    digest = _context_digest(files, workflow_binding)
    if digest != str(active.get("context_digest") or ""):
        state["active_batch"] = _empty_active_batch()
        _write_json(_state_path(work_dir), state)
        raise SystemExit("招标目录上下文已变化，请重新执行 decision-next")
    page = _context_page(
        files,
        digest,
        cursor=int(normalized_cursor),
        max_chars=max_chars,
    )
    active["context_next_cursor"] = page["next_cursor"]
    active["context_complete"] = page["complete"]
    state["active_batch"] = active
    _write_json(_state_path(work_dir), state)
    return page


def next_decision_batch(
    work_dir: Path,
    structure: dict[str, Any],
    *,
    max_items: int = 50,
    comparison_context: dict[str, Any] | None = None,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    if max_items < 1 or max_items > 50:
        raise SystemExit("decision-next max_items must be between 1 and 50")
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint, workflow_binding)
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
    context_files = _normalized_context_files(comparison_context)
    context_digest = _context_digest(context_files, workflow_binding)
    token = _batch_token(
        fingerprint,
        target_ids,
        context_digest,
        workflow_binding,
    )
    state["active_batch"] = {
        "token": token,
        "target_ids": target_ids,
        "context_digest": context_digest,
        "context_next_cursor": "0",
        "context_complete": False,
    }
    _write_json(_state_path(work_dir), state)
    first_context_page = next_decision_context_page(
        work_dir,
        structure,
        token,
        comparison_context=comparison_context,
        workflow_binding=workflow_binding,
    )
    return {
        "schema_version": STATE_SCHEMA,
        "batch_token": token,
        "comparison_context": first_context_page,
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
    comparison_context: dict[str, Any] | None = None,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint, workflow_binding)
    active = state.get("active_batch") or {}
    expected_ids = list(active.get("target_ids") or [])
    token = str(payload.get("batch_token") or "")
    if not expected_ids or token != str(active.get("token") or ""):
        raise SystemExit("decision-batch must use the current decision-next batch_token")
    current_context_digest = _context_digest(
        _normalized_context_files(comparison_context),
        workflow_binding,
    )
    if current_context_digest != str(active.get("context_digest") or ""):
        state["active_batch"] = _empty_active_batch()
        _write_json(_state_path(work_dir), state)
        raise SystemExit("招标目录上下文已变化，请重新执行 decision-next")
    if not active.get("context_complete"):
        raise SystemExit("当前决策批次尚未读完招标目录上下文")
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

    state["active_batch"] = _empty_active_batch()
    state["finalized_decisions_digest"] = ""
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
    *,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint, workflow_binding)
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
        result = outline_composer.submit_decisions(
            work_dir=work_dir,
            structure=structure,
            decisions=decisions,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    state["finalized_decisions_digest"] = outline_composer.decisions_digest(decisions)
    _write_json(_state_path(work_dir), state)
    return result


def validate_finalized_decisions(
    work_dir: Path,
    structure: dict[str, Any],
    decisions: dict[str, Any],
    *,
    workflow_binding: dict[str, str],
) -> dict[str, str]:
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    path = _state_path(work_dir)
    if not path.is_file():
        raise SystemExit("必须通过 decision-next、decision-batch 和 decisions 生成受控决策")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"outline decision state is invalid: {path}: {exc}") from exc
    if isinstance(state, dict) and state.get("schema_version") == LEGACY_STATE_SCHEMA:
        raise SystemExit("目录决策协议已升级，请重新生成目录")
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA:
        raise SystemExit(f"outline decision state schema is invalid: {path}")
    if state.get("input_fingerprint") != fingerprint:
        raise SystemExit("outline decision state does not match template_structure")
    if str(state.get("tender_inputs_digest") or "") != _binding_value(
        workflow_binding, "tenderInputsDigest"
    ):
        raise SystemExit("outline decision state does not match the current tender inputs")
    if str(state.get("headings_state_digest") or "") != _binding_value(
        workflow_binding, "headingsStateDigest"
    ):
        raise SystemExit("outline decision state does not match the completed headings state")
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("current decision-next batch has not been submitted")

    decisions_by_id = state.get("template_decisions")
    if not isinstance(decisions_by_id, dict):
        raise SystemExit("outline decision state template_decisions is invalid")
    expected_ids = [str(item["template_id"]) for item in items]
    if set(decisions_by_id) != set(expected_ids):
        raise SystemExit("outline decision state does not contain all controlled template decisions")
    expected_decisions = {
        "schema_version": outline_composer.DECISIONS_SCHEMA,
        "input_fingerprint": fingerprint,
        "template_decisions": [decisions_by_id[target_id] for target_id in expected_ids],
        "changes": state.get("additions") or [],
    }
    expected_digest = outline_composer.decisions_digest(expected_decisions)
    if outline_composer.decisions_digest(decisions) != expected_digest:
        raise SystemExit("outline decisions do not match the controlled decision state")
    if str(state.get("finalized_decisions_digest") or "") != expected_digest:
        raise SystemExit("必须先执行 s2outline decisions 完成受控决策")
    return {"decisionStateDigest": _payload_digest(state)}
