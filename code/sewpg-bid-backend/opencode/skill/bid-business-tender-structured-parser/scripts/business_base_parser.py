from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    from docx import Document
except ImportError:  # pragma: no cover
    Document = None  # type: ignore[assignment]


SKILL_NAME = "bid-business-tender-structured-parser-base"
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    aliases: tuple[str, ...]


PROJECT_BASIC_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("projectName", "项目名称", ("项目名称", "招标项目名称")),
    FieldSpec("tenderNo", "招标编号", ("招标编号", "项目编号", "招标文件编号")),
    FieldSpec("tenderer", "招标人", ("招标人", "业主", "建设单位", "项目单位")),
    FieldSpec("tenderAgency", "招标代理机构", ("招标代理机构", "代理机构")),
    FieldSpec("bidDeadline", "递交截止时间", ("递交截止时间", "投标截止时间", "投标文件递交截止时间", "提交截止时间")),
)

DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?"
    r"(?:\s*(?P<hour>\d{1,2})\s*(?:时|:)\s*(?P<minute>\d{1,2})?\s*分?)?"
)
LABEL_VALUE_PATTERN = re.compile(r"^\s*(?P<label>[^:：]{2,80})\s*[:：]\s*(?P<value>.+?)\s*$")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[（(]?\d+[）)]?)\s*[、.．\s]+")
BID_DEADLINE_CONTEXT = ("投标截止", "投标文件递交截止", "递交截止", "提交截止")
OPENING_TIME_CONTEXT = ("开标时间", "开标日期", "开标时间和地点", "开标地点")


def normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        compact.append(line)
        previous_blank = blank
    return "\n".join(compact).strip()


