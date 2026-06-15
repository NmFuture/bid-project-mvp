from __future__ import annotations

import copy
import re
from typing import Any


FRONTEND_PROJECT_BASIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("projectName", "项目名称"),
    ("tenderNo", "招标编号"),
    ("projectUnit", "项目单位"),
    ("tenderer", "招标人"),
    ("tenderAgency", "招标代理机构"),
    ("bidDeadline", "递交截止时间"),
)

PROJECT_BASIC_LABELS = dict(FRONTEND_PROJECT_BASIC_FIELDS)
DISPLAY_REQUIRED_PROJECT_BASIC_KEYS = ("projectName", "tenderer", "bidDeadline")

PROJECT_BASIC_KEY_ALIASES = {
    "projectName": "projectName",
    "name": "projectName",
    "tenderNumber": "tenderNo",
    "bidNumber": "tenderNo",
    "tenderNo": "tenderNo",
    "projectNo": "tenderNo",
    "projectNumber": "tenderNo",
    "procurementNo": "tenderNo",
    "purchaseNo": "tenderNo",
    "projectUnit": "projectUnit",
    "projectOwner": "projectUnit",
    "owner": "projectUnit",
    "tenderer": "tenderer",
    "bidInviter": "tenderer",
    "purchaser": "tenderer",
    "procurer": "tenderer",
    "buyer": "tenderer",
    "tenderAgency": "tenderAgency",
    "agency": "tenderAgency",
    "agent": "tenderAgency",
    "biddingAgency": "tenderAgency",
    "procurementAgency": "tenderAgency",
    "bidDeadline": "bidDeadline",
    "deadline": "bidDeadline",
    "submissionDeadline": "bidDeadline",
    "responseDeadline": "bidDeadline",
    "endDate": "bidDeadline",
}

PROJECT_BASIC_LABEL_ALIASES = {
    "项目名称": "projectName",
    "项目": "projectName",
    "招标编号": "tenderNo",
    "项目编号": "tenderNo",
    "采购编号": "tenderNo",
    "项目采购编号": "tenderNo",
    "谈判编号": "tenderNo",
    "项目单位": "projectUnit",
    "项目业主": "projectUnit",
    "建设单位": "projectUnit",
    "招标人": "tenderer",
    "采购人": "tenderer",
    "发包人": "tenderer",
    "业主单位": "tenderer",
    "招标代理机构": "tenderAgency",
    "采购代理机构": "tenderAgency",
    "代理机构": "tenderAgency",
    "招标代理": "tenderAgency",
    "采购代理": "tenderAgency",
    "递交截止时间": "bidDeadline",
    "投标截止时间": "bidDeadline",
    "投标文件递交截止时间": "bidDeadline",
    "响应文件递交截止时间": "bidDeadline",
    "响应文件提交截止时间": "bidDeadline",
    "提交截止时间": "bidDeadline",
    "截止时间": "bidDeadline",
}

CLAUSE_NO_PREFIX_RE = re.compile(r"^\s*(?P<no>\d+(?:\.\d+){0,4})\s*[、.．]?\s*(?P<name>.+?)\s*$")
CHINESE_DATETIME_RE = re.compile(
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
    r"(?:\s*(\d{1,2})\s*(?:时|:)\s*(\d{1,2})?\s*分?)?"
)
ISO_DATETIME_RE = re.compile(r"^(20\d{2})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::\d{1,2})?)?$")

