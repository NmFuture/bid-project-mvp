from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from gold_schema import FieldType, GoldRow, PredictionRow


@dataclass(frozen=True)
class DiffResult:
    score: float
    matched: bool
    reason: str


def diff_field(gold: GoldRow, prediction: PredictionRow | None) -> DiffResult:
    if prediction is None:
        return DiffResult(score=0.0, matched=False, reason="missing_prediction")

    if _field_type_value(gold) == FieldType.NOT_FILLABLE.value:
        if prediction.mark_yellow:
            return DiffResult(score=1.0, matched=True, reason="marked_yellow")
        return DiffResult(score=0.0, matched=False, reason="not_marked_yellow")

    if prediction.mark_yellow:
        return DiffResult(score=0.0, matched=False, reason="marked_yellow_but_fillable")
    if not prediction.predicted_answer:
        return DiffResult(score=0.0, matched=False, reason="empty_prediction")

    field_type = _field_type_value(gold)
    if field_type == FieldType.NUMERIC.value:
        return _diff_numeric(gold.human_answer, prediction.predicted_answer)
    if field_type == FieldType.ENUM.value:
        return _diff_normalized_exact(gold.human_answer, prediction.predicted_answer, "enum")
    if field_type == FieldType.PHRASE.value:
        return _diff_normalized_exact(gold.human_answer, prediction.predicted_answer, "phrase")
    if field_type == FieldType.LIST.value:
        return _diff_list(gold.human_answer, prediction.predicted_answer)
    if field_type == FieldType.PARAGRAPH.value:
        return _diff_paragraph_placeholder(gold.human_answer, prediction.predicted_answer)

    return DiffResult(score=0.0, matched=False, reason=f"unsupported_type:{gold.field_type.value}")


def normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("—", "-").replace("－", "-")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,。；;：:（）()\[\]【】\"'“”‘’]", "", text)
    return text


def _field_type_value(gold: GoldRow) -> str:
    return str(getattr(gold.field_type, "value", gold.field_type))


def split_list(value: str) -> set[str]:
    parts = re.split(r"[;；,，、\n]+", str(value or ""))
    return {normalize_text(part) for part in parts if normalize_text(part)}


def _diff_numeric(expected: str, actual: str) -> DiffResult:
    expected_number = _first_number(expected)
    actual_number = _first_number(actual)
    if expected_number is None or actual_number is None:
        return _diff_normalized_exact(expected, actual, "numeric_text")
    tolerance = max(0.01, abs(expected_number) * 0.005)
    delta = abs(expected_number - actual_number)
    if delta <= tolerance:
        return DiffResult(score=1.0, matched=True, reason="numeric_within_tolerance")
    return DiffResult(score=0.0, matched=False, reason=f"numeric_delta={delta:g}")


def _first_number(value: str) -> float | None:
    match = re.search(r"[-+]?[0-9]+(?:\.[0-9]+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _diff_normalized_exact(expected: str, actual: str, reason: str) -> DiffResult:
    expected_norm = normalize_text(expected)
    actual_norm = normalize_text(actual)
    if expected_norm and expected_norm == actual_norm:
        return DiffResult(score=1.0, matched=True, reason=f"{reason}_exact")
    return DiffResult(score=0.0, matched=False, reason=f"{reason}_mismatch")


def _diff_list(expected: str, actual: str) -> DiffResult:
    expected_set = split_list(expected)
    actual_set = split_list(actual)
    if not expected_set and not actual_set:
        return DiffResult(score=1.0, matched=True, reason="empty_list")
    if not expected_set or not actual_set:
        return DiffResult(score=0.0, matched=False, reason="list_empty_side")
    intersection = len(expected_set & actual_set)
    union = len(expected_set | actual_set)
    score = intersection / union if union else 0.0
    return DiffResult(score=score, matched=math.isclose(score, 1.0), reason=f"list_iou={score:.4f}")


def _diff_paragraph_placeholder(expected: str, actual: str) -> DiffResult:
    expected_norm = normalize_text(expected)
    actual_norm = normalize_text(actual)
    if expected_norm and expected_norm == actual_norm:
        return DiffResult(score=1.0, matched=True, reason="paragraph_exact")
    if expected_norm and (expected_norm in actual_norm or actual_norm in expected_norm):
        return DiffResult(score=0.5, matched=False, reason="paragraph_containment_needs_judge")
    return DiffResult(score=0.0, matched=False, reason="paragraph_needs_judge")


def diff_to_json(result: DiffResult) -> dict[str, object]:
    return {"score": result.score, "matched": result.matched, "reason": result.reason}


def diff_from_json(data: dict[str, object]) -> DiffResult:
    return DiffResult(
        score=float(data.get("score") or 0),
        matched=bool(data.get("matched")),
        reason=str(data.get("reason") or ""),
    )


def diff_json_line(gold: GoldRow, prediction: PredictionRow | None) -> str:
    return json.dumps(diff_to_json(diff_field(gold, prediction)), ensure_ascii=False)
