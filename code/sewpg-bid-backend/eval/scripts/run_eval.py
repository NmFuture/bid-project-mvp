from __future__ import annotations

import argparse
from pathlib import Path

from audit_evidence import audit_evidence
from compute_metrics import compute_metrics, write_metrics
from failure_breakdown import build_failure_breakdown, write_failure_breakdown
from load_gold import load_gold_paths
from load_predictions import load_prediction_paths
from render_report import render_report


def run_eval(
    *,
    gold_paths: list[Path],
    prediction_paths: list[Path],
    run_dir: Path,
    source_root: Path | None = None,
) -> dict[str, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = run_dir / "metrics.json"
    failure_path = run_dir / "failure_breakdown.json"
    evidence_path = run_dir / "evidence_audit.csv"
    report_path = run_dir / "report.md"

    gold_rows = load_gold_paths(gold_paths)
    prediction_rows = load_prediction_paths(prediction_paths)
    write_metrics(compute_metrics(gold_rows, prediction_rows), metrics_path)
    write_failure_breakdown(build_failure_breakdown(gold_rows, prediction_rows), failure_path)
    audit_evidence(prediction_paths, output_path=evidence_path, source_root=source_root)
    render_report(metrics_path, failure_path, evidence_path, report_path)
    return {
        "metrics": metrics_path,
        "failure_breakdown": failure_path,
        "evidence_audit": evidence_path,
        "report": report_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the field-level evaluation pipeline.")
    parser.add_argument("--gold", nargs="+", required=True, type=Path)
    parser.add_argument("--predictions", nargs="+", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=None)
    args = parser.parse_args()

    outputs = run_eval(
        gold_paths=args.gold,
        prediction_paths=args.predictions,
        run_dir=args.run_dir,
        source_root=args.source_root,
    )
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
