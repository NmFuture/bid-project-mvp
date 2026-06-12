from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from business_base_parser import (
    _iter_docx_blocks,
    extract_docx_text,
    parse_manifest as parse_base_manifest,
)
from qualification_section_selector import select_qualification_section_nodes


SKILL_NAME = "bid-business-tender-structured-parser"
SCHEMA_VERSION = "bid-business-tender-structured-v1"
MARKDOWN_TABLE_LINE_PATTERN = re.compile(r"^\s*\|.*\|\s*$")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[（(]?\d+[）)]?)\s*[、.．\s]+")
LABEL_VALUE_PATTERN = re.compile(r"^\s*(?P<label>[^:：]{2,80})\s*[:：]\s*(?P<value>.+?)\s*$")
BUSINESS_SCORING_EXACT_KEYWORD = "商务评分标准"
SCORING_ITEM_HEADERS = ("评分项", "评审因素", "评审项目", "项目", "因素")
SCORING_SCORE_HEADERS = ("分值", "满分", "权重", "标准分")
SCORING_POINT_VALUE_HEADERS = ("分值", "满分", "标准分")
SCORING_STANDARD_HEADERS = ("得分点", "评分标准", "评分办法", "评审标准", "标准")
BIDDER_INSTRUCTION_TABLE_TITLE = "投标人须知前附表"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    aliases: tuple[str, ...]


PROJECT_BASIC_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("projectName", "项目名称", ("项目名称", "招标项目名称", "采购项目名称")),
    FieldSpec("tenderNo", "招标编号", ("招标编号", "项目编号", "招标文件编号", "采购编号", "采购项目编号")),
    FieldSpec("tenderer", "招标人", ("招标人", "采购人", "采购单位", "业主", "建设单位", "项目单位")),
    FieldSpec("tenderAgency", "招标代理机构", ("招标代理机构", "采购代理机构", "代理机构")),
    FieldSpec("bidDeadline", "递交截止时间", ("递交截止时间", "投标截止时间", "投标文件递交截止时间", "提交截止时间", "响应文件提交截止时间", "响应截止时间", "提交响应文件截止时间")),
)

QUALIFICATION_SECTION_ANCHORS = (
    "投标人资格要求",
    "投标人资格条件",
    "资格能力要求",
    "专用资格条件",
    "通用资格条件",
    "合格投标人资格",
    "供应商资格要求",
    "资质条件、能力和信誉",
)
QUALIFICATION_STOP_ANCHORS = (
    "投标文件的组成",
    "投标报价",
    "投标保证金",
    "投标人须知",
    "资格审查资料",
    "评标办法",
    "商务评分",
    "投标文件格式",
    "合同条款",
)
QUALIFICATION_EXCLUDE_KEYWORDS = (
    "应具备下列条件",
    "具备下列条件",
    "需同时满足",
    "须同时满足",
    "应同时满足",
    "资格审查资料",
    "复印件",
    "扫描件",
    "附件",
    "评分",
    "得分",
    "分值",
    "满分",
    "基础分",
    "加分",
    "否决",
    "废标",
    "不予受理",
    "目录",
    "页码",
    "见投标人须知前附表",
    "见评标办法前附表",
    "同招标公告",
)
BUSINESS_SECTION_TREE_SCHEMA = "bid-business-section-tree-v1"
BIDDER_INSTRUCTION_SECTION_TREE_KEYWORDS = (
    "投标人须知前附表",
    "供应商须知前附表",
    "框架供应商须知前附表",
    "谈判采购供应商须知前附表",
)
QUALIFICATION_REQUIRED_CUES = (
    "投标人",
    "供应商",
    "联合体",
    "须",
    "应",
    "需",
    "具有",
    "具备",
    "不得",
    "不允许",
    "不接受",
    "没有处于",
    "未被",
)
COMMERCIAL_REJECTION_KEYWORDS = (
    "否决",
    "废标",
    "无效投标",
    "不予受理",
    "★",
    "实质性响应",
    "投标人不得存在",
    "不得存在下列情形",
)
HIGH_RISK_REJECTION_KEYWORDS = ("否决", "废标", "无效投标", "不予受理")
NON_BID_REJECTION_CONTEXT = ("异议", "投诉", "质疑", "合同执行", "合同履行", "保证金不退还", "不退还")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def _commercial_rejection_matched_keywords(content: str) -> list[str]:
    text = str(content or "")
    return [keyword for keyword in COMMERCIAL_REJECTION_KEYWORDS if keyword in text]


def _commercial_rejection_risk_level(matched_keywords: list[str]) -> str:
    return "high" if any(keyword in matched_keywords for keyword in HIGH_RISK_REJECTION_KEYWORDS) else "medium"


def _with_commercial_rejection_display_fields(row: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(row)
    content = str(item.get("content") or item.get("evidence") or "")
    matched_keywords = _commercial_rejection_matched_keywords(content)
    item["matchedKeywords"] = matched_keywords
    item["riskLevel"] = _commercial_rejection_risk_level(matched_keywords)
    return item


def _strip_leading_number(text: str) -> str:
    return LEADING_NUMBER_PATTERN.sub("", text).strip()


def _split_label_value(line: str, fallback_label: str) -> tuple[str, str]:
    normalized = _strip_leading_number(line)
    match = LABEL_VALUE_PATTERN.match(normalized)
    if match:
        label = _strip_leading_number(match.group("label")).strip()
        value = match.group("value").strip(" ；;。)）")
        return label or fallback_label, value or normalized
    return fallback_label, normalized


def _load_texts_by_id(documents: list[dict[str, Any]]) -> dict[str, str]:
    texts_by_id: dict[str, str] = {}
    for document in documents:
        document_id = str(document.get("id") or "")
        text = ""
        text_path_value = str(document.get("textPath") or "")
        source_path_value = str(document.get("sourcePath") or "")
        if text_path_value:
            text_path = Path(text_path_value)
            if text_path.exists() and text_path.is_file():
                text = text_path.read_text(encoding="utf-8", errors="replace")
        if not text and source_path_value:
            source_path = Path(source_path_value)
            if source_path.suffix.lower() in {".md", ".txt"} and source_path.exists() and source_path.is_file():
                text = source_path.read_text(encoding="utf-8", errors="replace")
            elif source_path.suffix.lower() == ".docx" and source_path.exists() and source_path.is_file():
                text = extract_docx_text(source_path)
        texts_by_id[document_id] = text
    return texts_by_id


def _is_docx_source(path: Path) -> bool:
    return path.suffix.lower() == ".docx" and path.exists() and path.is_file()


def _copy_meta_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceFile": str(item.get("sourceFile") or ""),
        "sourceDocumentId": str(item.get("sourceDocumentId") or ""),
        "section": str(item.get("section") or ""),
        "evidence": str(item.get("evidence") or ""),
        "evidenceLocation": str(item.get("evidenceLocation") or ""),
    }


def _evidence_id(document_id: str, location: str) -> str:
    doc = str(document_id or "DOC").strip() or "DOC"
    loc = str(location or "").strip()
    return f"{doc}:{loc}" if loc else doc


def _evidence_ids_from_item(item: dict[str, Any]) -> list[str]:
    existing = [str(value) for value in item.get("evidenceIds") or [] if str(value).strip()]
    if existing:
        return existing
    document_id = str(item.get("sourceDocumentId") or "")
    location = str(item.get("evidenceLocation") or "")
    return [_evidence_id(document_id, location)] if document_id and location else []


def _qualification_source_text(*, source_file: str, section: str, clause_no: str = "") -> str:
    parts = [part.strip(" ：") for part in (section, clause_no) if str(part or "").strip()]
    readable = " > ".join(dict.fromkeys(parts))
    return f"{source_file}：{readable}" if readable else source_file


def _business_field_from_item(spec: FieldSpec, item: dict[str, Any], *, value_override: str | None = None) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": (value_override if value_override is not None else str(item.get("value") or item.get("keyValue") or "")).strip(),
        "status": "found",
        **_copy_meta_fields(item),
        "evidenceIds": _evidence_ids_from_item(item),
        "confidence": float(item.get("confidence") or 0.86),
    }


def _empty_business_field(spec: FieldSpec, *, value: str = "") -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": value,
        "status": "missing" if not value else "derived",
        "sourceFile": "",
        "sourceDocumentId": "",
        "section": "",
        "evidence": "",
        "evidenceLocation": "",
        "evidenceIds": [],
        "confidence": 0.0,
    }


