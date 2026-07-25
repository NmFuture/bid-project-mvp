from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import outline_composer


STATE_SCHEMA = "technical-outline-decision-state.v6"
LEGACY_STATE_SCHEMAS = {
    "technical-outline-decision-state.v1",
    "technical-outline-decision-state.v2",
    "technical-outline-decision-state.v3",
    "technical-outline-decision-state.v4",
    "technical-outline-decision-state.v5",
}
STATE_FILE_NAME = "outline_decision_state.json"
MAX_DECISION_RESPONSE_BYTES = 24000
MAX_DECISION_UNIT_ITEMS = 50


def _payload_digest(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compact_json_bytes(payload: Any) -> int:
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


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
        "chapter_id": "",
        "decision_unit_id": "",
        "target_ids": [],
    }


def _empty_active_appendix_batch() -> dict[str, Any]:
    return {"token": "", "appendix_ids": []}


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
        "appendix_decisions": {},
        "additions": [],
        "addition_chapters": {},
        "active_batch": _empty_active_batch(),
        "active_appendix_batch": _empty_active_appendix_batch(),
        "appendix_inventory_digest": "",
        "finalized_decisions_digest": "",
        "global_review_digest": "",
        "global_review_summary": "",
        "global_review_read_baseline": None,
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
    if isinstance(state, dict) and state.get("schema_version") in LEGACY_STATE_SCHEMAS:
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
                or state.get("appendix_decisions")
                or state.get("additions")
                or (state.get("active_batch") or {}).get("target_ids")
                or (state.get("active_appendix_batch") or {}).get("appendix_ids")
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
    workflow_binding: dict[str, str] | None = None,
) -> str:
    payload = json.dumps(
        {
            "input_fingerprint": fingerprint,
            "tender_inputs_digest": _binding_value(workflow_binding, "tenderInputsDigest"),
            "headings_state_digest": _binding_value(workflow_binding, "headingsStateDigest"),
            "target_ids": target_ids,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decision_items(
    target_ids: list[str],
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "target_id": target_id,
            "parent_id": by_id[target_id].get("parent_id"),
            "number": str(by_id[target_id].get("number") or ""),
            "title": str(by_id[target_id].get("title") or ""),
            "level": int(by_id[target_id].get("level") or 1),
        }
        for target_id in target_ids
    ]


def template_headings(
    structure: dict[str, Any],
    *,
    cursor: int = 0,
    page_size: int = 40,
) -> dict[str, Any]:
    if cursor < 0:
        raise SystemExit("template-headings --cursor must be >= 0")
    if page_size < 1 or page_size > 200:
        raise SystemExit("template-headings --page-size must be between 1 and 200")
    _, items = _annotated_items(structure)
    if cursor > len(items):
        raise SystemExit("template-headings --cursor exceeds item count")
    end = min(len(items), cursor + page_size)
    by_id = {str(item["template_id"]): item for item in items}
    target_ids = [str(item["template_id"]) for item in items[cursor:end]]
    complete = end >= len(items)
    return {
        "schema_version": "technical-template-headings.v1",
        "cursor": str(cursor),
        "next_cursor": "" if complete else str(end),
        "complete": complete,
        "item_count": len(items),
        "items": _decision_items(target_ids, by_id),
    }


def _decision_batch_response(
    *,
    token: str,
    target_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    decided_count: int,
    item_count: int,
    chapter_id: str,
    decision_unit_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA,
        "batch_token": token,
        "chapter_id": chapter_id,
        "decision_unit_id": decision_unit_id,
        "items": _decision_items(target_ids, by_id),
        "decision_steps": [
            "定位本章相关的全部招标二、三级章节，即使与模板同名也逐个用 section 连续读到 complete=true；同名父节点或标题相似不等于响应粒度相当，search 只用于跨章节定位，关键词抽查不算完成",
            "逐项提取正文中“提供、提交、编制、出具”指向的方案、报告、承诺、计算书、清单和交付物；只有完整模板存在语义等价且粒度相当的节点才算覆盖，未覆盖且值得独立表达的形成 additions",
            "再从模板侧找出不适用、重复、可合并或没有独立成章价值的节点，形成 suggest_delete",
            "最后把剩余节点 retain；不得用 reason 把招标直接要求伪装成历史模板经验",
        ],
        "submission_contract": {
            "required_fields": ["batch_token", "items", "additions"],
            "items_must_match_batch": True,
            "additions_must_be_explicit": True,
            "new_controlled_read_required": True,
        },
        "decided_count": decided_count,
        "remaining_count": item_count - decided_count,
        "complete": False,
    }


def _chapter_groups(items: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    chapter_id = ""
    target_ids: list[str] = []
    for item in items:
        target_id = str(item["template_id"])
        if int(item.get("level") or 1) == 1:
            if target_ids:
                groups.append((chapter_id, target_ids))
            chapter_id = target_id
            target_ids = []
        if not chapter_id:
            chapter_id = target_id
        target_ids.append(target_id)
    if target_ids:
        groups.append((chapter_id, target_ids))
    return groups


def _decision_units(items: list[dict[str, Any]]) -> list[tuple[str, str, list[str]]]:
    by_id = {str(item["template_id"]): item for item in items}
    units: list[tuple[str, str, list[str]]] = []
    for chapter_id, chapter_ids in _chapter_groups(items):
        if len(chapter_ids) <= MAX_DECISION_UNIT_ITEMS:
            units.append((chapter_id, chapter_id, chapter_ids))
            continue

        root_ids = [chapter_id]
        section_units: list[tuple[str, str, list[str]]] = []
        section_id = ""
        section_ids: list[str] = []
        for target_id in chapter_ids[1:]:
            level = int(by_id[target_id].get("level") or 1)
            if level == 2:
                if section_ids:
                    section_units.append((chapter_id, section_id, section_ids))
                section_id = target_id
                section_ids = [target_id]
            elif section_ids:
                section_ids.append(target_id)
            else:
                root_ids.append(target_id)
        if section_ids:
            section_units.append((chapter_id, section_id, section_ids))
        units.append((chapter_id, chapter_id, root_ids))
        units.extend(section_units)
    return units


def _invalidate_global_review(state: dict[str, Any]) -> None:
    state["global_review_digest"] = ""
    state["global_review_summary"] = ""
    state["finalized_decisions_digest"] = ""
    state["global_review_read_baseline"] = None


def _evidence_read_event_count(work_dir: Path) -> int | None:
    path = work_dir / "tender_evidence_access.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"tender evidence access is invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "tender-evidence-access.v1":
        raise SystemExit(f"tender evidence access schema is invalid: {path}")
    return int(payload.get("read_event_count") or 0)


def _arm_global_review_if_ready(
    state: dict[str, Any],
    work_dir: Path,
    template_items: list[dict[str, Any]],
    appendix_items: list[dict[str, Any]],
) -> None:
    expected_template_ids = {str(item["template_id"]) for item in template_items}
    expected_appendix_ids = {str(item["appendix_id"]) for item in appendix_items}
    if set(state.get("template_decisions") or {}) != expected_template_ids:
        return
    if set(state.get("appendix_decisions") or {}) != expected_appendix_ids:
        return
    if state.get("global_review_read_baseline") is None:
        state["global_review_read_baseline"] = _evidence_read_event_count(work_dir)


def _current_decisions_digest(state: dict[str, Any]) -> str:
    return _payload_digest(
        {
            "template_decisions": state.get("template_decisions") or {},
            "additions": state.get("additions") or [],
            "appendix_decisions": state.get("appendix_decisions") or {},
        }
    )


def next_decision_batch(
    work_dir: Path,
    structure: dict[str, Any],
    *,
    max_items: int = 50,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    if max_items < 1 or max_items > 50:
        raise SystemExit("decision-next max_items must be between 1 and 50")
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint, workflow_binding)
    by_id = {str(item["template_id"]): item for item in items}
    decided_count = len(state.get("template_decisions") or {})
    active = state.get("active_batch") or {}
    active_ids = list(active.get("target_ids") or [])
    if active_ids:
        return _decision_batch_response(
            token=str(active.get("token") or ""),
            target_ids=active_ids,
            by_id=by_id,
            decided_count=decided_count,
            item_count=len(items),
            chapter_id=str(active.get("chapter_id") or active_ids[0]),
            decision_unit_id=str(active.get("decision_unit_id") or active_ids[0]),
        )

    decided = set((state.get("template_decisions") or {}).keys())
    pending_unit = next(
        (
            (
                chapter_id,
                decision_unit_id,
                [target_id for target_id in unit_ids if target_id not in decided],
            )
            for chapter_id, decision_unit_id, unit_ids in _decision_units(items)
            if any(target_id not in decided for target_id in unit_ids)
        ),
        None,
    )
    chapter_id, decision_unit_id, pending_ids = pending_unit or ("", "", [])
    if not pending_ids:
        return {
            "schema_version": STATE_SCHEMA,
            "batch_token": "",
            "chapter_id": "",
            "items": [],
            "decided_count": decided_count,
            "remaining_count": 0,
            "complete": True,
        }

    target_ids = pending_ids
    token = _batch_token(fingerprint, target_ids, workflow_binding)
    selected_response = _decision_batch_response(
        token=token,
        target_ids=target_ids,
        by_id=by_id,
        decided_count=decided_count,
        item_count=len(items),
        chapter_id=chapter_id,
        decision_unit_id=decision_unit_id,
    )
    if _compact_json_bytes(selected_response) >= MAX_DECISION_RESPONSE_BYTES:
        raise SystemExit("单个目录决策小节超过 24000 字节响应上限，请精简模板章节标题")
    selected_state = {
        "token": token,
        "chapter_id": chapter_id,
        "decision_unit_id": decision_unit_id,
        "target_ids": target_ids,
        "read_event_baseline": _evidence_read_event_count(work_dir),
    }
    state["active_batch"] = selected_state
    _write_json(_state_path(work_dir), state)
    return selected_response


def submit_decision_batch(
    work_dir: Path,
    structure: dict[str, Any],
    payload: dict[str, Any],
    *,
    appendix_items: list[dict[str, Any]] | None = None,
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
    additions = payload.get("additions") or []
    if not isinstance(additions, list):
        raise SystemExit("decision-batch additions must be a list")
    for index, addition in enumerate(additions):
        if not isinstance(addition, dict):
            raise SystemExit(f"decision-batch additions[{index}] must be an object")
        if "appendix_id" in addition:
            raise SystemExit("技术附表必须通过 appendix-decision-batch 决策")
    normalized_decisions: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_items):
        decision = str(item.get("decision") or "").strip()
        target_id = actual_ids[index]
        if decision == "retain":
            allowed = {"target_id", "decision", "reason", "tender_basis"}
            if set(item) - allowed:
                raise SystemExit(f"decision-batch items[{index}] retain has unsupported fields")
            has_reason = bool(str(item.get("reason") or "").strip())
            has_basis = isinstance(item.get("tender_basis"), dict)
            if has_reason and has_basis:
                raise SystemExit(
                    f"decision-batch items[{index}] retain requires exactly one of reason or tender_basis"
                )
            if not has_reason and not has_basis and (work_dir / "tender_evidence_access.json").is_file():
                raise SystemExit(
                    f"decision-batch items[{index}] retain requires exactly one of reason or tender_basis"
                )
            normalized_retain = {"target_id": target_id, "decision": "retain"}
            if has_reason:
                normalized_retain["reason"] = str(item["reason"]).strip()
            elif has_basis:
                normalized_retain["tender_basis"] = deepcopy(item["tender_basis"])
            normalized_decisions[target_id] = normalized_retain
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
        if set(item) != {"target_id", "decision", "reason"}:
            raise SystemExit(f"decision-batch items[{index}] suggest_delete has unsupported fields")
        normalized_decisions[target_id] = normalized

    read_event_baseline = active.get("read_event_baseline")
    if read_event_baseline is not None:
        current_read_count = _evidence_read_event_count(work_dir)
        if current_read_count is None or current_read_count <= int(read_event_baseline):
            raise SystemExit("decision-batch 前必须针对当前决策单元完成至少一次新的受控正文阅读")

    decisions = state.setdefault("template_decisions", {})
    decisions.update(normalized_decisions)

    existing_ids = {
        str(item.get("node_id") or "") for item in state.get("additions") or []
    }
    for index, addition in enumerate(additions):
        node_id = str(addition.get("node_id") or "").strip()
        reason = str(addition.get("reason") or "").strip()
        if not node_id or node_id in existing_ids:
            raise SystemExit(
                f"decision-batch additions[{index}].node_id is missing or duplicate"
            )
        if not reason:
            raise SystemExit(f"decision-batch additions[{index}].reason is required")
        if (
            not isinstance(addition.get("tender_basis"), dict)
            and (work_dir / "tender_evidence_access.json").is_file()
        ):
            raise SystemExit(f"decision-batch additions[{index}].tender_basis is required")
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
        state.setdefault("addition_chapters", {})[node_id] = str(
            active.get("chapter_id") or ""
        )
        existing_ids.add(node_id)

    state["active_batch"] = _empty_active_batch()
    _invalidate_global_review(state)
    inventory, _ = _normalized_appendix_inventory(appendix_items or [])
    _arm_global_review_if_ready(state, work_dir, items, inventory)
    _write_json(_state_path(work_dir), state)
    decided_count = len(decisions)
    return {
        "schema_version": STATE_SCHEMA,
        "decided_count": decided_count,
        "remaining_count": len(items) - decided_count,
        "addition_count": len(state.get("additions") or []),
    }


def _normalized_appendix_inventory(
    appendix_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(appendix_items, list):
        raise SystemExit("appendix inventory must be a list")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(appendix_items):
        if not isinstance(raw_item, dict):
            raise SystemExit(f"appendix inventory items[{index}] must be an object")
        appendix_id = str(raw_item.get("appendix_id") or "").strip()
        if not appendix_id:
            raise SystemExit(f"appendix inventory items[{index}].appendix_id is required")
        if appendix_id in seen_ids:
            raise SystemExit(f"appendix inventory appendix_id is duplicate: {appendix_id}")
        seen_ids.add(appendix_id)
        item = {
            "appendix_id": appendix_id,
            "file_id": str(raw_item.get("file_id") or "").strip(),
            "number": str(raw_item.get("number") or ""),
            "title": str(raw_item.get("title") or ""),
            "raw_text": str(raw_item.get("raw_text") or "").strip(),
        }
        try:
            item["following_table_count"] = int(
                raw_item.get("following_table_count") or 0
            )
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"appendix inventory items[{index}].following_table_count must be an integer"
            ) from exc
        source_status = str(raw_item.get("source_status") or "").strip()
        if source_status not in {"present", "missing"}:
            source_status = "present" if item["following_table_count"] > 0 else "missing"
        item["source_status"] = source_status
        evidence_id = str(raw_item.get("evidence_id") or "").strip()
        if evidence_id:
            item["evidence_id"] = evidence_id
        normalized.append(item)
    identity = [
        {key: value for key, value in item.items() if key != "evidence_id"}
        for item in normalized
    ]
    return normalized, _payload_digest(identity)


def _appendix_items_for_response(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "appendix_id": item["appendix_id"],
            "file_id": item["file_id"],
            "number": item["number"],
            "title": item["title"],
            "evidence_id": item.get("evidence_id") or "",
            "following_table_count": item["following_table_count"],
            "source_status": item["source_status"],
        }
        for item in items
    ]


def _appendix_batch_token(
    fingerprint: str,
    inventory_digest: str,
    appendix_ids: list[str],
    workflow_binding: dict[str, str] | None,
) -> str:
    return _payload_digest(
        {
            "input_fingerprint": fingerprint,
            "tender_inputs_digest": _binding_value(
                workflow_binding, "tenderInputsDigest"
            ),
            "headings_state_digest": _binding_value(
                workflow_binding, "headingsStateDigest"
            ),
            "appendix_inventory_digest": inventory_digest,
            "appendix_ids": appendix_ids,
        }
    )


def _require_template_decisions_complete(
    state: dict[str, Any], items: list[dict[str, Any]]
) -> None:
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("appendix-next 请先完成模板逐项判断并提交当前批次")
    decisions = state.get("template_decisions") or {}
    expected_ids = [str(item["template_id"]) for item in items]
    if set(decisions) != set(expected_ids):
        raise SystemExit("appendix-next 请先完成模板逐项判断")


def _reject_changed_appendix_inventory(
    state: dict[str, Any], inventory_digest: str
) -> None:
    issued_digest = str(state.get("appendix_inventory_digest") or "")
    if issued_digest and issued_digest != inventory_digest:
        raise SystemExit("appendix inventory changed after batch token issuance")


def next_appendix_batch(
    work_dir: Path,
    structure: dict[str, Any],
    appendix_items: list[dict[str, Any]],
    *,
    max_items: int = 20,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    if max_items < 1 or max_items > 20:
        raise SystemExit("appendix-next max_items must be between 1 and 20")
    annotated, template_items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint, workflow_binding)
    _require_template_decisions_complete(state, template_items)
    inventory, inventory_digest = _normalized_appendix_inventory(appendix_items)
    _reject_changed_appendix_inventory(state, inventory_digest)
    by_id = {str(item["appendix_id"]): item for item in inventory}
    decisions = state.get("appendix_decisions") or {}
    unknown_decisions = set(decisions) - set(by_id)
    if unknown_decisions:
        raise SystemExit(
            "appendix decision state contains unknown appendix_id: "
            + ", ".join(sorted(unknown_decisions)[:20])
        )
    active = state.get("active_appendix_batch") or {}
    active_ids = list(active.get("appendix_ids") or [])
    submission_contract = {
        "items_must_match_batch": True,
        "exclude_fields": ["appendix_id", "decision", "reason"],
        "include_fields": [
            "appendix_id",
            "decision",
            "node_id",
            "parent_id",
            "reason",
        ],
        "include_parent_id": "必须引用本批 root_addition.node_id 或已有唯一技术附表根节点",
        "missing_rule": "清单存在 present 候选时，source_status=missing 没有独立表格，必须 exclude",
        "root_addition": {
            "required_when": "首次 include 且尚无唯一的技术附表根节点",
            "fields": ["node_id", "parent_id", "number", "title", "reason"],
            "parent_id": None,
            "title": "技术附表",
        },
    }
    if active_ids:
        return {
            "schema_version": STATE_SCHEMA,
            "batch_token": str(active.get("token") or ""),
            "items": _appendix_items_for_response([by_id[item_id] for item_id in active_ids]),
            "submission_contract": submission_contract,
            "decided_count": len(decisions),
            "remaining_count": len(inventory) - len(decisions),
            "complete": False,
        }
    pending = [item for item in inventory if item["appendix_id"] not in decisions]
    if not pending:
        return {
            "schema_version": STATE_SCHEMA,
            "batch_token": "",
            "items": [],
            "decided_count": len(decisions),
            "remaining_count": 0,
            "complete": True,
        }
    selected = pending[:max_items]
    appendix_ids = [str(item["appendix_id"]) for item in selected]
    token = _appendix_batch_token(
        fingerprint, inventory_digest, appendix_ids, workflow_binding
    )
    state["appendix_inventory_digest"] = inventory_digest
    state["active_appendix_batch"] = {
        "token": token,
        "appendix_ids": appendix_ids,
    }
    _write_json(_state_path(work_dir), state)
    return {
        "schema_version": STATE_SCHEMA,
        "batch_token": token,
        "items": _appendix_items_for_response(selected),
        "submission_contract": submission_contract,
        "decided_count": len(decisions),
        "remaining_count": len(inventory) - len(decisions),
        "complete": False,
    }


def _required_json_string(value: Any, field_path: str) -> str:
    if value is None:
        raise SystemExit(f"{field_path} is required")
    if not isinstance(value, str):
        raise SystemExit(f"{field_path} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SystemExit(f"{field_path} is required")
    return normalized


def submit_appendix_batch(
    work_dir: Path,
    structure: dict[str, Any],
    payload: dict[str, Any],
    appendix_items: list[dict[str, Any]],
    *,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    annotated, template_items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint, workflow_binding)
    _require_template_decisions_complete(state, template_items)
    inventory, inventory_digest = _normalized_appendix_inventory(appendix_items)
    _reject_changed_appendix_inventory(state, inventory_digest)
    active = state.get("active_appendix_batch") or {}
    expected_ids = list(active.get("appendix_ids") or [])
    token = str(payload.get("batch_token") or "")
    if not expected_ids or token != str(active.get("token") or ""):
        raise SystemExit(
            "appendix-decision-batch must use the current appendix-next batch_token"
        )
    if token != _appendix_batch_token(
        fingerprint, inventory_digest, expected_ids, workflow_binding
    ):
        raise SystemExit("appendix-decision-batch batch_token binding is invalid")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise SystemExit("appendix-decision-batch items must be a list")
    actual_ids: list[str] = []
    decision_values: list[str] = []
    reasons: list[str] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise SystemExit(f"appendix-decision-batch items[{index}] must be an object")
        appendix_id = _required_json_string(
            raw_item.get("appendix_id"),
            f"appendix-decision-batch items[{index}].appendix_id",
        )
        decision = _required_json_string(
            raw_item.get("decision"),
            f"appendix-decision-batch items[{index}].decision",
        )
        reason = _required_json_string(
            raw_item.get("reason"),
            f"appendix-decision-batch items[{index}].reason",
        )
        if decision not in {"include", "exclude"}:
            raise SystemExit(
                f"appendix-decision-batch items[{index}].decision must be include or exclude"
            )
        actual_ids.append(appendix_id)
        decision_values.append(decision)
        reasons.append(reason)
    if actual_ids != expected_ids or len(raw_items) != len(expected_ids):
        raise SystemExit(
            "appendix-decision-batch items must exactly match the current appendix-next batch"
        )

    inventory_by_id = {str(item["appendix_id"]): item for item in inventory}
    inventory_has_present = any(
        str(item.get("source_status") or "") == "present" for item in inventory
    )
    for index, appendix_id in enumerate(actual_ids):
        if (
            inventory_has_present
            and decision_values[index] == "include"
            and str(inventory_by_id[appendix_id].get("source_status") or "") == "missing"
        ):
            raise SystemExit(
                f"appendix-decision-batch items[{index}] source_status=missing has no independent table and must be exclude"
            )
    normalized_decisions: list[dict[str, Any]] = []
    new_changes: list[dict[str, Any]] = []
    additions = state.get("additions") or []
    existing_node_ids = {
        str(item.get("node_id") or "") for item in additions if isinstance(item, dict)
    }
    template_node_ids = {
        str(item.get("template_id") or "")
        for item in annotated.get("items") or []
        if isinstance(item, dict) and str(item.get("template_id") or "")
    }
    deleted_addition_ids = {
        str(item.get("target_id") or item.get("node_id") or "")
        for item in additions
        if isinstance(item, dict)
        and str(item.get("operation") or "") in {"delete", "suggest_delete"}
    }
    valid_roots = [
        item
        for item in additions
        if isinstance(item, dict)
        and str(item.get("operation") or "") == "add"
        and not item.get("parent_id")
        and str(item.get("title") or "") == "技术附表"
        and str(item.get("node_id") or "")
        and str(item.get("node_id") or "") not in deleted_addition_ids
    ]
    valid_root_id = (
        str(valid_roots[0].get("node_id") or "") if len(valid_roots) == 1 else ""
    )
    has_include = "include" in decision_values
    root_supplied = "root_addition" in payload
    root_addition = payload.get("root_addition")
    batch_node_ids: set[str] = set()
    if root_supplied:
        if not has_include:
            raise SystemExit(
                "appendix-decision-batch root_addition must be omitted when the batch has no include"
            )
        if valid_root_id:
            raise SystemExit(
                "appendix-decision-batch root_addition must be omitted when a valid 技术附表 root already exists"
            )
        if valid_roots:
            raise SystemExit(
                "appendix-decision-batch root_addition cannot repair multiple valid 技术附表 roots"
            )
        if not isinstance(root_addition, dict):
            raise SystemExit("appendix-decision-batch root_addition must be an object")
        root_fields = {
            "node_id",
            "parent_id",
            "number",
            "title",
            "reason",
        }
        missing_root_fields = root_fields - set(root_addition)
        if missing_root_fields:
            raise SystemExit(
                "appendix-decision-batch root_addition."
                + sorted(missing_root_fields)[0]
                + " is required"
            )
        if set(root_addition) - root_fields:
            raise SystemExit(
                "appendix-decision-batch root_addition has unsupported fields"
            )
        root_node_id = _required_json_string(
            root_addition.get("node_id"),
            "appendix-decision-batch root_addition.node_id",
        )
        root_number = _required_json_string(
            root_addition.get("number"),
            "appendix-decision-batch root_addition.number",
        )
        root_title = _required_json_string(
            root_addition.get("title"),
            "appendix-decision-batch root_addition.title",
        )
        root_reason = _required_json_string(
            root_addition.get("reason"),
            "appendix-decision-batch root_addition.reason",
        )
        if root_node_id in template_node_ids:
            raise SystemExit(
                "appendix-decision-batch root_addition.node_id conflicts with a template node: "
                + root_node_id
            )
        if root_node_id in existing_node_ids:
            raise SystemExit(
                "appendix-decision-batch root_addition.node_id conflicts with an existing addition: "
                + root_node_id
            )
        if root_addition.get("parent_id") is not None:
            raise SystemExit("appendix-decision-batch root_addition.parent_id must be null")
        if root_addition["title"] != "技术附表":
            raise SystemExit(
                "appendix-decision-batch root_addition.title must be exactly 技术附表"
        )
        valid_root_id = root_node_id
        batch_node_ids.add(root_node_id)
        new_changes.append(
            {
                "operation": "add",
                "node_id": root_node_id,
                "parent_id": None,
                "number": root_number,
                "title": root_title,
                "suggestion_action": "建议增加",
                "suggestion_reason": root_reason,
            }
        )
    elif has_include and not valid_root_id:
        raise SystemExit(
            "appendix-decision-batch root_addition is required for the first include when no unique valid 技术附表 root exists"
        )

    for index, raw_item in enumerate(raw_items):
        appendix_id = actual_ids[index]
        decision = decision_values[index]
        reason = reasons[index]
        if decision == "exclude":
            if set(raw_item) != {"appendix_id", "decision", "reason"}:
                raise SystemExit(
                    f"appendix-decision-batch items[{index}] exclude has unsupported fields"
                )
            normalized_decisions.append(
                {"appendix_id": appendix_id, "decision": decision, "reason": reason}
            )
            continue
        node_id = _required_json_string(
            raw_item.get("node_id"),
            f"appendix-decision-batch items[{index}].node_id",
        )
        parent_id = _required_json_string(
            raw_item.get("parent_id"),
            f"appendix-decision-batch items[{index}].parent_id",
        )
        if set(raw_item) != {
            "appendix_id",
            "decision",
            "node_id",
            "parent_id",
            "reason",
        }:
            raise SystemExit(
                f"appendix-decision-batch items[{index}] include has unsupported fields"
            )
        if node_id in template_node_ids:
            raise SystemExit(
                f"appendix-decision-batch items[{index}].node_id conflicts with a template node: {node_id}"
            )
        if node_id in existing_node_ids:
            raise SystemExit(
                f"appendix-decision-batch items[{index}].node_id conflicts with an existing addition: {node_id}"
            )
        if node_id in batch_node_ids:
            raise SystemExit(
                f"appendix-decision-batch items[{index}].node_id is duplicate in the batch: {node_id}"
            )
        if not valid_root_id or parent_id != valid_root_id:
            raise SystemExit(
                f"appendix-decision-batch items[{index}].parent_id must reference the unique valid root-level 技术附表 addition"
            )
        batch_node_ids.add(node_id)
        normalized_decisions.append(
            {
                "appendix_id": appendix_id,
                "decision": decision,
                "reason": reason,
                "node_id": node_id,
                "parent_id": parent_id,
            }
        )
        appendix = inventory_by_id[appendix_id]
        tender_basis = {
            "file_id": appendix["file_id"],
            "search_text": appendix["raw_text"]
            or " ".join(
                part for part in (appendix["number"], appendix["title"]) if part
            ),
        }
        if appendix.get("evidence_id"):
            tender_basis["evidence_id"] = appendix["evidence_id"]
        new_changes.append(
            {
                "operation": "add",
                "node_id": node_id,
                "parent_id": parent_id,
                "number": appendix["number"],
                "title": appendix["title"],
                "suggestion_action": "建议增加",
                "suggestion_reason": reason,
                "tender_basis": tender_basis,
            }
        )

    template_decisions = state.get("template_decisions") or {}
    candidate_decisions = {
        "schema_version": outline_composer.DECISIONS_SCHEMA,
        "input_fingerprint": fingerprint,
        "template_decisions": deepcopy(
            [template_decisions[str(item["template_id"])] for item in template_items]
        ),
        "changes": deepcopy(additions) + deepcopy(new_changes),
    }
    try:
        outline_composer.build_composition(structure, candidate_decisions)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    decisions = state.setdefault("appendix_decisions", {})
    for item in normalized_decisions:
        decisions[item["appendix_id"]] = item
    state.setdefault("additions", []).extend(new_changes)
    state["active_appendix_batch"] = _empty_active_appendix_batch()
    _invalidate_global_review(state)
    _arm_global_review_if_ready(state, work_dir, template_items, inventory)
    _write_json(_state_path(work_dir), state)
    return {
        "schema_version": STATE_SCHEMA,
        "decided_count": len(decisions),
        "remaining_count": len(inventory) - len(decisions),
        "addition_count": len(state.get("additions") or []),
        "complete": len(decisions) == len(inventory),
    }


def reopen_decision_chapter(
    work_dir: Path,
    structure: dict[str, Any],
    chapter_id: str,
    *,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    state = _load_state(work_dir, annotated["input_fingerprint"], workflow_binding)
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("请先提交当前目录章节，再重开需要修正的章节")
    groups = dict(_chapter_groups(items))
    if chapter_id not in groups:
        raise SystemExit("decision-reopen chapter_id must reference a root template chapter")
    target_ids = set(groups[chapter_id])
    decisions = state.setdefault("template_decisions", {})
    for target_id in target_ids:
        decisions.pop(target_id, None)
    addition_chapters = state.setdefault("addition_chapters", {})
    removed_addition_ids = {
        node_id
        for node_id, owner_chapter_id in addition_chapters.items()
        if owner_chapter_id == chapter_id
    }
    state["additions"] = [
        item
        for item in state.get("additions") or []
        if str(item.get("node_id") or "") not in removed_addition_ids
    ]
    for node_id in removed_addition_ids:
        addition_chapters.pop(node_id, None)
    _invalidate_global_review(state)
    _write_json(_state_path(work_dir), state)
    return {
        "schema_version": STATE_SCHEMA,
        "chapter_id": chapter_id,
        "reopened_item_count": len(target_ids),
        "remaining_count": len(items) - len(decisions),
    }


def apply_global_review_corrections(
    work_dir: Path,
    structure: dict[str, Any],
    payload: dict[str, Any],
    *,
    appendix_items: list[dict[str, Any]] | None = None,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    state = _load_state(work_dir, annotated["input_fingerprint"], workflow_binding)
    inventory, inventory_digest = _normalized_appendix_inventory(appendix_items or [])
    _reject_changed_appendix_inventory(state, inventory_digest)
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("全局纠偏前必须提交当前目录章节")
    if (state.get("active_appendix_batch") or {}).get("appendix_ids"):
        raise SystemExit("全局纠偏前必须提交当前附表批次")

    template_ids = {str(item["template_id"]) for item in items}
    if set(state.get("template_decisions") or {}) != template_ids:
        raise SystemExit("全局纠偏前必须完成全部章节决策")
    appendix_ids = {str(item["appendix_id"]) for item in inventory}
    if set(state.get("appendix_decisions") or {}) != appendix_ids:
        raise SystemExit("全局纠偏前必须完成全部附表决策")

    raw_items = payload.get("items")
    additions = payload.get("additions")
    if not isinstance(raw_items, list) or not isinstance(additions, list):
        raise SystemExit("review-corrections requires items and additions lists")
    if not raw_items and not additions:
        raise SystemExit("review-corrections requires at least one correction")

    baseline = state.get("global_review_read_baseline")
    current_read_count = _evidence_read_event_count(work_dir)
    if current_read_count is not None:
        if baseline is None or current_read_count <= int(baseline):
            raise SystemExit("全局纠偏前必须从招标侧完成至少一次新的正文阅读")

    normalized_decisions: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise SystemExit(f"review-corrections items[{index}] must be an object")
        target_id = str(item.get("target_id") or "").strip()
        if target_id not in template_ids or target_id in normalized_decisions:
            raise SystemExit(
                f"review-corrections items[{index}].target_id is invalid or duplicate"
            )
        decision = str(item.get("decision") or "").strip()
        if decision == "suggest_delete":
            reason = str(item.get("reason") or "").strip()
            if not reason or set(item) != {"target_id", "decision", "reason"}:
                raise SystemExit(
                    f"review-corrections items[{index}] suggest_delete requires only target_id, decision and reason"
                )
            normalized_decisions[target_id] = {
                "target_id": target_id,
                "decision": decision,
                "reason": reason,
            }
            continue
        if decision != "retain":
            raise SystemExit(
                f"review-corrections items[{index}].decision must be retain or suggest_delete"
            )
        allowed = {"target_id", "decision", "reason", "tender_basis"}
        if set(item) - allowed:
            raise SystemExit(f"review-corrections items[{index}] retain has unsupported fields")
        has_reason = bool(str(item.get("reason") or "").strip())
        has_basis = isinstance(item.get("tender_basis"), dict)
        if has_reason == has_basis and (has_reason or (work_dir / "tender_evidence_access.json").is_file()):
            raise SystemExit(
                f"review-corrections items[{index}] retain requires exactly one of reason or tender_basis"
            )
        normalized = {"target_id": target_id, "decision": "retain"}
        if has_reason:
            normalized["reason"] = str(item["reason"]).strip()
        elif has_basis:
            normalized["tender_basis"] = deepcopy(item["tender_basis"])
        normalized_decisions[target_id] = normalized

    groups = dict(_chapter_groups(items))
    owner_by_target = {
        target_id: chapter_id
        for chapter_id, target_ids in groups.items()
        for target_id in target_ids
    }
    existing_ids = {
        str(item.get("node_id") or "") for item in state.get("additions") or []
    }
    new_changes: list[dict[str, Any]] = []
    new_owners: dict[str, str] = {}
    for index, addition in enumerate(additions):
        if not isinstance(addition, dict):
            raise SystemExit(f"review-corrections additions[{index}] must be an object")
        if "appendix_id" in addition:
            raise SystemExit("技术附表必须通过 appendix-decision-batch 决策")
        node_id = str(addition.get("node_id") or "").strip()
        reason = str(addition.get("reason") or "").strip()
        parent_id = addition.get("parent_id")
        parent_key = str(parent_id or "")
        if not node_id or node_id in existing_ids or node_id in new_owners:
            raise SystemExit(
                f"review-corrections additions[{index}].node_id is missing or duplicate"
            )
        if not reason:
            raise SystemExit(f"review-corrections additions[{index}].reason is required")
        if parent_id is not None and parent_key not in template_ids | existing_ids | set(new_owners):
            raise SystemExit(f"review-corrections additions[{index}].parent_id is invalid")
        if (
            not isinstance(addition.get("tender_basis"), dict)
            and (work_dir / "tender_evidence_access.json").is_file()
        ):
            raise SystemExit(f"review-corrections additions[{index}].tender_basis is required")
        change = {
            "operation": "add",
            "node_id": node_id,
            "parent_id": parent_id,
            "number": str(addition.get("number") or ""),
            "title": str(addition.get("title") or ""),
            "suggestion_action": "建议增加",
            "suggestion_reason": reason,
        }
        if "tender_basis" in addition:
            change["tender_basis"] = deepcopy(addition["tender_basis"])
        new_changes.append(change)
        owner = (
            owner_by_target.get(parent_key)
            or state.get("addition_chapters", {}).get(parent_key, "")
            or new_owners.get(parent_key, "")
        )
        new_owners[node_id] = str(owner or "")

    state.setdefault("template_decisions", {}).update(normalized_decisions)
    state.setdefault("additions", []).extend(new_changes)
    state.setdefault("addition_chapters", {}).update(new_owners)
    _invalidate_global_review(state)
    _arm_global_review_if_ready(state, work_dir, items, inventory)
    _write_json(_state_path(work_dir), state)
    return {
        "schema_version": STATE_SCHEMA,
        "corrected_item_count": len(normalized_decisions),
        "added_count": len(new_changes),
        "review_complete": False,
    }


def complete_global_review(
    work_dir: Path,
    structure: dict[str, Any],
    payload: dict[str, Any],
    *,
    appendix_items: list[dict[str, Any]] | None = None,
    workflow_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    state = _load_state(work_dir, annotated["input_fingerprint"], workflow_binding)
    inventory, inventory_digest = _normalized_appendix_inventory(appendix_items or [])
    _reject_changed_appendix_inventory(state, inventory_digest)
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("全局复核前必须提交当前目录章节")
    if (state.get("active_appendix_batch") or {}).get("appendix_ids"):
        raise SystemExit("全局复核前必须提交当前附表批次")
    expected_ids = {str(item["template_id"]) for item in items}
    if set(state.get("template_decisions") or {}) != expected_ids:
        raise SystemExit("全局复核前必须完成全部章节决策")
    expected_appendix_ids = {str(item["appendix_id"]) for item in inventory}
    if set(state.get("appendix_decisions") or {}) != expected_appendix_ids:
        raise SystemExit("全局复核前必须完成全部附表决策")
    summary = str(payload.get("review_summary") or "").strip()
    if not summary:
        raise SystemExit("review-complete review_summary is required")
    issues = payload.get("issues")
    if not isinstance(issues, list):
        raise SystemExit("review-complete issues must be a list")
    if issues:
        raise SystemExit("全局复核仍有问题；请按 chapter_id 重开对应章节")
    baseline = state.get("global_review_read_baseline")
    current_read_count = _evidence_read_event_count(work_dir)
    if current_read_count is not None:
        if baseline is None or current_read_count <= int(baseline):
            raise SystemExit("全局复核阶段必须从招标侧完成至少一次新的正文阅读")
    digest = _current_decisions_digest(state)
    state["global_review_digest"] = digest
    state["global_review_summary"] = summary
    _write_json(_state_path(work_dir), state)
    return {
        "schema_version": STATE_SCHEMA,
        "review_digest": digest,
        "review_complete": True,
    }


def finalize_decisions(
    work_dir: Path,
    structure: dict[str, Any],
    *,
    appendix_items: list[dict[str, Any]] | None = None,
    workflow_binding: dict[str, str] | None = None,
    require_global_review: bool = False,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    state = _load_state(work_dir, fingerprint, workflow_binding)
    inventory, inventory_digest = _normalized_appendix_inventory(appendix_items or [])
    _reject_changed_appendix_inventory(state, inventory_digest)
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("current decision-next batch has not been submitted")
    if (state.get("active_appendix_batch") or {}).get("appendix_ids"):
        raise SystemExit("current appendix-next batch has not been submitted")
    decisions_by_id = state.get("template_decisions") or {}
    missing = [
        str(item["template_id"])
        for item in items
        if str(item["template_id"]) not in decisions_by_id
    ]
    if missing:
        raise SystemExit("template decisions missing: " + ", ".join(missing[:20]))
    appendix_decisions = state.get("appendix_decisions") or {}
    expected_appendix_ids = [str(item["appendix_id"]) for item in inventory]
    missing_appendix_ids = [
        appendix_id
        for appendix_id in expected_appendix_ids
        if appendix_id not in appendix_decisions
    ]
    if missing_appendix_ids:
        raise SystemExit(
            "appendix decisions missing: " + ", ".join(missing_appendix_ids[:20])
        )
    if set(appendix_decisions) != set(expected_appendix_ids):
        raise SystemExit("appendix decision state does not match the current inventory")
    if require_global_review and str(
        state.get("global_review_digest") or ""
    ) != _current_decisions_digest(state):
        raise SystemExit("必须先完成一次全局复核，再生成最终目录决策")
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
    appendix_items: list[dict[str, Any]] | None = None,
    include_appendix_decisions: bool = False,
) -> dict[str, Any]:
    annotated, items = _annotated_items(structure)
    fingerprint = annotated["input_fingerprint"]
    path = _state_path(work_dir)
    if not path.is_file():
        raise SystemExit("必须通过 decision-next、decision-batch 和 decisions 生成受控决策")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"outline decision state is invalid: {path}: {exc}") from exc
    if isinstance(state, dict) and state.get("schema_version") in LEGACY_STATE_SCHEMAS:
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
    inventory, inventory_digest = _normalized_appendix_inventory(appendix_items or [])
    _reject_changed_appendix_inventory(state, inventory_digest)
    if (state.get("active_batch") or {}).get("target_ids"):
        raise SystemExit("current decision-next batch has not been submitted")
    if (state.get("active_appendix_batch") or {}).get("appendix_ids"):
        raise SystemExit("current appendix-next batch has not been submitted")

    decisions_by_id = state.get("template_decisions")
    if not isinstance(decisions_by_id, dict):
        raise SystemExit("outline decision state template_decisions is invalid")
    expected_ids = [str(item["template_id"]) for item in items]
    if set(decisions_by_id) != set(expected_ids):
        raise SystemExit("outline decision state does not contain all controlled template decisions")
    appendix_decisions = state.get("appendix_decisions")
    if not isinstance(appendix_decisions, dict):
        raise SystemExit("outline decision state appendix_decisions is invalid")
    expected_appendix_ids = [str(item["appendix_id"]) for item in inventory]
    if set(appendix_decisions) != set(expected_appendix_ids):
        raise SystemExit("outline decision state does not contain all appendix decisions")
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
    result: dict[str, Any] = {"decisionStateDigest": _payload_digest(state)}
    if include_appendix_decisions:
        resolved_appendix_decisions: list[dict[str, Any]] = []
        for item in inventory:
            appendix_id = str(item["appendix_id"])
            decision = appendix_decisions[appendix_id]
            if not isinstance(decision, dict) or decision.get("decision") not in {
                "include",
                "exclude",
            }:
                raise SystemExit(
                    f"outline decision state appendix decision is invalid: {appendix_id}"
                )
            resolved_appendix_decisions.append(
                {
                    "appendix_id": appendix_id,
                    "number": item["number"],
                    "title": item["title"],
                    "decision": decision["decision"],
                }
            )
        result["appendixDecisions"] = resolved_appendix_decisions
    return result
