from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from load_predictions import load_prediction_paths


AUDIT_COLUMNS = (
    "project_id",
    "doc_type",
    "locator",
    "field_name",
    "skill_name",
    "evidence_refs",
    "audit_status",
    "note",
)


def audit_evidence(
    prediction_paths: list[Path],
    *,
    output_path: Path,
    sample_size: int = 30,
    seed: int = 20260507,
    source_root: Path | None = None,
) -> list[dict[str, str]]:
    rows = [row for row in load_prediction_paths(prediction_paths) if row.predicted_answer and row.evidence_refs]
    rng = random.Random(seed)
    sample = rows if len(rows) <= sample_size else rng.sample(rows, sample_size)
    output: list[dict[str, str]] = []

    for row in sample:
        status = "needs_manual_audit"
        note = "source_root not provided"
        if source_root:
            status, note = _check_evidence_refs(source_root, row.evidence_refs)
        output.append(
            {
                "project_id": row.project_id,
                "doc_type": row.doc_type.value,
                "locator": row.locator,
                "field_name": row.field_name,
                "skill_name": row.skill_name,
                "evidence_refs": row.evidence_refs,
                "audit_status": status,
                "note": note,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(output)
    return output


def _check_evidence_refs(source_root: Path, evidence_refs: str) -> tuple[str, str]:
    text = evidence_refs.strip()
    if not text:
        return "missing_evidence", "empty evidence_refs"
    if not source_root.exists():
        return "needs_manual_audit", f"source_root not found: {source_root}"
    haystack = ""
    for path in source_root.rglob("*.txt"):
        try:
            haystack += "\n" + path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    if not haystack:
        return "needs_manual_audit", "no txt sources under source_root"
    return ("passed", "evidence text found") if text in haystack else ("failed", "evidence text not found")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample and audit prediction evidence references.")
    parser.add_argument("--predictions", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260507)
    parser.add_argument("--source-root", type=Path, default=None)
    args = parser.parse_args()

    rows = audit_evidence(
        args.predictions,
        output_path=args.output,
        sample_size=args.sample_size,
        seed=args.seed,
        source_root=args.source_root,
    )
    print(f"wrote {len(rows)} evidence audit rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