PROJECT_REFERENCE_PREFIX_PATTERN = re.compile(r"^(?:详见|见|参见|按|同)")
PROJECT_REFERENCE_TARGET_PATTERN = re.compile(r"^(?:详见|见|参见|按|同)\s*(?P<target>[^。；;，,\s]+)")
PROJECT_COVER_STOP_KEYWORDS = ("目录", "第一章", "第1章", "招标公告", "采购公告", "投标邀请", "投标人须知", "供应商须知")
PROJECT_ANNOUNCEMENT_SECTION_KEYWORDS = ("招标公告", "采购公告", "投标邀请", "采购邀请", "谈判采购公告", "询比采购公告", "竞争性谈判公告")
PROJECT_PARTY_NOISE_KEYWORDS = (
    "招标人代表",
    "采购人代表",
    "联系人",
    "联系方式",
    "联系电话",
    "电话",
    "邮箱",
    "电子邮件",
    "地址",
    "异议",
    "投诉",
    "质疑",
    "服务费",
    "代理服务费",
    "招标人不接受",
    "采购人不接受",
)


def _is_reference_only_value(value: str) -> bool:
    normalized = re.sub(r"\s+", "", str(value or ""))
    normalized = normalized.strip("|:：;；,，。()（）[]【】")
    if normalized in {
        "见招标公告",
        "见采购公告",
        "详见采购公告",
        "见投标人须知前附表",
        "详见招标公告",
        "详见招标文件",
        "按招标文件要求",
    }:
        return True
    return bool(PROJECT_REFERENCE_PREFIX_PATTERN.match(normalized)) and any(
        token in normalized
        for token in (
            "招标公告",
            "采购公告",
            "投标人须知前附表",
            "供应商须知前附表",
            "招标文件",
            "采购文件",
            "本章",
            "上表",
        )
    )


def _normalize_bid_deadline(value: str) -> str:
    match = re.search(
        r"(20\d{2})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*日?"
        r"(?:\s*(\d{1,2})\s*(?:时|:)\s*(\d{1,2})?\s*分?)?",
        str(value or ""),
    )
    if not match:
        return str(value or "").strip()
    try:
        parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return str(value or "").strip()
    if match.group(4) is None:
        return parsed.isoformat()
    minute = match.group(5) or "0"
    try:
        hour_int = int(match.group(4))
        minute_int = int(minute)
    except ValueError:
        return parsed.isoformat()
    if not (0 <= hour_int <= 23 and 0 <= minute_int <= 59):
        return parsed.isoformat()
    return f"{parsed.isoformat()} {hour_int:02d}:{minute_int:02d}"


def _is_normalized_bid_deadline(value: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}(?: \d{2}:\d{2})?", str(value or "").strip()))


