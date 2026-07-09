from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import nav_store
from .checklist import clean, load_checklist
from .delivery_contract import (
    ALLOWED_STATUSES,
    DISPLAY_REQUIRED_PROJECT_BASIC_KEYS,
    POSITIVE_STATUSES,
    PROJECT_BASIC_LABELS,
    datetime_candidates,
    evidence_ids_from_value,
    normalize_datetime_text,
    normalize_project_basics,
    valid_row_numbers,
)
from .paths import nav_store_path, submission_path, validation_report_path
from .submission_store import TARGET_KEYS, load as load_submissions


REQUIRED_TARGETS = {"projectBasics", "technicalInterpretation"}
MISSING_PROJECT_BASIC_STATUSES = {"missing", "needs_spec"}
BID_DEADLINE_POSITIVE_TERMS = (
    "递交截止",
    "提交截止",
    "投标截止",
    "响应截止",
    "响应文件递交",
    "投标文件递交",
    "开标时间",
    "截止时间",
)


def _submitted_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _iter_evidence_ids(value: Any):
    yield from evidence_ids_from_value(value)


def _compact_evidence_text(value: Any) -> str:
    return clean(value).replace(" ", "")


def _field_value_is_supported(value: Any, evidence_texts: list[str]) -> bool:
    text = clean(value)
    if not text:
        return True
    compact_value = _compact_evidence_text(text)
    compact_evidence = _compact_evidence_text(" ".join(evidence_texts))
    if compact_value and compact_value in compact_evidence:
        return True
    value_dates = datetime_candidates(text) or [normalize_datetime_text(text)]
    evidence_dates = datetime_candidates(" ".join(evidence_texts))
    return any(value_date and value_date in evidence_dates for value_date in value_dates)


def _project_basic_status(row: dict[str, Any], value: str) -> str:
    status = clean(row.get("status"))
    return status if status in ALLOWED_STATUSES else ("found" if value else "missing")


def _is_missing_project_basic_notice(value: str) -> bool:
    return (
        ("未提及" in value or "未找到" in value or "缺少" in value)
        and "建议补充上传" in value
    )


def _bid_deadline_evidence_has_deadline_context(evidence_texts: list[str]) -> bool:
    compact_text = _compact_evidence_text(" ".join(evidence_texts))
    return any(term in compact_text for term in BID_DEADLINE_POSITIVE_TERMS)


def _evidence_texts(conn, evidence_ids: list[str]) -> list[str]:
    texts: list[str] = []
    for evidence_id in evidence_ids:
        row = conn.execute("SELECT text FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is not None and clean(row["text"]):
            texts.append(clean(row["text"]))
    return texts


def _project_basic_errors(targets: dict[str, Any], conn) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    project_basics = normalize_project_basics(targets.get("projectBasics"))
    if not any(clean(row.get("value")) for row in project_basics):
        errors.append(
            {
                "code": "missing_displayable_project_basic",
                "targetKey": "projectBasics",
                "fieldKey": "projectBasics",
                "message": "项目基础信息没有任何可展示字段，请至少提交当前文件可支撑的项目名称、招标人、招标编号等字段。",
            }
        )
    for row in project_basics:
        key = clean(row.get("key"))
        value = clean(row.get("value"))
        status = _project_basic_status(row, value)
        evidence_ids = [clean(item) for item in row.get("evidenceIds") or [] if clean(item)]
        if not key or not value:
            continue
        if status in MISSING_PROJECT_BASIC_STATUSES:
            if not _is_missing_project_basic_notice(value):
                errors.append(
                    {
                        "code": "invalid_missing_project_basic_notice",
                        "targetKey": "projectBasics",
                        "fieldKey": key,
                        "message": f"项目基础信息字段 {PROJECT_BASIC_LABELS.get(key, key)} 标记为未找到时，展示值应写明当前文件未提及，并建议补充上传具体文件。",
                    }
                )
            continue
        if key in DISPLAY_REQUIRED_PROJECT_BASIC_KEYS and not evidence_ids:
            errors.append(
                {
                    "code": "missing_project_basic_evidence",
                    "targetKey": "projectBasics",
                    "fieldKey": key,
                    "message": f"项目基础信息字段 {PROJECT_BASIC_LABELS.get(key, key)} 缺少可校验的 evidenceId，请回查后带证据重新提交。",
                }
            )
            continue
        if key == "bidDeadline" and not datetime_candidates(value):
            errors.append(
                {
                    "code": "invalid_bid_deadline_datetime",
                    "targetKey": "projectBasics",
                    "fieldKey": key,
                    "message": "递交截止时间必须是投标/响应文件递交或提交截止日期时间；未找到时请标记为 missing 或 needs_spec 并建议补充上传对应文件。",
                }
            )
            continue
        if conn is None or not evidence_ids:
            continue
        evidence_texts = _evidence_texts(conn, evidence_ids)
        if key == "bidDeadline" and evidence_texts and not _bid_deadline_evidence_has_deadline_context(evidence_texts):
            errors.append(
                {
                    "code": "invalid_bid_deadline_evidence_context",
                    "targetKey": "projectBasics",
                    "fieldKey": key,
                    "evidenceIds": evidence_ids,
                    "message": "递交截止时间的证据必须明确指向投标/响应文件递交、提交截止或开标时间，不能使用供货期、交货期、工期或卷册标题作为证据。",
                }
            )
            continue
        if evidence_texts and not _field_value_is_supported(value, evidence_texts):
            errors.append(
                {
                    "code": "project_basic_value_not_supported_by_evidence",
                    "targetKey": "projectBasics",
                    "fieldKey": key,
                    "evidenceIds": evidence_ids,
                    "message": f"项目基础信息字段 {PROJECT_BASIC_LABELS.get(key, key)} 的提交值与引用证据文本不一致，请回查后重新提交。",
                }
            )
    return errors


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

    for target in sorted(set(targets) - TARGET_KEYS):
        errors.append({"code": "unknown_target", "targetKey": target, "message": "提交了未知目标字段。"})
    errors.extend(_project_basic_errors(targets, conn))
    if conn is not None:
        conn.close()

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
