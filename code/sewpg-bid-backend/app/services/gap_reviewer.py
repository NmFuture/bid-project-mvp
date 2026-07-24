from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.derive_rules import check_numeric_closure


KEY_FACT_FIELDS = ("项目名称", "招标编号", "招标人", "投标机型", "单机容量", "机组台数", "总装机容量")


def review_fill_instructions(instructions: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    issues.extend(_check_consistency(instructions))
    issues.extend(_check_cross_refs(instructions))
    issues.extend(_check_t5_reasonableness(instructions))
    facts = _facts_from_instructions(instructions)
    issues.extend(check_numeric_closure(facts))
    return {
        "schemaVersion": "bid-tech-gap-review-v1",
        "status": "passed" if not issues else "needs_review",
        "issueCount": len(issues),
        "issues": issues,
    }


def _check_consistency(instructions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values_by_field: dict[str, set[str]] = defaultdict(set)
    locators_by_field: dict[str, list[str]] = defaultdict(list)
    for item in instructions:
        field = str(item.get("field_name") or item.get("field") or "")
        if field not in KEY_FACT_FIELDS:
            continue
        value = _normalize(str(item.get("value") or item.get("predicted_answer") or ""))
        if not value:
            continue
        values_by_field[field].add(value)
        locators_by_field[field].append(str(item.get("locator") or ""))
    issues: list[dict[str, Any]] = []
    for field, values in values_by_field.items():
        if len(values) > 1:
            issues.append(
                {
                    "check": "consistency",
                    "severity": "high",
                    "field": field,
                    "message": f"{field} 出现多个不一致取值",
                    "values": sorted(values),
                    "locators": locators_by_field[field],
                }
            )
    return issues


def _check_cross_refs(instructions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    appendix_models = _values_for_field(instructions, "投标机型", doc_type="appendix")
    body_models = _values_for_field(instructions, "投标机型", doc_type="body")
    if appendix_models and body_models and appendix_models != body_models:
        return [
            {
                "check": "cross_ref",
                "severity": "high",
                "field": "投标机型",
                "message": "附表和正文投标机型不一致",
                "appendixValues": sorted(appendix_models),
                "bodyValues": sorted(body_models),
            }
        ]
    return []


def _check_t5_reasonableness(instructions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in instructions:
        path = str(item.get("path") or item.get("fill_path") or "")
        marked = bool(item.get("mark_yellow")) or path == "mark_yellow"
        searched = bool(item.get("searched")) or bool(item.get("evidence_refs")) or bool(item.get("evidence"))
        if marked and not searched:
            issues.append(
                {
                    "check": "t5_reasonableness",
                    "severity": "medium",
                    "field": str(item.get("field_name") or item.get("field") or ""),
                    "locator": str(item.get("locator") or ""),
                    "message": "字段被标黄，但未记录检索/证据过程",
                }
            )
    return issues


def _facts_from_instructions(instructions: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for item in instructions:
        field = str(item.get("field_name") or item.get("field") or "")
        value = str(item.get("value") or item.get("predicted_answer") or "")
        if field and value and field not in facts:
            facts[field] = value
    return facts


def _values_for_field(instructions: list[dict[str, Any]], field: str, *, doc_type: str) -> set[str]:
    values: set[str] = set()
    for item in instructions:
        if str(item.get("field_name") or item.get("field") or "") != field:
            continue
        if str(item.get("doc_type") or "") != doc_type:
            continue
        value = _normalize(str(item.get("value") or item.get("predicted_answer") or ""))
        if value:
            values.add(value)
    return values


def _normalize(value: str) -> str:
    return "".join(str(value or "").strip().lower().split())
