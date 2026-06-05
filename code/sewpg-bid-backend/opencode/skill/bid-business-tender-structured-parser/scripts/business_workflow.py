from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from business_contract import (
    SCHEMA_VERSION,
    SKILL_NAME,
    _clause_number_tuple,
    _build_business_coverage,
    _build_business_project_fact_fields,
    _clean,
    _is_docx_source,
    _is_rejection_child_line,
    _is_rejection_parent_heading,
    _is_same_or_higher_clause,
    _iter_docx_blocks,
    _business_template_appendices_from_manifest,
    _load_texts_by_id,
    _looks_like_qualification_requirement,
    _looks_like_section_heading,
    _normalize_applicable_scope,
    _normalize_qualification_content,
    _qualification_source_text,
    _with_commercial_rejection_display_fields,
    build_business_result,
)


TASK_NAMES = (
    "qualification_review",
    "rejection_clause_review",
    "scoring_table_review",
)
TASK_MODULE_KEYS = {
    "qualification_review": "qualification",
    "rejection_clause_review": "rejection",
    "scoring_table_review": "scoringTableReview",
}
TASK_INSTRUCTIONS = {
    "qualification_review": ("qualification", "只判断真正影响投标人资格的条件；材料说明、评分项、目录、引用句、废标项都应拒绝。"),
    "rejection_clause_review": ("rejection", "只保留影响投标有效性的商务废标、否决、无效投标、不予受理条款。"),
    "scoring_table_review": ("scoringTableReview", "只判断疑难评分行块是否属于商务评分细则；表头不固定时也要能从行块中识别评分/审查项、分值、评分标准，且只有看到具体分值时才能接受；权重、分值构成、推荐原则、报价评审条件不是商务评分细则。"),
}
DECISION_BUCKETS = ("accepted", "rejected", "needsReview")
REQUIRED_DECISION_ITEM_FIELDS = (
    "candidateId",
    "decision",
    "fieldType",
    "content",
    "applicableScope",
    "sourceText",
    "reason",
    "evidenceIds",
)
ALLOWED_AI_DECISION_KEYS = {
    "schemaVersion",
    "task",
    "taskId",
    "adapter",
    "qualificationItems",
    "rejectedEvidenceIds",
    "accepted",
    "rejected",
    "needsReview",
    "reason",
    "evidenceIds",
}
MAX_TASK_CANDIDATES = 12
MAX_TASK_CONTENT_CHARS = 24000

ALLOWED_FIELD_GROUP_KEYS = ("projectBasics", "qualificationRequirements", "bidderInstructions", "commercialRejectionClauses")
ALLOWED_STRUCTURED_KEYS = (
    "schemaVersion",
    "targetSkill",
    "workflow",
    "sourceDocuments",
    "scoringCriteria",
    "fieldGroups",
    "requirementPresence",
    "coverage",
    "projectDates",
    "appendices",
    "commitmentLetters",
    "commitmentClues",
    "projectFactFields",
    "categoryCounts",
)
ALLOWED_SCORING_KEYS = ("business",)
ALLOWED_PROJECT_DATE_KEYS = ("endDate",)
BUSINESS_SCORING_EXACT_KEYWORD = "商务评分标准"
SCORING_ITEM_HEADERS = ("评分项", "评审因素", "评审项目", "项目", "因素")
SCORING_SCORE_HEADERS = ("分值", "满分", "权重", "标准分")
SCORING_POINT_VALUE_HEADERS = ("分值", "满分", "标准分")
SCORING_STANDARD_HEADERS = ("得分点", "评分标准", "评分办法", "评审标准", "标准")

REJECTION_KEYWORDS = ("否决", "废标", "无效投标", "不予受理", "★", "实质性响应", "不得存在下列情形")
NON_BID_REJECTION_CONTEXT = ("异议", "投诉", "质疑", "合同执行", "合同履行", "保证金不退还", "不退还")
PROJECT_FACT_LABELS = ("项目名称", "招标编号", "项目编号", "招标人", "招标代理机构", "代理机构", "递交截止时间", "投标截止时间", "开标时间")
DETERMINISTIC_MODULES = ("projectBasics", "bidderInstructions", "businessScoringTables")
SEMANTIC_REVIEW_MODULES = {
    "qualification_review": "qualification",
    "rejection_clause_review": "commercialRejectionClauses",
    "scoring_table_review": "scoring_table_review",
}
QUALIFICATION_ANCHOR_KEYWORDS = ("投标人资格要求", "资格条件", "资质条件", "资格能力要求", "专用资格条件", "通用资格条件")
QUALIFICATION_STOP_KEYWORDS = ("招标文件的获取", "投标文件的递交", "投标人须知", "资格审查资料", "评标办法", "投标文件格式", "合同条款")
QUALIFICATION_ITEM_CUES = (
    "投标人",
    "供应商",
    "联合体",
    "须",
    "应",
    "需",
    "必须",
    "具有",
    "具备",
    "不得",
    "不允许",
    "不接受",
    "没有处于",
    "未被",
    "认证",
)
TOC_TITLE_KEYWORDS = (
    "招标公告",
    "项目概况",
    "招标范围",
    "招标文件的获取",
    "投标文件的递交",
    "联系方式",
    *QUALIFICATION_ANCHOR_KEYWORDS,
    *QUALIFICATION_STOP_KEYWORDS,
)


def _output_dir_for_manifest(manifest: dict[str, Any], manifest_path: Path | None = None) -> Path:
    structured_path = Path(str(manifest.get("structuredResultPath") or "")).expanduser()
    if structured_path:
        return structured_path.parent
    if manifest_path is not None:
        return manifest_path.parent
    return Path.cwd()


def _artifact_paths(manifest: dict[str, Any], manifest_path: Path | None = None) -> dict[str, Path]:
    output_dir = _output_dir_for_manifest(manifest, manifest_path)
    return {
        "outputDir": output_dir,
        "candidatePackage": Path(str(manifest.get("candidatePackagePath") or output_dir / "candidate_package.json")),
        "reviewPlan": Path(str(manifest.get("reviewPlanPath") or output_dir / "review_plan.json")),
        "aiTasksDir": Path(str(manifest.get("aiTasksDir") or output_dir / "ai_tasks")),
        "aiDecisionsDir": Path(str(manifest.get("aiDecisionsDir") or output_dir / "ai_decisions")),
        "validationReport": Path(str(manifest.get("validationReportPath") or output_dir / "validation_report.json")),
    }


def _evidence_id(document_id: str, location: str) -> str:
    doc = str(document_id or "DOC").strip() or "DOC"
    loc = str(location or "").strip()
    return f"{doc}:{loc}" if loc else doc


def _record_evidence_ids(record: dict[str, Any]) -> list[str]:
    existing = [str(item) for item in record.get("evidenceIds") or [] if str(item).strip()]
    if existing:
        return existing
    document_id = str(record.get("sourceDocumentId") or "")
    location = str(record.get("evidenceLocation") or "")
    return [_evidence_id(document_id, location)] if document_id and location else []


def _with_evidence_ids(record: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record)
    evidence_ids = _record_evidence_ids(item)
    if evidence_ids:
        item["evidenceIds"] = evidence_ids
    return item


def _readable_source_text(record: dict[str, Any]) -> str:
    source_file = str(record.get("sourceFile") or "招标文件")
    section = str(record.get("section") or "").strip()
    evidence_location = str(record.get("evidenceLocation") or "").strip()
    parts = [part for part in (section, evidence_location) if part]
    return f"{source_file}：" + " > ".join(parts) if parts else source_file


def _looks_like_markdown_table(line: str) -> bool:
    return bool(re.match(r"^\s*\|.*\|\s*$", line or ""))


def _is_toc_heading(line: str) -> bool:
    compact = re.sub(r"\s+", "", _clean(line))
    return compact in {"目录", "目录页"}


def _leading_clause_parts(line: str) -> tuple[int, ...]:
    cleaned = _clean(line)
    match = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[.．]\s*|\s+)", cleaned)
    if match:
        return tuple(int(part) for part in match.group(1).split(".") if part.isdigit())
    if re.match(r"^\s*[一二三四五六七八九十百]+[、.．]\s*", cleaned):
        return (0,)
    return ()


def _toc_title_without_page(line: str) -> str:
    cleaned = _clean(line)
    match = re.match(r"^(?P<title>.+?)(?:\s|[.·…])+(?:第\s*)?\d{1,4}\s*页?$", cleaned)
    if not match:
        return ""
    return match.group("title").strip(" .·…")


def _looks_like_toc_line(line: str) -> bool:
    title = _toc_title_without_page(line)
    if not title or len(title) > 90:
        return False
    return _looks_like_section_heading(title) or any(keyword in title for keyword in TOC_TITLE_KEYWORDS)


def _is_primary_qualification_section(section: str) -> bool:
    cleaned = _clean(section)
    if "投标人资格要求" not in cleaned:
        return False
    parts = _leading_clause_parts(cleaned)
    return not parts or len(parts) == 1


def _section_heading_level(line: str) -> int | None:
    cleaned = _clean(line).lstrip("#").strip()
    if not cleaned:
        return None
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[.．]\s*|\s+)", cleaned)
    if match:
        return len(match.group(1).split("."))
    if re.match(r"^第[一二三四五六七八九十百千0-9]+章(?:\s|[、.．：:])", cleaned):
        return 0
    if re.match(r"^[一二三四五六七八九十百]+[、.．]\s*", cleaned):
        return 1
    if _looks_like_section_heading(cleaned):
        return 1
    return None


def _qualification_section_priority(line: str) -> int:
    cleaned = _clean(line).lstrip("#").strip()
    if "投标人资格要求" in cleaned:
        parts = _leading_clause_parts(cleaned)
        if not parts:
            return 10
        if len(parts) == 1:
            return 0
        if len(parts) == 2 and parts[0] == 1 and parts[1] == 4:
            return 80
        return 50 + len(parts)
    if any(keyword in cleaned for keyword in ("通用资格条件", "专用资格条件", "资格能力要求", "资质条件")):
        return 70
    return 90


def _is_qualification_section_anchor(line: str) -> bool:
    cleaned = _clean(line).lstrip("#").strip()
    if not cleaned or len(cleaned) > 120:
        return False
    if _looks_like_toc_line(cleaned):
        return False
    return "投标人资格要求" in cleaned or cleaned == "投标人资格要求"


def _is_qualification_stop_heading(line: str, start_level: int) -> bool:
    cleaned = _clean(line).lstrip("#").strip()
    if not cleaned:
        return False
    if re.match(r"^(?:[（(]\s*\d+\s*[）)]|\d+[、])", cleaned):
        return False
    if any(stop in cleaned for stop in QUALIFICATION_STOP_KEYWORDS):
        return True
    level = _section_heading_level(cleaned)
    if level is None:
        return False
    if "投标人资格要求" in cleaned:
        return False
    return level <= start_level


def _is_qualification_scope_hint_text(text: str) -> bool:
    cleaned = _normalize_qualification_content(text)
    if not re.match(r"^(?:标段|第.*标段|全部标段|所有标段|本项目)", cleaned):
        return False
    return not any(
        token in cleaned
        for token in (
            "投标人",
            "供应商",
            "联合体",
            "须提供",
            "必须",
            "应是",
            "应承诺",
            "具有",
            "具备",
            "不得",
            "不接受",
            "业绩",
            "合同",
            "认证",
            "制造",
            "注册",
            "未被",
            "没有处于",
        )
    )


