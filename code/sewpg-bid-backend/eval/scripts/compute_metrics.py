from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from diff_engine import diff_field, normalize_text
from gold_schema import DifficultyTier, FieldKey, FieldType, GoldRow, PredictionRow
from load_gold import load_gold_paths
from load_predictions import load_prediction_paths


KEY_FACT_NAMES = {
    "项目名称",
    "招标编号",
    "招标人",
    "招标方",
    "客户名称",
    "投标机型",
    "单机容量",
    "机组台数",
    "总装机容量",
    "轮毂高度",
    "叶轮直径",
}


def compute_metrics(gold_rows: list[GoldRow], prediction_rows: list[PredictionRow]) -> dict[str, object]:
    predictions = {row.key: row for row in prediction_rows}
    fillable_rows = [row for row in gold_rows if _is_fillable(row)]
    t5_rows = [row for row in gold_rows if not _is_fillable(row)]

    attempted = 0
    correct = 0
    weighted_score = 0.0
    yellow_pred_count = 0
    yellow_true_count = 0
    evidence_filled_count = 0
    filled_with_evidence_count = 0

    tier_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"attempted": 0, "correct": 0, "score": 0.0})
    field_type_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"attempted": 0, "correct": 0, "score": 0.0})

    for gold in gold_rows:
        prediction = predictions.get(gold.key)
        if prediction and prediction.mark_yellow:
            yellow_pred_count += 1
            if not _is_fillable(gold):
                yellow_true_count += 1

        if not _is_fillable(gold):
            continue
        if not prediction or prediction.mark_yellow or not prediction.predicted_answer:
            continue

        attempted += 1
        result = diff_field(gold, prediction)
        weighted_score += result.score
        if result.matched:
            correct += 1
        if prediction.evidence_refs:
            filled_with_evidence_count += 1
        evidence_filled_count += 1

        tier = gold.difficulty_tier.value
        tier_stats[tier]["attempted"] += 1
        tier_stats[tier]["correct"] += 1 if result.matched else 0
        tier_stats[tier]["score"] += result.score

        field_type = gold.field_type.value
        field_type_stats[field_type]["attempted"] += 1
        field_type_stats[field_type]["correct"] += 1 if result.matched else 0
        field_type_stats[field_type]["score"] += result.score

    gold_t5_count = len(t5_rows)
    metrics = {
        "schemaVersion": "bid-eval-metrics-v1",
        "goldFieldCount": len(gold_rows),
        "predictionFieldCount": len(prediction_rows),
        "fillableFieldCount": len(fillable_rows),
        "attemptedFieldCount": attempted,
        "fillingRate": _rate(attempted, len(fillable_rows)),
        "accuracy": _rate(correct, attempted),
        "weightedAccuracy": round(weighted_score / attempted, 4) if attempted else 0.0,
        "yellowPrecision": _rate(yellow_true_count, yellow_pred_count),
        "yellowRecall": _rate(yellow_true_count, gold_t5_count),
        "keyFactConsistencyRate": _key_fact_consistency(gold_rows, predictions),
        "evidenceChainRate": _rate(filled_with_evidence_count, evidence_filled_count),
        "tierAccuracy": _summarize_breakdown(tier_stats),
        "fieldTypeAccuracy": _summarize_breakdown(field_type_stats),
        "unalignedPredictionCount": _unaligned_prediction_count(gold_rows, prediction_rows),
    }
    return metrics


def write_metrics(metrics: dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_fillable(row: GoldRow) -> bool:
    tier = str(getattr(row.difficulty_tier, "value", row.difficulty_tier))
    field_type = str(getattr(row.field_type, "value", row.field_type))
    return tier != DifficultyTier.T5.value and field_type != FieldType.NOT_FILLABLE.value


def _rate(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def _summarize_breakdown(stats: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for key in sorted(stats):
        attempted = int(stats[key]["attempted"])
        correct = int(stats[key]["correct"])
        score = float(stats[key]["score"])
        result[key] = {
            "attempted": attempted,
            "correct": correct,
            "accuracy": _rate(correct, attempted),
            "weightedAccuracy": round(score / attempted, 4) if attempted else 0.0,
        }
    return result


def _key_fact_consistency(gold_rows: list[GoldRow], predictions: dict[FieldKey, PredictionRow]) -> float:
    values_by_name: dict[str, set[str]] = defaultdict(set)
    expected_names = {row.field_name for row in gold_rows if row.field_name in KEY_FACT_NAMES}
    for gold in gold_rows:
        if gold.field_name not in KEY_FACT_NAMES:
            continue
        prediction = predictions.get(gold.key)
        if not prediction or prediction.mark_yellow or not prediction.predicted_answer:
            continue
        values_by_name[gold.field_name].add(normalize_text(prediction.predicted_answer))
    if not expected_names:
        return 0.0
    consistent = sum(1 for name in expected_names if len(values_by_name.get(name, set())) == 1)
    return _rate(consistent, len(expected_names))


def _unaligned_prediction_count(gold_rows: list[GoldRow], prediction_rows: list[PredictionRow]) -> int:
    gold_keys = {row.key for row in gold_rows}
    return sum(1 for row in prediction_rows if row.key not in gold_keys)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute field-level evaluation metrics.")
    parser.add_argument("--gold", nargs="+", required=True, type=Path)
    parser.add_argument("--predictions", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    metrics = compute_metrics(load_gold_paths(args.gold), load_prediction_paths(args.predictions))
    write_metrics(metrics, args.output)
    print(f"wrote metrics to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
