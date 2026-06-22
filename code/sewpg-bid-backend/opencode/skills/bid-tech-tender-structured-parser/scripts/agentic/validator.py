from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import nav_store
from .checklist import clean, load_checklist
from .delivery_contract import ALLOWED_STATUSES, POSITIVE_STATUSES, evidence_ids_from_value, valid_row_numbers
from .paths import nav_store_path, submission_path, validation_report_path
from .submission_store import TARGET_KEYS, load as load_submissions


REQUIRED_TARGETS = {"technicalInterpretation"}


def _submitted_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _iter_evidence_ids(value: Any):
    yield from evidence_ids_from_value(value)


def validate(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    submissions = load_submissions(manifest_path, manifest)
    targets = submissions.get("targets") if isinstance(submissions.get("targets"), dict) else {}
    missing_targets = sorted(REQUIRED_TARGETS - set(targets))
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    nav_path = nav_store_path(manifest_path, manifest)
    evidence_count = 0
    conn = None
    if not nav_path.is_file():
        errors.append({"code": "missing_nav_store", "message": "导航索引不存在，请先运行 prepare。"})
    else:
        conn = nav_store.connect(nav_path)
        evidence_values = [targets, targets.get("technicalInterpretation")]
        for evidence_id in sorted({evidence_id for value in evidence_values for evidence_id in _iter_evidence_ids(value)}):
            if not nav_store.evidence_exists(conn, evidence_id):
                errors.append(
                    {
                        "code": "unknown_evidence_id",
                        "evidenceId": evidence_id,
                        "message": "提交结果引用了导航索引中不存在的 evidenceId。",
                    }
                )
            else:
                evidence_count += 1
        conn.close()

    for target in sorted(set(targets) - TARGET_KEYS):
        errors.append({"code": "unknown_target", "targetKey": target, "message": "提交了未知目标字段。"})

    row_numbers = valid_row_numbers()
    submitted_rows = _submitted_rows(targets.get("technicalInterpretation"))
    for index, row in enumerate(submitted_rows, start=1):
        try:
            row_no = int(row.get("rowNo") or 0)
        except (TypeError, ValueError):
            row_no = 0
        if row_no not in row_numbers:
            errors.append(
                {
                    "code": "unknown_checklist_row",
                    "targetKey": "technicalInterpretation",
                    "rowIndex": index,
                    "rowNo": row_no,
                    "message": "technicalInterpretation 提交了不在内置清单中的 rowNo。",
                }
            )
            continue
        status = clean(row.get("status"))
        if status not in ALLOWED_STATUSES:
            errors.append(
                {
                    "code": "invalid_status",
                    "targetKey": "technicalInterpretation",
                    "rowNo": row_no,
                    "value": status,
                    "allowedValues": sorted(ALLOWED_STATUSES),
                    "message": "status 必须是 found、partial、missing 或 needs_spec。",
                }
            )
        ids = evidence_ids_from_value(row.get("evidenceIds") or row.get("evidence") or row.get("evidenceRefs"))
        if status in POSITIVE_STATUSES and not ids:
            errors.append(
                {
                    "code": "missing_evidence_for_positive_status",
                    "targetKey": "technicalInterpretation",
                    "rowNo": row_no,
                    "message": "found/partial 状态必须提供 evidenceIds。",
                }
            )
        if status == "needs_spec" and not clean(row.get("neededSourceName")):
            errors.append(
                {
                    "code": "missing_needed_source_name",
                    "targetKey": "technicalInterpretation",
                    "rowNo": row_no,
                    "message": "needs_spec 状态必须填写 neededSourceName，且使用招标文件原文叫法。",
                }
            )
    submitted_row_numbers = {
        int(row.get("rowNo"))
        for row in submitted_rows
        if isinstance(row.get("rowNo"), int) or str(row.get("rowNo") or "").isdigit()
    }
    missing_row_count = len(row_numbers - submitted_row_numbers)
    if missing_row_count:
        warnings.append(
            {
                "code": "unsubmitted_checklist_rows",
                "missingRowCount": missing_row_count,
                "message": "部分清单行尚未提交，finalize 会按 missing 输出。",
            }
        )
    for target in missing_targets:
        warnings.append({"code": "missing_target", "targetKey": target, "message": "尚未提交 technicalInterpretation。"})

    report = {
        "schemaVersion": "bid-tech-agentic-validation-v1",
        "status": "failed" if errors else "passed",
        "submissionPath": str(submission_path(manifest_path, manifest)),
        "navStorePath": str(nav_path),
        "submittedTargetCount": len(targets),
        "missingTargets": missing_targets,
        "checklistCount": len(load_checklist()),
        "evidenceCount": evidence_count,
        "validationErrors": errors,
        "validationWarnings": warnings,
    }
    path = validation_report_path(manifest_path, manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