def _prefer_primary_qualification_section(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary_sections = [
        str(candidate.get("section") or "")
        for candidate in candidates
        if isinstance(candidate, dict) and _is_primary_qualification_section(str(candidate.get("section") or ""))
    ]
    if not primary_sections:
        return candidates
    preferred_section = primary_sections[0]
    return [candidate for candidate in candidates if str(candidate.get("section") or "") == preferred_section]


def _qualification_source_path(path: list[str], line: str) -> str:
    cleaned_line = _clean(line)
    parts = [part for part in (*path, cleaned_line) if part]
    return " > ".join(dict.fromkeys(parts))


def _update_qualification_path(path: list[str], line: str) -> list[str]:
    parts = _leading_clause_parts(line)
    if not parts:
        return path
    trimmed = path[: max(0, len(parts) - 1)]
    return [*trimmed, line]


def _qualification_section_slices(document: dict[str, Any], text: str) -> list[dict[str, Any]]:
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    raw_lines = text.splitlines()
    lines = [(line_number, _clean(raw_line)) for line_number, raw_line in enumerate(raw_lines, start=1) if _clean(raw_line)]
    anchors: list[tuple[int, int, int]] = []
    in_toc = False
    for index, (_line_number, line) in enumerate(lines):
        if _is_toc_heading(line):
            in_toc = True
            continue
        if in_toc:
            if _looks_like_toc_line(line):
                continue
            in_toc = False
        if _looks_like_toc_line(line):
            continue
        if not _is_qualification_section_anchor(line):
            continue
        priority = _qualification_section_priority(line)
        level = _section_heading_level(line) or 1
        anchors.append((priority, index, level))
    if not anchors:
        return []
    _, start_index, start_level = min(anchors, key=lambda item: (item[0], item[1]))
    start_line_number, start_line = lines[start_index]
    slice_lines: list[dict[str, Any]] = []
    qualification_path = [start_line]
    current_scope = "全部标段"
    for index in range(start_index, len(lines)):
        line_number, line = lines[index]
        if index > start_index and _is_qualification_stop_heading(line, start_level):
            break
        if index == start_index:
            qualification_path = [line]
        else:
            if _is_qualification_scope_hint_text(line):
                current_scope = _normalize_applicable_scope(line)
            parts = _leading_clause_parts(line)
            if parts:
                qualification_path = _update_qualification_path(qualification_path, line)
        source_path = _qualification_source_path(qualification_path, "" if _leading_clause_parts(line) else line)
        evidence_id = _evidence_id(document_id, f"L{line_number}")
        slice_lines.append(
            {
                "lineNumber": line_number,
                "text": line,
                "evidenceId": evidence_id,
                "evidenceLocation": f"L{line_number}",
                "sourceText": _qualification_source_text(source_file=source_file, section=source_path or start_line),
                "sourcePath": source_path or start_line,
                "applicableScopeHint": current_scope or "全部标段",
            }
        )
    if len(slice_lines) <= 1:
        return []
    evidence_ids = [str(item["evidenceId"]) for item in slice_lines if item.get("evidenceId")]
    content = "\n".join(str(item.get("text") or "") for item in slice_lines if str(item.get("text") or "").strip())
    return [
        {
            "id": f"QUALIFICATION-SECTION-SLICE-{document_id or 'DOC'}-{start_line_number:04d}",
            "module": "qualification",
            "candidateType": "qualification_section_slice",
            "content": content,
            "applicableScope": "全部标段",
            "sourceFile": source_file,
            "sourceDocumentId": document_id,
            "section": start_line,
            "evidence": content,
            "evidenceLocation": f"L{start_line_number}",
            "evidenceIds": evidence_ids,
            "sourceText": _qualification_source_text(source_file=source_file, section=start_line),
            "confidence": 0.9,
            "startLine": start_line_number,
            "endLine": int(slice_lines[-1].get("lineNumber") or start_line_number),
            "lines": slice_lines,
        }
    ]


def _markdown_cells(line: str) -> list[str]:
    return [_clean(cell) for cell in str(line or "").strip().strip("|").split("|")]


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _business_scoring_table_type(title: str) -> str:
    text = _clean(title)
    if not text:
        return ""
    if BUSINESS_SCORING_EXACT_KEYWORD in text:
        return "business"
    return ""


def _is_non_target_scoring_title(title: str) -> bool:
    text = _clean(title)
    if "评分" not in text and "评审" not in text:
        return False
    if _business_scoring_table_type(text) == "business":
        return False
    return any(keyword in text for keyword in ("技术", "报价", "价格", "符合性", "热电", "LCOE", "lcoe"))


def _collect_markdown_tables(document: dict[str, Any], text: str) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    lines = text.splitlines()
    current_section = ""
    pending_table_title = ""
    index = 0
    while index < len(lines):
        line = _clean(lines[index])
        if not line:
            index += 1
            continue
        if line.startswith("#"):
            current_section = line.strip("# ").strip()
            pending_table_title = ""
            index += 1
            continue
        if _looks_like_section_heading(line):
            current_section = line
            pending_table_title = ""
            index += 1
            continue
        if not _looks_like_markdown_table(line):
            if _business_scoring_table_type(line) or _is_non_target_scoring_title(line):
                pending_table_title = line
            index += 1
            continue
        raw_rows: list[tuple[int, list[str]]] = []
        start_line = index + 1
        while index < len(lines) and _looks_like_markdown_table(lines[index]):
            cells = _markdown_cells(lines[index])
            if cells and not _is_markdown_separator(cells):
                raw_rows.append((index + 1, cells))
            index += 1
        if not raw_rows:
            continue
        headers = raw_rows[0][1]
        data_rows = raw_rows[1:]
        table_title = pending_table_title or current_section
        tables.append(
            {
                "id": f"{document.get('id') or 'DOC'}:T{len(tables) + 1:04d}",
                "sourceDocumentId": str(document.get("id") or ""),
                "sourceFile": str(document.get("name") or document.get("id") or "招标文件"),
                "section": table_title,
                "tableType": _business_scoring_table_type(table_title),
                "startLine": start_line,
                "endLine": raw_rows[-1][0],
                "headers": headers,
                "rows": [
                    {
                        "rowIndex": row_index,
                        "cells": cells,
                        "evidenceId": _evidence_id(str(document.get("id") or ""), f"L{line_no}"),
                        "evidenceLocation": f"L{line_no}",
                    }
                    for row_index, (line_no, cells) in enumerate(data_rows, start=1)
                ],
            }
        )
        pending_table_title = ""
    return tables


def _collect_docx_tables(document: dict[str, Any]) -> list[dict[str, Any]]:
    source_path = Path(str(document.get("sourcePath") or ""))
    if not _is_docx_source(source_path):
        return []
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    tables: list[dict[str, Any]] = []
    current_section = ""
    for block_index, block in enumerate(_iter_docx_blocks(source_path), start=1):
        if block.get("type") == "paragraph":
            text_value = _clean(block.get("text"))
            if text_value:
                current_section = text_value
            continue
        if block.get("type") != "table":
            continue
        raw_rows = [
            [_clean(cell) for cell in row]
            for row in block.get("rows") or []
            if any(_clean(cell) for cell in row)
        ]
        if not raw_rows:
            continue
        headers = raw_rows[0]
        data_rows = raw_rows[1:]
        tables.append(
            {
                "id": _evidence_id(document_id, f"B{block_index}"),
                "sourceDocumentId": document_id,
                "sourceFile": source_file,
                "section": current_section,
                "tableType": _business_scoring_table_type(current_section),
                "startLine": block_index,
                "endLine": block_index,
                "headers": headers,
                "rows": [
                    {
                        "rowIndex": row_index,
                        "cells": cells,
                        "evidenceId": _evidence_id(document_id, f"B{block_index}/R{row_index + 1}"),
                        "evidenceLocation": f"B{block_index}/R{row_index + 1}",
                    }
                    for row_index, cells in enumerate(data_rows, start=1)
                ],
            }
        )
    return tables


def _document_blocks(document: dict[str, Any], text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    blocks: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    current_section = ""
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _clean(raw_line)
        if not line:
            continue
        if line.startswith("#"):
            current_section = line.strip("# ").strip()
            sections.append(
                {
                    "id": _evidence_id(document_id, f"S{len(sections) + 1:04d}"),
                    "sourceDocumentId": document_id,
                    "title": current_section,
                    "level": max(1, len(raw_line) - len(raw_line.lstrip("#"))),
                    "evidenceId": _evidence_id(document_id, f"L{line_number}"),
                }
            )
        elif _looks_like_section_heading(line):
            current_section = line
            sections.append(
                {
                    "id": _evidence_id(document_id, f"S{len(sections) + 1:04d}"),
                    "sourceDocumentId": document_id,
                    "title": current_section,
                    "level": 1,
                    "evidenceId": _evidence_id(document_id, f"L{line_number}"),
                }
            )
        blocks.append(
            {
                "id": _evidence_id(document_id, f"L{line_number}"),
                "type": "paragraph",
                "sourceDocumentId": document_id,
                "sourceFile": source_file,
                "section": current_section,
                "text": line,
                "location": f"L{line_number}",
            }
        )
    return blocks, sections


def _line_candidate(
    *,
    module: str,
    document: dict[str, Any],
    line_number: int,
    section: str,
    content: str,
    candidate_type: str,
    applicable_scope: str = "全部标段",
    confidence: float = 0.7,
) -> dict[str, Any]:
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    evidence_id = _evidence_id(document_id, f"L{line_number}")
    return {
        "id": f"{module.upper()}-CAND-{document_id or 'DOC'}-{line_number:04d}",
        "module": module,
        "candidateType": candidate_type,
        "content": content,
        "applicableScope": applicable_scope or "全部标段",
        "sourceFile": source_file,
        "sourceDocumentId": document_id,
        "section": section,
        "evidence": content,
        "evidenceLocation": f"L{line_number}",
        "evidenceIds": [evidence_id],
        "sourceText": _qualification_source_text(source_file=source_file, section=section or "招标文件"),
        "confidence": confidence,
    }


def _raw_line_candidates(document: dict[str, Any], text: str) -> dict[str, list[dict[str, Any]]]:
    candidates = {
        "projectFacts": [],
        "bidderInstructions": [],
        "qualification": [],
        "rejection": [],
        "scoring": [],
        "scoringTableReview": [],
    }
    current_section = ""
    in_toc = False
    lines = text.splitlines()
    candidates["qualification"] = _qualification_section_slices(document, text)
    for line_number, raw_line in enumerate(lines, start=1):
        line = _clean(raw_line)
        if not line:
            continue
        if _is_toc_heading(line):
            in_toc = True
            continue
        if in_toc:
            if _looks_like_toc_line(line):
                continue
            in_toc = False
        if _looks_like_toc_line(line):
            continue
        if line.startswith("#"):
            current_section = line.strip("# ").strip()
            continue
        if _looks_like_section_heading(line):
            current_section = line

        if any(label in line for label in PROJECT_FACT_LABELS):
            candidates["projectFacts"].append(
                _line_candidate(module="projectFacts", document=document, line_number=line_number, section=current_section, content=line, candidate_type="project_fact")
            )
        if "投标人须知前附表" in current_section or "投标人须知前附表" in line:
            candidates["bidderInstructions"].append(
                _line_candidate(module="bidderInstructions", document=document, line_number=line_number, section=current_section, content=line, candidate_type="bidder_instruction")
            )
        if any(keyword in line for keyword in REJECTION_KEYWORDS) and not any(keyword in line for keyword in NON_BID_REJECTION_CONTEXT):
            block_lines = [line]
            if _is_rejection_parent_heading(line):
                parent_parts = _clause_number_tuple(line)
                collecting_children = False
                for next_line_number in range(line_number + 1, len(lines) + 1):
                    next_line = _clean(lines[next_line_number - 1])
                    if not next_line:
                        continue
                    if parent_parts and _is_same_or_higher_clause(next_line, parent_parts):
                        break
                    if _looks_like_section_heading(next_line) and not re.match(r"^\s*[（(]\d+[）)]", next_line):
                        break
                    if _is_rejection_child_line(next_line):
                        collecting_children = True
                        block_lines.append(next_line)
                        continue
                    if not collecting_children:
                        break
                    block_lines.append(next_line)
            candidate = _line_candidate(
                module="rejection",
                document=document,
                line_number=line_number,
                section=current_section,
                content="\n".join(block_lines),
                candidate_type="rejection_clause",
            )
            if len(block_lines) > 1:
                document_id = str(document.get("id") or "")
                candidate["evidence"] = "\n".join(block_lines)
                candidate["sourceText"] = _qualification_source_text(source_file=str(document.get("name") or document_id or "招标文件"), section=current_section or "商务废标项")
                candidate["evidenceIds"] = [
                    _evidence_id(document_id, f"L{line_number + offset}")
                    for offset in range(len(block_lines))
                ]
            candidates["rejection"].append(candidate)
        if "商务" in line and "评分" in line:
            candidates["scoring"].append(
                _line_candidate(module="scoring", document=document, line_number=line_number, section=current_section, content=line, candidate_type="business_scoring")
            )
    return candidates


def _candidate_from_result(module: str, record: dict[str, Any], candidate_type: str, content_key: str = "content") -> dict[str, Any]:
    item = copy.deepcopy(record)
    candidate_id = str(item.get("id") or f"{module.upper()}-RESULT-{abs(hash(json.dumps(item, ensure_ascii=False, sort_keys=True))) % 100000:05d}")
    item.update(
        {
            "id": candidate_id,
            "module": module,
            "candidateType": candidate_type,
            "content": str(record.get(content_key) or record.get("content") or record.get("value") or record.get("evidence") or ""),
            "evidenceIds": _record_evidence_ids(record),
            "sourceText": str(record.get("sourceText") or _readable_source_text(record)),
        }
    )
    return item


def _record_with_evidence_ids(record: dict[str, Any]) -> dict[str, Any]:
    return _with_evidence_ids(record)


def _deterministic_scoring_tables(base_result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    structured = base_result.get("structured") if isinstance(base_result.get("structured"), dict) else {}
    scoring = structured.get("scoringCriteria") if isinstance(structured.get("scoringCriteria"), dict) else {}
    return {"business": [_with_evidence_ids(row) for row in scoring.get("business") or [] if isinstance(row, dict)]}


def _table_text(table: dict[str, Any]) -> str:
    parts = [str(table.get("section") or ""), *[str(header) for header in table.get("headers") or []]]
    for row in table.get("rows") or []:
        if isinstance(row, dict):
            parts.extend(str(cell) for cell in row.get("cells") or [])
    return " ".join(parts)


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


def _table_has_scoring_columns(table: dict[str, Any]) -> bool:
    rows = [[str(cell) for cell in table.get("headers") or []]]
    rows.extend([[str(cell) for cell in row.get("cells") or []] for row in table.get("rows") or [] if isinstance(row, dict)])
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


def _table_has_exact_business_scoring_anchor(table: dict[str, Any]) -> bool:
    if BUSINESS_SCORING_EXACT_KEYWORD in _clean(str(table.get("section") or "")):
        return True
    return any(
        BUSINESS_SCORING_EXACT_KEYWORD in _clean(" ".join(str(cell) for cell in row.get("cells") or []))
        for row in table.get("rows") or []
        if isinstance(row, dict)
    )


def _is_business_scoring_table(table: dict[str, Any]) -> bool:
    return _table_has_exact_business_scoring_anchor(table)


def _extract_score_from_text(text: str) -> str:
    normalized = _clean(text)
    if not normalized:
        return ""
    match = re.search(r"(\d+(?:\.\d+)?\s*(?:[-~－—至]\s*\d+(?:\.\d+)?)?\s*分)", normalized)
    if match:
        return _clean(match.group(1))
    match = re.search(r"(?:满分|得|加|扣)\s*(\d+(?:\.\d+)?)", normalized)
    if match:
        return f"{match.group(1)}分"
    return ""


def _strip_score_from_item(text: str) -> str:
    normalized = _clean(text)
    normalized = re.sub(r"[（(]\s*\d+(?:\.\d+)?\s*(?:[-~－—至]\s*\d+(?:\.\d+)?)?\s*分\s*[）)]", "", normalized)
    return _clean(normalized)


def _find_header_col(headers: list[str], aliases: tuple[str, ...]) -> int:
    return next((index for index, header in enumerate(headers) if any(alias in _clean(header) for alias in aliases)), -1)


def _score_row_cells_by_headers(headers: list[str], cells: list[str]) -> dict[str, str]:
    order_index = _find_header_col(headers, ("序号", "条款号", "编号"))
    item_index = _find_header_col(headers, SCORING_ITEM_HEADERS)
    score_index = _find_header_col(headers, SCORING_POINT_VALUE_HEADERS)
    standard_index = _find_header_col(headers, SCORING_STANDARD_HEADERS)
    proof_index = _find_header_col(headers, ("证明材料要求", "证明材料", "证明文件", "材料要求", "资料要求"))
    if item_index < 0:
        item_index = 1 if order_index == 0 and len(cells) > 1 else 0
    score = cells[score_index] if 0 <= score_index < len(cells) else ""
    score_point = cells[standard_index] if 0 <= standard_index < len(cells) else ""
    scoring_item = cells[item_index] if 0 <= item_index < len(cells) else ""
    if not score:
        score = _extract_score_from_text(scoring_item) or _extract_score_from_text(score_point)
    return {
        "scoringItem": scoring_item,
        "score": score,
        "scorePoint": score_point or "；".join(cell for cell in cells if cell),
        "proofRequirement": cells[proof_index] if 0 <= proof_index < len(cells) else "",
    }


def _score_row_cells_by_exact_anchor(table: dict[str, Any], cells: list[str]) -> dict[str, str]:
    anchor_index = next((index for index, cell in enumerate(cells) if BUSINESS_SCORING_EXACT_KEYWORD in _clean(cell)), -1)
    headers = [str(header) for header in table.get("headers") or []]
    standard_index = _find_header_col(headers, SCORING_STANDARD_HEADERS)
    score_point = cells[standard_index] if 0 <= standard_index < len(cells) else ""
    item_index = -1
    for index in range(anchor_index + 1 if anchor_index >= 0 else 0, len(cells)):
        if index == standard_index:
            continue
        cell = _clean(cells[index])
        if not cell or BUSINESS_SCORING_EXACT_KEYWORD in cell:
            continue
        if "评分标准" in cell or "评审标准" in cell:
            continue
        item_index = index
        break
    if item_index < 0:
        item_index = _find_header_col(headers, SCORING_ITEM_HEADERS)
    scoring_item = cells[item_index] if 0 <= item_index < len(cells) else ""
    if not score_point:
        score_point = next(
            (
                cell
                for index, cell in enumerate(cells)
                if index != item_index and index != anchor_index and _text_has_concrete_score(cell)
            ),
            "；".join(cell for cell in cells if cell),
        )
    score = _extract_score_from_text(scoring_item) or _extract_score_from_text(score_point)
    return {
        "scoringItem": _strip_score_from_item(scoring_item),
        "score": score,
        "scorePoint": score_point,
        "proofRequirement": "",
    }


def _row_has_concrete_score(table: dict[str, Any], row: dict[str, Any]) -> bool:
    cells = [str(cell) for cell in row.get("cells") or []]
    row_text = " ".join(cells)
    headers = [str(header) for header in table.get("headers") or []]
    score_index = next((idx for idx, header in enumerate(headers) if any(keyword in header for keyword in SCORING_POINT_VALUE_HEADERS)), -1)
    standard_index = next((idx for idx, header in enumerate(headers) if any(keyword in header for keyword in SCORING_STANDARD_HEADERS)), -1)
    if score_index >= 0 and score_index < len(cells) and _score_value_cell_has_concrete_score(cells[score_index]):
        return True
    if standard_index >= 0 and standard_index < len(cells) and _text_has_concrete_score(cells[standard_index]):
        return True
    return _text_has_concrete_score(row_text)


def _score_row_from_table(table: dict[str, Any], row: dict[str, Any], order: int) -> dict[str, Any]:
    cells = [_clean(str(cell)) for cell in row.get("cells") or []]
    headers = [str(item) for item in table.get("headers") or []]
    evidence = "；".join(
        f"{headers[index]}：{cell}" if index < len(headers) and headers[index] else cell
        for index, cell in enumerate(cells)
        if str(cell).strip()
    )
    if _table_has_scoring_columns(table):
        parsed = _score_row_cells_by_headers(headers, cells)
    else:
        parsed = _score_row_cells_by_exact_anchor(table, cells)
    evidence_id = str(row.get("evidenceId") or "")
    return {
        "id": f"BUS-SCORE-{order:04d}",
        "order": order,
        "scoringItem": parsed["scoringItem"],
        "score": parsed["score"],
        "scorePoint": parsed["scorePoint"],
        "proofRequirement": parsed["proofRequirement"],
        "status": "found",
        "sourceFile": str(table.get("sourceFile") or ""),
        "sourceDocumentId": str(table.get("sourceDocumentId") or ""),
        "section": str(table.get("section") or ""),
        "evidence": evidence,
        "evidenceLocation": str(table.get("id") or ""),
        "evidenceIds": [evidence_id] if evidence_id else [],
        "scoringType": "business",
    }


def _normalize_scoring_clause(value: str) -> str:
    return str(value or "").replace("（", "(").replace("）", ")").replace(" ", "")


def _is_business_scoring_row_anchor(text: str) -> bool:
    return "商务" in text and any(keyword in text for keyword in ("评分", "评审", "分值"))


def _score_group_from_table_row(table: dict[str, Any], row: dict[str, Any], current_group: str = "") -> str:
    cells = [str(cell) for cell in row.get("cells") or []]
    text = _clean(" ".join(cells[:2]))
    clause_no = _normalize_scoring_clause(cells[0] if cells else "")
    if re.search(r"2\.2\.4\(?1\)?", clause_no) or BUSINESS_SCORING_EXACT_KEYWORD in text or _is_business_scoring_row_anchor(text):
        return "business"
    if re.search(r"2\.2\.4\(?2\)?", clause_no) or ("技术" in text and ("评分" in text or "评审" in text)):
        return "technical"
    if re.search(r"2\.2\.4\(?3\)?", clause_no) or (("报价" in text or "价格" in text) and ("评分" in text or "评审" in text)):
        return "price"
    if "符合性" in text and ("审查" in text or "评审" in text):
        return "compliance"
    return current_group


def _table_row_text(table: dict[str, Any], row: dict[str, Any]) -> str:
    cells = [str(cell) for cell in row.get("cells") or [] if str(cell).strip()]
    return " | ".join(cells)


def _candidate_from_scoring_row_block(table: dict[str, Any], rows: list[dict[str, Any]], block_index: int) -> dict[str, Any]:
    table_id = re.sub(r"[^A-Za-z0-9]+", "-", str(table.get("id") or "TABLE")).strip("-") or "TABLE"
    first_row = rows[0] if rows else {}
    row_texts = [_table_row_text(table, row) for row in rows if isinstance(row, dict) and _table_row_text(table, row)]
    evidence_ids = [str(row.get("evidenceId") or "") for row in rows if isinstance(row, dict) and str(row.get("evidenceId") or "")]
    return {
        "id": f"SCORING-ROW-BLOCK-REVIEW-{table_id}-{block_index}",
        "module": "scoringTableReview",
        "candidateType": "business_scoring_row_block_review",
        "content": "\n".join(row_texts),
        "sourceFile": str(table.get("sourceFile") or ""),
        "sourceDocumentId": str(table.get("sourceDocumentId") or ""),
        "section": str(table.get("section") or ""),
        "tableTitle": str(table.get("section") or ""),
        "tableHeaders": [str(item) for item in table.get("headers") or []],
        "evidence": "\n".join(row_texts),
        "evidenceLocation": str(first_row.get("evidenceLocation") or table.get("id") or ""),
        "evidenceIds": evidence_ids,
        "sourceText": _readable_source_text(table),
        "confidence": 0.6,
        "clauseNo": str((first_row.get("cells") or [""])[0] or ""),
        "scoreGroup": "business",
        "rowIndex": int(first_row.get("rowIndex") or block_index),
        "rowIndexes": [int(row.get("rowIndex") or 0) for row in rows if isinstance(row, dict)],
        "tableId": str(table.get("id") or ""),
        "hasConcreteScore": any(_row_has_concrete_score(table, row) for row in rows if isinstance(row, dict)),
    }


def _table_row_evidence_index(tables: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for table in tables:
        if not isinstance(table, dict):
            continue
        for row in table.get("rows") or []:
            if not isinstance(row, dict):
                continue
            evidence_id = str(row.get("evidenceId") or "")
            if not evidence_id:
                continue
            location = str(row.get("evidenceLocation") or "")
            if not location and ":" in evidence_id:
                location = evidence_id.split(":", 1)[1]
            evidence[evidence_id] = {
                "sourceDocumentId": str(table.get("sourceDocumentId") or ""),
                "sourceFile": str(table.get("sourceFile") or ""),
                "section": str(table.get("section") or ""),
                "text": _table_row_text(table, row),
                "location": location,
                "tableId": str(table.get("id") or ""),
                "rowIndex": str(row.get("rowIndex") or ""),
            }
    return evidence


def _apply_table_deterministic_scoring(deterministic: dict[str, list[dict[str, Any]]], tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ambiguous_candidates: list[dict[str, Any]] = []
    seen_evidence = {
        evidence_id
        for row in deterministic.get("business") or []
        for evidence_id in row.get("evidenceIds") or _record_evidence_ids(row)
        }
    if deterministic.get("business"):
        return ambiguous_candidates
    for table in tables:
        text = _table_text(table)
        if "评分" not in text and "评审" not in text and "分值" not in text:
            continue
        if _is_non_target_scoring_title(str(table.get("section") or "")):
            continue
        has_scoring_columns = _table_has_scoring_columns(table)
        has_exact_anchor = _table_has_exact_business_scoring_anchor(table)
        if not has_scoring_columns and not has_exact_anchor:
            continue
        table_type = str(table.get("tableType") or "")
        if has_exact_anchor and not has_scoring_columns:
            table_type = "business"
        current_group = "business" if table_type == "business" else ""
        if table_type == "business" and has_scoring_columns:
            for row in table.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                current_group = _score_group_from_table_row(table, row, current_group)
                if current_group != "business":
                    continue
                if not _row_has_concrete_score(table, row):
                    continue
                evidence_id = str(row.get("evidenceId") or "")
                if evidence_id in seen_evidence:
                    continue
                deterministic.setdefault("business", []).append(_score_row_from_table(table, row, len(deterministic.get("business") or []) + 1))
                seen_evidence.add(evidence_id)
            continue
        current_business_block: list[dict[str, Any]] = []
        block_index = 1
        for row in table.get("rows") or []:
            if not isinstance(row, dict):
                continue
            evidence_id = str(row.get("evidenceId") or "")
            if evidence_id in seen_evidence:
                continue
            current_group = _score_group_from_table_row(table, row, current_group)
            row_text = _table_row_text(table, row)
            if not row_text or not _row_has_concrete_score(table, row):
                continue
            if current_group == "business":
                current_business_block.append(row)
                continue
            if current_business_block:
                ambiguous_candidates.append(_candidate_from_scoring_row_block(table, current_business_block, block_index))
                block_index += 1
                current_business_block = []
        if current_business_block:
            ambiguous_candidates.append(_candidate_from_scoring_row_block(table, current_business_block, block_index))
    return ambiguous_candidates


def build_candidate_package(manifest: dict[str, Any], base_result: dict[str, Any]) -> dict[str, Any]:
    documents = [item for item in manifest.get("documents") or [] if isinstance(item, dict)]
    texts_by_id = _load_texts_by_id(documents)
    structured = base_result.get("structured") if isinstance(base_result.get("structured"), dict) else {}
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    scoring = structured.get("scoringCriteria") if isinstance(structured.get("scoringCriteria"), dict) else {}

    package_documents: list[dict[str, Any]] = []
    all_blocks: list[dict[str, Any]] = []
    all_sections: list[dict[str, Any]] = []
    all_tables: list[dict[str, Any]] = []
    candidates: dict[str, list[dict[str, Any]]] = {
        "projectFacts": [],
        "bidderInstructions": [],
        "qualification": [],
        "rejection": [],
        "scoring": [],
        "scoringTableReview": [],
    }

    for document in documents:
        document_id = str(document.get("id") or "")
        text = str(texts_by_id.get(document_id) or "")
        package_documents.append(
            {
                "id": document_id,
                "name": str(document.get("name") or document_id or "招标文件"),
                "sourcePath": str(document.get("sourcePath") or ""),
                "textPath": str(document.get("textPath") or ""),
                "textLength": len(text),
                "textSource": "textPath" if document.get("textPath") else "sourcePath",
            }
        )
        blocks, sections = _document_blocks(document, text)
        all_blocks.extend(blocks)
        all_sections.extend(sections)
        all_tables.extend(_collect_markdown_tables(document, text))
        all_tables.extend(_collect_docx_tables(document))
        raw_candidates = _raw_line_candidates(document, text)
        for key, values in raw_candidates.items():
            candidates[key].extend(values)

    for row in field_groups.get("commercialRejectionClauses") or []:
        candidates["rejection"].append(_candidate_from_result("rejection", row, "rejection_clause"))
    for row in field_groups.get("bidderInstructions") or []:
        candidates["bidderInstructions"].append(_candidate_from_result("bidderInstructions", row, "bidder_instruction", content_key="content"))
    for field in field_groups.get("projectBasics") or []:
        if str(field.get("status") or "") == "found":
            candidates["projectFacts"].append(_candidate_from_result("projectFacts", field, "project_fact", content_key="value"))
    for field in structured.get("projectFactFields") or []:
        if str(field.get("status") or "") == "found":
            candidates["projectFacts"].append(_candidate_from_result("projectFacts", field, "project_fact", content_key="value"))
    for row in scoring.get("business") or []:
        candidate = _candidate_from_result("scoring", row, "business_scoring", content_key="scorePoint")
        candidate["scoringType"] = "business"
        candidate["scoringItem"] = str(row.get("scoringItem") or "")
        candidate["score"] = str(row.get("score") or "")
        candidates["scoring"].append(candidate)

    deterministic_scoring = _deterministic_scoring_tables(base_result)
    candidates["scoringTableReview"] = _apply_table_deterministic_scoring(deterministic_scoring, all_tables)
    if not deterministic_scoring.get("business") and not candidates["scoringTableReview"]:
        candidates["scoringTableReview"] = [
            {
                **candidate,
                "module": "scoringTableReview",
                "candidateType": "business_scoring_line_review",
                "scoreGroup": "business",
                "hasConcreteScore": True,
            }
            for candidate in candidates.get("scoring") or []
            if "商务" in str(candidate.get("content") or "")
            and ("评分" in str(candidate.get("content") or "") or "评审" in str(candidate.get("content") or ""))
            and _text_has_concrete_score(str(candidate.get("content") or ""))
        ]

    evidence_index = {
        str(block["id"]): {
            "sourceDocumentId": str(block.get("sourceDocumentId") or ""),
            "sourceFile": str(block.get("sourceFile") or ""),
            "section": str(block.get("section") or ""),
            "text": str(block.get("text") or ""),
            "location": str(block.get("location") or ""),
        }
        for block in all_blocks
    }
    evidence_index.update(_table_row_evidence_index(all_tables))

    return {
        "schemaVersion": "bid-business-candidate-package-v1",
        "targetSkill": SKILL_NAME,
        "documents": package_documents,
        "sections": all_sections,
        "blocks": all_blocks,
        "tables": all_tables,
        "deterministicExtracts": {
            "projectBasics": [_record_with_evidence_ids(row) for row in field_groups.get("projectBasics") or []],
            "bidderInstructions": [_record_with_evidence_ids(row) for row in field_groups.get("bidderInstructions") or []],
            "scoringTables": deterministic_scoring,
        },
        "sectionSlices": {},
        "candidates": candidates,
        "evidenceIndex": evidence_index,
    }


def _candidate_context(candidate: dict[str, Any], candidate_package: dict[str, Any]) -> dict[str, Any]:
    evidence_index = candidate_package.get("evidenceIndex") if isinstance(candidate_package.get("evidenceIndex"), dict) else {}
    blocks = [block for block in candidate_package.get("blocks") or [] if isinstance(block, dict)]
    block_index = {str(block.get("id") or ""): index for index, block in enumerate(blocks)}
    evidence_ids = [str(item) for item in candidate.get("evidenceIds") or [] if str(item)]
    source_blocks = [
        evidence_index.get(evidence_id)
        for evidence_id in evidence_ids
        if isinstance(evidence_index.get(evidence_id), dict)
    ]
    before_text = ""
    after_text = ""
    for evidence_id in evidence_ids:
        index = block_index.get(evidence_id)
        if index is None:
            continue
        previous_blocks = [
            _clean(str(blocks[item].get("text") or ""))
            for item in range(max(0, index - 2), index)
            if _clean(str(blocks[item].get("text") or ""))
        ]
        next_blocks = [
            _clean(str(blocks[item].get("text") or ""))
            for item in range(index + 1, min(len(blocks), index + 3))
            if _clean(str(blocks[item].get("text") or ""))
        ]
        before_text = "\n".join(previous_blocks)
        after_text = "\n".join(next_blocks)
        break
    context = {
        "candidateId": str(candidate.get("id") or ""),
        "module": str(candidate.get("module") or ""),
        "candidateType": str(candidate.get("candidateType") or ""),
        "id": str(candidate.get("id") or ""),
        "content": str(candidate.get("content") or ""),
        "evidence": str(candidate.get("evidence") or candidate.get("content") or ""),
        "evidenceIds": evidence_ids,
        "sourceFile": str(candidate.get("sourceFile") or ""),
        "sourceDocumentId": str(candidate.get("sourceDocumentId") or ""),
        "sectionPath": str(candidate.get("section") or (source_blocks[0].get("section") if source_blocks else "")),
        "sourceText": str(candidate.get("sourceText") or _readable_source_text(candidate)),
        "location": str(candidate.get("evidenceLocation") or ""),
        "sourceType": "table" if candidate.get("tableHeaders") else "body",
        "beforeText": before_text,
        "afterText": after_text,
        "tableTitle": str(candidate.get("tableTitle") or ""),
        "tableHeaders": [str(item) for item in candidate.get("tableHeaders") or []],
        "neighborItems": [item for item in (before_text, after_text) if item],
        "confidence": candidate.get("confidence"),
        "scoringType": str(candidate.get("scoringType") or ""),
        "scoreGroup": str(candidate.get("scoreGroup") or ""),
        "hasConcreteScore": bool(candidate.get("hasConcreteScore")),
        "clauseNo": str(candidate.get("clauseNo") or ""),
        "rowIndex": candidate.get("rowIndex"),
        "rowIndexes": [int(item) for item in candidate.get("rowIndexes") or [] if str(item).strip()],
        "scoringItem": str(candidate.get("scoringItem") or ""),
        "score": str(candidate.get("score") or ""),
    }
    if candidate.get("candidateType") == "qualification_section_slice":
        context["lines"] = [
            copy.deepcopy(line)
            for line in candidate.get("lines") or []
            if isinstance(line, dict)
        ]
        context["startLine"] = candidate.get("startLine")
        context["endLine"] = candidate.get("endLine")
    return context


def _estimated_candidate_size(candidate: dict[str, Any]) -> int:
    return len(json.dumps(candidate, ensure_ascii=False))


def _chunk_review_candidates(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not candidates:
        return []
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size = 0
    for candidate in candidates:
        candidate_size = _estimated_candidate_size(candidate)
        if current and (len(current) >= MAX_TASK_CANDIDATES or current_size + candidate_size > MAX_TASK_CONTENT_CHARS):
            chunks.append(current)
            current = []
            current_size = 0
        current.append(candidate)
        current_size += candidate_size
    if current:
        chunks.append(current)
    return chunks


def _ai_review_modules_from_tasks(tasks: list[dict[str, Any]]) -> list[str]:
    modules: list[str] = []
    for task in tasks:
        task_name = str(task.get("task") or "")
        module = SEMANTIC_REVIEW_MODULES.get(task_name, task_name)
        if module and module not in modules:
            modules.append(module)
    return modules


def _skipped_ai_modules(ai_review_modules: list[str]) -> list[str]:
    possible = ["qualification", "commercialRejectionClauses", "scoring_table_review"]
    active = set(ai_review_modules)
    return [module for module in possible if module not in active]


def _make_task(
    task_name: str,
    candidate_package: dict[str, Any],
    *,
    task_id: str | None = None,
    part_index: int = 1,
    part_count: int = 1,
    candidates: list[dict[str, Any]] | None = None,
    decision_path: str = "",
) -> dict[str, Any]:
    module_key, instruction = TASK_INSTRUCTIONS[task_name]
    task_candidates = candidates if candidates is not None else candidate_package.get("candidates", {}).get(module_key) or []
    if task_name == "qualification_review":
        return {
            "schemaVersion": "bid-business-ai-task-v1",
            "task": task_name,
            "taskId": task_id or task_name,
            "module": module_key,
            "partIndex": part_index,
            "partCount": part_count,
            "decisionPath": decision_path,
            "candidatePackageSchema": candidate_package.get("schemaVersion"),
            "instruction": (
                "从 candidates 中的投标人资格要求整节切片拆出多个资格要求 item。"
                "只输出真正影响投标人资格的条件；目录、第二章 1.4 引用句、资格审查资料、评分项、材料复印件说明、废标条款不输出。"
                "副标题、父标题、范围提示行不得作为 qualificationItems；例如“通用资格条件”“专用资格条件”“业绩要求”“资格能力要求”“标段一（需同时满足）”只作为上下文。"
                "同一条实质要求在不同标段下重复出现时，应按不同 applicableScope 分别输出；项目级条款不得继承上一标段范围。"
                "资格任务不得使用 decision-all 或 decision-set 让脚本自动拆分，必须用 qualification-item 逐条写入 AI 原始拆分内容。"
            ),
            "decisionContract": {
                "schemaVersion": "bid-business-ai-decision-v1",
                "task": task_name,
                "taskId": task_id or task_name,
                "adapter": "opencode-agent",
                "qualificationItems": [
                    {
                        "content": "要求内容；由 AI 基于切片行证据拆分，不要照搬整节。",
                        "applicableScope": "适用范围；无法细分时写全部标段。",
                        "sourceText": "来源路径；建议使用 lines[].sourceText，例如 3. 投标人资格要求 > 3.1 通用资格条件 > 3.1.1 ...",
                        "evidenceIds": ["只能引用 candidates[].evidenceIds 或 lines[].evidenceId。"],
                    }
                ],
                "rejectedEvidenceIds": ["可选；切片中明确拒绝采纳的证据行。"],
                "reason": "整体拆分说明。",
            },
            "constraints": [
                "qualificationItems[].content、applicableScope、sourceText、evidenceIds 均必填。",
                "evidenceIds 只能来自本任务 candidates[].evidenceIds 或 lines[].evidenceId。",
                "sourceText 必须是可读章节路径，不要只写 L 行号。",
                "不要输出 final fieldGroups、id、order、status、sourceFile/sourceDocumentId 等脚本合成字段。",
                "同一要求跨父子行时，可以同时引用父行和子行 evidenceIds。",
                "副标题和适用范围提示只能放入 sourceText 或 applicableScope，不得放入 content。",
                "content 保留 AI 拆分出的原始条款内容；脚本不会兜底拆分或修复 content。",
            ],
            "candidates": task_candidates,
        }
    return {
        "schemaVersion": "bid-business-ai-task-v1",
        "task": task_name,
        "taskId": task_id or task_name,
        "module": module_key,
        "partIndex": part_index,
        "partCount": part_count,
        "decisionPath": decision_path,
        "candidatePackageSchema": candidate_package.get("schemaVersion"),
        "instruction": instruction,
        "decisionContract": {
            bucket: [
                {
                    "candidateId": "只能引用本任务 candidates[].id",
                    "decision": bucket,
                    "fieldType": "字段类型，例如 qualification_requirement",
                    "content": "使用候选 content 原文或摘要",
                    "applicableScope": "适用范围，无法细分时写全部标段",
                    "sourceText": "可读来源文本或章节路径",
                    "reason": "裁判理由",
                    "evidenceIds": ["只能引用该候选 evidenceIds"],
                }
            ]
            for bucket in DECISION_BUCKETS
        },
        "constraints": [
            "基于候选项中的 evidenceIds 作出判断。",
            "直接提交 accepted、rejected 或 needsReview 裁判项。",
            "资格要求、商务废标项、商务评分细则分别独立裁判。",
            "最终 JSON 由脚本合成，AI 只提交结构化决策。",
        ],
        "candidates": task_candidates,
    }


def write_ai_tasks(candidate_package: dict[str, Any], tasks_dir: Path, decisions_dir: Path, review_plan_path: Path) -> dict[str, Any]:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    for task_name in TASK_NAMES:
        module_key = TASK_MODULE_KEYS[task_name]
        raw_candidates = candidate_package.get("candidates", {}).get(module_key) or []
        review_candidates = [_candidate_context(candidate, candidate_package) for candidate in raw_candidates if isinstance(candidate, dict)]
        if not review_candidates:
            continue
        chunks = _chunk_review_candidates(review_candidates)
        part_count = len(chunks)
        task_dir = tasks_dir / task_name
        for part_index, chunk in enumerate(chunks, start=1):
            file_name = f"part-{part_index:03d}.json"
            task_path = task_dir / file_name
            decision_path = decisions_dir / task_name / file_name
            relative_task_path = task_path.relative_to(tasks_dir.parent).as_posix()
            relative_decision_path = decision_path.relative_to(tasks_dir.parent).as_posix()
            task_id = f"{task_name}/part-{part_index:03d}"
            task_payload = _make_task(
                task_name,
                candidate_package,
                task_id=task_id,
                part_index=part_index,
                part_count=part_count,
                candidates=chunk,
                decision_path=relative_decision_path,
            )
            task_path.parent.mkdir(parents=True, exist_ok=True)
            decision_path.parent.mkdir(parents=True, exist_ok=True)
            task_path.write_text(json.dumps(task_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tasks.append(
                {
                    "taskId": task_id,
                    "task": task_name,
                    "module": module_key,
                    "partIndex": part_index,
                    "partCount": part_count,
                    "candidateCount": len(chunk),
                    "taskPath": relative_task_path,
                    "decisionPath": relative_decision_path,
                    "required": True,
                }
            )
    ai_review_modules = _ai_review_modules_from_tasks(tasks)
    review_plan = {
        "schemaVersion": "bid-business-review-plan-v1",
        "targetSkill": SKILL_NAME,
        "candidatePackagePath": str((tasks_dir.parent / "candidate_package.json").resolve()) if (tasks_dir.parent / "candidate_package.json").exists() else "candidate_package.json",
        "aiTasksDir": str(tasks_dir),
        "aiDecisionsDir": str(decisions_dir),
        "status": "pending",
        "taskCount": len(tasks),
        "requiredTaskCount": sum(1 for task in tasks if task.get("required")),
        "deterministicModules": list(DETERMINISTIC_MODULES),
        "aiReviewModules": ai_review_modules,
        "skippedAiModules": _skipped_ai_modules(ai_review_modules),
        "tasks": tasks,
        "completion": {
            "required": "所有 required=true 的 decisionPath 均存在且通过脚本合约校验后才能 finalize。",
        },
    }
    review_plan_path.parent.mkdir(parents=True, exist_ok=True)
    review_plan_path.write_text(json.dumps(review_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return review_plan


def _decision_item(candidate: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        "candidateId": str(candidate.get("candidateId") or candidate.get("id") or ""),
        "decision": status,
        "fieldType": str(candidate.get("candidateType") or "review_candidate"),
        "content": str(candidate.get("content") or ""),
        "applicableScope": str(candidate.get("applicableScope") or "全部标段"),
        "sourceText": str(candidate.get("sourceText") or candidate.get("sectionPath") or candidate.get("sourceFile") or "招标文件"),
        "reason": reason,
        "evidenceIds": [str(item) for item in candidate.get("evidenceIds") or []],
    }


def _qualification_line_item_source(line: dict[str, Any], parent_line: dict[str, Any] | None = None) -> str:
    source_text = str(line.get("sourceText") or "").strip()
    if source_text:
        return source_text
    parent_source = str((parent_line or {}).get("sourceText") or "").strip()
    return parent_source or str(line.get("sourcePath") or "投标人资格要求")


def _is_empty_qualification_line(text: str) -> bool:
    normalized = _clean(text).strip(" ：:；;。/\\")
    return not normalized or normalized in {"", "/"}


def _is_qualification_parent_line(text: str) -> bool:
    cleaned = _normalize_qualification_content(text)
    if not cleaned:
        return True
    return any(
        token in cleaned
        for token in (
            "投标人资格要求",
            "通用资格条件",
            "专用资格条件",
            "业绩要求",
            "资质要求",
            "财务要求",
            "信誉要求",
            "其他要求",
            "应具备下列条件",
            "具备下列条件",
        )
    ) and not any(cue in cleaned for cue in ("不接受", "不得", "须提供", "必须取得", "应是", "具有", "具备提供"))


def _looks_like_qualification_item_text(text: str) -> bool:
    cleaned = _normalize_qualification_content(text)
    if len(cleaned) < 4 or _is_empty_qualification_line(cleaned):
        return False
    if _is_qualification_scope_hint_text(cleaned):
        return False
    if any(keyword in cleaned for keyword in ("目录", "资格审查资料", "复印件", "扫描件", "评分", "得分", "见投标人须知前附表")):
        return False
    if _is_qualification_parent_line(text):
        return False
    return any(cue in cleaned for cue in QUALIFICATION_ITEM_CUES)


def _qualification_items_from_section_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [line for line in candidate.get("lines") or [] if isinstance(line, dict)]
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    parent_line: dict[str, Any] | None = None
    current_scope = str(candidate.get("applicableScope") or "全部标段")
    for line in lines:
        text = _clean(str(line.get("text") or ""))
        if not text:
            continue
        if _is_qualification_scope_hint_text(text):
            current_scope = _normalize_applicable_scope(text)
            parent_line = line
            continue
        if _is_qualification_parent_line(text):
            parent_line = line
            continue
        if not _looks_like_qualification_item_text(text):
            continue
        content = _normalize_qualification_content(text)
        if not content or content in seen:
            continue
        seen.add(content)
        evidence_ids = [str(line.get("evidenceId") or "")] if line.get("evidenceId") else []
        if parent_line and parent_line.get("evidenceId") and str(parent_line.get("evidenceId")) not in evidence_ids:
            evidence_ids.insert(0, str(parent_line.get("evidenceId")))
        items.append(
            {
                "content": content,
                "applicableScope": "全部标段" if str(line.get("applicableScopeHint") or "").strip() == text else str(line.get("applicableScopeHint") or current_scope or "全部标段"),
                "sourceText": _qualification_line_item_source(line, parent_line),
                "evidenceIds": evidence_ids,
            }
        )
    return items


def _qualification_decision_from_task(task_payload: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for candidate in task_payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        for item in _qualification_items_from_section_candidate(candidate):
            items.append(item)
            evidence_ids.update(str(value) for value in item.get("evidenceIds") or [] if str(value))
    return {
        "schemaVersion": "bid-business-ai-decision-v1",
        "task": "qualification_review",
        "taskId": str(task_payload.get("taskId") or "qualification_review"),
        "adapter": "offline-evidence-bound-semantic-review",
        "qualificationItems": items,
        "rejectedEvidenceIds": [],
        "reason": "离线启发式从投标人资格要求整节切片拆分，仅用于调试和 fallback。",
        "evidenceIds": sorted(evidence_ids),
    }


def _classify_candidate(task_name: str, candidate: dict[str, Any]) -> tuple[str, str]:
    content = _clean(str(candidate.get("content") or ""))
    if task_name == "qualification_review":
        return ("accepted", "属于投标人资格条件。") if _looks_like_qualification_requirement(content) else ("rejected", "不是投标人资格条件，或属于材料说明、评分、目录、引用句。")
    if task_name == "rejection_clause_review":
        if any(token in content for token in NON_BID_REJECTION_CONTEXT):
            return "rejected", "属于异议投诉、合同流程或保证金退还等非投标有效性事项。"
        return ("accepted", "属于影响投标有效性的商务废标或否决条款。") if any(token in content for token in REJECTION_KEYWORDS) else ("rejected", "不属于商务废标或否决条款。")
    if task_name == "scoring_table_review":
        score_group = str(candidate.get("scoreGroup") or "").strip().lower()
        clause_no = _normalize_scoring_clause(str(candidate.get("clauseNo") or ""))
        has_concrete_score = bool(candidate.get("hasConcreteScore")) or _text_has_concrete_score(content)
        is_business_scoring = score_group == "business" or re.search(r"2\.2\.4\(?1\)?", clause_no) or _is_business_scoring_row_anchor(content)
        if is_business_scoring and has_concrete_score:
            return "accepted", "属于商务评分细则，且候选中有具体分值。"
        if is_business_scoring:
            return "rejected", "未看到具体分值，不能作为商务评分细则。"
        return "rejected", "不是商务评分细则。"
    return "rejected", "不属于当前审查任务。"


def _task_paths_from_review_plan(review_plan: dict[str, Any], base_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for task in review_plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        path = Path(str(task.get("taskPath") or ""))
        paths.append(path if path.is_absolute() else base_dir / path)
    return paths


def run_offline_ai_adapter(tasks_dir: Path, decisions_dir: Path, review_plan: dict[str, Any] | None = None) -> list[Path]:
    written: list[Path] = []
    task_paths = _task_paths_from_review_plan(review_plan, tasks_dir.parent) if isinstance(review_plan, dict) else sorted(tasks_dir.glob("*/*.json"))
    for task_path in task_paths:
        if not task_path.is_file():
            continue
        task_payload = json.loads(task_path.read_text(encoding="utf-8"))
        task_name = str(task_payload.get("task") or task_path.parent.name)
        if task_name == "qualification_review":
            decision = _qualification_decision_from_task(task_payload)
            decision_path = decisions_dir / task_name / task_path.name
            decision_path.parent.mkdir(parents=True, exist_ok=True)
            decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(decision_path)
            continue
        decision = {
            "schemaVersion": "bid-business-ai-decision-v1",
            "task": task_name,
            "taskId": str(task_payload.get("taskId") or task_name),
            "adapter": "offline-evidence-bound-semantic-review",
            "accepted": [],
            "rejected": [],
            "needsReview": [],
            "reason": "离线启发式审查，仅用于调试和 fallback。",
            "evidenceIds": [],
        }
        for candidate in task_payload.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            status, reason = _classify_candidate(task_name, candidate)
            item = _decision_item(candidate, status, reason)
            decision[status].append(item)
            decision["evidenceIds"].extend(item["evidenceIds"])
        decision["evidenceIds"] = sorted(set(decision["evidenceIds"]))
        decision_path = decisions_dir / task_name / task_path.name
        decision_path.parent.mkdir(parents=True, exist_ok=True)
        decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(decision_path)
    return written


def _external_decision_paths(manifest: dict[str, Any]) -> list[Path]:
    values: list[Any] = []
    for key in ("aiDecisionPaths", "aiDecisions", "aiDecisionFiles"):
        raw = manifest.get(key)
        if isinstance(raw, list):
            values.extend(raw)
    source_dir = manifest.get("aiDecisionSourceDir")
    if source_dir:
        directory = Path(str(source_dir))
        if directory.is_dir():
            values.extend(sorted(directory.glob("*.json")))
    return [Path(str(value)) for value in values if str(value or "").strip()]


def stage_external_ai_decisions(manifest: dict[str, Any], decisions_dir: Path, review_plan: dict[str, Any] | None = None) -> list[Path]:
    staged: list[Path] = []
    task_refs = [item for item in (review_plan or {}).get("tasks") or [] if isinstance(item, dict)]
    task_refs_by_name: dict[str, list[dict[str, Any]]] = {}
    for task_ref in task_refs:
        task_refs_by_name.setdefault(str(task_ref.get("task") or ""), []).append(task_ref)
    for source_path in _external_decision_paths(manifest):
        if not source_path.is_file():
            continue
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        task_name = str(payload.get("task") or source_path.stem)
        if source_path.stem in task_refs_by_name:
            task_name = source_path.stem
        refs = task_refs_by_name.get(task_name) or []
        if refs and "/" not in str(payload.get("taskId") or ""):
            for ref in refs:
                target = decisions_dir.parent / str(ref.get("decisionPath") or "")
                target.parent.mkdir(parents=True, exist_ok=True)
                clone = copy.deepcopy(payload)
                clone["task"] = task_name
                clone["taskId"] = str(ref.get("taskId") or "")
                target.write_text(json.dumps(clone, ensure_ascii=False, indent=2), encoding="utf-8")
                staged.append(target)
            continue
        target = decisions_dir / task_name / source_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        staged.append(target)
    return staged


def _candidate_index_for_task(candidate_package: dict[str, Any], task_name: str) -> dict[str, dict[str, Any]]:
    module_key = TASK_MODULE_KEYS.get(task_name, "")
    candidates = candidate_package.get("candidates") if isinstance(candidate_package.get("candidates"), dict) else {}
    return {str(item.get("id") or ""): item for item in candidates.get(module_key) or [] if isinstance(item, dict)}


def _candidate_evidence_for_task(candidate_package: dict[str, Any], task_name: str) -> set[str]:
    module_key = TASK_MODULE_KEYS.get(task_name, "")
    candidates = candidate_package.get("candidates") if isinstance(candidate_package.get("candidates"), dict) else {}
    evidence_ids: set[str] = set()
    for candidate in candidates.get(module_key) or []:
        if not isinstance(candidate, dict):
            continue
        evidence_ids.update(_record_evidence_ids(candidate))
        for line in candidate.get("lines") or []:
            if isinstance(line, dict) and str(line.get("evidenceId") or "").strip():
                evidence_ids.add(str(line.get("evidenceId")))
    return evidence_ids


def _decision_issue(task: str, bucket: str, code: str, message: str, *, candidate_id: str = "", evidence_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "task": task,
        "bucket": bucket,
        "code": code,
        "candidateId": candidate_id,
        "evidenceIds": evidence_ids or [],
        "message": message,
    }


def _normalize_qualification_item_decision(normalized: dict[str, Any], *, task_name: str, candidate_package: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    allowed_evidence = _candidate_evidence_for_task(candidate_package, task_name)
    raw_items = normalized.get("qualificationItems")
    if not isinstance(raw_items, list):
        issues.append(_decision_issue(task_name, "qualificationItems", "invalid_bucket", "qualificationItems 必须是数组。"))
        raw_items = []
    valid_items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            issues.append(_decision_issue(task_name, "qualificationItems", "invalid_decision_item", "qualificationItems 项必须是对象。"))
            continue
        item = copy.deepcopy(raw_item)
        missing_fields = [field for field in ("content", "applicableScope", "sourceText", "evidenceIds") if field not in item or item.get(field) in (None, "", [])]
        if missing_fields:
            issues.append(_decision_issue(task_name, "qualificationItems", "missing_required_decision_fields", "qualificationItems 缺少必填字段：" + ",".join(missing_fields)))
            continue
        item_evidence = [str(value) for value in item.get("evidenceIds") or [] if str(value).strip()]
        item_evidence_set = set(item_evidence)
        if not item_evidence_set or not item_evidence_set <= allowed_evidence:
            issues.append(
                _decision_issue(
                    task_name,
                    "qualificationItems",
                    "invalid_evidence_ids",
                    "qualificationItems[].evidenceIds 必须来自资格整节切片候选。",
                    evidence_ids=sorted(item_evidence_set),
                )
            )
            continue
        source_text = str(item.get("sourceText") or "").strip()
        if not _has_chinese(source_text) or re.fullmatch(r"[BL]\d+(?:/R\d+)?", source_text):
            issues.append(_decision_issue(task_name, "qualificationItems", "invalid_source_text", "qualificationItems[].sourceText 必须是可读章节路径。", evidence_ids=item_evidence))
            continue
        item["content"] = str(item.get("content") or "").strip()
        item["applicableScope"] = str(item.get("applicableScope") or "全部标段").strip() or "全部标段"
        item["sourceText"] = source_text
        item["evidenceIds"] = item_evidence
        valid_items.append(item)
    rejected_evidence = {str(value) for value in normalized.get("rejectedEvidenceIds") or [] if str(value).strip()}
    if rejected_evidence and not rejected_evidence <= allowed_evidence:
        issues.append(
            _decision_issue(
                task_name,
                "rejectedEvidenceIds",
                "invalid_evidence_ids",
                "rejectedEvidenceIds 必须来自资格整节切片候选。",
                evidence_ids=sorted(rejected_evidence),
            )
        )
    normalized["qualificationItems"] = valid_items
    normalized["rejectedEvidenceIds"] = sorted(rejected_evidence)
    normalized["accepted"] = []
    normalized["rejected"] = []
    normalized["needsReview"] = []
    normalized["evidenceIds"] = sorted({value for item in valid_items for value in item.get("evidenceIds") or []} | rejected_evidence)
    return normalized


def normalize_ai_decision(decision: dict[str, Any], *, task_name: str, candidate_package: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized = copy.deepcopy(decision) if isinstance(decision, dict) else {}
    issues: list[dict[str, Any]] = []
    if normalized.get("schemaVersion") != "bid-business-ai-decision-v1":
        issues.append(_decision_issue(task_name, "", "invalid_schema_version", "AI 决策 schemaVersion 必须为 bid-business-ai-decision-v1。"))
    unexpected_keys = sorted(set(normalized) - ALLOWED_AI_DECISION_KEYS)
    if unexpected_keys:
        issues.append(_decision_issue(task_name, "", "unexpected_top_level_fields", "AI 决策应只包含裁判字段，当前多出：" + ",".join(unexpected_keys)))
    if task_name not in TASK_MODULE_KEYS:
        issues.append(_decision_issue(task_name, "", "unknown_task", "AI 决策 task 不属于当前商务解析任务。"))
        return normalized, issues
    if task_name == "qualification_review" and "qualificationItems" in normalized:
        normalized["task"] = task_name
        return _normalize_qualification_item_decision(normalized, task_name=task_name, candidate_package=candidate_package, issues=issues), issues
    candidate_index = _candidate_index_for_task(candidate_package, task_name)
    normalized["task"] = task_name
    normalized.setdefault("accepted", [])
    normalized.setdefault("rejected", [])
    normalized.setdefault("needsReview", [])
    for bucket in DECISION_BUCKETS:
        if not isinstance(normalized.get(bucket), list):
            issues.append(_decision_issue(task_name, bucket, "invalid_bucket", f"{bucket} 必须是数组。"))
            normalized[bucket] = []
            continue
        valid_items: list[dict[str, Any]] = []
        for raw_item in normalized.get(bucket) or []:
            if not isinstance(raw_item, dict):
                issues.append(_decision_issue(task_name, bucket, "invalid_decision_item", "决策项必须是对象。"))
                continue
            item = copy.deepcopy(raw_item)
            candidate_id = str(item.get("candidateId") or "").strip()
            missing_fields = [field for field in REQUIRED_DECISION_ITEM_FIELDS if field not in item or item.get(field) in (None, "")]
            if missing_fields:
                issues.append(_decision_issue(task_name, bucket, "missing_required_decision_fields", "决策项缺少必填字段：" + ",".join(missing_fields), candidate_id=candidate_id))
                continue
            if candidate_id not in candidate_index:
                issues.append(_decision_issue(task_name, bucket, "unknown_candidate_id", "candidateId 不属于本任务候选。", candidate_id=candidate_id))
                continue
            candidate_evidence = set(_record_evidence_ids(candidate_index[candidate_id]))
            item_evidence = {str(value) for value in item.get("evidenceIds") or [] if str(value)}
            if not item_evidence or not item_evidence <= candidate_evidence:
                issues.append(
                    _decision_issue(
                        task_name,
                        bucket,
                        "invalid_evidence_ids",
                        "evidenceIds 必须来自对应候选。",
                        candidate_id=candidate_id,
                        evidence_ids=sorted(item_evidence),
                    )
                )
                continue
            item["decision"] = bucket
            valid_items.append(item)
        normalized[bucket] = valid_items
    normalized["evidenceIds"] = sorted(
        {
            str(value)
            for bucket in DECISION_BUCKETS
            for item in normalized.get(bucket) or []
            for value in item.get("evidenceIds") or []
        }
    )
    return normalized, issues


def _decision_file_refs(review_plan: dict[str, Any], base_dir: Path) -> list[tuple[str, str, Path, bool]]:
    refs: list[tuple[str, str, Path, bool]] = []
    for item in review_plan.get("tasks") or []:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("taskId") or "")
        task_name = str(item.get("task") or task_id)
        path = Path(str(item.get("decisionPath") or ""))
        refs.append((task_id, task_name, path if path.is_absolute() else base_dir / path, bool(item.get("required", True))))
    return refs


def _merge_module_decisions(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts:
        return {}
    merged = {
        "schemaVersion": "bid-business-ai-decision-v1",
        "task": str(parts[0].get("task") or ""),
        "adapter": "merged-opencode-agent",
        "accepted": [],
        "rejected": [],
        "needsReview": [],
        "qualificationItems": [],
        "rejectedEvidenceIds": [],
        "reason": "merged task parts",
        "evidenceIds": [],
    }
    adapters = []
    for part in parts:
        adapters.append(str(part.get("adapter") or ""))
        for bucket in DECISION_BUCKETS:
            merged[bucket].extend(copy.deepcopy(part.get(bucket) or []))
        merged["qualificationItems"].extend(copy.deepcopy(part.get("qualificationItems") or []))
        merged["rejectedEvidenceIds"].extend(str(item) for item in part.get("rejectedEvidenceIds") or [] if str(item))
        merged["evidenceIds"].extend(str(item) for item in part.get("evidenceIds") or [])
    merged["adapter"] = adapters[0] if len(set(adapters)) == 1 else "mixed"
    merged["evidenceIds"] = sorted(set(merged["evidenceIds"]))
    merged["rejectedEvidenceIds"] = sorted(set(merged["rejectedEvidenceIds"]))
    return merged


def _invalid_decision_placeholder(task_name: str, task_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": "bid-business-ai-decision-v1",
        "task": task_name,
        "taskId": task_id,
        "adapter": "invalid-ai-decision-contract",
        "accepted": [],
        "rejected": [],
        "needsReview": [],
        "reason": "AI 决策文件未通过契约校验。",
        "evidenceIds": [],
    }


def _load_decisions(decisions_dir: Path, candidate_package: dict[str, Any], review_plan: dict[str, Any] | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    parts_by_task: dict[str, list[dict[str, Any]]] = {}
    decisions_by_part: dict[str, dict[str, Any]] = {}
    refs = _decision_file_refs(review_plan or {}, decisions_dir.parent)
    for task_id, task_name, path, required in refs:
        if not path.is_file():
            if required:
                issues.append(_decision_issue(task_id, "", "missing_decision_file", "缺少 required AI 决策文件。"))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            issues.append(_decision_issue(task_id, "", "invalid_json", f"AI 决策文件不是合法 JSON：{exc}"))
            continue
        normalized, part_issues = normalize_ai_decision(payload, task_name=task_name, candidate_package=candidate_package)
        if part_issues:
            issues.extend(part_issues)
            parts_by_task.setdefault(task_name, []).append(_invalid_decision_placeholder(task_name, task_id))
            continue
        normalized["taskId"] = str(normalized.get("taskId") or task_id)
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        parts_by_task.setdefault(task_name, []).append(normalized)
        decisions_by_part[task_id] = normalized
    decisions = {task_name: _merge_module_decisions(parts) for task_name, parts in parts_by_task.items()}
    return decisions, {"issues": issues, "decisionsByPart": decisions_by_part}


def _accepted_candidate_ids(decision: dict[str, Any]) -> set[str]:
    return {str(item.get("candidateId") or "") for item in decision.get("accepted") or [] if isinstance(item, dict)}


def _accepted_evidence_ids(decision: dict[str, Any]) -> set[str]:
    return {str(value) for item in decision.get("accepted") or [] if isinstance(item, dict) for value in item.get("evidenceIds") or []}


def _accepted_candidate_id_to_reason(decision: dict[str, Any]) -> dict[str, str]:
    return {str(item.get("candidateId") or ""): str(item.get("reason") or "") for item in decision.get("accepted") or [] if isinstance(item, dict)}


def _candidate_ids_by_evidence(candidates: list[dict[str, Any]]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "")
        for evidence_id in _record_evidence_ids(candidate):
            mapping.setdefault(evidence_id, set()).add(candidate_id)
    return mapping


def _record_is_accepted(record: dict[str, Any], accepted_ids: set[str], accepted_evidence: set[str], evidence_to_candidates: dict[str, set[str]]) -> bool:
    record_id = str(record.get("id") or "")
    if record_id and record_id in accepted_ids:
        return True
    for evidence_id in _record_evidence_ids(record):
        if evidence_id in accepted_evidence and evidence_to_candidates.get(evidence_id, set()) & accepted_ids:
            return True
    return False


def _has_review_decision(decision: dict[str, Any]) -> bool:
    return bool(decision) and str(decision.get("schemaVersion") or "") == "bid-business-ai-decision-v1"


def _filter_records_by_decision(records: list[dict[str, Any]], candidates: list[dict[str, Any]], decision: dict[str, Any]) -> list[dict[str, Any]]:
    if not _has_review_decision(decision):
        return [_with_evidence_ids(row) for row in records if isinstance(row, dict)]
    accepted_ids = _accepted_candidate_ids(decision)
    accepted_evidence = _accepted_evidence_ids(decision)
    evidence_to_candidates = _candidate_ids_by_evidence(candidates)
    return [
        _with_evidence_ids(row)
        for row in records
        if isinstance(row, dict) and _record_is_accepted(row, accepted_ids, accepted_evidence, evidence_to_candidates)
    ]


def _candidate_by_id(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(candidate.get("id") or ""): candidate for candidate in candidates if isinstance(candidate, dict)}


def _qualification_rows_from_accepted_candidates(records: list[dict[str, Any]], candidates: list[dict[str, Any]], decision: dict[str, Any]) -> list[dict[str, Any]]:
    if not _has_review_decision(decision):
        return records
    by_id = _candidate_by_id(candidates)
    reasons = _accepted_candidate_id_to_reason(decision)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate_id in _accepted_candidate_ids(decision):
        candidate = by_id.get(candidate_id)
        if not candidate:
            continue
        content = _normalize_qualification_content(str(candidate.get("content") or ""))
        if not content or content in seen:
            continue
        seen.add(content)
        rows.append(
            {
                "id": f"QUAL-AI-{len(rows) + 1:04d}",
                "order": len(rows) + 1,
                "content": content,
                "applicableScope": str(candidate.get("applicableScope") or "全部标段"),
                "sourceText": str(candidate.get("sourceText") or _readable_source_text(candidate)),
                "sourceFile": str(candidate.get("sourceFile") or ""),
                "sourceDocumentId": str(candidate.get("sourceDocumentId") or ""),
                "section": str(candidate.get("section") or ""),
                "evidence": str(candidate.get("evidence") or candidate.get("content") or ""),
                "evidenceLocation": str(candidate.get("evidenceLocation") or ""),
                "evidenceIds": _record_evidence_ids(candidate),
                "reviewReason": reasons.get(candidate_id, ""),
                "status": "found",
            }
        )
    return rows


def _qualification_candidate_meta_by_evidence(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for evidence_id in _record_evidence_ids(candidate):
            meta.setdefault(
                evidence_id,
                {
                    "sourceFile": str(candidate.get("sourceFile") or ""),
                    "sourceDocumentId": str(candidate.get("sourceDocumentId") or ""),
                    "section": str(candidate.get("section") or ""),
                    "evidenceLocation": str(candidate.get("evidenceLocation") or ""),
                    "evidence": str(candidate.get("evidence") or candidate.get("content") or ""),
                },
            )
        for line in candidate.get("lines") or []:
            if not isinstance(line, dict):
                continue
            evidence_id = str(line.get("evidenceId") or "")
            if not evidence_id:
                continue
            meta[evidence_id] = {
                "sourceFile": str(candidate.get("sourceFile") or ""),
                "sourceDocumentId": str(candidate.get("sourceDocumentId") or ""),
                "section": str(candidate.get("section") or ""),
                "evidenceLocation": str(line.get("evidenceLocation") or ""),
                "evidence": str(line.get("text") or ""),
            }
    return meta


def _qualification_rows_from_decision_items(candidates: list[dict[str, Any]], decision: dict[str, Any]) -> list[dict[str, Any]]:
    if not _has_review_decision(decision) or not isinstance(decision.get("qualificationItems"), list):
        return []
    meta_by_evidence = _qualification_candidate_meta_by_evidence(candidates)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in decision.get("qualificationItems") or []:
        if not isinstance(item, dict):
            continue
        content = _clean(str(item.get("content") or ""))
        if not content or content in seen:
            continue
        seen.add(content)
        evidence_ids = [str(value) for value in item.get("evidenceIds") or [] if str(value)]
        first_meta = next((meta_by_evidence[evidence_id] for evidence_id in evidence_ids if evidence_id in meta_by_evidence), {})
        rows.append(
            {
                "id": f"QUAL-AI-{len(rows) + 1:04d}",
                "order": len(rows) + 1,
                "content": content,
                "applicableScope": str(item.get("applicableScope") or "全部标段"),
                "sourceText": str(item.get("sourceText") or ""),
                "sourceFile": str(first_meta.get("sourceFile") or ""),
                "sourceDocumentId": str(first_meta.get("sourceDocumentId") or ""),
                "section": str(first_meta.get("section") or ""),
                "evidence": str(first_meta.get("evidence") or content),
                "evidenceLocation": str(first_meta.get("evidenceLocation") or ""),
                "evidenceIds": evidence_ids,
                "reviewReason": str(decision.get("reason") or ""),
                "status": "found",
            }
        )
    return rows


def _is_business_scoring_candidate(candidate: dict[str, Any]) -> bool:
    score_group = str(candidate.get("scoreGroup") or "").strip().lower()
    clause_no = _normalize_scoring_clause(str(candidate.get("clauseNo") or ""))
    content = str(candidate.get("content") or "")
    has_concrete_score = bool(candidate.get("hasConcreteScore")) or _text_has_concrete_score(content)
    return (score_group == "business" or bool(re.search(r"2\.2\.4\(?1\)?", clause_no)) or _is_business_scoring_row_anchor(content)) and has_concrete_score


def _accepted_scoring_field_types(decision: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("candidateId") or ""): str(item.get("fieldType") or "").strip().lower()
        for item in decision.get("accepted") or []
        if isinstance(item, dict)
    }


def _append_scoring_from_accepted_rows(scoring: dict[str, list[dict[str, Any]]], candidate_package: dict[str, Any], decision: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not _has_review_decision(decision):
        return scoring
    accepted_ids = _accepted_candidate_ids(decision)
    accepted_field_types = _accepted_scoring_field_types(decision)
    candidates = candidate_package.get("candidates") if isinstance(candidate_package.get("candidates"), dict) else {}
    accepted_rows = [
        candidate
        for candidate in candidates.get("scoringTableReview") or []
        if str(candidate.get("id") or "") in accepted_ids
        and (_is_business_scoring_candidate(candidate) or accepted_field_types.get(str(candidate.get("id") or "")) == "business")
    ]
    if not accepted_rows:
        return scoring
    existing = {evidence_id for row in scoring.get("business") or [] for evidence_id in _record_evidence_ids(row)}
    for row_candidate in accepted_rows:
        candidate_evidence_ids = set(_record_evidence_ids(row_candidate))
        for table in candidate_package.get("tables") or []:
            if not isinstance(table, dict):
                continue
            for row in table.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                evidence_id = str(row.get("evidenceId") or "")
                if evidence_id not in candidate_evidence_ids:
                    continue
                if evidence_id in existing:
                    continue
                if not _row_has_concrete_score(table, row):
                    continue
                scoring.setdefault("business", []).append(_score_row_from_table(table, row, len(scoring.get("business") or []) + 1))
                existing.add(evidence_id)
    return scoring


def _filter_scoring(scoring: dict[str, Any], scoring_candidates: list[dict[str, Any]], decision: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    filtered = {"business": []}
    rows = [row for row in scoring.get("business") or [] if isinstance(row, dict)] if isinstance(scoring, dict) else []
    if not _has_review_decision(decision):
        filtered["business"] = [_with_evidence_ids(row) for row in rows]
        return filtered
    accepted_ids = _accepted_candidate_ids(decision)
    accepted_evidence = _accepted_evidence_ids(decision)
    evidence_to_candidates = _candidate_ids_by_evidence(scoring_candidates)
    filtered["business"] = [
        _with_evidence_ids(row)
        for row in rows
        if _record_is_accepted(row, accepted_ids, accepted_evidence, evidence_to_candidates)
    ]
    return filtered


def _has_chinese(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value or ""))


def _validation_check(name: str, passed: bool, message: str, count: int = 0) -> dict[str, Any]:
    return {"name": name, "status": "passed" if passed else "failed", "message": message, "count": count}


def validate_final_result(result: dict[str, Any], candidate_package: dict[str, Any], decision_validation: dict[str, Any] | None = None) -> dict[str, Any]:
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    scoring = structured.get("scoringCriteria") if isinstance(structured.get("scoringCriteria"), dict) else {}
    evidence_index = candidate_package.get("evidenceIndex") if isinstance(candidate_package.get("evidenceIndex"), dict) else {}
    final_records: list[dict[str, Any]] = []
    for key in ("projectBasics", "qualificationRequirements", "bidderInstructions", "commercialRejectionClauses"):
        values = field_groups.get(key) or []
        final_records.extend([item for item in values if isinstance(item, dict)])
    final_records.extend([item for item in scoring.get("business") or [] if isinstance(item, dict)])
    final_records.extend([item for item in structured.get("projectFactFields") or [] if isinstance(item, dict)])
    missing_evidence = [
        record
        for record in final_records
        if (record.get("status") in {None, "", "found", "derived"} or record.get("content") or record.get("value"))
        and not any(evidence_id in evidence_index for evidence_id in _record_evidence_ids(record))
        and str(record.get("evidence") or "").strip()
    ]
    qualification_rows = field_groups.get("qualificationRequirements") or []
    qualification_pollution = [
        row
        for row in qualification_rows
        if any(token in str(row.get("content") or "") for token in ("评分", "得分", "目录", "资格审查资料", "复印件", "扫描件"))
    ]
    rejection_rows = field_groups.get("commercialRejectionClauses") or []
    rejection_pollution = [
        row
        for row in rejection_rows
        if any(token in str(row.get("content") or "") for token in NON_BID_REJECTION_CONTEXT)
    ]
    source_text_bad = [
        row
        for row in qualification_rows
        if not _has_chinese(str(row.get("sourceText") or "")) or re.fullmatch(r"[BL]\d+(?:/R\d+)?", str(row.get("sourceText") or ""))
    ]
    scope_bad = [row for row in qualification_rows if not str(row.get("applicableScope") or "").strip()]
    unexpected_fields = [key for key in field_groups if key not in ALLOWED_FIELD_GROUP_KEYS]
    unexpected_structured = [key for key in structured if key not in ALLOWED_STRUCTURED_KEYS]
    scoring_non_business = [key for key in scoring if key not in ALLOWED_SCORING_KEYS and scoring.get(key)]
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
    unexpected_dates = [key for key in project_dates if key not in ALLOWED_PROJECT_DATE_KEYS]
    checks = [
        _validation_check("evidence_references", not missing_evidence, "所有有来源的最终记录均可回到候选包 evidenceIndex。", len(final_records)),
        _validation_check("qualification_boundaries", not qualification_pollution, "资格要求未混入评分、目录或材料说明。", len(qualification_rows)),
        _validation_check("qualification_scope", not scope_bad, "资格要求均保留适用范围。", len(qualification_rows)),
        _validation_check("rejection_boundaries", not rejection_pollution, "商务废标项未混入异议投诉或合同流程。", len(rejection_rows)),
        _validation_check("scoring_boundaries", not scoring_non_business, "最终评分结果只包含商务评分细则。", len(scoring.get("business") or [])),
        _validation_check("target_scope_only", not unexpected_fields and not unexpected_structured and not unexpected_dates, "最终结果只包含目标结构。", len(unexpected_fields) + len(unexpected_structured) + len(unexpected_dates)),
        _validation_check("source_text_readable", not source_text_bad, "资格来源为中文路径式来源，不是裸行号。", len(qualification_rows)),
    ]
    decision_issues = []
    missing_decision_issues = []
    decisions_by_part = {}
    if isinstance(decision_validation, dict):
        raw_decision_issues = [item for item in decision_validation.get("issues") or [] if isinstance(item, dict)]
        decisions_by_part = decision_validation.get("decisionsByPart") if isinstance(decision_validation.get("decisionsByPart"), dict) else {}
        decision_issues = [item for item in raw_decision_issues if item.get("code") != "missing_decision_file"]
        missing_decision_issues = [item for item in raw_decision_issues if item.get("code") == "missing_decision_file"]
    checks.append(_validation_check("ai_decision_coverage", not missing_decision_issues, "review_plan 中 required AI 决策文件均已产出。", len(missing_decision_issues)))
    checks.append(_validation_check("ai_decision_contract", not decision_issues, "AI 决策仅包含结构化裁判，且 accepted 项均引用候选包内 candidateId 与 evidenceIds。", len(decision_issues)))
    missing_decision_tasks = sorted([str(item.get("task") or "") for item in missing_decision_issues if str(item.get("task") or "")])
    required_decision_task_count = len(missing_decision_tasks) + len(decisions_by_part)
    present_decision_task_count = len(decisions_by_part)
    return {
        "schemaVersion": "bid-business-validation-report-v1",
        "targetSkill": SKILL_NAME,
        "status": "passed" if all(check["status"] == "passed" for check in checks) else "failed",
        "checks": checks,
        "aiDecisionCoverage": {
            "status": "failed" if missing_decision_tasks else "passed",
            "requiredDecisionTaskCount": required_decision_task_count,
            "presentDecisionTaskCount": present_decision_task_count,
            "missingDecisionTasks": missing_decision_tasks,
        },
        "aiDecisionIssues": decision_issues,
        "missingDecisionIssues": missing_decision_issues,
    }


def _rebuild_field_groups(
    base_result: dict[str, Any],
    manifest: dict[str, Any],
    candidate_package: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    _ = manifest
    structured = copy.deepcopy(base_result.get("structured") if isinstance(base_result.get("structured"), dict) else {})
    field_groups = copy.deepcopy(structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {})
    candidates = candidate_package.get("candidates") if isinstance(candidate_package.get("candidates"), dict) else {}
    qualification_decision = decisions.get("qualification_review") or {}
    rejection_decision = decisions.get("rejection_clause_review") or {}
    scoring_decision = decisions.get("scoring_table_review") or {}
    deterministic = candidate_package.get("deterministicExtracts") if isinstance(candidate_package.get("deterministicExtracts"), dict) else {}
    field_groups = {
        "projectBasics": [
            _with_evidence_ids(row)
            for row in deterministic.get("projectBasics") or field_groups.get("projectBasics") or []
            if isinstance(row, dict)
        ],
        "qualificationRequirements": [],
        "bidderInstructions": [
            _with_evidence_ids(row)
            for row in deterministic.get("bidderInstructions") or field_groups.get("bidderInstructions") or []
            if isinstance(row, dict)
        ],
        "commercialRejectionClauses": [],
    }
    field_groups["qualificationRequirements"] = _qualification_rows_from_decision_items(
        candidates.get("qualification") or [],
        qualification_decision,
    )
    if not field_groups["qualificationRequirements"]:
        filtered_qualification_rows = _filter_records_by_decision(
            structured.get("fieldGroups", {}).get("qualificationRequirements") if isinstance(structured.get("fieldGroups"), dict) else [],
            candidates.get("qualification") or [],
            qualification_decision,
        )
        field_groups["qualificationRequirements"] = _qualification_rows_from_accepted_candidates(
            filtered_qualification_rows,
            candidates.get("qualification") or [],
            qualification_decision,
        )
    for index, row in enumerate(field_groups["qualificationRequirements"], start=1):
        row["order"] = index
        row["sourceText"] = str(row.get("sourceText") or _qualification_source_text(source_file=str(row.get("sourceFile") or "招标文件"), section=str(row.get("section") or "投标人资格要求")))
    field_groups["commercialRejectionClauses"] = _filter_records_by_decision(
        structured.get("fieldGroups", {}).get("commercialRejectionClauses") if isinstance(structured.get("fieldGroups"), dict) else [],
        candidates.get("rejection") or [],
        rejection_decision,
    )
    field_groups["commercialRejectionClauses"] = [
        _with_commercial_rejection_display_fields(row)
        for row in field_groups["commercialRejectionClauses"]
    ]
    deterministic_scoring = deterministic.get("scoringTables") if isinstance(deterministic.get("scoringTables"), dict) else {}
    scoring = {
        "business": [
            _with_evidence_ids(row)
            for row in deterministic_scoring.get("business") or []
            if isinstance(row, dict)
        ]
    }
    if not scoring["business"]:
        scoring = _filter_scoring(structured.get("scoringCriteria") or {}, candidates.get("scoring") or [], scoring_decision)
    scoring = _append_scoring_from_accepted_rows(scoring, candidate_package, scoring_decision)
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
    project_fact_fields = _build_business_project_fact_fields(field_groups, project_dates)
    return field_groups, scoring, project_fact_fields


def finalize_business_result(
    manifest: dict[str, Any],
    base_result: dict[str, Any],
    candidate_package: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
    paths: dict[str, Path],
    decision_validation: dict[str, Any] | None = None,
    review_provenance: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_structured = base_result.get("structured") if isinstance(base_result.get("structured"), dict) else {}
    field_groups, scoring, project_fact_fields = _rebuild_field_groups(base_result, manifest, candidate_package, decisions)
    coverage = _build_business_coverage(field_groups, scoring)
    appendices = _business_template_appendices_from_manifest(manifest)
    provenance = review_provenance or {}
    semantic_review_mode = str(provenance.get("semanticReviewMode") or "offline-fallback")
    offline_adapter_used = bool(provenance.get("offlineAdapterUsed"))
    structured = {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "workflow": {
            "stage": "fallback",
            "layers": ["candidate", "review", "verify", "synthesize"],
            "candidatePackagePath": str(paths["candidatePackage"]),
            "reviewPlanPath": str(paths["reviewPlan"]),
            "aiTasksDir": str(paths["aiTasksDir"]),
            "aiDecisionsDir": str(paths["aiDecisionsDir"]),
            "validationReportPath": str(paths["validationReport"]),
            "semanticReviewMode": semantic_review_mode,
            "aiReviewTrusted": False,
            "offlineAdapterUsed": offline_adapter_used,
            "deterministicModules": list(provenance.get("deterministicModules") or DETERMINISTIC_MODULES),
            "aiReviewModules": list(provenance.get("aiReviewModules") or []),
            "skippedAiModules": list(provenance.get("skippedAiModules") or []),
            "trustedDecisionCount": int(provenance.get("trustedDecisionCount") or 0),
            "offlineDecisionCount": int(provenance.get("offlineDecisionCount") or 0),
            "trustedTasks": list(provenance.get("trustedTasks") or []),
            "offlineTasks": list(provenance.get("offlineTasks") or []),
            "missingTrustedTasks": list(provenance.get("missingTrustedTasks") or []),
            "missingDecisionTasks": list(provenance.get("missingDecisionTasks") or []),
            "invalidDecisionFiles": list(provenance.get("invalidDecisionFiles") or []),
            "requiredDecisionTaskCount": int(provenance.get("requiredDecisionTaskCount") or 0),
            "presentDecisionTaskCount": int(provenance.get("presentDecisionTaskCount") or 0),
        },
        "sourceDocuments": copy.deepcopy(base_structured.get("sourceDocuments") or []),
        "scoringCriteria": scoring,
        "fieldGroups": field_groups,
        "requirementPresence": {},
        "coverage": coverage,
        "projectDates": {"endDate": str((base_structured.get("projectDates") or {}).get("endDate") or "")},
        "appendices": appendices,
        "commitmentLetters": [],
        "commitmentClues": [],
        "projectFactFields": project_fact_fields,
        "categoryCounts": {},
    }
    result = {"items": copy.deepcopy(base_result.get("items") or []), "structured": structured}
    validation_report = validate_final_result(result, candidate_package, decision_validation)
    validation_passed = validation_report["status"] == "passed"
    ai_review_trusted = bool(provenance.get("aiReviewTrusted")) and validation_passed
    result["structured"]["workflow"]["validationStatus"] = validation_report["status"]
    result["structured"]["workflow"]["aiReviewTrusted"] = ai_review_trusted
    result["structured"]["workflow"]["stage"] = "finalized" if ai_review_trusted else "fallback"
    return result, validation_report


def _prepared_business_result(base_result: dict[str, Any], candidate_package: dict[str, Any], paths: dict[str, Path], review_plan: dict[str, Any]) -> dict[str, Any]:
    base_structured = base_result.get("structured") if isinstance(base_result.get("structured"), dict) else {}
    structured = {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "workflow": {
            "stage": "prepared",
            "layers": ["candidate", "review", "verify", "synthesize"],
            "candidatePackagePath": str(paths["candidatePackage"]),
            "reviewPlanPath": str(paths["reviewPlan"]),
            "aiTasksDir": str(paths["aiTasksDir"]),
            "aiDecisionsDir": str(paths["aiDecisionsDir"]),
            "validationReportPath": str(paths["validationReport"]),
            "semanticReviewMode": "opencode-agent",
            "aiReviewTrusted": False,
            "deterministicModules": list(review_plan.get("deterministicModules") or DETERMINISTIC_MODULES),
            "aiReviewModules": list(review_plan.get("aiReviewModules") or []),
            "skippedAiModules": list(review_plan.get("skippedAiModules") or []),
            "requiredDecisionTaskCount": int(review_plan.get("requiredTaskCount") or review_plan.get("taskCount") or 0),
            "presentDecisionTaskCount": 0,
            "missingDecisionTasks": [
                str(task.get("taskId") or "")
                for task in review_plan.get("tasks") or []
                if isinstance(task, dict) and task.get("required", True)
            ],
            "candidateCounts": {
                key: len(values or [])
                for key, values in (candidate_package.get("candidates") or {}).items()
                if isinstance(values, list)
            },
        },
        "sourceDocuments": copy.deepcopy(base_structured.get("sourceDocuments") or []),
        "appendices": copy.deepcopy(base_structured.get("appendices") or []),
        "commitmentLetters": copy.deepcopy(base_structured.get("commitmentLetters") or []),
        "commitmentClues": copy.deepcopy(base_structured.get("commitmentClues") or []),
    }
    return {"items": copy.deepcopy(base_result.get("items") or []), "structured": structured}


def _review_provenance(review_plan: dict[str, Any], decisions: dict[str, dict[str, Any]], decision_validation: dict[str, Any] | None = None) -> dict[str, Any]:
    task_refs = [item for item in review_plan.get("tasks") or [] if isinstance(item, dict)]
    required_task_ids = {
        str(item.get("taskId") or "")
        for item in task_refs
        if item.get("required", True) and str(item.get("taskId") or "")
    }
    decisions_by_part = {}
    if isinstance(decision_validation, dict) and isinstance(decision_validation.get("decisionsByPart"), dict):
        decisions_by_part = decision_validation.get("decisionsByPart") or {}
    decision_ids = set(decisions_by_part)
    offline_ids = {
        task_id
        for task_id, decision in decisions_by_part.items()
        if str(decision.get("adapter") or "") == "offline-evidence-bound-semantic-review"
    }
    trusted_ids = decision_ids - offline_ids
    decision_issues = []
    if isinstance(decision_validation, dict):
        decision_issues = [
            item
            for item in decision_validation.get("issues") or []
            if isinstance(item, dict) and item.get("code") != "missing_decision_file"
        ]
    missing_decisions = sorted(required_task_ids - decision_ids)
    missing_trusted = sorted(required_task_ids - trusted_ids)
    ai_review_trusted = bool(required_task_ids) and not missing_decisions and not missing_trusted and not offline_ids and not decision_issues
    if ai_review_trusted:
        semantic_review_mode = "opencode-agent"
    elif trusted_ids:
        semantic_review_mode = "mixed-ai-fallback"
    elif offline_ids:
        semantic_review_mode = "offline-fallback"
    else:
        semantic_review_mode = "opencode-agent"
    return {
        "semanticReviewMode": semantic_review_mode,
        "aiReviewTrusted": ai_review_trusted,
        "offlineAdapterUsed": bool(offline_ids),
        "deterministicModules": list(review_plan.get("deterministicModules") or DETERMINISTIC_MODULES),
        "aiReviewModules": list(review_plan.get("aiReviewModules") or []),
        "skippedAiModules": list(review_plan.get("skippedAiModules") or []),
        "trustedDecisionCount": len(trusted_ids),
        "offlineDecisionCount": len(offline_ids),
        "trustedTasks": sorted(trusted_ids),
        "offlineTasks": sorted(offline_ids),
        "missingTrustedTasks": missing_trusted,
        "missingDecisionTasks": missing_decisions,
        "requiredDecisionTaskCount": len(required_task_ids),
        "presentDecisionTaskCount": len(decision_ids),
        "invalidDecisionFiles": [str(item.get("task") or "") for item in decision_issues if isinstance(item, dict)],
    }


def _normalize_workflow_stage(manifest: dict[str, Any], workflow_stage: str | None) -> str:
    raw = str(
        workflow_stage
        or manifest.get("businessWorkflowStage")
        or manifest.get("workflowStage")
        or manifest.get("businessParserMode")
        or manifest.get("mode")
        or "prepare"
    ).strip().lower()
    if raw in {"", "prepare", "candidate", "candidates", "prepare-only", "candidate-only"}:
        return "prepare"
    if raw in {"finalize", "finalise", "synthesize", "synthesise"}:
        return "finalize"
    if raw in {"offline-fallback", "fallback", "debug-fallback"}:
        return "offline-fallback"
    return raw


def build_business_workflow_result(
    manifest: dict[str, Any],
    *,
    manifest_path: Path | None = None,
    mode: str = "opencode-skill",
    workflow_stage: str | None = None,
) -> dict[str, Any]:
    paths = _artifact_paths(manifest, manifest_path)
    paths["outputDir"].mkdir(parents=True, exist_ok=True)
    stage = _normalize_workflow_stage(manifest, workflow_stage)
    base_result = build_business_result(manifest, mode=f"{mode}-recall")
    candidate_package = build_candidate_package(manifest, base_result)
    paths["candidatePackage"].parent.mkdir(parents=True, exist_ok=True)
    paths["candidatePackage"].write_text(json.dumps(candidate_package, ensure_ascii=False, indent=2), encoding="utf-8")
    review_plan = write_ai_tasks(candidate_package, paths["aiTasksDir"], paths["aiDecisionsDir"], paths["reviewPlan"])
    if stage == "prepare":
        return _prepared_business_result(base_result, candidate_package, paths, review_plan)
    stage_external_ai_decisions(manifest, paths["aiDecisionsDir"], review_plan)
    if stage == "offline-fallback":
        run_offline_ai_adapter(paths["aiTasksDir"], paths["aiDecisionsDir"], review_plan)
    decisions, decision_validation = _load_decisions(paths["aiDecisionsDir"], candidate_package, review_plan)
    provenance = _review_provenance(review_plan, decisions, decision_validation)
    result, validation_report = finalize_business_result(
        manifest,
        base_result,
        candidate_package,
        decisions,
        paths,
        decision_validation,
        provenance,
    )
    paths["validationReport"].write_text(json.dumps(validation_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
