from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import nav_store
from .delivery_contract import (
    DISPLAY_REQUIRED_PROJECT_BASIC_KEYS,
    PROJECT_BASIC_LABELS,
    clean,
    datetime_candidates,
    is_non_rejection_deposit_clause,
    normalize_datetime_text,
    normalize_bidder_instructions,
    normalize_business_scoring,
    normalize_project_basics,
    project_dates as normalize_project_dates,
)
from .paths import nav_store_path, submission_path, validation_report_path
from .submission_store import TARGET_KEYS, load as load_submissions


REQUIRED_TARGETS = {
    "projectBasics",
    "qualificationRequirements",
    "bidderInstructions",
    "commercialRejectionClauses",
    "businessScoringCriteria",
}
ALLOWED_REJECTION_RISK_LEVELS = {"high", "medium", "low"}


def _iter_evidence_ids(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"evidenceIds", "__evidenceIds"} and isinstance(item, list):
                for evidence_id in item:
                    if str(evidence_id).strip():
                        yield str(evidence_id).strip()
            elif key in {"evidenceId", "sourceEvidenceId"} and str(item).strip():
                yield str(item).strip()
            elif key == "evidence":
                yield from _iter_evidence_object_ids(item)
            else:
                yield from _iter_evidence_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_evidence_ids(item)


def _iter_evidence_object_ids(value: Any):
    if isinstance(value, dict):
        for key in ("id", "evidenceId"):
            if str(value.get(key) or "").strip():
                yield str(value.get(key)).strip()
        for key in ("evidenceIds", "items"):
            yield from _iter_evidence_object_ids(value.get(key))
    elif isinstance(value, list):
        for item in value:
            yield from _iter_evidence_object_ids(item)
    elif isinstance(value, str) and value.strip():
        yield value.strip()


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
    for value_date in value_dates:
        if value_date and value_date in evidence_dates:
            return True
    return False


def _evidence_texts(conn, evidence_ids: list[str]) -> list[str]:
    texts: list[str] = []
    for evidence_id in evidence_ids:
        row = conn.execute("SELECT text FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is not None and clean(row["text"]):
            texts.append(clean(row["text"]))
    return texts


def _project_basic_evidence_errors(project_basics: list[dict[str, Any]], conn) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for row in project_basics:
        key = clean(row.get("key"))
        value = clean(row.get("value"))
        evidence_ids = [clean(item) for item in row.get("evidenceIds") or [] if clean(item)]
        if not key or not value or not evidence_ids:
            if key in DISPLAY_REQUIRED_PROJECT_BASIC_KEYS and value and not evidence_ids:
                errors.append(
                    {
                        "code": "missing_project_basic_evidence",
                        "targetKey": "projectBasics",
                        "fieldKey": key,
                        "message": f"项目基础信息字段 {PROJECT_BASIC_LABELS.get(key, key)} 缺少可校验的 evidenceId，请回查后带证据重新提交。",
                    }
                )
            continue
        evidence_texts = _evidence_texts(conn, evidence_ids)
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


def _display_errors(targets: dict[str, Any], conn=None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    project_dates = normalize_project_dates(targets.get("projectDates"))
    project_basics = normalize_project_basics(targets.get("projectBasics"), project_dates)
    basics_by_key = {str(row.get("key") or ""): row for row in project_basics}
    for key in DISPLAY_REQUIRED_PROJECT_BASIC_KEYS:
        row = basics_by_key.get(key) or {}
        if not clean(row.get("value")):
            errors.append(
                {
                    "code": "missing_displayable_project_basic",
                    "targetKey": "projectBasics",
                    "fieldKey": key,
                    "message": f"项目基础信息缺少可展示的{PROJECT_BASIC_LABELS.get(key, key)}。",
                }
            )
    if conn is not None:
        errors.extend(_project_basic_evidence_errors(project_basics, conn))

    for index, row in enumerate(normalize_bidder_instructions(targets.get("bidderInstructions")), start=1):
        missing = [
            label
            for field, label in (
                ("clauseNo", "条款号"),
                ("clauseName", "条款名称"),
                ("content", "编列内容"),
            )
            if not clean(row.get(field))
        ]
        if missing:
            errors.append(
                {
                    "code": "invalid_bidder_instruction_row",
                    "targetKey": "bidderInstructions",
                    "rowIndex": index,
                    "missingFields": missing,
                    "message": "投标人须知前附表行缺少前端展示必需字段：" + "、".join(missing),
                }
            )

    for index, row in enumerate(normalize_business_scoring(targets.get("businessScoringCriteria")), start=1):
        missing = [
            label
            for field, label in (
                ("scoringItem", "评分项"),
                ("score", "分值"),
                ("scorePoint", "得分点/要求"),
            )
            if not clean(row.get(field))
        ]
        if missing:
            errors.append(
                {
                    "code": "invalid_business_scoring_row",
                    "targetKey": "businessScoringCriteria",
                    "rowIndex": index,
                    "missingFields": missing,
                    "message": "商务评分行缺少前端展示必需字段：" + "、".join(missing),
                }
            )

    for index, row in enumerate(targets.get("commercialRejectionClauses") if isinstance(targets.get("commercialRejectionClauses"), list) else [], start=1):
        if not isinstance(row, dict):
            continue
        risk_level = clean(row.get("riskLevel"))
        rejection_text = " ".join(
            clean(row.get(key))
            for key in ("matchedKeywords", "label", "title", "content", "value", "evidence")
            if clean(row.get(key))
        )
        if risk_level not in ALLOWED_REJECTION_RISK_LEVELS:
            errors.append(
                {
                    "code": "invalid_rejection_clause_risk_level",
                    "targetKey": "commercialRejectionClauses",
                    "rowIndex": index,
                    "fieldKey": "riskLevel",
                    "value": risk_level,
                    "allowedValues": sorted(ALLOWED_REJECTION_RISK_LEVELS),
                    "message": "商务废标项 riskLevel 必须填写为 high、medium 或 low，不要填写“否决投标”“不予受理”等处置结果。",
                }
            )
        if is_non_rejection_deposit_clause(row):
            errors.append(
                {
                    "code": "non_rejection_deposit_clause",
                    "targetKey": "commercialRejectionClauses",
                    "rowIndex": index,
                    "message": "商务废标项混入了普通保证金不予退还条款，缺少无效、否决或实质性不响应语义。",
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
        for evidence_id in sorted(set(_iter_evidence_ids(targets))):
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
    errors.extend(_display_errors(targets, conn))
    for target in missing_targets:
        warnings.append({"code": "missing_target", "targetKey": target, "message": "该目标尚未提交，finalize 会输出空列表或空值。"})
    report = {
        "schemaVersion": "bid-business-agentic-validation-v1",
        "status": "failed" if errors else "passed",
        "submissionPath": str(submission_path(manifest_path, manifest)),
        "navStorePath": str(nav_path),
        "submittedTargetCount": len(targets),
        "missingTargets": missing_targets,
        "evidenceCount": evidence_count,
        "validationErrors": errors,
        "validationWarnings": warnings,
    }
    path = validation_report_path(manifest_path, manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