def extract_docx_text(path: Path) -> str:
    pieces: list[str] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as xml_file:
            for _, element in ET.iterparse(xml_file, events=("end",)):
                if element.tag == f"{WORD_NAMESPACE}t":
                    pieces.append(element.text or "")
                elif element.tag == f"{WORD_NAMESPACE}tab":
                    pieces.append("\t")
                elif element.tag in {f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"}:
                    pieces.append("\n")
                elif element.tag == f"{WORD_NAMESPACE}p":
                    pieces.append("\n")
                    element.clear()
    return normalize_text("".join(pieces))


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


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


def _normalize_date(value: str) -> str:
    match = DATE_PATTERN.search(value)
    if not match:
        return _clean(value)
    try:
        parsed = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return _clean(value)
    hour = match.group("hour")
    if hour is None:
        return parsed.isoformat()
    minute = match.group("minute") or "0"
    try:
        hour_int = int(hour)
        minute_int = int(minute)
    except ValueError:
        return parsed.isoformat()
    if not (0 <= hour_int <= 23 and 0 <= minute_int <= 59):
        return parsed.isoformat()
    return f"{parsed.isoformat()} {hour_int:02d}:{minute_int:02d}"


def _is_normalized_deadline_datetime(value: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}(?: \d{2}:\d{2})?", str(value or "").strip()))


def _is_opening_time_context(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not any(token in compact for token in OPENING_TIME_CONTEXT):
        return False
    return not any(token in compact for token in ("递交截止时间", "投标文件递交截止时间", "提交截止时间"))


def _docx_paragraph_text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(f"{WORD_NAMESPACE}t")).strip()


def _docx_table_rows(table: Any) -> list[list[str]]:
    return [[_clean(cell.text) for cell in row.cells] for row in table.rows]


def _iter_docx_blocks(path: Path) -> list[dict[str, Any]]:
    if Document is None or not path.exists() or path.suffix.lower() != ".docx":
        return []
    doc = Document(str(path))
    tables = iter(doc.tables)
    blocks: list[dict[str, Any]] = []
    for child in doc.element.body.iterchildren():
        if child.tag == f"{WORD_NAMESPACE}p":
            blocks.append({"type": "paragraph", "text": _docx_paragraph_text(child)})
        elif child.tag == f"{WORD_NAMESPACE}tbl":
            table = next(tables, None)
            if table is not None:
                blocks.append({"type": "table", "rows": _docx_table_rows(table)})
    return blocks


def _new_item(
    items: list[dict[str, Any]],
    *,
    label: str,
    value: str,
    document: dict[str, Any],
    evidence: str,
    location: str,
    section: str = "",
    field_key: str = "",
    confidence: float = 0.86,
) -> dict[str, Any]:
    normalized_value = _normalize_date(value) if field_key == "bidDeadline" else _clean(value)
    item = {
        "id": f"REQ-{len(items) + 1:04d}",
        "type": "商务核心字段候选",
        "category": "project_basics",
        "title": label,
        "keyEntity": label,
        "keyValue": normalized_value,
        "value": normalized_value,
        "sourceFile": str(document.get("name") or document.get("id") or "招标文件"),
        "sourceDocumentId": str(document.get("id") or ""),
        "section": section,
        "evidence": evidence,
        "evidenceLocation": location,
        "confidence": confidence,
        "fieldKey": field_key,
        "fieldGroup": "projectBasics",
    }
    items.append(item)
    return item


def _field_match(text: str) -> FieldSpec | None:
    for spec in PROJECT_BASIC_FIELDS:
        if any(alias in text for alias in spec.aliases):
            return spec
    return None


def _value_from_label_cell(cell: str, spec: FieldSpec) -> str:
    text = _clean(cell)
    for alias in sorted(spec.aliases, key=len, reverse=True):
        if alias in text:
            tail = text.split(alias, 1)[1].strip(" ：:；;，,。")
            if tail and tail != alias:
                return tail
    return ""


def _next_value(cells: list[str], index: int) -> str:
    for value in cells[index + 1 :]:
        cleaned = _clean(value)
        if cleaned and cleaned not in {"：", ":", "内容", "编列内容"}:
            return cleaned
    return ""


def _extract_line_items(
    items: list[dict[str, Any]],
    *,
    document: dict[str, Any],
    text: str,
    project_dates: dict[str, str],
    seen: set[tuple[str, str, str]],
) -> None:
    current_section = ""
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = _clean(raw_line)
        if not line:
            continue
        if line.startswith("#"):
            current_section = line.strip("# ").strip()
            continue
        if len(line) <= 80 and re.match(r"^\d+(?:\.\d+)*\s+", line):
            current_section = line

        spec = _field_match(line)
        if spec is None:
            continue
        label, value = _split_label_value(line, spec.label)
        if spec.key == "bidDeadline" and _is_opening_time_context(line):
            continue
        if spec.key == "bidDeadline" and not any(keyword in line for keyword in BID_DEADLINE_CONTEXT):
            continue
        if value == line:
            value = _value_from_label_cell(line, spec)
        if not value:
            continue
        dedupe_key = (spec.key, str(document.get("name") or ""), line)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        item = _new_item(
            items,
            label=spec.label if spec.label in line else label,
            value=value,
            document=document,
            evidence=line,
            location=f"L{line_no}",
            section=current_section,
            field_key=spec.key,
        )
        if spec.key == "bidDeadline" and _is_normalized_deadline_datetime(item["value"]):
            project_dates["endDate"] = item["value"]


def _extract_table_field_items(
    items: list[dict[str, Any]],
    *,
    document: dict[str, Any],
    rows: list[list[str]],
    section: str,
    block_index: int,
    project_dates: dict[str, str],
    seen: set[tuple[str, str, str, str]],
) -> None:
    for row_index, row in enumerate(rows, start=1):
        cells = [_clean(cell) for cell in row]
        for cell_index, cell in enumerate(cells):
            spec = _field_match(cell)
            if spec is None:
                continue
            value = _value_from_label_cell(cell, spec) or _next_value(cells, cell_index)
            if not value:
                continue
            evidence = " | ".join(cell for cell in cells if cell)
            if spec.key == "bidDeadline" and _is_opening_time_context(evidence):
                continue
            dedupe_key = (str(document.get("id") or ""), spec.key, value, evidence)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            item = _new_item(
                items,
                label=spec.label,
                value=value,
                document=document,
                evidence=evidence,
                location=f"B{block_index}/R{row_index}",
                section=section,
                field_key=spec.key,
                confidence=0.9 if "投标人须知前附表" in section or block_index <= 30 else 0.82,
            )
            if spec.key == "bidDeadline" and _is_normalized_deadline_datetime(item["value"]):
                project_dates["endDate"] = item["value"]


BUSINESS_SCORING_EXACT_KEYWORD = "商务评分标准"
SCORING_ITEM_HEADERS = ("评分项", "评审因素", "评审项目", "项目", "因素")
SCORING_SCORE_HEADERS = ("分值", "满分", "权重", "标准分")
SCORING_POINT_VALUE_HEADERS = ("分值", "满分", "标准分")
SCORING_STANDARD_HEADERS = ("得分点", "评分标准", "评分办法", "评审标准", "标准")


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


def _row_text(row: list[str]) -> str:
    return _clean(" ".join(_clean(cell) for cell in row if _clean(cell)))


def _has_scoring_table_columns(rows: list[list[str]]) -> bool:
    for row in rows[:5]:
        joined = "".join(_clean(cell) for cell in row)
        if not joined:
            continue
        has_item = any(keyword in joined for keyword in SCORING_ITEM_HEADERS)
        has_score = any(keyword in joined for keyword in SCORING_SCORE_HEADERS)
        has_standard = any(keyword in joined for keyword in SCORING_STANDARD_HEADERS)
        if has_item and has_score and has_standard:
            return True
    return False


def _business_scoring_table(title: str, rows: list[list[str]]) -> bool:
    title_text = _clean(title)
    if BUSINESS_SCORING_EXACT_KEYWORD in title_text and _has_scoring_table_columns(rows):
        return True
    if not _has_scoring_table_columns(rows):
        return False
    return any(BUSINESS_SCORING_EXACT_KEYWORD in _row_text(row) for row in rows[1:])


def _find_col(headers: list[str], aliases: tuple[str, ...]) -> int:
    for alias in aliases:
        for index, header in enumerate(headers):
            if alias in header:
                return index
    return -1


def _cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return _clean(row[index])


def _make_evidence(headers: list[str], row: list[str]) -> str:
    parts: list[str] = []
    for index, value in enumerate(row):
        cleaned = _clean(value)
        if not cleaned:
            continue
        header = _clean(headers[index]) if index < len(headers) else ""
        parts.append(f"{header}：{cleaned}" if header else cleaned)
    return "；".join(parts)


def _scoring_group_from_row(row: list[str], current_group: str = "") -> str:
    text = _row_text(row[:2])
    clause_no = _clean(row[0] if row else "").replace("（", "(").replace("）", ")").replace(" ", "")
    if re.search(r"2\.2\.4\(?1\)?", clause_no) or BUSINESS_SCORING_EXACT_KEYWORD in text or ("商务" in text and any(keyword in text for keyword in ("评分", "评审", "分值"))):
        return "business"
    if re.search(r"2\.2\.4\(?2\)?", clause_no) or ("技术" in text and ("评分" in text or "评审" in text)):
        return "technical"
    if re.search(r"2\.2\.4\(?3\)?", clause_no) or (("报价" in text or "价格" in text or "度电成本" in text) and ("评分" in text or "评审" in text)):
        return "price"
    if "符合性" in text and ("审查" in text or "评审" in text):
        return "compliance"
    return current_group


def _parse_business_scoring_rows(
    *,
    rows: list[list[str]],
    document: dict[str, Any],
    section: str,
    block_index: int,
    start_index: int,
) -> list[dict[str, Any]]:
    cleaned_rows = [[_clean(cell) for cell in row] for row in rows if any(_clean(cell) for cell in row)]
    if len(cleaned_rows) <= 1:
        return []
    header_index = 0
    for index, row in enumerate(cleaned_rows[:5]):
        joined = "".join(row)
        if any(keyword in joined for keyword in ("评分项", "评审因素", "分值", "评分标准", "得分点")):
            header_index = index
            break
    headers = cleaned_rows[header_index]
    data_rows = cleaned_rows[header_index + 1 :]
    order_col = _find_col(headers, ("序号", "条款号", "编号"))
    item_col = _find_col(headers, ("评分项", "评审因素", "评审项目", "项目", "因素"))
    score_col = _find_col(headers, ("分值", "满分", "权重", "标准分"))
    point_col = _find_col(headers, ("得分点", "评分标准", "评分办法", "评审标准", "标准", "内容"))
    proof_col = _find_col(headers, ("证明材料要求", "证明材料", "证明文件", "材料要求", "资料要求"))

    if item_col == -1:
        item_col = 1 if order_col == 0 and len(headers) > 1 else 0
    if point_col == item_col:
        point_col = _find_col(headers, ("评分标准", "评分办法", "评审标准"))

    parsed: list[dict[str, Any]] = []
    last_item = ""
    current_group = "business" if BUSINESS_SCORING_EXACT_KEYWORD in _clean(section) else ""
    for offset, row in enumerate(data_rows, start=header_index + 2):
        current_group = _scoring_group_from_row(row, current_group)
        if current_group != "business":
            continue
        order = _cell(row, order_col) or str(len(parsed) + 1)
        scoring_item = _cell(row, item_col) or last_item
        if scoring_item in {"合计", "总计"} or order in {"合计", "总计"}:
            continue
        if scoring_item:
            last_item = scoring_item
        score = _cell(row, score_col)
        score_point = _cell(row, point_col)
        if not score_point:
            score_point = "；".join(_clean(cell) for cell in row if _clean(cell) and _clean(cell) not in {order, scoring_item, score})
        if not scoring_item and not score_point:
            continue
        if score_col == -1 and not _text_has_concrete_score(score_point):
            continue
        if score_col != -1 and not (_score_value_cell_has_concrete_score(score) or _text_has_concrete_score(score_point)):
            continue
        parsed.append(
            {
                "id": f"BUS-SCORE-{start_index + len(parsed):04d}",
                "order": order,
                "scoringItem": scoring_item,
                "score": score,
                "scorePoint": score_point,
                "proofRequirement": _cell(row, proof_col),
                "status": "found",
                "sourceFile": str(document.get("name") or document.get("id") or "招标文件"),
                "sourceDocumentId": str(document.get("id") or ""),
                "section": section,
                "evidence": _make_evidence(headers, row),
                "evidenceLocation": f"B{block_index}/R{offset}",
            }
        )
    return parsed


def _extract_docx_table_items(
    items: list[dict[str, Any]],
    scoring: dict[str, list[dict[str, Any]]],
    *,
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    project_dates: dict[str, str],
    seen_fields: set[tuple[str, str, str, str]],
) -> None:
    current_section = ""
    for block_index, block in enumerate(blocks, start=1):
        if block.get("type") == "paragraph":
            text = _clean(block.get("text"))
            if text:
                current_section = text
            continue
        if block.get("type") != "table":
            continue
        rows = block.get("rows") or []
        if _business_scoring_table(current_section, rows):
            parsed_rows = _parse_business_scoring_rows(
                rows=rows,
                document=document,
                section=current_section,
                block_index=block_index,
                start_index=len(scoring["business"]) + 1,
            )
            scoring["business"].extend(parsed_rows)
            continue
        _extract_table_field_items(
            items,
            document=document,
            rows=rows,
            section=current_section,
            block_index=block_index,
            project_dates=project_dates,
            seen=seen_fields,
        )


def _empty_field(spec: FieldSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": "",
        "status": "missing",
        "sourceFile": "",
        "sourceDocumentId": "",
        "section": "",
        "evidence": "",
        "evidenceLocation": "",
    }


def _field_from_item(spec: FieldSpec, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": str(item.get("value") or item.get("keyValue") or "").strip(),
        "status": "found",
        "sourceFile": str(item.get("sourceFile") or ""),
        "sourceDocumentId": str(item.get("sourceDocumentId") or ""),
        "section": str(item.get("section") or ""),
        "evidence": str(item.get("evidence") or ""),
        "evidenceLocation": str(item.get("evidenceLocation") or ""),
    }


def _field_score(item: dict[str, Any], spec: FieldSpec) -> int:
    value = str(item.get("value") or "").strip()
    section = str(item.get("section") or "")
    location = str(item.get("evidenceLocation") or "")
    evidence = str(item.get("evidence") or "")
    score = 0
    if location.startswith("B"):
        score += 40
    if "投标人须知前附表" in section:
        score += 80
    if "招标公告" in section:
        score += 40
    if spec.key == "projectName" and len(value) <= 120:
        score += 40
    if spec.key == "tenderNo" and re.search(r"[A-Z]{2,}.*\d", value):
        score += 60
    if spec.key in {"tenderer", "tenderAgency"} and len(value) <= 100:
        score += 40
    if spec.key == "bidDeadline" and any(keyword in evidence for keyword in BID_DEADLINE_CONTEXT):
        score += 90
        if _is_normalized_deadline_datetime(value):
            score += 120
        if _is_opening_time_context(evidence):
            score -= 240
    if not value:
        score -= 300
    return score


def _build_project_basics(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for spec in PROJECT_BASIC_FIELDS:
        candidates = [item for item in items if item.get("fieldKey") == spec.key]
        matched = max(candidates, key=lambda item: _field_score(item, spec)) if candidates else None
        fields.append(_field_from_item(spec, matched) if matched else _empty_field(spec))
    return fields


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


def _build_coverage(field_groups: dict[str, list[dict[str, Any]]], scoring: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    project_fields = field_groups.get("projectBasics") or []
    found_project = [field for field in project_fields if field.get("status") == "found"]
    business_rows = scoring.get("business") or []
    return [
        {
            "label": "项目基础信息",
            "status": "covered" if len(found_project) == len(project_fields) else "partial" if found_project else "missing",
            "sources": _unique_sources(found_project),
        },
        {
            "label": "商务评分细则",
            "status": "covered" if business_rows else "missing",
            "sources": _unique_sources(business_rows),
        },
    ]


def parse_documents(documents: list[dict[str, Any]], texts_by_id: dict[str, str] | None = None, *, mode: str = "local-structured-parser") -> dict[str, Any]:
    texts_by_id = texts_by_id or {}
    items: list[dict[str, Any]] = []
    scoring: dict[str, list[dict[str, Any]]] = {"business": []}
    project_dates = {"endDate": ""}
    line_seen: set[tuple[str, str, str]] = set()
    field_seen: set[tuple[str, str, str, str]] = set()
    source_documents: list[dict[str, Any]] = []

    for document in documents:
        document_id = str(document.get("id") or "")
        source_path = Path(str(document.get("sourcePath") or ""))
        text = texts_by_id.get(document_id, "")
        if not text:
            text_path_value = str(document.get("textPath") or "")
            text_path = Path(text_path_value) if text_path_value else None
            if text_path is not None and text_path.exists() and text_path.is_file():
                text = text_path.read_text(encoding="utf-8", errors="replace")
            elif source_path.suffix.lower() == ".docx" and source_path.exists():
                text = extract_docx_text(source_path)
        text = normalize_text(text)
        blocks = _iter_docx_blocks(source_path)
        source_documents.append(
            {
                "id": document_id,
                "name": str(document.get("name") or source_path.name or document_id or "招标文件"),
                "role": "business_tender",
                "textLength": len(text),
            }
        )
        _extract_line_items(items, document=document, text=text, project_dates=project_dates, seen=line_seen)
        if blocks:
            _extract_docx_table_items(
                items,
                scoring,
                document=document,
                blocks=blocks,
                project_dates=project_dates,
                seen_fields=field_seen,
            )

    field_groups = {"projectBasics": _build_project_basics(items)}
    project_basics = {
        field["label"]: field["value"]
        for field in field_groups["projectBasics"]
        if field.get("status") == "found" and field.get("value")
    }
    structured = {
        "schemaVersion": "bid-tender-structured-v1",
        "targetSkill": SKILL_NAME,
        "sourceDocuments": source_documents,
        "projectDates": project_dates,
        "projectBasics": project_basics,
        "categories": [],
        "fieldGroups": field_groups,
        "scoringCriteria": scoring,
        "coverage": _build_coverage(field_groups, scoring),
    }
    return {"items": items, "structured": structured}


def parse_manifest(manifest: dict[str, Any], *, mode: str = "opencode-skill") -> dict[str, Any]:
    documents = [item for item in manifest.get("documents") or [] if isinstance(item, dict)]
    return parse_documents(documents, mode=mode)