def _is_opening_time_context(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not any(token in compact for token in ("开标时间", "开标日期", "开标时间和地点", "开标地点")):
        return False
    return not any(token in compact for token in ("递交截止时间", "投标文件递交截止时间", "提交截止时间"))


def _strip_core_party_contact_tail(value: str) -> str:
    text = _clean(value).strip(" ：")
    text = re.sub(r"^(?:名\s*称|单位名称)\s*[：:]\s*", "", text, count=1)
    tail_match = re.search(r"\s*(?:地\s*址|联\s*系\s*人|电\s*话|电子\s*邮\s*件|邮箱|传真|网址)\s*[：:]", text)
    if tail_match:
        text = text[: tail_match.start()]
    return text.strip(" ：")


def _normalize_core_field_value(spec: FieldSpec, value: str) -> str:
    cleaned = _clean(value)
    if spec.key == "bidDeadline":
        return _normalize_bid_deadline(cleaned)
    stripped = cleaned
    for alias in sorted(spec.aliases, key=len, reverse=True):
        stripped_candidate = re.sub(rf"^\s*{re.escape(alias)}\s*[：:]\s*", "", cleaned, count=1)
        if stripped_candidate != cleaned:
            stripped = stripped_candidate.strip()
            break
    if spec.key in {"tenderer", "tenderAgency"}:
        return _strip_core_party_contact_tail(stripped)
    return stripped


def _field_matches_label(text: str, spec: FieldSpec) -> bool:
    return any(alias in str(text or "") for alias in spec.aliases)


def _business_core_field_score(item: dict[str, Any], spec: FieldSpec) -> int:
    value = str(item.get("value") or item.get("keyValue") or "").strip()
    section = str(item.get("section") or "")
    evidence = str(item.get("evidence") or "")
    location = str(item.get("evidenceLocation") or "")
    score = 0
    if location.startswith("B"):
        score += 40
    if "投标人须知前附表" in section:
        score += 80
    if "招标公告" in section or "联系方式" in section:
        score += 50
    if _is_reference_only_value(value):
        score -= 220
    if spec.key == "bidDeadline" and any(token in evidence for token in ("递交截止时间", "投标文件递交截止时间", "投标截止时间", "提交截止时间")):
        score += 120
        if _is_normalized_bid_deadline(value):
            score += 140
        if _is_opening_time_context(evidence):
            score -= 260
    if spec.key == "projectName" and "项目" in value and len(value) <= 120:
        score += 45
    if spec.key == "tenderNo" and re.search(r"[A-Z]{2,}.*\d", value):
        score += 70
    if spec.key in {"tenderer", "tenderAgency"} and len(value) <= 100:
        score += 35
    if len(value) > 180:
        score -= 50
    if not value:
        score -= 300
    return score


def _normalized_clause_name(row: dict[str, Any]) -> str:
    return re.sub(r"\s+", "", str(row.get("clauseName") or ""))


def _normalized_clause_no(row: dict[str, Any]) -> str:
    return str(row.get("clauseNo") or "").strip().replace("（", "(").replace("）", ")")


def _is_bid_deadline_relative_context(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return bool(
        re.search(r"投标截止时间\d{1,3}(?:日|天)前", compact)
        or re.search(r"收到(?:澄清|修改)后\d{1,3}小时内", compact)
        or re.search(r"开标结束后\d{1,3}分钟内", compact)
    )


def _is_strong_bid_deadline_row(row: dict[str, Any]) -> bool:
    clause_name = _normalized_clause_name(row)
    content = str(row.get("content") or "")
    if _is_bid_deadline_relative_context(f"{clause_name} {content}"):
        return False
    if clause_name in {"投标截止时间", "投标文件递交截止时间", "递交截止时间"}:
        return True
    return bool(
        re.search(r"递交截止时间\s*[：:]\s*20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{1,2}\s*时", content)
    )


def _bidder_instruction_for_project_field(rows: list[dict[str, Any]], spec: FieldSpec) -> dict[str, Any] | None:
    if spec.key == "tenderer":
        for row in rows:
            if _normalized_clause_no(row) == "1.1.2" and _normalized_clause_name(row) == "招标人":
                return row
        for row in rows:
            if _normalized_clause_name(row) == "招标人":
                return row
        return None
    if spec.key == "bidDeadline":
        for row in rows:
            clause_name = _normalized_clause_name(row)
            content = str(row.get("content") or "")
            if _normalized_clause_no(row) == "4.2.1" and (
                any(alias in clause_name for alias in spec.aliases)
                or _project_reference_target(content)
            ):
                return row
        for row in rows:
            clause_name = _normalized_clause_name(row)
            content = str(row.get("content") or "")
            if any(alias in clause_name for alias in spec.aliases) and not _is_opening_time_context(f"{clause_name} {content}"):
                return row
        for row in rows:
            if _is_strong_bid_deadline_row(row):
                return row
        return None
    for row in rows:
        clause_name = str(row.get("clauseName") or "")
        content = str(row.get("content") or "")
        if any(alias in clause_name or alias in content for alias in spec.aliases):
            return row
    return None


def _business_field_from_bidder_instruction(row: dict[str, Any], spec: FieldSpec) -> dict[str, Any]:
    content = str(row.get("content") or "")
    label, value = _split_label_value(content, spec.label)
    _ = label
    if value == content:
        for alias in sorted(spec.aliases, key=len, reverse=True):
            if alias in content:
                value = content.split(alias, 1)[1].strip(" ：:；;，,。") or content
                break
    normalized_value = _normalize_core_field_value(spec, value)
    item = {
        "value": normalized_value,
        "confidence": 0.92,
        **_copy_meta_fields(row),
        "evidenceIds": _evidence_ids_from_item(row),
    }
    return _business_field_from_item(spec, item)


def _spec_by_key() -> dict[str, FieldSpec]:
    return {spec.key: spec for spec in PROJECT_BASIC_FIELDS}


def _project_candidate_item(
    *,
    spec: FieldSpec,
    value: str,
    document: dict[str, Any],
    section: str,
    evidence: str,
    location: str,
    confidence: float,
    source_priority: str,
) -> dict[str, Any]:
    document_id = str(document.get("id") or "")
    normalized = _normalize_core_field_value(spec, value)
    return {
        "id": f"PROJECT-{document_id or 'DOC'}-{location}-{spec.key}",
        "type": "商务项目基础信息候选",
        "category": "project_basics",
        "title": spec.label,
        "keyEntity": spec.label,
        "keyValue": normalized,
        "value": normalized,
        "sourceFile": str(document.get("name") or document_id or "招标文件"),
        "sourceDocumentId": document_id,
        "section": section,
        "evidence": evidence,
        "evidenceLocation": location,
        "evidenceIds": [_evidence_id(document_id, location)] if document_id and location else [],
        "confidence": confidence,
        "fieldKey": spec.key,
        "fieldGroup": "projectBasics",
        "sourcePriority": source_priority,
    }


def _project_field_from_candidate(spec: FieldSpec, candidate: dict[str, Any]) -> dict[str, Any]:
    field = _business_field_from_item(spec, candidate, value_override=str(candidate.get("value") or ""))
    if candidate.get("sourcePriority"):
        field["sourcePriority"] = str(candidate.get("sourcePriority") or "")
    if candidate.get("referenceTarget"):
        field["referenceTarget"] = str(candidate.get("referenceTarget") or "")
    return field


def _project_reference_target(value: str) -> str:
    normalized = _clean(value).strip("。；;，,")
    compact = re.sub(r"\s+", "", normalized)
    if not _is_reference_only_value(compact):
        return ""
    match = PROJECT_REFERENCE_TARGET_PATTERN.match(compact)
    target = match.group("target") if match else compact
    target = target.strip("。；;，,")
    if "招标公告" in target:
        return "招标公告"
    if "采购公告" in target:
        return "采购公告"
    if "投标人须知前附表" in target:
        return "投标人须知前附表"
    if "供应商须知前附表" in target:
        return "供应商须知前附表"
    return target


def _project_value_is_usable(spec: FieldSpec, value: str, evidence: str = "") -> bool:
    cleaned = _clean(value).strip(" ：:；;，,。")
    if not cleaned or _is_reference_only_value(cleaned):
        return False
    if spec.key == "bidDeadline":
        normalized = _normalize_bid_deadline(cleaned)
        if not _is_normalized_bid_deadline(normalized):
            return False
        combined = f"{evidence} {cleaned}"
        return not _is_opening_time_context(combined) and not _is_bid_deadline_relative_context(combined)
    if spec.key in {"tenderer", "tenderAgency"}:
        if len(cleaned) > 100:
            return False
        combined = f"{evidence} {cleaned}"
        contact_noise = ("联系人", "联系方式", "联系电话", "电话", "邮箱", "电子邮件", "地址")
        if any(keyword in cleaned for keyword in contact_noise):
            return False
        hard_noise = ("招标人代表", "采购人代表", "异议", "投诉", "质疑", "服务费", "代理服务费", "招标人不接受", "采购人不接受")
        if any(keyword in combined for keyword in hard_noise):
            return False
        if re.search(r"(?:现)?委托.+(?:招标|采购|代理)", cleaned):
            return False
        if "，" in cleaned and any(token in cleaned for token in ("进行公开招标", "进行采购", "项目业主为")):
            return False
    if spec.key == "projectName" and len(cleaned) > 160:
        return False
    return True


def _label_value_candidates_from_text(
    *,
    document: dict[str, Any],
    line: str,
    line_number: int,
    section: str,
    source_priority: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    compact_line = _clean(line)
    specs = list(PROJECT_BASIC_FIELDS)
    matches: list[tuple[int, FieldSpec, str]] = []
    for spec in specs:
        for alias in sorted(spec.aliases, key=len, reverse=True):
            pattern = r"\s*".join(re.escape(char) for char in alias)
            match = re.search(rf"{pattern}\s*[：:]", compact_line)
            if match:
                matches.append((match.start(), spec, alias))
                break
    matches.sort(key=lambda item: item[0])
    if not matches:
        return []
    for index, (start, spec, alias) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(compact_line)
        segment = compact_line[start:next_start]
        value = re.sub(rf"^\s*{re.escape(alias)}\s*[：:]\s*", "", segment).strip(" ：:；;，,。")
        if not _project_value_is_usable(spec, value, compact_line):
            continue
        candidates.append(
            _project_candidate_item(
                spec=spec,
                value=value,
                document=document,
                section=section,
                evidence=compact_line,
                location=f"L{line_number}",
                confidence=0.9 if source_priority == "cover" else 0.86,
                source_priority=source_priority,
            )
        )
    return candidates


def _project_candidates_from_table_row(
    *,
    document: dict[str, Any],
    row: list[str],
    location: str,
    section: str,
    source_priority: str,
) -> list[dict[str, Any]]:
    cells = [_clean(cell) for cell in row]
    evidence = " | ".join(cell for cell in cells if cell)
    candidates: list[dict[str, Any]] = []
    for cell_index, cell in enumerate(cells):
        if not cell:
            continue
        for spec in PROJECT_BASIC_FIELDS:
            alias = next((item for item in sorted(spec.aliases, key=len, reverse=True) if item in cell), "")
            if not alias:
                continue
            value = ""
            tail = cell.split(alias, 1)[1].strip(" ：:；;，,。")
            if tail and tail != alias:
                value = tail
            if not value:
                for next_cell in cells[cell_index + 1 :]:
                    if next_cell and next_cell not in {"：", ":", "内容", "编列内容"}:
                        value = next_cell
                        break
            if not _project_value_is_usable(spec, value, evidence):
                continue
            candidates.append(
                _project_candidate_item(
                    spec=spec,
                    value=value,
                    document=document,
                    section=section,
                    evidence=evidence,
                    location=location,
                    confidence=0.92 if source_priority == "cover" else 0.86,
                    source_priority=source_priority,
                )
            )
    return candidates


def _first_section_start(document_id: str, section_tree: dict[str, Any] | None) -> tuple[int, int]:
    if not isinstance(section_tree, dict):
        return 0, 0
    starts = [
        (int(node.get("startBlockIndex") or 0), int(node.get("startLine") or 0))
        for node in section_tree.get("nodes") or []
        if isinstance(node, dict) and str(node.get("documentId") or "") == document_id
    ]
    starts = [(block, line) for block, line in starts if block > 0 or line > 0]
    return min(starts, default=(0, 0), key=lambda item: (item[0] or 999999, item[1] or 999999))


def _cover_project_candidates(
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    section_tree: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for document in documents:
        document_id = str(document.get("id") or "")
        source_path = Path(str(document.get("sourcePath") or ""))
        first_block, first_line = _first_section_start(document_id, section_tree)
        if _is_docx_source(source_path):
            blocks = _iter_docx_blocks(source_path)
            stop_block = first_block - 1 if first_block > 1 else min(len(blocks), 12)
            for block_index, block in enumerate(blocks[:stop_block], start=1):
                if block.get("type") == "paragraph":
                    text = _clean(block.get("text"))
                    if any(keyword in text for keyword in PROJECT_COVER_STOP_KEYWORDS):
                        break
                    candidates.extend(
                        _label_value_candidates_from_text(
                            document=document,
                            line=text,
                            line_number=block_index,
                            section="封面",
                            source_priority="cover",
                        )
                    )
                elif block.get("type") == "table":
                    for row_index, row in enumerate(block.get("rows") or [], start=1):
                        candidates.extend(
                            _project_candidates_from_table_row(
                                document=document,
                                row=row,
                                location=f"B{block_index}/R{row_index}",
                                section="封面",
                                source_priority="cover",
                            )
                        )
            continue

        lines = str(texts_by_id.get(document_id) or "").splitlines()
        stop_line = first_line - 1 if first_line > 1 else min(len(lines), 20)
        for line_number, raw_line in enumerate(lines[:stop_line], start=1):
            text = _clean(raw_line).strip("# ").strip()
            if any(keyword in text for keyword in PROJECT_COVER_STOP_KEYWORDS):
                break
            candidates.extend(
                _label_value_candidates_from_text(
                    document=document,
                    line=text,
                    line_number=line_number,
                    section="封面",
                    source_priority="cover",
                )
            )
    return candidates


def _target_section_keywords(reference_target: str) -> tuple[str, ...]:
    target = _clean(reference_target)
    if "采购公告" in target:
        return ("采购公告", "谈判采购公告", "询比采购公告", "竞争性谈判公告")
    if "招标公告" in target:
        return PROJECT_ANNOUNCEMENT_SECTION_KEYWORDS
    if "投标人须知前附表" in target:
        return BIDDER_INSTRUCTION_SECTION_TREE_KEYWORDS
    if "供应商须知前附表" in target:
        return BIDDER_INSTRUCTION_SECTION_TREE_KEYWORDS
    return (target,) if target else PROJECT_ANNOUNCEMENT_SECTION_KEYWORDS


def _reference_section_nodes(
    section_tree: dict[str, Any] | None,
    document_id: str,
    reference_target: str,
) -> list[dict[str, Any]]:
    return _section_tree_scope_nodes(section_tree, document_id, _target_section_keywords(reference_target))


def _reference_section_project_candidates(
    *,
    spec: FieldSpec,
    reference_target: str,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    section_tree: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for document in documents:
        document_id = str(document.get("id") or "")
        lines = str(texts_by_id.get(document_id) or "").splitlines()
        for node in _reference_section_nodes(section_tree, document_id, reference_target):
            section_title = _section_tree_node_title(node)
            start_line = max(1, int(node.get("contentStartLine") or node.get("startLine") or 1))
            end_line = min(len(lines), int(node.get("endLine") or len(lines)))
            for line_number in range(start_line, end_line + 1):
                if line_number < 1 or line_number > len(lines):
                    continue
                line_candidates = _label_value_candidates_from_text(
                    document=document,
                    line=lines[line_number - 1],
                    line_number=line_number,
                    section=section_title,
                    source_priority="reference_section",
                )
                candidates.extend([candidate for candidate in line_candidates if str(candidate.get("fieldKey") or "") == spec.key])
    return candidates


def _best_project_candidate(candidates: list[dict[str, Any]], spec: FieldSpec) -> dict[str, Any] | None:
    filtered = [
        candidate
        for candidate in candidates
        if str(candidate.get("fieldKey") or "") == spec.key
        and _project_value_is_usable(spec, str(candidate.get("value") or ""), str(candidate.get("evidence") or ""))
    ]
    if not filtered:
        return None
    priority = {"cover": 400, "reference_section": 320, "bidder_instruction": 260, "base_item": 100}
    return max(
        filtered,
        key=lambda item: (
            priority.get(str(item.get("sourcePriority") or ""), 0),
            float(item.get("confidence") or 0),
            _business_core_field_score(item, spec),
        ),
    )


def _candidate_from_bidder_instruction(row: dict[str, Any], spec: FieldSpec) -> dict[str, Any]:
    field = _business_field_from_bidder_instruction(row, spec)
    candidate = {
        "value": str(field.get("value") or ""),
        "confidence": 0.92,
        **_copy_meta_fields(row),
        "evidenceIds": _evidence_ids_from_item(row),
        "fieldKey": spec.key,
        "sourcePriority": "bidder_instruction",
    }
    reference_target = _project_reference_target(candidate["value"])
    if reference_target:
        candidate["referenceTarget"] = reference_target
    return candidate


def _build_business_project_basics(
    items: list[dict[str, Any]],
    project_dates: dict[str, Any],
    *,
    bidder_instruction_rows: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    section_tree: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cover_candidates = _cover_project_candidates(documents, texts_by_id, section_tree)
    fields: list[dict[str, Any]] = []
    for spec in PROJECT_BASIC_FIELDS:
        matched = _best_project_candidate(cover_candidates, spec)
        if matched is not None:
            fields.append(_project_field_from_candidate(spec, matched))
            if spec.key == "bidDeadline":
                project_dates["endDate"] = str(matched.get("value") or "")
            continue

        instruction = _bidder_instruction_for_project_field(bidder_instruction_rows, spec)
        reference_target = ""
        if instruction is not None:
            instruction_candidate = _candidate_from_bidder_instruction(instruction, spec)
            reference_target = str(instruction_candidate.get("referenceTarget") or "")
            if not reference_target and _project_value_is_usable(spec, str(instruction_candidate.get("value") or ""), str(instruction_candidate.get("evidence") or "")):
                fields.append(_project_field_from_candidate(spec, instruction_candidate))
                if spec.key == "bidDeadline":
                    project_dates["endDate"] = str(instruction_candidate.get("value") or "")
                continue

        if reference_target:
            if spec.key != "bidDeadline":
                reference_candidates = _reference_section_project_candidates(
                    spec=spec,
                    reference_target=reference_target,
                    documents=documents,
                    texts_by_id=texts_by_id,
                    section_tree=section_tree,
                )
                referenced = _best_project_candidate(reference_candidates, spec)
                if referenced is not None:
                    referenced["referenceTarget"] = reference_target
                    fields.append(_project_field_from_candidate(spec, referenced))
                    continue
            else:
                fields.append(_empty_business_field(spec))
                continue

        candidates = [
            {**item, "sourcePriority": "base_item"}
            for item in items
            if str(item.get("fieldKey") or "") == spec.key
            or _field_matches_label(" ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "evidence")), spec)
        ]
        matched = _best_project_candidate(candidates, spec)
        if matched:
            normalized = _normalize_core_field_value(spec, str(matched.get("value") or matched.get("keyValue") or ""))
            fields.append(_business_field_from_item(spec, matched, value_override=normalized))
            if spec.key == "bidDeadline":
                project_dates["endDate"] = normalized
            continue
        if spec.key == "bidDeadline" and project_dates.get("endDate"):
            fields.append(_empty_business_field(spec, value=str(project_dates.get("endDate") or "")))
            continue
        fields.append(_empty_business_field(spec))
    return fields


def _looks_like_section_heading(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned or len(cleaned) > 90:
        return False
    return bool(re.match(r"^(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[0-9]+(?:\.[0-9]+)*)[、.．\s]", cleaned))


def _normalize_qualification_content(text: str) -> str:
    return _clean(_strip_leading_number(text))


def _normalize_applicable_scope(text: str) -> str:
    cleaned = _clean(text).strip(" ：:")
    cleaned = re.sub(r"[（(]\s*(?:需|须|应)?同时满足\s*[）)]", "", cleaned)
    return cleaned.strip(" ：:")


def _looks_like_qualification_requirement(text: str) -> bool:
    cleaned = _normalize_qualification_content(text)
    if len(cleaned) < 8:
        return False
    if any(keyword in cleaned for keyword in QUALIFICATION_EXCLUDE_KEYWORDS):
        return False
    return any(keyword in cleaned for keyword in QUALIFICATION_REQUIRED_CUES)


def _document_text_lines(document: dict[str, Any], texts_by_id: dict[str, str]) -> list[dict[str, Any]]:
    document_id = str(document.get("id") or "")
    text = str(texts_by_id.get(document_id) or "")
    return [
        {"lineNumber": line_number, "text": _clean(line), "evidenceLocation": f"L{line_number}"}
        for line_number, line in enumerate(text.splitlines(), start=1)
        if _clean(line)
    ]


def _instruction_row_from_cells(
    *,
    cells: list[str],
    headers: list[str],
    document_id: str,
    source_file: str,
    section: str,
    evidence_location: str,
    row_id: int,
    table_title: str = BIDDER_INSTRUCTION_TABLE_TITLE,
    table_location: str = "",
) -> dict[str, Any] | None:
    if len(cells) < 2:
        return None
    cleaned_cells = [_clean(cell) for cell in cells]
    cleaned_headers = [_clean(header) for header in headers]
    clause_no = cleaned_cells[0]
    clause_name = cleaned_cells[1] if len(cleaned_cells) > 1 else ""
    content = "；".join(cell for cell in cleaned_cells[2:] if cell) if len(cleaned_cells) > 2 else ""
    if not clause_no and not clause_name and not content:
        return None
    return {
        "id": f"BIDDER-INST-{row_id:04d}",
        "clauseNo": clause_no,
        "clauseName": clause_name,
        "content": content or clause_name,
        "headers": cleaned_headers,
        "cells": cleaned_cells,
        "tableTitle": table_title or BIDDER_INSTRUCTION_TABLE_TITLE,
        "tableLocation": table_location,
        "status": "found",
        "sourceFile": source_file,
        "sourceDocumentId": document_id,
        "section": section or BIDDER_INSTRUCTION_TABLE_TITLE,
        "evidence": " | ".join(cell for cell in cleaned_cells if cell),
        "evidenceLocation": evidence_location,
        "evidenceIds": [_evidence_id(document_id, evidence_location)],
    }


def _strip_bidder_instruction_title_prefix(text: str) -> str:
    cleaned = _clean(text).strip("# ").strip(" ：:。；;")
    cleaned = re.sub(r"^\s*第?[一二三四五六七八九十百千0-9]+[章节条]?\s*[、.．\s]+", "", cleaned)
    return re.sub(r"\s+", "", cleaned)


def _is_bidder_instruction_title_anchor(text: str) -> bool:
    compact = _strip_bidder_instruction_title_prefix(text)
    if not compact.startswith(BIDDER_INSTRUCTION_TABLE_TITLE):
        return False
    suffix = compact.removeprefix(BIDDER_INSTRUCTION_TABLE_TITLE)
    return bool(re.fullmatch(r"(?:[0-9一二三四五六七八九十百千页（）()、.．:-]*)", suffix))


def _markdown_table_after_anchor(
    lines: list[str],
    anchor_index: int,
    *,
    max_text_gap: int,
) -> tuple[int, list[tuple[int, list[str]]]] | None:
    gap = 0
    index = anchor_index + 1
    while index < len(lines):
        line = _clean(lines[index])
        if not line:
            index += 1
            continue
        if MARKDOWN_TABLE_LINE_PATTERN.match(line):
            if gap > max_text_gap:
                return None
            table_rows, _ = _collect_markdown_table(lines, index)
            parsed_rows = [(line_no, _parse_markdown_table_row(row)) for line_no, row in table_rows]
            filtered_rows = [(line_no, cells) for line_no, cells in parsed_rows if cells and not _is_markdown_separator_row(cells)]
            return (index, filtered_rows) if len(filtered_rows) > 1 else None
        gap += 1
        if gap > max_text_gap:
            return None
        index += 1
    return None


def _parse_bidder_instruction_table_rows(
    *,
    table_rows: list[tuple[int | str, list[str]]],
    document_id: str,
    source_file: str,
    section: str,
    row_id_start: int = 1,
    table_title: str = BIDDER_INSTRUCTION_TABLE_TITLE,
    table_location: str = "",
    location_prefix: str = "L",
) -> list[dict[str, Any]]:
    if len(table_rows) <= 1:
        return []
    headers = [_clean(cell) for cell in table_rows[0][1]]
    rows_out: list[dict[str, Any]] = []
    for row_number, cells in table_rows[1:]:
        evidence_location = f"{location_prefix}{row_number}" if location_prefix else str(row_number)
        row = _instruction_row_from_cells(
            cells=cells,
            headers=headers,
            document_id=document_id,
            source_file=source_file,
            section=section or BIDDER_INSTRUCTION_TABLE_TITLE,
            evidence_location=evidence_location,
            row_id=row_id_start + len(rows_out),
            table_title=table_title,
            table_location=table_location,
        )
        if row:
            rows_out.append(row)
    return rows_out


def _extract_markdown_bidder_instruction_rows_for_document(document: dict[str, Any], text: str) -> list[dict[str, Any]]:
    if "|" not in text or BIDDER_INSTRUCTION_TABLE_TITLE not in text:
        return []
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    lines = text.splitlines()
    anchors = [(index, _clean(line).strip("# ").strip()) for index, line in enumerate(lines) if _is_bidder_instruction_title_anchor(line)]
    for max_text_gap in (0, 3):
        for anchor_index, anchor_title in anchors:
            match = _markdown_table_after_anchor(lines, anchor_index, max_text_gap=max_text_gap)
            if not match:
                continue
            table_start, table_rows = match
            return _parse_bidder_instruction_table_rows(
                table_rows=table_rows,
                document_id=document_id,
                source_file=source_file,
                section=anchor_title or BIDDER_INSTRUCTION_TABLE_TITLE,
                table_title=anchor_title or BIDDER_INSTRUCTION_TABLE_TITLE,
                table_location=f"L{table_start + 1}",
                location_prefix="L",
            )
    return []


def _docx_table_after_anchor(
    blocks: list[dict[str, Any]],
    anchor_index: int,
    *,
    max_text_gap: int,
) -> tuple[int, list[list[str]]] | None:
    gap = 0
    index = anchor_index + 1
    while index < len(blocks):
        block = blocks[index]
        if block.get("type") == "table":
            rows = [[_clean(cell) for cell in row] for row in block.get("rows") or [] if any(_clean(cell) for cell in row)]
            return (index, rows) if gap <= max_text_gap and len(rows) > 1 else None
        text = _clean(block.get("text")) if block.get("type") == "paragraph" else ""
        if text:
            gap += 1
            if gap > max_text_gap:
                return None
        index += 1
    return None


def _load_business_section_tree(manifest: dict[str, Any]) -> dict[str, Any] | None:
    tree_path = Path(str(manifest.get("businessSectionTreePath") or "")).expanduser()
    if not tree_path.is_file():
        return None
    try:
        payload = json.loads(tree_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict) or str(payload.get("schemaVersion") or "") != BUSINESS_SECTION_TREE_SCHEMA:
        return None
    return payload


def _section_node_path_text(node: dict[str, Any]) -> str:
    return " ".join([*(str(item or "") for item in node.get("path") or []), str(node.get("title") or "")]).strip()


def _section_tree_scope_nodes(
    section_tree: dict[str, Any] | None,
    document_id: str,
    keywords: tuple[str, ...],
    *,
    title_only: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(section_tree, dict):
        return []
    matched: list[dict[str, Any]] = []
    for node in section_tree.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("documentId") or "") != document_id:
            continue
        text = str(node.get("title") or "") if title_only else _section_node_path_text(node)
        if not any(keyword in text for keyword in keywords):
            continue
        start_line = int(node.get("startLine") or 0)
        end_line = int(node.get("endLine") or 0)
        if start_line <= 0 or end_line < start_line:
            continue
        matched.append(node)
    return sorted(matched, key=lambda item: (int(item.get("startLine") or 0), int(item.get("level") or 9)))


def _section_tree_node_title(node: dict[str, Any]) -> str:
    return _clean(node.get("title")) or BIDDER_INSTRUCTION_TABLE_TITLE


def _qualification_section_tree_nodes(section_tree: dict[str, Any] | None, document_id: str) -> list[dict[str, Any]]:
    return select_qualification_section_nodes(section_tree, document_id)


def _extract_markdown_bidder_instruction_rows_from_tree(
    document: dict[str, Any],
    text: str,
    section_tree: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if "|" not in text:
        return []
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    lines = text.splitlines()
    for node in _section_tree_scope_nodes(section_tree, document_id, BIDDER_INSTRUCTION_SECTION_TREE_KEYWORDS):
        section_title = _section_tree_node_title(node)
        start_line = max(1, int(node.get("contentStartLine") or node.get("startLine") or 1))
        end_line = min(len(lines), int(node.get("endLine") or len(lines)))
        if end_line < start_line:
            continue
        index = start_line - 1
        while index <= end_line - 1:
            if not MARKDOWN_TABLE_LINE_PATTERN.match(lines[index].strip()):
                index += 1
                continue
            raw_rows: list[tuple[int, list[str]]] = []
            table_start = index
            while index <= end_line - 1 and MARKDOWN_TABLE_LINE_PATTERN.match(lines[index].strip()):
                cells = _parse_markdown_table_row(lines[index])
                if cells and not _is_markdown_separator_row(cells):
                    raw_rows.append((index + 1, cells))
                index += 1
            if len(raw_rows) <= 1:
                continue
            return _parse_bidder_instruction_table_rows(
                table_rows=raw_rows,
                document_id=document_id,
                source_file=source_file,
                section=section_title,
                table_title=section_title,
                table_location=f"L{table_start + 1}",
                location_prefix="L",
            )
            index += 1
    return []


def _extract_docx_bidder_instruction_rows_from_tree(document: dict[str, Any], section_tree: dict[str, Any] | None) -> list[dict[str, Any]]:
    source_path = Path(str(document.get("sourcePath") or ""))
    if not _is_docx_source(source_path):
        return []
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    blocks = _iter_docx_blocks(source_path)
    for node in _section_tree_scope_nodes(section_tree, document_id, BIDDER_INSTRUCTION_SECTION_TREE_KEYWORDS):
        section_title = _section_tree_node_title(node)
        start_index = max(0, int(node.get("contentStartBlockIndex") or node.get("startBlockIndex") or 1) - 1)
        end_index = min(len(blocks) - 1, int(node.get("endBlockIndex") or len(blocks)) - 1)
        if end_index < start_index:
            continue
        for block_index in range(start_index, end_index + 1):
            block = blocks[block_index]
            if block.get("type") != "table":
                continue
            table_rows = [[_clean(cell) for cell in row] for row in block.get("rows") or [] if any(_clean(cell) for cell in row)]
            if len(table_rows) <= 1:
                continue
            numbered_rows = [(f"B{block_index + 1}/R{row_index}", row) for row_index, row in enumerate(table_rows, start=1)]
            return _parse_bidder_instruction_table_rows(
                table_rows=numbered_rows,
                document_id=document_id,
                source_file=source_file,
                section=section_title,
                table_title=section_title,
                table_location=f"B{block_index + 1}",
                location_prefix="",
            )
    return []


def _extract_docx_bidder_instruction_rows_for_document(document: dict[str, Any], section_tree: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = _extract_docx_bidder_instruction_rows_from_tree(document, section_tree)
    if rows:
        return rows
    source_path = Path(str(document.get("sourcePath") or ""))
    if not _is_docx_source(source_path):
        return []
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    blocks = _iter_docx_blocks(source_path)
    anchors = [
        (index, _clean(block.get("text")))
        for index, block in enumerate(blocks)
        if block.get("type") == "paragraph" and _is_bidder_instruction_title_anchor(str(block.get("text") or ""))
    ]
    for max_text_gap in (0, 3):
        for anchor_index, anchor_title in anchors:
            match = _docx_table_after_anchor(blocks, anchor_index, max_text_gap=max_text_gap)
            if not match:
                continue
            table_index, table_rows = match
            numbered_rows = [(f"B{table_index + 1}/R{row_index}", row) for row_index, row in enumerate(table_rows, start=1)]
            return _parse_bidder_instruction_table_rows(
                table_rows=numbered_rows,
                document_id=document_id,
                source_file=source_file,
                section=anchor_title or BIDDER_INSTRUCTION_TABLE_TITLE,
                table_title=anchor_title or BIDDER_INSTRUCTION_TABLE_TITLE,
                table_location=f"B{table_index + 1}",
                location_prefix="",
            )
    return []


def _extract_bidder_instruction_rows(
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    section_tree: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    for document in documents:
        rows = _extract_docx_bidder_instruction_rows_for_document(document, section_tree)
        if rows:
            return rows
    for document in documents:
        document_id = str(document.get("id") or "")
        rows = _extract_markdown_bidder_instruction_rows_from_tree(document, str(texts_by_id.get(document_id) or ""), section_tree)
        if rows:
            return rows
    for document in documents:
        document_id = str(document.get("id") or "")
        rows = _extract_markdown_bidder_instruction_rows_for_document(document, str(texts_by_id.get(document_id) or ""))
        if rows:
            return rows
    return []


def _extract_qualification_requirements(
    items: list[dict[str, Any]],
    *,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    section_tree: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    _ = items
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        lines = _document_text_lines(document, texts_by_id)
        line_by_number = {int(line.get("lineNumber") or 0): line for line in lines}
        for node in _qualification_section_tree_nodes(section_tree, document_id):
            section_title = _section_tree_node_title(node)
            start_line = int(node.get("contentStartLine") or node.get("startLine") or 0)
            end_line = int(node.get("endLine") or 0)
            if start_line <= 0 or end_line < start_line:
                continue
            current_section = section_title
            current_scope = "全部标段"
            for line_number in range(start_line, end_line + 1):
                line = line_by_number.get(line_number)
                if not line:
                    continue
                text = str(line.get("text") or "")
                if _looks_like_section_heading(text) or text.startswith("#"):
                    current_section = text.strip("# ").strip()
                if any(anchor in text for anchor in QUALIFICATION_SECTION_ANCHORS):
                    current_section = text
                    continue
                if current_section and any(stop in text for stop in QUALIFICATION_STOP_ANCHORS):
                    break
                if re.match(r"^(?:标段|第.*标段|全部标段|所有标段|本项目)", text):
                    current_scope = _normalize_applicable_scope(text)
                    continue
                content = _normalize_qualification_content(text)
                if not _looks_like_qualification_requirement(content):
                    continue
                key = (document_id, content)
                if key in seen:
                    continue
                seen.add(key)
                location = str(line.get("evidenceLocation") or "")
                rows.append(
                    {
                        "id": f"QUAL-{len(rows) + 1:04d}",
                        "order": len(rows) + 1,
                        "content": content,
                        "applicableScope": current_scope,
                        "sourceText": _qualification_source_text(source_file=source_file, section=current_section or section_title or "投标人资格要求"),
                        "sourceFile": source_file,
                        "sourceDocumentId": document_id,
                        "section": current_section or section_title or "投标人资格要求",
                        "evidence": text,
                        "evidenceLocation": location,
                        "evidenceIds": [_evidence_id(document_id, location)] if location else [],
                        "status": "found",
                    }
                )
    if rows:
        return rows

    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        current_section = ""
        active = False
        current_scope = "全部标段"
        for line in _document_text_lines(document, texts_by_id):
            text = str(line.get("text") or "")
            if _looks_like_section_heading(text) or text.startswith("#"):
                current_section = text.strip("# ").strip()
            if any(anchor in text for anchor in QUALIFICATION_SECTION_ANCHORS):
                active = True
                current_section = text
                continue
            if active and current_section and any(stop in text for stop in QUALIFICATION_STOP_ANCHORS):
                active = False
            if not active:
                continue
            if re.match(r"^(?:标段|第.*标段|全部标段|所有标段|本项目)", text):
                current_scope = _normalize_applicable_scope(text)
                continue
            content = _normalize_qualification_content(text)
            if not _looks_like_qualification_requirement(content):
                continue
            key = (document_id, content)
            if key in seen:
                continue
            seen.add(key)
            location = str(line.get("evidenceLocation") or "")
            rows.append(
                {
                    "id": f"QUAL-{len(rows) + 1:04d}",
                    "order": len(rows) + 1,
                    "content": content,
                    "applicableScope": current_scope,
                    "sourceText": _qualification_source_text(source_file=source_file, section=current_section or "投标人资格要求"),
                    "sourceFile": source_file,
                    "sourceDocumentId": document_id,
                    "section": current_section or "投标人资格要求",
                    "evidence": text,
                    "evidenceLocation": location,
                    "evidenceIds": [_evidence_id(document_id, location)] if location else [],
                    "status": "found",
                }
            )
    return rows


def _clause_number_tuple(text: str) -> tuple[int, ...]:
    match = re.match(r"^\s*(\d+(?:\.\d+)+)", str(text or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split(".") if part.isdigit())


def _is_same_or_higher_clause(text: str, parent_clause: tuple[int, ...]) -> bool:
    clause = _clause_number_tuple(text)
    if not clause or not parent_clause:
        return False
    return len(clause) <= len(parent_clause) and clause[: max(0, len(clause) - 1)] == parent_clause[: max(0, len(clause) - 1)]


def _is_rejection_child_line(text: str) -> bool:
    cleaned = _clean(text)
    return bool(
        re.match(
            r"^\s*(?:[（(]\s*(?:\d+|[一二三四五六七八九十]+)\s*[）)]|(?:\d+|[一二三四五六七八九十]+)[、．.](?!\d))",
            cleaned,
        )
    )


def _is_rejection_parent_heading(text: str) -> bool:
    cleaned = _clean(text)
    if any(keyword in cleaned for keyword in ("投标人不得存在", "不得存在下列情形", "下列情形之一")):
        return True
    if not _clause_number_tuple(cleaned):
        return False
    if len(cleaned) > 70:
        return False
    return cleaned.rstrip("。；;").endswith(("否决其投标", "不予受理"))


def _rejection_clause_block(lines: list[dict[str, Any]], start_index: int) -> list[dict[str, Any]]:
    start_text = str(lines[start_index].get("text") or "")
    parent_clause = _clause_number_tuple(start_text)
    block = [lines[start_index]]
    index = start_index + 1
    collecting_children = False
    while index < len(lines):
        text = str(lines[index].get("text") or "")
        if parent_clause and _is_same_or_higher_clause(text, parent_clause):
            break
        if _looks_like_section_heading(text) and not re.match(r"^\s*[（(]\d+[）)]", text):
            break
        if _is_rejection_child_line(text):
            collecting_children = True
            block.append(lines[index])
            index += 1
            continue
        if collecting_children:
            block.append(lines[index])
            index += 1
            continue
        break
        index += 1
    return block


def _extract_commercial_rejection_clauses(documents: list[dict[str, Any]], texts_by_id: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        current_section = ""
        lines = _document_text_lines(document, texts_by_id)
        line_sections: dict[int, str] = {}
        for index, line in enumerate(lines):
            text = str(line.get("text") or "")
            if _looks_like_section_heading(text) or text.startswith("#"):
                current_section = text.strip("# ").strip()
            line_sections[index] = current_section
        for index, line in enumerate(lines):
            text = str(line.get("text") or "")
            if not any(keyword in text for keyword in COMMERCIAL_REJECTION_KEYWORDS):
                continue
            if any(keyword in text for keyword in NON_BID_REJECTION_CONTEXT):
                continue
            block = _rejection_clause_block(lines, index) if _is_rejection_parent_heading(text) else [line]
            content = "\n".join(str(item.get("text") or "") for item in block if str(item.get("text") or "").strip())
            key = (document_id, content)
            if key in seen:
                continue
            seen.add(key)
            location = str(line.get("evidenceLocation") or "")
            evidence_ids = [
                _evidence_id(document_id, str(item.get("evidenceLocation") or ""))
                for item in block
                if str(item.get("evidenceLocation") or "")
            ]
            rows.append(
                _with_commercial_rejection_display_fields(
                    {
                    "id": f"REJECT-{len(rows) + 1:04d}",
                    "order": len(rows) + 1,
                    "content": content,
                    "sourceText": _qualification_source_text(source_file=source_file, section=line_sections.get(index) or "商务废标项"),
                    "sourceFile": source_file,
                    "sourceDocumentId": document_id,
                    "section": line_sections.get(index) or "",
                    "evidence": content,
                    "evidenceLocation": location,
                    "evidenceIds": evidence_ids,
                    "status": "found",
                    }
                )
            )
    return rows


def _scoring_bucket_from_title(title: str) -> str:
    text = _clean(title)
    if not text:
        return ""
    if BUSINESS_SCORING_EXACT_KEYWORD in text:
        return "business"
    return ""


def _is_non_target_scoring_title(title: str) -> bool:
    text = _clean(title)
    return "评分" in text and _scoring_bucket_from_title(text) != "business"


def _parse_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _markdown_rows_have_scoring_columns(cells_rows: list[list[str]]) -> bool:
    for row in cells_rows[:5]:
        joined = "".join(_clean(cell) for cell in row)
        if not joined:
            continue
        has_item = any(keyword in joined for keyword in SCORING_ITEM_HEADERS)
        has_score = any(keyword in joined for keyword in SCORING_SCORE_HEADERS)
        has_standard = any(keyword in joined for keyword in SCORING_STANDARD_HEADERS)
        if has_item and has_score and has_standard:
            return True
    return False


def _text_has_concrete_score(text: str) -> bool:
    normalized = _clean(text)
    return bool(
        re.search(r"\d+(?:\.\d+)?\s*(?:[-~－—至]\s*\d+(?:\.\d+)?)?\s*分", normalized)
        or re.search(r"(?:满分|得|加|扣)\s*\d+(?:\.\d+)?", normalized)
    )


def _score_value_cell_has_concrete_score(text: str) -> bool:
    normalized = _clean(text)
    return bool(
        _text_has_concrete_score(normalized)
        or re.fullmatch(r"\d+(?:\.\d+)?", normalized)
        or re.fullmatch(r"\d+(?:\.\d+)?\s*(?:[-~－—至]\s*\d+(?:\.\d+)?)", normalized)
    )


def _collect_markdown_table(lines: list[str], start_index: int) -> tuple[list[tuple[int, str]], int]:
    rows: list[tuple[int, str]] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        if not MARKDOWN_TABLE_LINE_PATTERN.match(line.strip()):
            break
        rows.append((index + 1, line))
        index += 1
    return rows, index


def _parse_markdown_scoring_rows(
    *,
    rows: list[tuple[int, str]],
    document: dict[str, Any],
    section: str,
    start_index: int,
) -> list[dict[str, Any]]:
    parsed_rows: list[dict[str, Any]] = []
    table_rows = [(line_no, _parse_markdown_table_row(line)) for line_no, line in rows]
    filtered_rows = [(line_no, cells) for line_no, cells in table_rows if cells and not _is_markdown_separator_row(cells)]
    if len(filtered_rows) <= 1:
        return parsed_rows
    header = filtered_rows[0][1]
    data_rows = filtered_rows[1:]
    score_col = next((index for index, cell in enumerate(header) if any(keyword in _clean(cell) for keyword in SCORING_POINT_VALUE_HEADERS)), -1)
    standard_col = next((index for index, cell in enumerate(header) if any(keyword in _clean(cell) for keyword in SCORING_STANDARD_HEADERS)), -1)
    order = start_index
    for line_no, cells in data_rows:
        if len(cells) < 4:
            continue
        scoring_item = cells[1].strip() if len(cells) > 1 else ""
        score = cells[2].strip() if len(cells) > 2 else ""
        score_point = cells[3].strip() if len(cells) > 3 else ""
        proof_requirement = cells[4].strip() if len(cells) > 4 else ""
        if not scoring_item and not score_point:
            continue
        score_cell = cells[score_col].strip() if score_col >= 0 and score_col < len(cells) else score
        standard_cell = cells[standard_col].strip() if standard_col >= 0 and standard_col < len(cells) else score_point
        if not (_score_value_cell_has_concrete_score(score_cell) or _text_has_concrete_score(standard_cell)):
            continue
        parsed_rows.append(
            {
                "id": f"BUS-MD-SCORE-{order:04d}",
                "order": order,
                "scoringItem": scoring_item,
                "score": score,
                "scorePoint": score_point,
                "proofRequirement": proof_requirement,
                "sourceFile": str(document.get("name") or ""),
                "sourceDocumentId": str(document.get("id") or ""),
                "section": section,
                "evidence": " | ".join(cell for cell in cells if cell),
                "evidenceLocation": f"L{line_no}",
                "evidenceIds": [_evidence_id(str(document.get("id") or ""), f"L{line_no}")],
            }
        )
        order += 1
    return parsed_rows


def _extract_markdown_scoring(documents: list[dict[str, Any]], texts_by_id: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    scoring = {"business": []}
    for document in documents:
        text = str(texts_by_id.get(str(document.get("id") or "")) or "")
        if "|" not in text:
            continue
        lines = text.splitlines()
        current_section = ""
        pending_scoring_title = ""
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if not line:
                index += 1
                continue
            if line.startswith("#"):
                current_section = line.strip("# ").strip()
                pending_scoring_title = ""
                index += 1
                continue
            if _is_non_target_scoring_title(line):
                pending_scoring_title = "__NON_TARGET__"
                index += 1
                continue
            bucket_from_line = _scoring_bucket_from_title(line)
            if _looks_like_section_heading(line):
                current_section = line
                pending_scoring_title = line if bucket_from_line else ""
                index += 1
                continue
            if bucket_from_line:
                pending_scoring_title = line
            if MARKDOWN_TABLE_LINE_PATTERN.match(line):
                rows, next_index = _collect_markdown_table(lines, index)
                table_cells = [
                    _parse_markdown_table_row(row_line)
                    for _, row_line in rows
                    if not _is_markdown_separator_row(_parse_markdown_table_row(row_line))
                ]
                if pending_scoring_title == "__NON_TARGET__":
                    pending_scoring_title = ""
                    index = next_index
                    continue
                bucket = _scoring_bucket_from_title(pending_scoring_title or current_section)
                has_inline_exact_anchor = any(BUSINESS_SCORING_EXACT_KEYWORD in _clean(" ".join(cells)) for cells in table_cells[1:])
                if bucket == "business" and _markdown_rows_have_scoring_columns(table_cells):
                    scoring["business"].extend(
                        _parse_markdown_scoring_rows(
                            rows=rows,
                            document=document,
                            section=pending_scoring_title or current_section,
                            start_index=len(scoring["business"]) + 1,
                        )
                    )
                    pending_scoring_title = ""
                    index = next_index
                    continue
                if not bucket and has_inline_exact_anchor and _markdown_rows_have_scoring_columns(table_cells):
                    scoring["business"].extend(
                        _parse_markdown_scoring_rows(
                            rows=rows,
                            document=document,
                            section=pending_scoring_title or current_section,
                            start_index=len(scoring["business"]) + 1,
                        )
                    )
                    pending_scoring_title = ""
                    index = next_index
                    continue
            index += 1
    return scoring


def _filter_business_scoring(scoring: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(scoring, dict):
        return {"business": []}
    return {"business": copy.deepcopy(scoring.get("business") or [])}


def _merge_business_scoring(base_scoring: dict[str, Any], markdown_scoring: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    merged = _filter_business_scoring(base_scoring)
    seen = {
        (
            str(row.get("sourceDocumentId") or ""),
            str(row.get("evidenceLocation") or ""),
            str(row.get("scoringItem") or ""),
            str(row.get("score") or ""),
        )
        for row in merged.get("business") or []
        if isinstance(row, dict)
    }
    for row in markdown_scoring.get("business") or []:
        key = (
            str(row.get("sourceDocumentId") or ""),
            str(row.get("evidenceLocation") or ""),
            str(row.get("scoringItem") or ""),
            str(row.get("score") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged["business"].append(row)
    return merged


def _unique_sources(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    sources: list[dict[str, str]] = []
    for record in records:
        source_file = str(record.get("sourceFile") or "")
        source_document_id = str(record.get("sourceDocumentId") or "")
        if not source_file and not source_document_id:
            continue
        key = (source_document_id, source_file)
        if key in seen:
            continue
        seen.add(key)
        sources.append({"sourceDocumentId": source_document_id, "sourceFile": source_file})
    return sources


def _build_business_coverage(field_groups: dict[str, Any], scoring: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    checks = [
        ("项目基础信息", all(field.get("status") == "found" for field in field_groups.get("projectBasics") or [])),
        ("资格要求", len(field_groups.get("qualificationRequirements") or []) > 0),
        ("投标人须知前附表", len(field_groups.get("bidderInstructions") or []) > 0),
        ("商务废标项", len(field_groups.get("commercialRejectionClauses") or []) > 0),
        ("商务评分细则", len(scoring.get("business") or []) > 0),
    ]
    return [{"label": label, "status": "covered" if covered else "missing"} for label, covered in checks]


def _business_project_name_from_fields(field_groups: dict[str, Any]) -> str:
    for field in field_groups.get("projectBasics") or []:
        if isinstance(field, dict) and str(field.get("key") or "") == "projectName" and str(field.get("value") or "").strip():
            return str(field.get("value") or "").strip()
    return ""


def _business_tenderer_name_from_fields(field_groups: dict[str, Any]) -> str:
    for field in field_groups.get("projectBasics") or []:
        if isinstance(field, dict) and str(field.get("key") or "") == "tenderer" and str(field.get("value") or "").strip():
            return str(field.get("value") or "").strip()
    return ""


BUSINESS_PROJECT_FACT_FIELD_SPECS: tuple[dict[str, Any], ...] = (
    {"fieldKey": "projectName", "label": "项目名称", "required": True},
    {"fieldKey": "tenderNo", "label": "招标编号", "required": True},
    {"fieldKey": "tenderer", "label": "招标人", "required": True},
    {"fieldKey": "tenderAgency", "label": "招标代理机构", "required": True},
    {"fieldKey": "bidDeadline", "label": "递交截止时间", "required": True},
)


def _build_business_project_fact_fields(field_groups: dict[str, Any], project_dates: dict[str, Any]) -> list[dict[str, Any]]:
    _ = project_dates
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups.get("projectBasics"), list) else []
    fields_by_key = {str(field.get("key") or ""): field for field in project_basics if isinstance(field, dict)}
    fact_fields: list[dict[str, Any]] = []
    for spec in BUSINESS_PROJECT_FACT_FIELD_SPECS:
        field_key = str(spec["fieldKey"])
        source = fields_by_key.get(field_key) or {}
        value = str(source.get("value") or "").strip()
        fact_fields.append(
            {
                "fieldKey": field_key,
                "label": str(spec["label"]),
                "value": value,
                "category": "项目基础信息",
                "status": "found" if value else "missing",
                "required": bool(spec.get("required", False)),
                "confidence": float(source.get("confidence") or (0.86 if value else 0.0)),
                "sourceFile": str(source.get("sourceFile") or ""),
                "sourceDocumentId": str(source.get("sourceDocumentId") or ""),
                "section": str(source.get("section") or ""),
                "evidence": str(source.get("evidence") or ""),
                "evidenceLocation": str(source.get("evidenceLocation") or ""),
                "evidenceIds": [str(item) for item in source.get("evidenceIds") or []],
            }
        )
    return fact_fields


def _load_business_template_extraction(manifest: dict[str, Any]) -> dict[str, Any]:
    extraction_path = Path(str(manifest.get("businessTemplateExtractionPath") or "")).expanduser()
    if not extraction_path.is_file():
        return {}
    try:
        payload = json.loads(extraction_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _template_extraction_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    return [copy.deepcopy(item) for item in values if isinstance(item, dict)]


def _business_template_appendices_from_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return _template_extraction_list(_load_business_template_extraction(manifest), "appendices")


def _existing_structured_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(str(manifest.get("structuredResultPath") or "")).expanduser()
    if not output_path.is_file():
        return {}
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    structured = payload.get("structured") if isinstance(payload, dict) else {}
    return copy.deepcopy(structured) if isinstance(structured, dict) else {}


def _structured_record_list(structured: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = structured.get(key) if isinstance(structured, dict) else []
    if not isinstance(values, list):
        return []
    return [copy.deepcopy(item) for item in values if isinstance(item, dict)]


def business_appendices_for_result(manifest: dict[str, Any], *structured_sources: dict[str, Any]) -> list[dict[str, Any]]:
    template_appendices = _business_template_appendices_from_manifest(manifest)
    if template_appendices:
        return template_appendices
    for structured in structured_sources:
        appendices = _structured_record_list(structured, "appendices")
        if appendices:
            return appendices
    return []


def business_structured_records(key: str, *structured_sources: dict[str, Any]) -> list[dict[str, Any]]:
    for structured in structured_sources:
        values = _structured_record_list(structured, key)
        if values:
            return values
    return []


def build_business_result(manifest: dict[str, Any], *, mode: str = "opencode-skill") -> dict[str, Any]:
    base_result = parse_base_manifest(manifest, mode=f"{mode}-business-base")
    documents = [item for item in manifest.get("documents") or [] if isinstance(item, dict)]
    texts_by_id = _load_texts_by_id(documents)
    section_tree = _load_business_section_tree(manifest)

    base_items = copy.deepcopy(base_result.get("items") if isinstance(base_result.get("items"), list) else [])
    structured = copy.deepcopy(base_result.get("structured") if isinstance(base_result.get("structured"), dict) else {})
    existing_structured = _existing_structured_from_manifest(manifest)
    merged_items = copy.deepcopy(base_items)

    scoring = _merge_business_scoring(structured.get("scoringCriteria") or {}, _extract_markdown_scoring(documents, texts_by_id))
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
    bidder_instruction_rows = _extract_bidder_instruction_rows(documents, texts_by_id, section_tree)
    field_groups = {
        "projectBasics": _build_business_project_basics(
            merged_items,
            project_dates,
            bidder_instruction_rows=bidder_instruction_rows,
            documents=documents,
            texts_by_id=texts_by_id,
            section_tree=section_tree,
        ),
        "qualificationRequirements": _extract_qualification_requirements(
            merged_items,
            documents=documents,
            texts_by_id=texts_by_id,
            section_tree=section_tree,
        ),
        "bidderInstructions": bidder_instruction_rows,
        "commercialRejectionClauses": _extract_commercial_rejection_clauses(documents, texts_by_id),
    }
    project_fact_fields = _build_business_project_fact_fields(field_groups, project_dates)
    appendices = business_appendices_for_result(manifest, existing_structured, structured)
    commitment_letters = business_structured_records("commitmentLetters", existing_structured, structured)
    commitment_clues = business_structured_records("commitmentClues", existing_structured, structured)

    return {
        "items": merged_items,
        "structured": {
            "schemaVersion": SCHEMA_VERSION,
            "targetSkill": SKILL_NAME,
            "sourceDocuments": copy.deepcopy(structured.get("sourceDocuments") or []),
            "scoringCriteria": scoring,
            "fieldGroups": field_groups,
            "requirementPresence": {},
            "coverage": _build_business_coverage(field_groups, scoring),
            "projectDates": {"endDate": str(project_dates.get("endDate") or "")},
            "appendices": appendices,
            "commitmentLetters": commitment_letters,
            "commitmentClues": commitment_clues,
            "projectFactFields": project_fact_fields,
            "categoryCounts": {},
        },
    }
