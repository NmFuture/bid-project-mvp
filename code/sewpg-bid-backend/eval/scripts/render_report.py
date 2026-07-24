from __future__ import annotations

import argparse
import json
from pathlib import Path


def render_report(metrics_path: Path, failure_path: Path, evidence_audit_path: Path, output_path: Path) -> str:
    metrics = _load_json(metrics_path)
    failures = _load_json(failure_path)
    lines = [
        "# Field-Level Evaluation Report",
        "",
        "## Summary",
        "",
        f"- Gold fields: {metrics.get('goldFieldCount', 0)}",
        f"- Prediction fields: {metrics.get('predictionFieldCount', 0)}",
        f"- Filling rate: {_pct(metrics.get('fillingRate'))}",
        f"- Accuracy: {_pct(metrics.get('accuracy'))}",
        f"- Weighted accuracy: {_pct(metrics.get('weightedAccuracy'))}",
        f"- Yellow precision: {_pct(metrics.get('yellowPrecision'))}",
        f"- Yellow recall: {_pct(metrics.get('yellowRecall'))}",
        f"- Key fact consistency: {_pct(metrics.get('keyFactConsistencyRate'))}",
        f"- Evidence chain rate: {_pct(metrics.get('evidenceChainRate'))}",
        "",
        "## Tier Accuracy",
        "",
        "| tier | attempted | correct | accuracy | weighted |",
        "|---|---:|---:|---:|---:|",
    ]
    for tier, row in sorted((metrics.get("tierAccuracy") or {}).items()):
        lines.append(
            f"| {tier} | {row.get('attempted', 0)} | {row.get('correct', 0)} | "
            f"{_pct(row.get('accuracy'))} | {_pct(row.get('weightedAccuracy'))} |"
        )

    lines.extend(
        [
            "",
            "## Failure Breakdown",
            "",
            "| failure type | count |",
            "|---|---:|",
        ]
    )
    for key, count in sorted((failures.get("byFailureType") or {}).items()):
        lines.append(f"| {key} | {count} |")

    lines.extend(["", "## Top Failures", ""])
    for item in (failures.get("failures") or [])[:20]:
        lines.append(
            "- "
            f"{item.get('failureType')} | {item.get('projectId')} | "
            f"{item.get('docType')} | {item.get('locator')} | {item.get('fieldName')} | "
            f"{item.get('reason')}"
        )

    lines.extend(
        [
            "",
            "## Evidence Audit",
            "",
            f"- Evidence audit CSV: `{evidence_audit_path}`",
        ]
    )
    text = "\n".join(lines).strip() + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return text


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _pct(value: object) -> str:
    try:
        return f"{float(value or 0) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Markdown evaluation report.")
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--failures", required=True, type=Path)
    parser.add_argument("--evidence-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    render_report(args.metrics, args.failures, args.evidence_audit, args.output)
    print(f"wrote report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
