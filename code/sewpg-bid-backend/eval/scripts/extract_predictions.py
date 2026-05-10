from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from gold_schema import PREDICTION_COLUMNS


def extract_predictions_from_reports(
    report_paths: list[Path],
    *,
    project_id: str,
    doc_type: str,
    skill_name: str = "",
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in report_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(_rows_from_report(data, project_id=project_id, doc_type=doc_type, skill_name=skill_name, source_path=path))
    return rows


def write_prediction_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREDICTION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _rows_from_report(
    data: dict[str, Any],
    *,
    project_id: str,
    doc_type: str,
    skill_name: str,
    source_path: Path,
) -> list[dict[str, str]]:
    if isinstance(data.get("targetResults"), list):
        rows: list[dict[str, str]] = []
        for item in data["targetResults"]:
            if isinstance(item, dict):
                rows.extend(
                    _rows_from_report(
                        item,
                        project_id=project_id,
                        doc_type=doc_type,
                        skill_name=skill_name,
                        source_path=source_path,
                    )
                )
        return rows

    report = data.get("fillReport") if isinstance(data.get("fillReport"), dict) else {}
    title = str(report.get("title") or report.get("appendixId") or source_path.stem)
    details = data.get("filledFieldDetails") if isinstance(data.get("filledFieldDetails"), list) else []
    evidence_refs = data.get("evidenceRefs") if isinstance(data.get("evidenceRefs"), list) else []
    evidence_text = json.dumps(evidence_refs, ensure_ascii=False) if evidence_refs else ""
    resolved_skill = skill_name or _skill_from_schema(str(data.get("schema_version") or data.get("schemaVersion") or ""))
    rows: list[dict[str, str]] = []
    for index, detail in enumerate(details, start=1):
        if not isinstance(detail, dict):
            continue
        field_name = str(detail.get("field") or detail.get("label") or detail.get("field_name") or f"field-{index}").strip()
        if not field_name:
            continue
        action = str(detail.get("action") or "").strip()
        value = str(detail.get("value") or "").strip()
        confidence = str(detail.get("confidence") or "").strip()
        locator = str(detail.get("location") or detail.get("locator") or f"{title}/字段{index}").strip()
        rows.append(
            {
                "project_id": project_id,
                "doc_type": doc_type,
                "locator": locator,
                "field_name": field_name,
                "predicted_answer": "" if action == "manual" else value,
                "mark_yellow": "true" if action == "manual" else "false",
                "evidence_refs": evidence_text,
                "skill_name": resolved_skill,
                "fill_path": "mark_yellow" if action == "manual" else "kb_lookup",
                "confidence": confidence if confidence else "",
            }
        )
    return rows


def _skill_from_schema(schema: str) -> str:
    if "word-placeholder" in schema:
        return "bid-tech-word-placeholder-filler"
    if "table-fill" in schema:
        return "bid-tech-table-filler"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract prediction CSV from S3 fill report JSON files.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--doc-type", choices=["appendix", "body"], required=True)
    parser.add_argument("--reports", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--skill-name", default="")
    args = parser.parse_args()

    rows = extract_predictions_from_reports(
        args.reports,
        project_id=args.project_id,
        doc_type=args.doc_type,
        skill_name=args.skill_name,
    )
    write_prediction_csv(rows, args.output)
    print(f"wrote {len(rows)} prediction rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
