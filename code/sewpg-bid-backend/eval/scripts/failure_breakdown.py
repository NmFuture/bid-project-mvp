from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from diff_engine import diff_field
from gold_schema import DifficultyTier, FieldType, GoldRow, PredictionRow
from load_gold import load_gold_paths
from load_predictions import load_prediction_paths


def build_failure_breakdown(gold_rows: list[GoldRow], prediction_rows: list[PredictionRow]) -> dict[str, object]:
    predictions = {row.key: row for row in prediction_rows}
    failures: list[dict[str, object]] = []
    counts = Counter()
    by_field_type: dict[str, Counter[str]] = defaultdict(Counter)
    by_tier: dict[str, Counter[str]] = defaultdict(Counter)
    by_skill: dict[str, Counter[str]] = defaultdict(Counter)
    by_project: dict[str, Counter[str]] = defaultdict(Counter)

    for gold in gold_rows:
        prediction = predictions.get(gold.key)
        failure_type = _failure_type(gold, prediction)
        if not failure_type:
            continue
        result = diff_field(gold, prediction)
        skill_name = prediction.skill_name if prediction else "missing_prediction"
        item = {
            "failureType": failure_type,
            "projectId": gold.project_id,
            "docType": gold.doc_type.value,
            "locator": gold.locator,
            "fieldName": gold.field_name,
            "fieldType": gold.field_type.value,
            "difficultyTier": gold.difficulty_tier.value,
            "skillName": skill_name,
            "humanAnswer": gold.human_answer,
            "predictedAnswer": prediction.predicted_answer if prediction else "",
            "markYellow": prediction.mark_yellow if prediction else False,
            "reason": result.reason,
        }
        failures.append(item)
        counts[failure_type] += 1
        by_field_type[gold.field_type.value][failure_type] += 1
        by_tier[gold.difficulty_tier.value][failure_type] += 1
        by_skill[skill_name][failure_type] += 1
        by_project[gold.project_id][failure_type] += 1

    return {
        "schemaVersion": "bid-eval-failure-breakdown-v1",
        "failureCount": len(failures),
        "byFailureType": dict(counts),
        "byFieldType": _counter_map(by_field_type),
        "byDifficultyTier": _counter_map(by_tier),
        "bySkillName": _counter_map(by_skill),
        "byProjectId": _counter_map(by_project),
        "failures": failures,
    }


def write_failure_breakdown(data: dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _failure_type(gold: GoldRow, prediction: PredictionRow | None) -> str:
    tier = str(getattr(gold.difficulty_tier, "value", gold.difficulty_tier))
    field_type = str(getattr(gold.field_type, "value", gold.field_type))
    is_t5 = tier == DifficultyTier.T5.value or field_type == FieldType.NOT_FILLABLE.value
    if is_t5:
        if prediction and prediction.mark_yellow:
            return ""
        return "漏标黄"
    if prediction and prediction.mark_yellow:
        return "错标黄"
    if not prediction or not prediction.predicted_answer:
        return "漏填"
    result = diff_field(gold, prediction)
    if result.matched:
        return ""
    return "误填"


def _counter_map(value: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
    return {key: dict(counter) for key, counter in sorted(value.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build failure breakdown from gold and prediction CSV files.")
    parser.add_argument("--gold", nargs="+", required=True, type=Path)
    parser.add_argument("--predictions", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    data = build_failure_breakdown(load_gold_paths(args.gold), load_prediction_paths(args.predictions))
    write_failure_breakdown(data, args.output)
    print(f"wrote failure breakdown to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
