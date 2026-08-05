from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


DECISIONS_SCHEMA = "technical-outline-decisions.v1"
REPORT_SCHEMA = "technical-outline-compose-report.v1"
DECISIONS_FILE_NAME = "outline_authoring_decisions.json"
REPORT_FILE_NAME = "outline_compose_report.json"
ALLOWED_SUGGESTION_ACTIONS = {"必要", "建议增加", "建议删除", "待确认"}
# 决策粒度只到二级；三级节点跟随最近的已决策祖先，最终目录仍是三级。
DECISION_MAX_LEVEL = 2
APPENDIX_ROOT_TITLE = "技术附表"
OUTPUT_NODE_FIELDS = {
    "number",
    "title",
    "suggestion_action",
    "suggestion_reason",
    "tender_basis",
}


def annotate_template_structure(structure: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(structure)
    items = result.get("items")
    if not isinstance(items, list):
        raise ValueError("templateStructureFile.items must be a list")

    stack: list[tuple[int, str]] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(items, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError(f"templateStructureFile.items[{index - 1}] must be an object")
        level = _positive_int(raw_item.get("level"), f"templateStructureFile.items[{index - 1}].level")
        template_id = str(raw_item.get("template_id") or f"TPL-{index:04d}").strip()
        if template_id in seen_ids:
            raise ValueError(f"duplicate template_id: {template_id}")
        seen_ids.add(template_id)
        while stack and stack[-1][0] >= level:
            stack.pop()
        raw_item["template_id"] = template_id
        raw_item["parent_id"] = stack[-1][1] if stack else None
        stack.append((level, template_id))

    result["input_fingerprint"] = template_fingerprint(result)
    return result


def template_fingerprint(structure: dict[str, Any]) -> str:
    items = structure.get("items")
    if not isinstance(items, list):
        raise ValueError("templateStructureFile.items must be a list")
    canonical = []
    stack: list[tuple[int, str]] = []
    for index, raw_item in enumerate(items, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError(f"templateStructureFile.items[{index - 1}] must be an object")
        level = _positive_int(raw_item.get("level"), f"templateStructureFile.items[{index - 1}].level")
        template_id = str(raw_item.get("template_id") or f"TPL-{index:04d}").strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = str(raw_item.get("parent_id") or (stack[-1][1] if stack else "")).strip()
        canonical.append(
            {
                "template_id": template_id,
                "parent_id": parent_id,
                "number": str(raw_item.get("number") or ""),
                "title": str(raw_item.get("title") or ""),
                "level": level,
            }
        )
        stack.append((level, template_id))
    return _payload_digest(canonical)


def submit_decisions(
    *,
    work_dir: Path,
    structure: dict[str, Any],
    decisions: dict[str, Any],
) -> dict[str, Any]:
    annotated = annotate_template_structure(structure)
    normalized = deepcopy(decisions)
    build_composition(annotated, normalized)
    output_path = work_dir / DECISIONS_FILE_NAME
    _write_json(output_path, normalized)
    return {
        "schema_version": DECISIONS_SCHEMA,
        "decisionsFile": str(output_path),
        "changeCount": len(normalized.get("changes") or []),
        "templateDecisionCount": len(normalized.get("template_decisions") or []),
        "remainingTemplateDecisionCount": 0,
        "inputFingerprint": annotated["input_fingerprint"],
    }


def load_decisions(
    work_dir: Path,
    structure: dict[str, Any],
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    annotated = annotate_template_structure(structure)
    path = work_dir / DECISIONS_FILE_NAME
    if not path.exists():
        if required:
            raise ValueError("必须先执行 s2outline decisions，再执行 s2outline compose")
        return None
    decisions = _load_json_dict(path, "outlineAuthoringDecisionsFile")
    build_composition(annotated, decisions)
    return decisions


def build_composition(
    structure: dict[str, Any],
    decisions: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    annotated = annotate_template_structure(structure)
    _validate_decisions_header(annotated, decisions)
    roots, records = _build_template_records(annotated)
    _apply_template_decisions(records, decisions.get("template_decisions") or [])
    _inherit_decisions(roots)
    _apply_changes(roots, records, decisions.get("changes") or [])
    outline = {
        "schema_version": "technical-outline.v1",
        "nodes": [_serialize_record(record) for record in roots if not record["collapsed"]],
    }
    context = {
        "roots": roots,
        "records": records,
        "inputFingerprint": annotated["input_fingerprint"],
        "decisionsDigest": _payload_digest(decisions),
    }
    return outline, context


def build_level_three_report(
    structure: dict[str, Any],
    decisions: dict[str, Any] | None,
    output_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    if decisions is None:
        annotated = annotate_template_structure(structure)
        decisions = {
            "schema_version": DECISIONS_SCHEMA,
            "input_fingerprint": annotated["input_fingerprint"],
            "template_decisions": [
                {
                    "target_id": str(item["template_id"]),
                    "decision": "retain",
                }
                for item in annotated["items"]
                if int(item.get("level") or 1) <= DECISION_MAX_LEVEL
            ],
            "changes": [],
        }
    _, context = build_composition(structure, decisions)
    records = context["records"]
    template_level_three = [
        record
        for record in records.values()
        if record["is_template"] and record["source_level"] == 3
    ]
    level_two_records = [
        record
        for record in records.values()
        if (record["is_template"] and record["source_level"] == 2)
        or (not record["collapsed"] and record["depth"] == 2)
    ]

    actual_by_id = {
        record["id"]: None if record["collapsed"] else _find_actual_node(record, output_nodes)
        for record in records.values()
    }
    retained_template_ids = {
        record["id"]
        for record in template_level_three
        if not record["collapsed"]
        and record["depth"] == 3
        and actual_by_id[record["id"]] is not None
    }
    collapsed_ids = {record["id"] for record in template_level_three if record["collapsed"]}
    moved_out_of_level_three_ids = {
        record["id"]
        for record in template_level_three
        if not record["collapsed"]
        and record["depth"] != 3
        and actual_by_id[record["id"]] is not None
    }
    moved_into_level_three_ids = {
        record["id"]
        for record in records.values()
        if record["is_template"]
        and record["source_level"] != 3
        and not record["collapsed"]
        and record["depth"] == 3
        and actual_by_id[record["id"]] is not None
    }
    explicit_added_level_three_ids = {
        record["id"]
        for record in records.values()
        if not record["is_template"]
        and not record["collapsed"]
        and record["depth"] == 3
        and actual_by_id[record["id"]] is not None
    }
    output_level_three_count = len(_nodes_at_depth(output_nodes, target_depth=3))
    known_level_three_count = sum(
        1
        for record in records.values()
        if not record["collapsed"]
        and record["depth"] == 3
        and actual_by_id[record["id"]] is not None
    )
    untracked_added_count = max(0, output_level_three_count - known_level_three_count)
    parents = []
    for parent in level_two_records:
        original_children = [
            child
            for child in parent["original_children"]
            if child["is_template"] and child["source_level"] == 3
        ]
        retained = [
            child
            for child in original_children
            if child["id"] in retained_template_ids and child["parent_id"] == parent["id"]
        ]
        collapsed = [child for child in original_children if child["id"] in collapsed_ids]
        moved_out = [
            child
            for child in original_children
            if not child["collapsed"]
            and actual_by_id[child["id"]] is not None
            and (child["parent_id"] != parent["id"] or child["depth"] != 3)
        ]
        moved_in = [
            child
            for child in parent["children"]
            if child["is_template"]
            and child["original_parent_id"] != parent["id"]
            and child["depth"] == 3
            and actual_by_id[child["id"]] is not None
        ]
        actual_parent = actual_by_id[parent["id"]]
        actual_children = (
            actual_parent.get("children") or []
            if actual_parent is not None and parent["depth"] == 2
            else []
        )
        known_children_here = [
            child
            for child in parent["children"]
            if not child["collapsed"]
            and child["depth"] == 3
            and actual_by_id[child["id"]] is not None
        ]
        explicit_added_here = sum(
            1
            for child in known_children_here
            if not child["is_template"]
        )
        added_count = explicit_added_here + max(0, len(actual_children) - len(known_children_here))
        unexplained = [
            child
            for child in original_children
            if child["id"] not in collapsed_ids and actual_by_id[child["id"]] is None
        ]
        parents.append(
            {
                "parentId": parent["id"],
                "number": str(parent["node"].get("number") or ""),
                "title": str(parent["node"].get("title") or ""),
                "templateCount": len(original_children),
                "retainedCount": len(retained),
                "collapsedCount": len(collapsed),
                "movedOutCount": len(moved_out),
                "movedInCount": len(moved_in),
                "addedCount": added_count,
                "finalCount": len(actual_children),
                "unexplainedMissingCount": len(unexplained),
            }
        )

    retained_count = len(retained_template_ids)
    template_count = len(template_level_three)
    unexplained_count = sum(
        1
        for record in template_level_three
        if record["id"] not in collapsed_ids and actual_by_id[record["id"]] is None
    )
    return {
        "templateCount": template_count,
        "outputCount": output_level_three_count,
        "retainedCount": retained_count,
        "collapsedCount": len(collapsed_ids),
        "movedOutOfLevel3Count": len(moved_out_of_level_three_ids),
        "movedIntoLevel3Count": len(moved_into_level_three_ids),
        "addedCount": len(explicit_added_level_three_ids) + untracked_added_count,
        "unexplainedMissingCount": unexplained_count,
        "parentsWithUnexplainedMissing": sum(
            1 for item in parents if item["unexplainedMissingCount"] > 0
        ),
        "retentionRate": round(retained_count / template_count, 4) if template_count else 1.0,
        "parents": parents,
    }


def write_compose_report(
    *,
    work_dir: Path,
    output_file: Path,
    structure: dict[str, Any],
    decisions: dict[str, Any],
    level_three_report: dict[str, Any],
    workflow_proof: dict[str, str] | None = None,
) -> Path:
    report_path = work_dir / REPORT_FILE_NAME
    payload = {
        "schema_version": REPORT_SCHEMA,
        "inputFingerprint": template_fingerprint(annotate_template_structure(structure)),
        "decisionsDigest": _payload_digest(decisions),
        "outputSha256": _file_digest(output_file),
        "outputFile": str(output_file),
        "templateLevel3": level_three_report,
    }
    if workflow_proof:
        for field in ("tenderInputsDigest", "headingsStateDigest", "decisionStateDigest"):
            value = str(workflow_proof.get(field) or "").strip()
            if not value:
                raise ValueError(f"compose workflow proof is missing {field}")
            payload[field] = value
    _write_json(report_path, payload)
    return report_path


def validate_compose_report(
    *,
    work_dir: Path,
    output_file: Path,
    structure: dict[str, Any],
    decisions: dict[str, Any],
    workflow_proof: dict[str, str] | None = None,
) -> dict[str, Any]:
    report_path = work_dir / REPORT_FILE_NAME
    if not report_path.exists():
        raise ValueError("requireComposedOutline 已启用，但尚未执行 s2outline compose")
    report = _load_json_dict(report_path, "outlineComposeReportFile")
    if report.get("schema_version") != REPORT_SCHEMA:
        raise ValueError("outlineComposeReportFile schema_version is invalid")
    current_fingerprint = template_fingerprint(annotate_template_structure(structure))
    if report.get("inputFingerprint") != current_fingerprint:
        raise ValueError("template_structure 在 compose 后被修改")
    if report.get("decisionsDigest") != _payload_digest(decisions):
        raise ValueError("outline_authoring_decisions 在 compose 后被修改")
    if report.get("outputSha256") != _file_digest(output_file):
        raise ValueError("outputFile 在 compose 后被修改")
    if workflow_proof:
        for field in ("tenderInputsDigest", "headingsStateDigest", "decisionStateDigest"):
            expected = str(workflow_proof.get(field) or "").strip()
            if not expected or report.get(field) != expected:
                raise ValueError(f"outlineComposeReportFile {field} 与当前受控流程不一致")
    expected_outline, _ = build_composition(structure, decisions)
    actual_outline = _load_json_dict(output_file, "outputFile")
    comparable_actual = {
        "schema_version": actual_outline.get("schema_version"),
        "nodes": actual_outline.get("nodes"),
    }
    if _payload_digest(comparable_actual) != _payload_digest(expected_outline):
        raise ValueError("outputFile 与 decisions 合成结果不一致")
    return report


def decisions_digest(decisions: dict[str, Any]) -> str:
    return _payload_digest(decisions)


def _validate_decisions_header(structure: dict[str, Any], decisions: dict[str, Any]) -> None:
    if not isinstance(decisions, dict):
        raise ValueError("outline decisions must be an object")
    extra_keys = set(decisions) - {
        "schema_version",
        "input_fingerprint",
        "template_decisions",
        "changes",
    }
    if extra_keys:
        raise ValueError("outline decisions has unsupported fields: " + ", ".join(sorted(extra_keys)))
    if decisions.get("schema_version") != DECISIONS_SCHEMA:
        raise ValueError(f"outline decisions schema_version must be {DECISIONS_SCHEMA}")
    changes = decisions.get("changes")
    if not isinstance(changes, list):
        raise ValueError("outline decisions changes must be a list")
    expected = str(structure.get("input_fingerprint") or template_fingerprint(structure))
    actual = str(decisions.get("input_fingerprint") or "").strip()
    if not actual:
        raise ValueError("outline decisions input_fingerprint is required")
    if actual != expected:
        raise ValueError("outline decisions input_fingerprint does not match template_structure")
    _validate_template_decisions(structure, decisions.get("template_decisions"))


def _validate_template_decisions(structure: dict[str, Any], raw_decisions: Any) -> None:
    if not isinstance(raw_decisions, list):
        raise ValueError("outline decisions template_decisions must be a list")
    expected_ids = {
        str(item.get("template_id") or "")
        for item in structure.get("items") or []
        if isinstance(item, dict) and int(item.get("level") or 1) <= DECISION_MAX_LEVEL
    }
    seen: set[str] = set()
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            raise ValueError(f"template_decisions[{index}] must be an object")
        target_id = _required_text(
            item.get("target_id"),
            f"template_decisions[{index}].target_id",
        )
        if target_id not in expected_ids:
            raise ValueError(f"template_decisions[{index}].target_id is unknown: {target_id}")
        if target_id in seen:
            raise ValueError(f"duplicate template decision target_id: {target_id}")
        seen.add(target_id)
        decision = str(item.get("decision") or "").strip()
        if decision == "retain":
            _assert_template_decision_keys(
                item,
                {"target_id", "decision", "reason", "tender_basis"},
                index,
            )
        elif decision == "suggest_delete":
            _assert_template_decision_keys(
                item,
                {"target_id", "decision", "reason", "tender_basis"},
                index,
            )
            _required_text(item.get("reason"), f"template_decisions[{index}].reason")
        else:
            raise ValueError(
                f"template_decisions[{index}].decision must be retain or suggest_delete"
            )
    missing = sorted(expected_ids - seen)
    if missing:
        raise ValueError("template decisions missing: " + ", ".join(missing[:20]))


def _assert_template_decision_keys(
    decision: dict[str, Any],
    allowed: set[str],
    index: int,
) -> None:
    extra = set(decision) - allowed
    if extra:
        raise ValueError(
            f"template_decisions[{index}] has unsupported fields: {', '.join(sorted(extra))}"
        )


def _build_template_records(
    structure: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    roots: list[dict[str, Any]] = []
    records: dict[str, dict[str, Any]] = {}
    stack: list[dict[str, Any]] = []
    for raw_item in structure.get("items") or []:
        source_level = int(raw_item.get("level") or 1)
        if source_level > 3:
            continue
        template_id = str(raw_item.get("template_id") or "")
        while stack and stack[-1]["source_level"] >= source_level:
            stack.pop()
        parent = stack[-1] if stack else None
        depth = int(parent["depth"] + 1) if parent else 1
        if depth > 3:
            continue
        record = {
            "id": template_id,
            "is_template": True,
            "source_level": source_level,
            "depth": depth,
            "node": {
                "number": str(raw_item.get("number") or ""),
                "title": str(raw_item.get("title") or ""),
                "suggestion_action": "",
                "suggestion_reason": "",
            },
            "parent": parent,
            "parent_id": parent["id"] if parent else None,
            "original_parent_id": parent["id"] if parent else None,
            "children": [],
            "original_children": [],
            "collapsed": False,
            "collapse_reason": "",
        }
        if template_id in records:
            raise ValueError(f"duplicate template_id: {template_id}")
        records[template_id] = record
        siblings = parent["children"] if parent else roots
        siblings.append(record)
        if parent:
            parent["original_children"].append(record)
        stack.append(record)
    if not roots:
        raise ValueError("template_structure has no level 1-3 nodes")
    return roots, records


def _apply_template_decisions(
    records: dict[str, dict[str, Any]],
    decisions: list[Any],
) -> None:
    for item in decisions:
        target = records[str(item["target_id"])]
        if item["decision"] == "retain":
            target["node"]["suggestion_action"] = "必要"
            target["node"]["suggestion_reason"] = str(item.get("reason") or "")
            if "tender_basis" in item:
                target["node"]["tender_basis"] = deepcopy(item["tender_basis"])
            continue
        target["node"]["suggestion_action"] = "建议删除"
        target["node"]["suggestion_reason"] = str(item["reason"])
        if "tender_basis" in item:
            target["node"]["tender_basis"] = deepcopy(item["tender_basis"])


def _inherit_decisions(
    records: list[dict[str, Any]],
    inherited: dict[str, Any] | None = None,
) -> None:
    """二级决策下沉：没有独立决策的三级节点跟随最近的已决策祖先。"""
    for record in records:
        node = record["node"]
        if node.get("suggestion_action"):
            source = node
        else:
            source = inherited
            if source is not None:
                node["suggestion_action"] = str(source.get("suggestion_action") or "")
                node["suggestion_reason"] = str(source.get("suggestion_reason") or "")
                if "tender_basis" in source:
                    node["tender_basis"] = deepcopy(source["tender_basis"])
        _inherit_decisions(record["children"], source)


def _apply_changes(
    roots: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    changes: list[Any],
) -> None:
    used_targets: set[str] = set()
    for index, raw_change in enumerate(changes):
        if not isinstance(raw_change, dict):
            raise ValueError(f"changes[{index}] must be an object")
        operation = str(raw_change.get("operation") or "").strip()
        if operation == "add":
            _apply_add(roots, records, raw_change, index)
            continue
        if operation not in {"collapse", "suggest_delete", "update"}:
            raise ValueError(f"changes[{index}].operation is invalid: {operation}")
        target_id = str(raw_change.get("target_id") or "").strip()
        target = records.get(target_id)
        if target is None or not target["is_template"]:
            raise ValueError(f"changes[{index}].target_id is unknown: {target_id}")
        if target_id in used_targets:
            raise ValueError(f"duplicate decision target_id: {target_id}")
        used_targets.add(target_id)
        if operation == "collapse":
            _apply_collapse(target, raw_change, index)
        elif operation == "suggest_delete":
            _apply_suggest_delete(target, raw_change, index)
        else:
            _apply_update(roots, records, target, raw_change, index)


def _apply_collapse(target: dict[str, Any], change: dict[str, Any], index: int) -> None:
    _assert_keys(change, {"operation", "target_id", "reason"}, index)
    reason = _required_text(change.get("reason"), f"changes[{index}].reason")
    if any(not child["collapsed"] for child in target["children"]):
        raise ValueError(f"changes[{index}] cannot collapse a node with active children")
    target["collapsed"] = True
    target["collapse_reason"] = reason


def _apply_suggest_delete(target: dict[str, Any], change: dict[str, Any], index: int) -> None:
    _assert_keys(change, {"operation", "target_id", "reason", "tender_basis"}, index)
    reason = _required_text(change.get("reason"), f"changes[{index}].reason")
    target["node"]["suggestion_action"] = "建议删除"
    target["node"]["suggestion_reason"] = reason
    if "tender_basis" in change:
        target["node"]["tender_basis"] = deepcopy(change["tender_basis"])


def _apply_update(
    roots: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    target: dict[str, Any],
    change: dict[str, Any],
    index: int,
) -> None:
    allowed = {
        "operation",
        "target_id",
        "reason",
        "parent_id",
        "after_id",
        *OUTPUT_NODE_FIELDS,
    }
    _assert_keys(change, allowed, index)
    _required_text(change.get("reason"), f"changes[{index}].reason")
    for field in OUTPUT_NODE_FIELDS:
        if field not in change:
            continue
        if field == "tender_basis" and change[field] is None:
            target["node"].pop(field, None)
        else:
            target["node"][field] = deepcopy(change[field])
    if "parent_id" in change or "after_id" in change:
        new_parent_id = change.get("parent_id", target["parent_id"])
        new_parent = records.get(str(new_parent_id)) if new_parent_id is not None else None
        if new_parent_id is not None and new_parent is None:
            raise ValueError(f"changes[{index}].parent_id is unknown: {new_parent_id}")
        _move_record(roots, target, new_parent, change.get("after_id"), index)


def _apply_add(
    roots: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    change: dict[str, Any],
    index: int,
) -> None:
    allowed = {
        "operation",
        "node_id",
        "parent_id",
        "after_id",
        *OUTPUT_NODE_FIELDS,
    }
    _assert_keys(change, allowed, index)
    node_id = _required_text(change.get("node_id"), f"changes[{index}].node_id")
    if node_id in records:
        raise ValueError(f"duplicate decision node_id: {node_id}")
    parent_id = change.get("parent_id")
    parent = records.get(str(parent_id)) if parent_id is not None else None
    if parent_id is not None and parent is None:
        raise ValueError(f"changes[{index}].parent_id is unknown: {parent_id}")
    _assert_active_ancestry(parent, index)
    depth = int(parent["depth"] + 1) if parent else 1
    if depth > 3:
        raise ValueError(f"changes[{index}] would create a level {depth} node")
    number = _required_text(change.get("number"), f"changes[{index}].number")
    title = _required_text(change.get("title"), f"changes[{index}].title")
    action = str(change.get("suggestion_action") or "")
    if action != "建议增加":
        raise ValueError(f"changes[{index}].suggestion_action must be 建议增加")
    reason = _required_text(change.get("suggestion_reason"), f"changes[{index}].suggestion_reason")
    node = {
        "number": number,
        "title": title,
        "suggestion_action": action,
        "suggestion_reason": reason,
    }
    if "tender_basis" in change:
        node["tender_basis"] = deepcopy(change["tender_basis"])
    record = {
        "id": node_id,
        "is_template": False,
        "source_level": depth,
        "depth": depth,
        "node": node,
        "parent": parent,
        "parent_id": parent["id"] if parent else None,
        "original_parent_id": None,
        "children": [],
        "original_children": [],
        "collapsed": False,
        "collapse_reason": "",
    }
    records[node_id] = record
    after_id = change.get("after_id")
    if parent is None and after_id is None and title != APPENDIX_ROOT_TITLE:
        # 技术附表必须留在最后一个根节点，新增一级章插到它前面。
        appendix_index = next(
            (
                position
                for position, root in enumerate(roots)
                if str(root["node"].get("title") or "") == APPENDIX_ROOT_TITLE
            ),
            None,
        )
        if appendix_index is not None:
            roots.insert(appendix_index, record)
            return
    _insert_record(roots, record, parent, after_id, index)


def _move_record(
    roots: list[dict[str, Any]],
    target: dict[str, Any],
    new_parent: dict[str, Any] | None,
    after_id: Any,
    index: int,
) -> None:
    _assert_active_ancestry(new_parent, index)
    if new_parent is target or _is_descendant(new_parent, target):
        raise ValueError(f"changes[{index}] would create a parent cycle")
    new_depth = int(new_parent["depth"] + 1) if new_parent else 1
    if new_depth + _subtree_height(target) - 1 > 3:
        raise ValueError(f"changes[{index}] would create a level greater than 3")
    old_siblings = target["parent"]["children"] if target["parent"] else roots
    old_siblings.remove(target)
    target["parent"] = new_parent
    target["parent_id"] = new_parent["id"] if new_parent else None
    _set_depth(target, new_depth)
    _insert_record(roots, target, new_parent, after_id, index)


def _insert_record(
    roots: list[dict[str, Any]],
    record: dict[str, Any],
    parent: dict[str, Any] | None,
    after_id: Any,
    index: int,
) -> None:
    siblings = parent["children"] if parent else roots
    if after_id is None:
        siblings.append(record)
        return
    after_text = str(after_id)
    after_index = next((i for i, sibling in enumerate(siblings) if sibling["id"] == after_text), None)
    if after_index is None:
        raise ValueError(f"changes[{index}].after_id is not a sibling: {after_text}")
    siblings.insert(after_index + 1, record)


def _serialize_record(record: dict[str, Any]) -> dict[str, Any]:
    node = deepcopy(record["node"])
    node["children"] = [
        _serialize_record(child) for child in record["children"] if not child["collapsed"]
    ]
    return node


def _find_actual_node(
    record: dict[str, Any],
    output_roots: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lineage = []
    cursor: dict[str, Any] | None = record
    while cursor is not None:
        lineage.append(cursor)
        cursor = cursor["parent"]
    candidates: list[dict[str, Any]] = output_roots
    actual = None
    for expected in reversed(lineage):
        actual = next(
            (item for item in candidates if _nodes_match(expected["node"], item)),
            None,
        )
        if actual is None:
            return None
        candidates = actual.get("children") or []
    return actual


def _nodes_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    expected_number = _identity(expected.get("number"))
    actual_number = _identity(actual.get("number"))
    if expected_number and actual_number:
        return expected_number == actual_number
    expected_title = _identity(expected.get("title"))
    actual_title = _identity(actual.get("title"))
    return bool(expected_title and actual_title and expected_title == actual_title)


def _nodes_at_depth(
    nodes: list[dict[str, Any]],
    *,
    target_depth: int,
    depth: int = 1,
) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        if depth == target_depth:
            result.append(node)
        elif depth < target_depth:
            result.extend(
                _nodes_at_depth(node.get("children") or [], target_depth=target_depth, depth=depth + 1)
            )
    return result


def _subtree_height(record: dict[str, Any]) -> int:
    active_children = [child for child in record["children"] if not child["collapsed"]]
    return 1 + max((_subtree_height(child) for child in active_children), default=0)


def _set_depth(record: dict[str, Any], depth: int) -> None:
    record["depth"] = depth
    for child in record["children"]:
        _set_depth(child, depth + 1)


def _is_descendant(candidate: dict[str, Any] | None, ancestor: dict[str, Any]) -> bool:
    cursor = candidate
    while cursor is not None:
        if cursor is ancestor:
            return True
        cursor = cursor["parent"]
    return False


def _assert_active_ancestry(record: dict[str, Any] | None, index: int) -> None:
    cursor = record
    while cursor is not None:
        if cursor["collapsed"]:
            raise ValueError(f"changes[{index}] cannot use a collapsed parent or ancestor")
        cursor = cursor["parent"]


def _assert_keys(change: dict[str, Any], allowed: set[str], index: int) -> None:
    extra = set(change) - allowed
    if extra:
        raise ValueError(f"changes[{index}] has unsupported fields: {', '.join(sorted(extra))}")


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _positive_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if result < 1:
        raise ValueError(f"{label} must be positive")
    return result


def _payload_digest(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"outputFile not found: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _load_json_dict(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
