from __future__ import annotations

import re
from typing import Any


STRONG_SCOPES = {"parent_context", "format_area", "high_value_area"}
FALLBACK_SCOPES = {"history_fallback"}

CATEGORY_TERMS = [
    ("bid_bond", ["投标保证金", "保证金"]),
    ("qualification_requirement", ["资格", "资质", "证书", "证明文件", "合格投标人"]),
    ("scoring_response", ["评分", "评审", "业绩", "奖项", "认证"]),
    ("submission_requirement", ["提交", "递交", "投标文件组成", "包括"]),
    ("contract_clause", ["合同", "履约", "商务条款"]),
    ("format_appendix", ["附件", "附表", "格式", "表"]),
    ("material_proof", ["证明", "材料", "承诺", "声明", "报告", "清单"]),
]


def compact(text: Any) -> str:
    value = re.sub(r"\s+", "", str(text or "")).lower()
    return re.sub(r"[，。；：、,.\-—_:;()（）\[\]【】《》\"'“”‘’/\\|]", "", value)


def has_any(text: Any, terms: list[str]) -> bool:
    value = compact(text)
    return any(compact(term) in value for term in terms)


def infer_category(section: dict[str, Any], candidate: dict[str, Any] | None = None) -> str:
    if candidate and candidate.get("evidence_category"):
        return str(candidate.get("evidence_category"))
    text = " ".join([
        str(section.get("title") or ""),
        str(section.get("source_text") or ""),
        str((candidate or {}).get("source_text") or ""),
        " ".join((candidate or {}).get("heading_path", []) or []),
    ])
    for category, terms in CATEGORY_TERMS:
        if has_any(text, terms):
            return category
    return "material_proof"


def infer_strength(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return "fallback"
    explicit = candidate.get("evidence_strength")
    if explicit:
        return str(explicit)
    scope = str(candidate.get("scope") or "")
    score = float(candidate.get("score") or 0)
    confidence = str(candidate.get("confidence") or "")
    if scope in FALLBACK_SCOPES:
        return "fallback"
    if scope in STRONG_SCOPES and (score >= 0.85 or confidence == "high"):
        return "strong"
    if scope in STRONG_SCOPES and (score >= 0.55 or confidence in {"medium", "high"}):
        return "medium"
    if scope == "broad_clause":
        return "weak"
    return "weak"


def choose_candidate(candidates: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for candidate in candidates or []:
        if candidate.get("scope") != "history_fallback":
            return candidate
    return (candidates or [None])[0]


def decide_required_status(
    section: dict[str, Any],
    candidates: list[dict[str, Any]] | None,
    parent_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = choose_candidate(candidates)
    if candidate is None and parent_decision and parent_decision.get("evidence_scope") == "format_area":
        return {
            "required_status": "待确认",
            "evidence_scope": "parent_context",
            "evidence_strength": "medium",
            "evidence_category": str(parent_decision.get("evidence_category") or "format_appendix"),
            "reason": "继承父项 format_area 强证据，但本子项未找到直接当前原文，需人工确认是否单独编排。",
        }

    scope = str((candidate or {}).get("scope") or "history_fallback")
    strength = infer_strength(candidate)
    category = infer_category(section, candidate)
    level = int(section.get("level") or 1)
    if strength == "strong" and scope in STRONG_SCOPES:
        required_status = "必要"
    elif strength == "medium" and scope in {"parent_context", "format_area"} and level <= 2:
        required_status = "必要"
    else:
        required_status = "待确认"

    if scope == "history_fallback" or strength == "fallback":
        reason = f"仅命中历史目录，未在当前招标文件找到强证据，需要人工确认；scope={scope} strength={strength} category={category}。"
        required_status = "待确认"
    elif strength == "weak":
        reason = f"仅找到弱证据，需人工确认是否作为独立目录项；scope={scope} strength={strength} category={category}。"
        required_status = "待确认"
    else:
        reason = f"根据当前招标文件证据判定；scope={scope} strength={strength} category={category}。"

    return {
        "required_status": required_status,
        "evidence_scope": scope,
        "evidence_strength": strength,
        "evidence_category": category,
        "reason": reason,
    }


def decide_tree(sections: list[dict[str, Any]], candidates_by_id: dict[str, list[dict[str, Any]]]) -> None:
    def walk(items: list[dict[str, Any]], parent_decision: dict[str, Any] | None = None) -> None:
        for section in items or []:
            decision = decide_required_status(section, candidates_by_id.get(str(section.get("id"))) or [], parent_decision)
            section.update(decision)
            walk(section.get("children", []) or [], decision)

    walk(sections)