DEPOSIT_FORFEIT_TOKENS = ("保证金不予退还", "保证金不退还", "保证金将不予退还", "不退还投标保证金")
REJECTION_SEMANTIC_TOKENS = (
    "否决",
    "废标",
    "无效",
    "不予受理",
    "重大偏差",
    "实质性不响应",
    "响应文件将被视为无效",
    "投标将被否决",
    "作无效标处理",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def compact_label(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"[\s:：；;，,。\.（）()【】\[\]《》<>]", "", text)
    return text


def as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [copy.deepcopy(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [copy.deepcopy(value)]
    return []


def canonical_project_basic_key(row: dict[str, Any], fallback_key: Any = "") -> str:
    raw_key = clean(row.get("key") or row.get("fieldKey") or fallback_key)
    if raw_key:
        alias = PROJECT_BASIC_KEY_ALIASES.get(raw_key)
        if alias:
            return alias
        label_alias = PROJECT_BASIC_LABEL_ALIASES.get(compact_label(raw_key))
        if label_alias:
            return label_alias
        return raw_key
    label = compact_label(row.get("label") or row.get("name") or row.get("field") or row.get("source"))
    return PROJECT_BASIC_LABEL_ALIASES.get(label, "")


def value_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = clean(row.get(key))
        if text:
            return text
    return ""


def normalize_datetime_text(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    iso = ISO_DATETIME_RE.match(text)
    if iso:
        year, month, day, hour, minute = iso.groups()
        date_part = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        if hour:
            return f"{date_part} {hour.zfill(2)}:{(minute or '0').zfill(2)}"
        return date_part
    chinese = CHINESE_DATETIME_RE.search(text)
    if not chinese:
        return text
    year, month, day, hour, minute = chinese.groups()
    date_part = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    if hour:
        return f"{date_part} {hour.zfill(2)}:{(minute or '0').zfill(2)}"
    return date_part


def datetime_candidates(value: Any) -> list[str]:
    text = clean(value)
    candidates: list[str] = []
    iso = ISO_DATETIME_RE.match(text)
    if iso:
        normalized = normalize_datetime_text(text)
        if normalized:
            candidates.append(normalized)
    for match in CHINESE_DATETIME_RE.finditer(text):
        year, month, day, hour, minute = match.groups()
        date_part = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        candidates.append(f"{date_part} {hour.zfill(2)}:{(minute or '0').zfill(2)}" if hour else date_part)
    return list(dict.fromkeys(candidates))


def _evidence_ids_from_value(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, str):
        if value.strip():
            ids.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            ids.extend(_evidence_ids_from_value(item))
    elif isinstance(value, dict):
        for key in ("evidenceId", "id"):
            evidence_id = clean(value.get(key))
            if evidence_id:
                ids.append(evidence_id)
        for key in ("evidenceIds", "ids"):
            ids.extend(_evidence_ids_from_value(value.get(key)))
    return list(dict.fromkeys(ids))


def attach_evidence_ids(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("evidenceIds"):
        row.pop("__evidenceIds", None)
        return row
    ids = _evidence_ids_from_value(
        row.get("evidence")
        or row.get("__evidenceIds")
        or row.get("sourceEvidenceIds")
        or row.get("sourceEvidenceId")
    )
    if ids:
        row["evidenceIds"] = ids
    row.pop("__evidenceIds", None)
    return row


def project_basic_source_evidence(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    raw_items = value.get("sourceEvidence") or value.get("sourceEvidences") or value.get("evidenceRefs") or value.get("evidence")
    if not isinstance(raw_items, list):
        return {}
    by_key: dict[str, list[str]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = canonical_project_basic_key(item, item.get("field") or item.get("fieldKey") or item.get("key") or item.get("name"))
        if not key:
            evidence_text = clean(item.get("text") or item.get("evidence") or item.get("content"))
            evidence_id = clean(item.get("evidenceId") or item.get("id"))
            for raw_key, raw_value in value.items():
                candidate_key = canonical_project_basic_key({}, raw_key)
                candidate_value = clean(raw_value)
                if not candidate_key or not candidate_value or not evidence_id:
                    continue
                if candidate_key == "bidDeadline":
                    matched = normalize_datetime_text(candidate_value) in datetime_candidates(evidence_text)
                else:
                    matched = candidate_value.replace(" ", "") in evidence_text.replace(" ", "")
                if matched:
                    by_key.setdefault(candidate_key, [])
                    if evidence_id not in by_key[candidate_key]:
                        by_key[candidate_key].append(evidence_id)
            continue
        if not key:
            continue
        ids = _evidence_ids_from_value(item)
        if not ids:
            continue
        by_key.setdefault(key, [])
        for evidence_id in ids:
            if evidence_id not in by_key[key]:
                by_key[key].append(evidence_id)
    return by_key


def project_dates(value: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if isinstance(value, dict):
        data = value
    elif isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        data = value[0]
    dates = {
        "startDate": normalize_datetime_text(data.get("startDate")),
        "endDate": normalize_datetime_text(data.get("endDate") or data.get("bidDeadline") or data.get("deadline")),
    }
    evidence_ids = _evidence_ids_from_value(data.get("evidenceIds") or data.get("evidence") or data.get("evidenceId"))
    if evidence_ids:
        dates["evidenceIds"] = evidence_ids
    return dates


def normalize_project_basics(value: Any, dates: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    source_evidence = project_basic_source_evidence(value)
    if isinstance(value, dict) and any(isinstance(item, dict) for item in value.values()):
        for raw_key, raw_row in value.items():
            if raw_key in {"sourceEvidence", "sourceEvidences", "evidenceRefs", "evidence"}:
                continue
            row = copy.deepcopy(raw_row)
            key = canonical_project_basic_key(row, raw_key)
            if key:
                row["key"] = key
            candidates.append(row)
    elif isinstance(value, dict) and not ({"key", "fieldKey", "label", "value", "content"} & set(value)):
        for raw_key, raw_value in value.items():
            if raw_key in {"sourceEvidence", "sourceEvidences", "evidenceRefs", "evidence"}:
                continue
            key = canonical_project_basic_key({}, raw_key)
            if key:
                candidates.append(
                    {
                        "key": key,
                        "label": PROJECT_BASIC_LABELS.get(key, clean(raw_key)),
                        "value": raw_value,
                    }
                )
    else:
        candidates = as_list(value)
        for row in candidates:
            key = canonical_project_basic_key(row)
            if key:
                row["key"] = key

    by_key: dict[str, dict[str, Any]] = {}
    for row in candidates:
        key = canonical_project_basic_key(row)
        if not key:
            continue
        normalized = copy.deepcopy(row)
        normalized["key"] = key
        normalized["fieldKey"] = key
        normalized["label"] = PROJECT_BASIC_LABELS.get(key, clean(normalized.get("label")) or key)
        if "value" not in normalized:
            normalized["value"] = value_text(normalized, "content", "text", "evidence")
        if key == "bidDeadline":
            normalized["value"] = normalize_datetime_text(normalized.get("value"))
        if source_evidence.get(key) and not normalized.get("evidenceIds"):
            normalized["evidenceIds"] = source_evidence[key]
        attach_evidence_ids(normalized)
        if key not in by_key or (not clean(by_key[key].get("value")) and clean(normalized.get("value"))):
            by_key[key] = normalized

    if clean(dates.get("endDate")) and "bidDeadline" not in by_key:
        by_key["bidDeadline"] = {
            "key": "bidDeadline",
            "fieldKey": "bidDeadline",
            "label": PROJECT_BASIC_LABELS["bidDeadline"],
            "value": clean(dates.get("endDate")),
            "source": "projectDates",
        }
        if dates.get("evidenceIds"):
            by_key["bidDeadline"]["evidenceIds"] = list(dates.get("evidenceIds") or [])

    rows: list[dict[str, Any]] = []
    for key, label in FRONTEND_PROJECT_BASIC_FIELDS:
        row = copy.deepcopy(by_key.get(key) or {})
        row["key"] = key
        row["fieldKey"] = key
        row["label"] = label
        row.setdefault("value", "")
        rows.append(row)
    return rows


def normalize_project_fact_fields(value: Any, project_basics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = as_list(value)
    if not rows:
        rows = copy.deepcopy(project_basics)
    for row in rows:
        key = canonical_project_basic_key(row)
        if key:
            row["key"] = key
            row["fieldKey"] = key
            row["label"] = PROJECT_BASIC_LABELS.get(key, clean(row.get("label")) or key)
    return rows


def normalize_qualification_requirements(value: Any) -> list[dict[str, Any]]:
    rows = as_list(value)
    for index, row in enumerate(rows, start=1):
        attach_evidence_ids(row)
        row["order"] = index
        if not clean(row.get("applicableScope")):
            row["applicableScope"] = "全部标段"
        if "content" not in row:
            row["content"] = value_text(row, "value", "text", "evidence")
    return rows


def split_clause_name(clause_no: Any, clause_name: Any) -> tuple[str, str]:
    current_no = clean(clause_no)
    current_name = clean(clause_name)
    if current_no or not current_name:
        return current_no, current_name
    match = CLAUSE_NO_PREFIX_RE.match(current_name)
    if not match:
        return current_no, current_name
    return match.group("no"), clean(match.group("name"))


def normalize_bidder_instructions(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(value):
        key_items = item.get("keyItems")
        source_rows = [copy.deepcopy(key_item) for key_item in key_items if isinstance(key_item, dict)] if isinstance(key_items, list) else [item]
        for source in source_rows:
            row = copy.deepcopy(source)
            cells = row.get("cells")
            if isinstance(cells, list) and len(cells) >= 3:
                row.setdefault("clauseNo", cells[0])
                row.setdefault("clauseName", cells[1])
                row.setdefault("content", cells[2])
            clause_no, clause_name = split_clause_name(row.get("clauseNo") or row.get("clause"), row.get("clauseName") or row.get("name"))
            row["clauseNo"] = clause_no
            row["clauseName"] = clause_name
            row["content"] = value_text(row, "content", "value", "text", "evidence")
            if row.get("rowId") and not row.get("evidenceIds"):
                row["evidenceIds"] = [row["rowId"]]
            attach_evidence_ids(row)
            rows.append(row)
    return rows


def has_rejection_semantics(text: str) -> bool:
    compact = clean(text)
    return any(token in compact for token in REJECTION_SEMANTIC_TOKENS)


def is_non_rejection_deposit_clause(row: dict[str, Any]) -> bool:
    text = " ".join(
        clean(row.get(key))
        for key in ("matchedKeywords", "label", "title", "content", "value", "evidence")
        if clean(row.get(key))
    )
    if not any(token in text for token in DEPOSIT_FORFEIT_TOKENS):
        return False
    return not has_rejection_semantics(text)


def normalize_rejection_clauses(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in as_list(value):
        if is_non_rejection_deposit_clause(source):
            continue
        row = copy.deepcopy(source)
        label = clean(row.get("matchedKeywords") or row.get("label") or row.get("title"))
        content = value_text(row, "content", "value", "evidence")
        if label and not row.get("matchedKeywords"):
            row["matchedKeywords"] = label
        if content:
            row["content"] = content
        attach_evidence_ids(row)
        rows.append(row)
    return rows


def normalize_business_scoring(value: Any) -> list[dict[str, Any]]:
    rows = as_list(value)
    for index, row in enumerate(rows, start=1):
        attach_evidence_ids(row)
        row["order"] = index
        if "scoringItem" not in row:
            row["scoringItem"] = value_text(row, "item", "name", "label", "title")
        if "score" not in row:
            row["score"] = value_text(row, "points", "point", "scoreValue", "分值")
        standard = value_text(row, "scorePoint", "scoringStandard", "content", "requirement", "value", "text")
        if standard:
            row["scorePoint"] = standard
            row["scoringStandard"] = standard
        row.pop("proofRequirement", None)
        row.pop("proofMaterials", None)
    return rows
