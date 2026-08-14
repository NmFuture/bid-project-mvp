"""附表提取与物化：文本/导航/docx 附表提取、docx 写入与源文件切片、商务模板判定。

来源：parsing-01 拆分，自 app/services/parsing.py 逐字搬迁，实现与行为不变；
符号经 parsing.py 门面 re-export，外部仍按 `app.services.parsing.<符号>` 访问。
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.config import settings
from app.services.agent_engine.factory import AgentEngineFactory
from app.services.parse_business_fields import (
    MARKDOWN_TABLE_LINE_PATTERN,
    _business_project_name_from_structured,
    _business_tenderer_name_from_structured,
    _is_markdown_separator_row,
    _parse_markdown_table_row,
)
from app.services.parse_common import (
    _raise_if_parse_cancelled,
    _run_coroutine_blocking,
    _run_with_progress_heartbeat,
    parsed_appendix_path,
)
from app.services.parse_extract import WORD_NAMESPACE
from app.services.parse_profiles import (
    BUSINESS_PARSE_PROFILE,
    TECHNICAL_PARSE_PROFILE,
    ParseProfile,
    resolve_parse_profile,
)

DOCX_SLICE_STORED_XML_THRESHOLD_BYTES = 5 * 1024 * 1024


def _business_text_lines(text: str) -> list[tuple[int, str]]:
    return [
        (line_number, line.strip())
        for line_number, line in enumerate(str(text or "").splitlines(), start=1)
        if line.strip()
    ]


def _looks_like_toc_or_directory_line(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lstrip("#").strip())
    if not normalized:
        return False
    if any(token in normalized for token in ("……", "....", "----")):
        return True
    if re.search(r"(?:\s|\.{2,}|…{2,})\d{1,4}$", normalized):
        return True
    return False


def _looks_like_business_template_body_sentence(text: str) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    if not normalized:
        return False
    if any(mark in normalized for mark in ("。", "；", ";")):
        return True
    return any(
        token in normalized
        for token in (
            "我方",
            "本公司",
            "投标人承诺",
            "按招标文件",
            "按照招标文件",
            "愿意",
            "承担",
            "提交",
            "提供",
        )
    )


def _looks_like_business_template_stop_heading(text: str, profile: ParseProfile) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    if not normalized:
        return False
    if _is_scoring_appendix_heading(normalized):
        return True
    if profile.key == "business" and _is_business_major_section_heading(normalized):
        return True
    if _is_relevant_appendix_heading(normalized, profile):
        return True
    if profile.key == "business" and _looks_like_business_attachment_template_title(normalized, in_template_section=True):
        return True
    return bool(
        re.match(r"^(?:第[一二三四五六七八九十百千0-9]+[章节条]|[一二三四五六七八九十]+[、.．]|[（(][一二三四五六七八九十0-9]+[）)])", normalized)
        and any(
            token in normalized
            for token in (
                "投标函", "法定代表人", "授权", "廉洁", "专用章", "投标价格", "开标价格",
                "商务偏差", "货物规格", "供货范围", "保证金", "履约", "附件",
                "资格", "证明", "其他内容", "承诺函", "承诺书",
            )
        )
    )


def _appendix_has_material_content(rows: list[list[str]], content_blocks: list[dict[str, Any]]) -> bool:
    if rows:
        return True
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "paragraph" and len(str(block.get("text") or "").strip()) >= 6:
            return True
        if block.get("type") == "table" and isinstance(block.get("rows"), list) and block.get("rows"):
            return True
    return False


def _business_template_should_materialize(metadata: dict[str, Any], rows: list[list[str]], content_blocks: list[dict[str, Any]]) -> bool:
    if not _appendix_has_material_content(rows, content_blocks):
        return False
    quality = str(metadata.get("extractionQuality") or "").strip()
    issues = metadata.get("qualityIssues") if isinstance(metadata.get("qualityIssues"), list) else []
    if quality in {"title_only", "probably_incomplete"}:
        return False
    if any("未识别到明显表格、签章栏或待填写占位" in str(issue) for issue in issues):
        return False
    return True


def _business_text_template_appendix_title(line: str, profile: ParseProfile) -> str:
    title = str(line or "").strip().lstrip("#").strip()
    if _is_relevant_appendix_heading(title, profile):
        return title.strip(" #") or "商务附件模板"
    match = re.match(
        r"^(?:[一二三四五六七八九十0-9]+[、.．]\s*|[（(][一二三四五六七八九十0-9]+[）)]\s*)?"
        r"(?P<title>(?:投标函|法定代表人(?:（单位负责人）)?身份证明|法定代表人授权书|法定代表人授权委托书|授权委托书|投标人廉洁自律承诺书|廉洁承诺书|投标专用章效力说明|投标价格表|开标价格表|商务偏差表|货物规格表|供货范围表|投标保证金|履约保证函格式承诺书|履约承诺书|否决项响应|投标人需要说明的其他内容|其他说明|附件\s*[0-9一二三四五六七八九十]+)[^：:。；;]*)",
        title,
    )
    return (match.group("title").strip() if match else title) or "商务附件模板"


def _extract_text_business_appendices(
    project_id: str,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    *,
    start_index: int = 0,
    profile: ParseProfile = BUSINESS_PARSE_PROFILE,
) -> list[dict[str, Any]]:
    if profile.key != "business":
        return []
    appendices: list[dict[str, Any]] = []
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() in {".md", ".docx"}:
            continue
        lines = _business_text_lines(texts_by_id.get(document_id, ""))
        in_template_section = False
        template_section_title = ""
        for index, (line_number, line) in enumerate(lines):
            if _is_business_template_section_heading(line):
                in_template_section = True
                template_section_title = line
                continue
            if in_template_section and _is_business_major_section_heading(line):
                in_template_section = False
                template_section_title = ""
            if not _business_template_title_allowed(line, in_template_section=in_template_section):
                continue
            title = _business_text_template_appendix_title(line, profile)
            content_blocks: list[dict[str, Any]] = []
            next_boundary_index = len(lines)
            for lookahead_index, (_, next_line) in enumerate(lines[index + 1:], start=index + 1):
                if _is_business_template_section_heading(next_line):
                    next_boundary_index = lookahead_index
                    break
                if _is_business_major_section_heading(next_line):
                    next_boundary_index = lookahead_index
                    break
                if _looks_like_business_template_stop_heading(next_line, profile):
                    next_boundary_index = lookahead_index
                    break
                content_blocks.append({"type": "paragraph", "text": next_line})
                if len(content_blocks) >= 80:
                    next_boundary_index = lookahead_index + 1
                    break
            metadata = _business_template_metadata(
                title=title,
                source_file=source_file,
                evidence=line,
                evidence_location=f"L{line_number}",
                template_section_title=template_section_title,
                source_start=_business_template_source_start(template_section_title, f"L{line_number}", line),
                source_end=_business_template_source_end_from_lines([text for _, text in lines], next_boundary_index),
                rows=[],
                content_blocks=content_blocks,
                extraction_mode="text_slice",
            )
            if not _business_template_should_materialize(metadata, [], content_blocks):
                continue
            appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
            appendices.append(
                materialize_appendix_docx(
                    project_id,
                    {
                        "id": appendix_id,
                        "title": title,
                        "status": "generated",
                        "rows": [],
                        "contentBlocks": content_blocks,
                        "rowCount": 0,
                        "docxPath": "",
                        **metadata,
                    },
                    profile=profile,
                )
            )
    return appendices


def _is_text_appendix_toc_artifact(line: str, next_line: str = "") -> bool:
    text = str(line or "").strip()
    following = str(next_line or "").strip()
    if re.search(r"(?:\.{2,}|…{2,}).*(?:\d{1,4}|错误！未定义书签。?)$", text):
        return True
    if "错误！未定义书签" in text:
        return True
    if re.search(r"\D\d{2,4}$", text):
        return True
    return bool(following and re.search(r"(?:\.{2,}|…{2,}).*(?:\d{1,4}|错误！未定义书签。?)$", following))


def _is_text_appendix_noise_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return True
    if re.fullmatch(r"\d{1,4}", text):
        return True
    return text.startswith("中国华能集团有限公司") or text in {"技术规范"}


def _plain_text_table_cells(line: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(line or "").strip())
    normalized = re.sub(r"序\s+号", "序号", normalized)
    return [cell for cell in normalized.split(" ") if cell]


def _is_plain_text_table_header(cells: list[str]) -> bool:
    return len(cells) >= 2 and any(cell == "序号" for cell in cells[:2])


def _is_plain_text_table_data_row(cells: list[str], expected_columns: int) -> bool:
    if len(cells) < 2:
        return False
    first = cells[0].strip()
    if re.fullmatch(r"(?:\d+|[一二三四五六七八九十]+|[A-Za-z]\d*)[).、．]?", first):
        return True
    return expected_columns > 0 and len(cells) >= max(2, expected_columns - 1)


def _text_appendix_content_blocks(lines: list[tuple[int, str]]) -> tuple[list[dict[str, Any]], list[list[str]]]:
    content_blocks: list[dict[str, Any]] = []
    current_table: list[list[str]] = []
    primary_rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal current_table, primary_rows
        if not current_table:
            return
        if not primary_rows:
            primary_rows = current_table
        content_blocks.append({"type": "table", "rows": current_table})
        current_table = []

    for _, line in lines:
        if _is_text_appendix_noise_line(line):
            continue
        cells = _plain_text_table_cells(line)
        if not current_table:
            if _is_plain_text_table_header(cells):
                current_table = [cells]
            else:
                content_blocks.append({"type": "paragraph", "text": line.strip()})
            continue

        expected_columns = len(current_table[0])
        if _is_plain_text_table_data_row(cells, expected_columns):
            if expected_columns and len(cells) < expected_columns:
                cells = [*cells, *([""] * (expected_columns - len(cells)))]
            current_table.append(cells)
            continue

        flush_table()
        content_blocks.append({"type": "paragraph", "text": line.strip()})

    flush_table()
    return content_blocks, primary_rows


def _extract_text_appendices(
    project_id: str,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    *,
    start_index: int = 0,
    profile: ParseProfile = TECHNICAL_PARSE_PROFILE,
    skip_document_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if profile.key == "business":
        return []
    appendices: list[dict[str, Any]] = []
    max_content_lines = 200
    skipped = skip_document_ids or set()
    for document in documents:
        document_id = str(document.get("id") or "")
        if document_id in skipped:
            continue
        source_file = str(document.get("name") or document_id or "招标文件")
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".pdf":
            continue
        lines = [
            (line_number, line.strip())
            for line_number, line in enumerate(texts_by_id.get(document_id, "").splitlines(), start=1)
            if line.strip()
        ]
        index = 0
        while index < len(lines):
            line_number, line = lines[index]
            next_line = lines[index + 1][1] if index + 1 < len(lines) else ""
            if (
                not _is_relevant_appendix_heading(line, profile)
                or _is_text_appendix_toc_artifact(line, next_line)
                or _is_scoring_appendix_heading(line)
            ):
                index += 1
                continue

            next_heading = len(lines)
            for lookahead in range(index + 1, len(lines)):
                next_line = lines[lookahead][1]
                following_line = lines[lookahead + 1][1] if lookahead + 1 < len(lines) else ""
                if _is_relevant_appendix_heading(next_line, profile) and not _is_text_appendix_toc_artifact(next_line, following_line):
                    next_heading = lookahead
                    break

            content_end = min(next_heading, index + 1 + max_content_lines)
            content_blocks, rows = _text_appendix_content_blocks(lines[index + 1:content_end])
            if not content_blocks and not rows:
                index = max(index + 1, next_heading)
                continue

            appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
            title = line.strip(" #")
            appendices.append(
                materialize_appendix_docx(
                    project_id,
                    {
                        "id": appendix_id,
                        "title": title,
                        "status": "generated",
                        "sourceFile": source_file,
                        "sourceDocumentId": document_id,
                        "evidence": line,
                        "evidenceLocation": f"L{line_number}",
                        "rows": rows,
                        "contentBlocks": content_blocks,
                        "rowCount": len(rows),
                        "docxPath": "",
                        "extractionMode": "pdf_text_slice",
                    },
                    profile=profile,
                )
            )
            index = max(index + 1, next_heading)
    return appendices


def _document_nav_page_no(block: dict[str, Any]) -> int:
    try:
        page_no = int(block.get("pageNo") or 0)
    except (TypeError, ValueError):
        return 0
    return page_no if page_no > 0 else 0


def _document_nav_table_rows(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    rows: list[list[str]] = []
    for row in value:
        if isinstance(row, list):
            rows.append([str(cell if cell is not None else "") for cell in row])
    return rows


def _document_nav_table_cells(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cells: list[dict[str, Any]] = []
    for cell in value:
        if not isinstance(cell, dict):
            continue
        try:
            row_start = int(cell.get("rowStart") if cell.get("rowStart") is not None else cell.get("start_row_offset_idx"))
            row_end = int(cell.get("rowEnd") if cell.get("rowEnd") is not None else cell.get("end_row_offset_idx"))
            col_start = int(cell.get("colStart") if cell.get("colStart") is not None else cell.get("start_col_offset_idx"))
            col_end = int(cell.get("colEnd") if cell.get("colEnd") is not None else cell.get("end_col_offset_idx"))
        except (TypeError, ValueError):
            continue
        if row_end <= row_start or col_end <= col_start:
            continue
        bbox = cell.get("bbox")
        cells.append(
            {
                "rowStart": row_start,
                "rowEnd": row_end,
                "colStart": col_start,
                "colEnd": col_end,
                "rowSpan": row_end - row_start,
                "colSpan": col_end - col_start,
                "text": str(cell.get("text") or ""),
                "bbox": bbox if isinstance(bbox, list) else [],
            }
        )
    return cells


def _document_nav_blocks(document_nav: dict[str, Any]) -> list[dict[str, Any]]:
    source_engine = str(document_nav.get("sourceEngine") or "docling")
    tables_by_id = {
        str(table.get("id") or ""): table
        for table in (document_nav.get("tables") if isinstance(document_nav.get("tables"), list) else [])
        if isinstance(table, dict)
    }
    blocks: list[dict[str, Any]] = []
    for order, raw_block in enumerate(document_nav.get("blocks") if isinstance(document_nav.get("blocks"), list) else [], start=1):
        if not isinstance(raw_block, dict):
            continue
        table_id = str(raw_block.get("tableId") or "")
        table = tables_by_id.get(table_id, {})
        rows = _document_nav_table_rows(raw_block.get("rows"))
        if not rows and isinstance(table, dict):
            rows = _document_nav_table_rows(table.get("rows"))
        cells = _document_nav_table_cells(raw_block.get("cells"))
        if not cells and isinstance(table, dict):
            cells = _document_nav_table_cells(table.get("cells"))
        page_no = raw_block.get("pageNo") or (table.get("pageNo") if isinstance(table, dict) else 0) or 0
        try:
            page_no = int(page_no)
        except (TypeError, ValueError):
            page_no = 0
        text = str(raw_block.get("text") or "").strip()
        if not text and isinstance(table, dict):
            text = str(table.get("title") or "").strip()
        block_type = str(raw_block.get("type") or ("table" if rows else "paragraph")).lower()
        bbox = raw_block.get("bbox")
        if not isinstance(bbox, list) and isinstance(table, dict):
            bbox = table.get("bbox")
        blocks.append(
            {
                "blockId": order,
                "type": block_type,
                "text": text,
                "rows": rows,
                "cells": cells,
                "pageNo": page_no if page_no > 0 else 0,
                "bbox": bbox if isinstance(bbox, list) else [],
                "tableId": table_id,
                "sourceEngine": str(
                    raw_block.get("sourceEngine")
                    or (table.get("sourceEngine") if isinstance(table, dict) else "")
                    or source_engine
                ),
            }
        )
    return blocks


def _next_document_nav_text(blocks: list[dict[str, Any]], index: int) -> str:
    for lookahead in range(index + 1, min(len(blocks), index + 6)):
        text = str(blocks[lookahead].get("text") or "").strip()
        if text:
            return text
    return ""


def _is_document_nav_appendix_heading(blocks: list[dict[str, Any]], index: int, profile: ParseProfile) -> bool:
    block = blocks[index]
    block_type = str(block.get("type") or "").lower()
    if block_type not in {"heading", "paragraph", "title", "section_header"}:
        return False
    text = str(block.get("text") or "").strip()
    if (
        not _is_relevant_appendix_heading(text, profile)
        or _is_text_appendix_toc_artifact(text, _next_document_nav_text(blocks, index))
        or _looks_like_toc_or_directory_line(text)
        or _is_scoring_appendix_heading(text)
    ):
        return False
    return True


def _next_document_nav_appendix_heading_index(blocks: list[dict[str, Any]], start_index: int, profile: ParseProfile) -> int:
    for lookahead in range(start_index + 1, len(blocks)):
        if _is_document_nav_appendix_heading(blocks, lookahead, profile):
            return lookahead
    return len(blocks)


def _document_nav_appendix_content_blocks(
    blocks: list[dict[str, Any]],
    start_index: int,
    end_index: int,
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    content_blocks: list[dict[str, Any]] = []
    primary_rows: list[list[str]] = []
    for block in blocks[start_index + 1:end_index]:
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        cells = block.get("cells") if isinstance(block.get("cells"), list) else []
        if rows:
            if not primary_rows:
                primary_rows = rows
            table_block = {
                "type": "table",
                "rows": rows,
                "pageNo": block.get("pageNo") or 0,
                "bbox": block.get("bbox") if isinstance(block.get("bbox"), list) else [],
            }
            if cells:
                table_block["cells"] = cells
            content_blocks.append(table_block)
            continue
        text = str(block.get("text") or "").strip()
        if text and not _is_text_appendix_noise_line(text):
            content_blocks.append(
                {
                    "type": "paragraph",
                    "text": text,
                    "pageNo": block.get("pageNo") or 0,
                    "bbox": block.get("bbox") if isinstance(block.get("bbox"), list) else [],
                }
            )
    return content_blocks, primary_rows


def _document_nav_page_label(block: dict[str, Any]) -> str:
    page_no = _document_nav_page_no(block)
    return f"P{page_no}" if page_no else ""


def _extract_document_nav_appendices(
    project_id: str,
    documents: list[dict[str, Any]],
    *,
    start_index: int = 0,
    profile: ParseProfile = TECHNICAL_PARSE_PROFILE,
) -> list[dict[str, Any]]:
    if profile.key != "technical":
        return []
    appendices: list[dict[str, Any]] = []
    max_content_blocks = 250
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "tender.pdf")
        source_path = Path(str(document.get("sourcePath") or ""))
        nav_path = Path(str(document.get("documentNavPath") or ""))
        if source_path.suffix.lower() != ".pdf" or not nav_path.is_file():
            continue
        try:
            document_nav = json.loads(nav_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document_nav, dict):
            continue
        blocks = _document_nav_blocks(document_nav)
        source_engine = str(document.get("documentParseEngine") or document_nav.get("sourceEngine") or "docling")
        index = 0
        while index < len(blocks):
            if not _is_document_nav_appendix_heading(blocks, index, profile):
                index += 1
                continue
            next_heading = _next_document_nav_appendix_heading_index(blocks, index, profile)
            content_end = min(next_heading, index + 1 + max_content_blocks)
            content_blocks, rows = _document_nav_appendix_content_blocks(blocks, index, content_end)
            if not _appendix_has_material_content(rows, content_blocks):
                index = max(index + 1, next_heading)
                continue

            selected = blocks[index:content_end]
            source_start = _document_nav_page_label(selected[0]) if selected else ""
            source_end = _document_nav_page_label(selected[-1]) if selected else source_start
            title = str(blocks[index].get("text") or "").strip(" #")
            appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
            appendices.append(
                materialize_appendix_docx(
                    project_id,
                    {
                        "id": appendix_id,
                        "title": title,
                        "status": "generated",
                        "sourceFile": source_file,
                        "sourceDocumentId": document_id,
                        "sourceEngine": source_engine,
                        "evidence": title,
                        "evidenceLocation": source_start or f"B{blocks[index].get('blockId') or index + 1}",
                        "sourceStart": source_start,
                        "sourceEnd": source_end,
                        "rows": rows,
                        "contentBlocks": content_blocks,
                        "rowCount": len(rows),
                        "docxPath": "",
                        "extractionMode": "pdf_document_nav_slice",
                    },
                    profile=profile,
                )
            )
            index = max(index + 1, next_heading)
    return appendices


def _sanitize_docx_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    while len(cleaned.encode("utf-8")) > 120:
        cleaned = cleaned[:-1].strip(" .")
    return cleaned or fallback


def _append_text_to_docx_paragraph(paragraph_element: Any, text: str) -> None:
    parts = str(text or "").split("\n")
    for index, part in enumerate(parts):
        run = OxmlElement("w:r")
        if index > 0:
            run.append(OxmlElement("w:br"))
        if part:
            text_element = OxmlElement("w:t")
            if part != part.strip():
                text_element.set(qn("xml:space"), "preserve")
            text_element.text = part
            run.append(text_element)
        paragraph_element.append(run)


def _docx_table_column_count(rows: list[list[str]], cells: list[dict[str, Any]]) -> int:
    return max(
        max((len(row) for row in rows), default=0),
        max((int(cell.get("colEnd") or 0) for cell in cells), default=0),
    )


def _append_docx_table_cell(
    row_element: Any,
    text: str,
    *,
    col_span: int = 1,
    v_merge: str = "",
) -> None:
    cell = OxmlElement("w:tc")
    cell_pr = OxmlElement("w:tcPr")
    cell_width = OxmlElement("w:tcW")
    cell_width.set(qn("w:w"), str(2400 * max(1, col_span)))
    cell_width.set(qn("w:type"), "dxa")
    cell_pr.append(cell_width)
    if col_span > 1:
        grid_span = OxmlElement("w:gridSpan")
        grid_span.set(qn("w:val"), str(col_span))
        cell_pr.append(grid_span)
    if v_merge:
        vertical_merge = OxmlElement("w:vMerge")
        if v_merge == "restart":
            vertical_merge.set(qn("w:val"), "restart")
        cell_pr.append(vertical_merge)
    cell.append(cell_pr)

    paragraph = OxmlElement("w:p")
    _append_text_to_docx_paragraph(paragraph, text)
    cell.append(paragraph)
    row_element.append(cell)


def _write_table_to_docx(doc: Document, rows: list[list[str]], cells: list[dict[str, Any]] | None = None) -> None:
    normalized_cells = _document_nav_table_cells(cells)
    column_count = _docx_table_column_count(rows, normalized_cells)
    if column_count <= 0:
        return
    row_count = max(len(rows), max((int(cell.get("rowEnd") or 0) for cell in normalized_cells), default=0))
    table = OxmlElement("w:tbl")
    table_pr = OxmlElement("w:tblPr")
    table_style = OxmlElement("w:tblStyle")
    table_style.set(qn("w:val"), "TableGrid")
    table_pr.append(table_style)
    table.append(table_pr)

    table_grid = OxmlElement("w:tblGrid")
    for _ in range(column_count):
        grid_col = OxmlElement("w:gridCol")
        grid_col.set(qn("w:w"), "2400")
        table_grid.append(grid_col)
    table.append(table_grid)

    origin_cells: dict[tuple[int, int], dict[str, Any]] = {}
    continuation_cells: dict[tuple[int, int], dict[str, Any]] = {}
    skipped_positions: set[tuple[int, int]] = set()
    for cell in normalized_cells:
        row_start = int(cell.get("rowStart") or 0)
        row_end = int(cell.get("rowEnd") or row_start + 1)
        col_start = int(cell.get("colStart") or 0)
        col_end = int(cell.get("colEnd") or col_start + 1)
        origin_cells[(row_start, col_start)] = cell
        for row_index in range(row_start, row_end):
            for col_index in range(col_start, col_end):
                if row_index == row_start and col_index == col_start:
                    continue
                if row_index > row_start and col_index == col_start:
                    continuation_cells[(row_index, col_index)] = cell
                    continue
                skipped_positions.add((row_index, col_index))

    for row_index in range(row_count):
        row = rows[row_index] if row_index < len(rows) and isinstance(rows[row_index], list) else []
        row_element = OxmlElement("w:tr")
        col_index = 0
        while col_index < column_count:
            if (row_index, col_index) in skipped_positions:
                col_index += 1
                continue
            origin_cell = origin_cells.get((row_index, col_index))
            if origin_cell is not None:
                col_span = max(1, int(origin_cell.get("colSpan") or 1))
                row_span = max(1, int(origin_cell.get("rowSpan") or 1))
                _append_docx_table_cell(
                    row_element,
                    str(origin_cell.get("text") or ""),
                    col_span=col_span,
                    v_merge="restart" if row_span > 1 else "",
                )
                col_index += col_span
                continue
            continuation_cell = continuation_cells.get((row_index, col_index))
            if continuation_cell is not None:
                col_span = max(1, int(continuation_cell.get("colSpan") or 1))
                _append_docx_table_cell(row_element, "", col_span=col_span, v_merge="continue")
                col_index += col_span
                continue
            _append_docx_table_cell(row_element, row[col_index] if col_index < len(row) else "")
            col_index += 1
        table.append(row_element)
    doc._body._element.insert_element_before(table, "w:sectPr")


def _write_appendix_docx(
    path: Path,
    title: str,
    rows: list[list[str]],
    content_blocks: list[dict[str, Any]] | None = None,
) -> None:
    """Fallback: build a fresh docx from flattened rows/content blocks.

    Source docx slicing is preferred when available because it preserves merged
    cells and styles. Business attachments can additionally pass content blocks
    so template body text is not reduced to a title-only Word file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading(title, level=1)
    wrote_content = False
    for block in content_blocks or []:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type == "paragraph":
            block_text = str(block.get("text") or "").strip()
            if block_text:
                doc.add_paragraph(block_text)
                wrote_content = True
        elif block_type == "table":
            block_rows = block.get("rows") if isinstance(block.get("rows"), list) else []
            block_cells = block.get("cells") if isinstance(block.get("cells"), list) else []
            if block_rows:
                _write_table_to_docx(doc, block_rows, block_cells)
                wrote_content = True
    if rows and not wrote_content:
        _write_table_to_docx(doc, rows)
    doc.save(path)

def _build_appendix_slice_state(source_docx: Path) -> dict[str, Any] | None:
    """Read ``source_docx`` once and return cached state for repeated calls
    to :func:`_slice_appendix_from_source`.

    A real RFP can be 20+ MB with millions of XML elements and dozens of
    appendices. Cloning the entire document tree per appendix (the previous
    approach) burned multiple seconds each — the caller froze for minutes
    on production-sized files. The current approach is genuinely a "cut":
    we hold direct references to every body child of the source, and each
    slice MOVES the kept children into a fresh per-appendix body element
    rather than cloning. Children are O(1) to detach; only the trailing
    ``<w:sectPr>`` is deepcopied (it's a single small element shared across
    all outputs).

    The returned dict carries:
    - ``sourcePath``  — original file path (kept for diagnostics)
    - ``parts``       — every zip entry of the source as ``{name: (info, bytes)}``,
      so each output zip can be assembled without re-reading the source
    - ``rootTag`` / ``rootAttrib`` / ``rootNsmap`` — used to clone the
      ``<w:document>`` shell (without its body) for each output
    - ``rootChildrenBeforeBody`` — non-body siblings of body (rare, e.g.
      ``<w:background>``) cached as deepcopies so each output gets a fresh
      copy
    - ``bodyTag`` / ``bodyAttrib`` — used to build the new body element
    - ``bodyChildren`` — list of references to each body child of the source,
      indexable by ``body_index``. Children are MOVED out of this list into
      per-appendix bodies, mutating the source tree in the process.
    - ``sectPr`` — reference to the source's trailing ``<w:sectPr>`` so each
      output can deepcopy its own copy
    """

    if not source_docx.is_file():
        return None
    try:
        from lxml import etree as _etree
        from copy import deepcopy as _deepcopy

        with zipfile.ZipFile(source_docx, "r") as zf:
            parts: dict[str, tuple[Any, bytes]] = {
                info.filename: (info, zf.read(info.filename))
                for info in zf.infolist()
            }
        doc_xml = parts["word/document.xml"][1]
        doc_tree = _etree.fromstring(doc_xml)
        body_tag = f"{WORD_NAMESPACE}body"
        sect_pr_tag = f"{WORD_NAMESPACE}sectPr"
        body = doc_tree.find(body_tag)
        if body is None:
            return None

        # Cache non-body siblings of <w:document> (e.g. <w:background>) as
        # deepcopies so each output gets a fresh, independent copy.
        root_children_before_body: list[Any] = []
        for child in doc_tree.iterchildren():
            if child.tag == body_tag:
                break
            root_children_before_body.append(_deepcopy(child))

        body_children = list(body.iterchildren())
        sect_pr = body.find(sect_pr_tag)
    except Exception:
        return None

    return {
        "sourcePath": str(source_docx),
        "parts": parts,
        "rootTag": doc_tree.tag,
        "rootAttrib": dict(doc_tree.attrib),
        "rootNsmap": dict(doc_tree.nsmap),
        "rootChildrenBeforeBody": root_children_before_body,
        "bodyTag": body_tag,
        "bodyAttrib": dict(body.attrib),
        "bodyChildren": body_children,
        "sectPr": sect_pr,
    }


def _slice_appendix_from_source(
    source_docx: Path,
    target_docx: Path,
    keep_start: int,
    keep_end: int,
    source_state: dict[str, Any] | None = None,
) -> bool:
    """Produce ``target_docx`` by literally CUTTING children
    ``[keep_start, keep_end]`` (inclusive, by ``body_index``) out of the
    source docx body and dropping them into a fresh ``<w:document>`` shell.

    The kept children are MOVED, not cloned: lxml's ``new_parent.append(elem)``
    detaches ``elem`` from its old parent in O(1). For a 21 MB RFP with 50
    appendices this brings per-appendix CPU work from ~3 s (full-tree
    deepcopy) to a few ms (deepcopy of one ``<w:sectPr>``).

    All non-document parts of the docx (``word/styles.xml``,
    ``word/numbering.xml``, ``word/_rels/document.xml.rels``,
    ``word/media/*`` …) are written to the output zip from cached source
    bytes, so cell merges, fonts, embedded images, list numbering and
    hyperlinks render exactly as in the source.

    Caveat: because moves mutate the shared ``source_state``, processing
    appendices that overlap on body indices is not supported (``S0`` already
    enforces disjoint ranges via ``used_tables``). Children that have been
    moved into one output's body cannot be moved again.

    Returns ``True`` on success, ``False`` if the source is missing or the
    indices are not valid."""

    if keep_end < keep_start:
        return False
    if source_state is None:
        source_state = _build_appendix_slice_state(source_docx)
    if source_state is None:
        return False
    target_docx.parent.mkdir(parents=True, exist_ok=True)

    from copy import deepcopy as _deepcopy
    from lxml import etree as _etree

    body_children: list[Any] = source_state["bodyChildren"]
    sect_pr = source_state["sectPr"]
    sect_pr_tag = f"{WORD_NAMESPACE}sectPr"

    # Build a fresh <w:document> shell with the source's namespaces / attribs.
    new_root = _etree.Element(
        source_state["rootTag"],
        attrib=source_state["rootAttrib"],
        nsmap=source_state["rootNsmap"],
    )
    # Re-attach any non-body siblings that lived above <w:body> in the source
    # (rare, but safe).
    for sibling in source_state["rootChildrenBeforeBody"]:
        new_root.append(_deepcopy(sibling))
    new_body = _etree.SubElement(
        new_root,
        source_state["bodyTag"],
        attrib=source_state["bodyAttrib"],
    )

    # MOVE each kept child from source body into the new body. lxml semantics:
    # ``new_body.append(child)`` detaches ``child`` from its prior parent.
    n = len(body_children)
    start = max(0, keep_start)
    end = min(n - 1, keep_end)
    for idx in range(start, end + 1):
        child = body_children[idx]
        if child.tag == sect_pr_tag:
            # sect_pr is appended at the end as a deepcopy so subsequent
            # appendices can also reference it.
            continue
        # If this child has already been moved (overlapping ranges, which
        # shouldn't happen but we guard anyway), skip it.
        if child.getparent() is None or child.getparent() is not None and child.getparent().tag != source_state["bodyTag"]:
            # Already moved out of the source body — skip silently.
            if child.getparent() is None:
                continue
        new_body.append(child)

    if sect_pr is not None:
        new_body.append(_deepcopy(sect_pr))

    new_doc_xml = _etree.tostring(
        new_root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )

    # Assemble the output zip from cached source parts. The only entry that
    # changes per appendix is ``word/document.xml``; everything else
    # (styles, numbering, rels, media) ships byte-for-byte.
    parts: dict[str, tuple[Any, bytes]] = source_state["parts"]
    try:
        with zipfile.ZipFile(target_docx, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as dst:
            for filename, (info, data) in parts.items():
                if filename == "word/document.xml":
                    if len(new_doc_xml) >= DOCX_SLICE_STORED_XML_THRESHOLD_BYTES:
                        dst.writestr(filename, new_doc_xml, compress_type=zipfile.ZIP_STORED)
                    else:
                        dst.writestr(info, new_doc_xml)
                else:
                    dst.writestr(info, data)
    except Exception:
        target_docx.unlink(missing_ok=True)
        return False
    return True


def _appendix_output_dir(project_id: str) -> Path:
    return parsed_appendix_path(project_id)


def _commitment_letter_output_dir(project_id: str) -> Path:
    path = settings.parsed_dir / project_id / "s1_commitment_letters"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workspace_appendix_output_dir(project_id: str, profile: ParseProfile) -> Path:
    return settings.documents_dir / project_id / profile.workspace_dirname / "appendices"


def _workspace_commitment_letter_output_dir(project_id: str, profile: ParseProfile) -> Path:
    return settings.documents_dir / project_id / profile.workspace_dirname / "commitment-letters"


def _appendix_asset_path(project_id: str, appendix_id: str, title: str) -> tuple[Path, str]:
    file_name = f"{appendix_id}-{_sanitize_docx_name(title, '附表')}.docx"
    return _appendix_output_dir(project_id) / file_name, f"s1_appendices/{file_name}"


def _commitment_letter_asset_path(project_id: str, letter_id: str, title: str) -> tuple[Path, str]:
    file_name = f"{letter_id}-{_sanitize_docx_name(title, '承诺函')}.docx"
    return _commitment_letter_output_dir(project_id) / file_name, f"s1_commitment_letters/{file_name}"


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _write_commitment_letter_docx(path: Path, letter: dict[str, Any], *, project_name: str = "", tenderer_name: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    title = str(letter.get("title") or "承诺函").strip() or "承诺函"
    trigger_context = str(letter.get("triggerContext") or letter.get("evidence") or letter.get("triggerText") or "").strip()
    commitment_type = str(letter.get("commitmentType") or "").strip()

    doc = Document()
    doc.add_heading(title, level=1)
    if project_name:
        doc.add_paragraph(f"项目名称：{project_name}")
    if tenderer_name:
        doc.add_paragraph(f"招标人：{tenderer_name}")
    if trigger_context:
        doc.add_paragraph(f"触发依据：{trigger_context}")

    doc.add_paragraph("致：招标人")
    doc.add_paragraph("说明：本文件为商务标解析阶段自动生成的承诺函草稿，请结合招标文件原文、法务要求和项目实际情况复核后使用。")

    if commitment_type == "disqualification":
        doc.add_paragraph("我方在参加本项目投标过程中，郑重承诺如下：")
        doc.add_paragraph("1. 我方不存在招标文件中列示的“投标人不得存在下列情形之一”所述任一情形。")
        doc.add_paragraph("2. 如本承诺与实际情况不符，我方愿意按照招标文件和相关规定承担相应责任。")
    else:
        doc.add_paragraph("根据招标文件中的承诺要求，我方郑重承诺如下：")
        doc.add_paragraph("1. 我方将严格按照招标文件要求对相关事项进行响应并履行承诺。")
        if trigger_context:
            doc.add_paragraph(f"2. 本承诺函重点对应的招标文件原文为：{trigger_context}")
        doc.add_paragraph("3. 如本承诺与实际情况不符，我方愿意按照招标文件和相关规定承担相应责任。")

    doc.add_paragraph("")
    doc.add_paragraph("投标人（盖章）：________________")
    doc.add_paragraph("法定代表人或授权代表（签字或盖章）：________________")
    doc.add_paragraph("日期：________________")
    doc.save(path)


def materialize_appendix_docx(project_id: str, appendix: dict[str, Any], *, profile: ParseProfile = TECHNICAL_PARSE_PROFILE) -> dict[str, Any]:
    """Ensure an appendix entry has a generated Word asset, even when no template table was found.

    The slice metadata, if present under the private ``_slice`` key, is consumed
    here and stripped from the returned dict so it never enters JSON / DB. The
    expected shape is::

        {"sourcePath": str, "keepStart": int, "keepEnd": int}

    When provided and the slice succeeds, the appendix docx is produced by
    cutting the body of ``sourcePath`` directly, which preserves merges, styles,
    media, numbering and section properties verbatim. Otherwise we fall back to
    rebuilding from ``rows`` (Markdown/PDF inputs)."""

    # Peel off the private ``_slice`` key BEFORE deep-copying, since it can
    # carry an in-memory lxml tree (``sourceState``) that is large and
    # expensive to copy element-by-element. Shallow-copy the rest of the
    # dict so we don't mutate the caller's payload.
    slice_info = None
    if isinstance(appendix, dict) and "_slice" in appendix:
        appendix_without_slice = dict(appendix)
        slice_info = appendix_without_slice.pop("_slice", None)
        item = copy.deepcopy(appendix_without_slice)
    else:
        item = copy.deepcopy(appendix)
    appendix_id = str(item.get("id") or "").strip() or "APPX-0000"
    title = str(item.get("title") or item.get("evidence") or "附表").strip() or "附表"
    rows = item.get("rows") if isinstance(item.get("rows"), list) else []
    content_blocks = item.get("contentBlocks") if isinstance(item.get("contentBlocks"), list) else []
    output_dir = _appendix_output_dir(project_id)
    workspace_output_dir = _workspace_appendix_output_dir(project_id, profile)
    project_workspace_root = settings.documents_dir / project_id

    existing_path = Path(str(item.get("docxPath") or ""))
    if not existing_path.is_absolute():
        existing_path = Path()
    extractor_docx_path = existing_path if str(item.get("extractionMode") or "") == "business_template_extractor_skill" else Path()
    existing_path_allowed = (
        bool(existing_path)
        and (
            _path_is_inside(existing_path, output_dir)
            or _path_is_inside(existing_path, workspace_output_dir)
            or _path_is_inside(existing_path, project_workspace_root)
        )
    )
    if not existing_path_allowed:
        existing_path, workspace_path = _appendix_asset_path(project_id, appendix_id, title)
    else:
        workspace_path = str(item.get("workspacePath") or f"{profile.workspace_dirname}/appendices/{existing_path.name}")
    if (
        extractor_docx_path
        and extractor_docx_path.is_file()
        and existing_path != extractor_docx_path
        and not existing_path.exists()
    ):
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(extractor_docx_path), str(existing_path))

    should_rewrite = False
    if should_rewrite or isinstance(slice_info, dict) or not existing_path.exists():
        sliced = False
        if isinstance(slice_info, dict):
            source_path = Path(str(slice_info.get("sourcePath") or ""))
            keep_start_raw = slice_info.get("keepStart")
            keep_end_raw = slice_info.get("keepEnd")
            source_state = slice_info.get("sourceState")
            if (
                source_path.is_file()
                and isinstance(keep_start_raw, int)
                and isinstance(keep_end_raw, int)
            ):
                sliced = _slice_appendix_from_source(
                    source_path,
                    existing_path,
                    keep_start_raw,
                    keep_end_raw,
                    source_state=source_state if isinstance(source_state, dict) else None,
                )
        if sliced and profile.key == "business":
            item["extractionMode"] = "source_docx_slice"
            quality = _business_template_quality(
                title=title,
                rows=rows,
                content_blocks=content_blocks,
                extraction_mode="source_docx_slice",
                template_section_title=str(item.get("templateSectionTitle") or ""),
            )
            item.update(quality)
        if not sliced:
            if isinstance(slice_info, dict) and profile.key == "business":
                item["extractionMode"] = "source_docx_rebuild_fallback"
                existing_issues = item.get("qualityIssues") if isinstance(item.get("qualityIssues"), list) else []
                item["qualityIssues"] = [*existing_issues, "原 DOCX 切片失败，已退回重建 Word"]
                item["needsReview"] = True
            _write_appendix_docx(existing_path, title, rows, content_blocks)

    item.update(
        {
            "id": appendix_id,
            "title": title,
            "status": "generated",
            "rows": rows,
            "contentBlocks": content_blocks,
            "rowCount": len(rows),
            "docxPath": str(existing_path),
            "workspacePath": workspace_path,
        }
    )
    return item


def materialize_business_commitment_letter_docx(
    project_id: str,
    letter: dict[str, Any],
    *,
    profile: ParseProfile = BUSINESS_PARSE_PROFILE,
    project_name: str = "",
    tenderer_name: str = "",
) -> dict[str, Any]:
    item = copy.deepcopy(letter)
    letter_id = str(item.get("id") or "").strip() or "CL-0000"
    title = str(item.get("title") or item.get("triggerText") or "承诺函").strip() or "承诺函"
    output_dir = _commitment_letter_output_dir(project_id)
    workspace_output_dir = _workspace_commitment_letter_output_dir(project_id, profile)
    project_workspace_root = settings.documents_dir / project_id

    existing_path = Path(str(item.get("docxPath") or ""))
    if not existing_path.is_absolute():
        existing_path = Path()
    existing_path_allowed = (
        bool(existing_path)
        and (
            _path_is_inside(existing_path, output_dir)
            or _path_is_inside(existing_path, workspace_output_dir)
            or _path_is_inside(existing_path, project_workspace_root)
        )
    )
    if not existing_path_allowed:
        existing_path, workspace_path = _commitment_letter_asset_path(project_id, letter_id, title)
    else:
        if str(item.get("workspacePath") or "").strip():
            workspace_path = str(item.get("workspacePath") or "")
        elif _path_is_inside(existing_path, workspace_output_dir):
            workspace_path = f"{profile.workspace_dirname}/commitment-letters/{existing_path.name}"
        else:
            workspace_path = f"s1_commitment_letters/{existing_path.name}"

    if not existing_path.exists():
        _write_commitment_letter_docx(existing_path, item, project_name=project_name, tenderer_name=tenderer_name)

    item.update(
        {
            "id": letter_id,
            "title": title,
            "status": "generated",
            "docxPath": str(existing_path),
            "workspacePath": workspace_path,
            "previewType": "onlyoffice",
        }
    )
    return item


def _appendix_title_for_match(value: str) -> str:
    title = str(value or "").strip().lstrip("#").strip()
    return re.sub(r"\s+", " ", title)


def _appendix_row_count(item: dict[str, Any]) -> int:
    row_count = item.get("rowCount")
    if isinstance(row_count, int):
        return row_count
    rows = item.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def _is_toc_page_number_appendix(item: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    if str(item.get("extractionMode") or "") == "source_docx_table_fingerprint":
        return False
    fingerprint = item.get("tableFingerprint") if isinstance(item.get("tableFingerprint"), dict) else {}
    if str(fingerprint.get("type") or "").strip():
        return False
    if _appendix_row_count(item) > 0:
        return False

    title = _appendix_title_for_match(str(item.get("title") or item.get("evidence") or ""))
    if not re.search(r"\d{1,4}$", title):
        return False

    for candidate in candidates:
        if candidate is item:
            continue
        candidate_title = _appendix_title_for_match(str(candidate.get("title") or candidate.get("evidence") or ""))
        if not candidate_title or candidate_title == title or not title.startswith(candidate_title):
            continue

        suffix = title[len(candidate_title):]
        if not re.fullmatch(r"\d{1,4}", suffix):
            continue
        if len(suffix) == 1 and re.search(r"[\w.]$", candidate_title):
            continue
        return True

    return False


def _dedupe_appendix_page_number_artifacts(
    appendices: list[dict[str, Any]],
    *,
    include_attachments: bool = False,
    include_business_templates: bool = False,
) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in appendices
        if isinstance(item, dict) and (
            str(item.get("extractionMode") or "") in {
                "source_docx_table_fingerprint",
                "business_template_extractor_skill",
            }
            or (
                isinstance(item.get("tableFingerprint"), dict)
                and bool(str(item["tableFingerprint"].get("type") or "").strip())
            )
            or
            _looks_like_business_attachment_template_title(
                str(item.get("title") or item.get("evidence") or ""),
                in_template_section=True,
            )
            if include_business_templates
            else _is_appendix_heading(
                str(item.get("title") or item.get("evidence") or ""),
                include_attachments=include_attachments,
            )
        )
    ]
    return [item for item in candidates if not _is_toc_page_number_appendix(item, candidates)]


def _prepare_appendix_outputs(
    project_id: str,
    appendices: list[dict[str, Any]],
    *,
    renumber: bool,
    profile: ParseProfile = TECHNICAL_PARSE_PROFILE,
) -> list[dict[str, Any]]:
    """Materialize appendix docx assets, renumbering IDs sequentially when asked.

    On renumber, an appendix may already have a docx generated under its old ID
    by an earlier pass (typically the slicing pass in ``_extract_docx_appendices``).
    Re-running ``materialize_appendix_docx`` with a cleared ``docxPath`` would
    fall back to a rows-rebuild and lose the carefully preserved formatting.
    Instead, when the existing file is on disk, move it to its new ID-aligned
    path so the materializer sees a valid ``docxPath`` and skips regeneration."""

    prepared: list[dict[str, Any]] = []
    for index, appendix in enumerate(
        _dedupe_appendix_page_number_artifacts(
            appendices,
            include_attachments=profile.key == "business",
            include_business_templates=profile.key == "business",
        ),
        start=1,
    ):
        item = copy.deepcopy(appendix)
        if profile.key == "business":
            rows = item.get("rows") if isinstance(item.get("rows"), list) else []
            content_blocks = item.get("contentBlocks") if isinstance(item.get("contentBlocks"), list) else []
            if (
                str(item.get("extractionMode") or "") != "business_template_extractor_skill"
                and not _business_template_should_materialize(item, rows, content_blocks)
            ):
                continue
        if renumber:
            new_id = f"APPX-{index:04d}"
            old_id = str(item.get("id") or "").strip()
            old_docx = Path(str(item.get("docxPath") or ""))
            old_docx_valid = bool(str(item.get("docxPath") or "")) and old_docx.is_file()
            renamed = False
            if old_docx_valid and old_id and old_id != new_id:
                title = str(item.get("title") or item.get("evidence") or "附表").strip() or "附表"
                new_docx_path, new_workspace_path = _appendix_asset_path(project_id, new_id, title)
                if old_docx.resolve() != new_docx_path.resolve():
                    new_docx_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.move(str(old_docx), str(new_docx_path))
                    except Exception:
                        # Move can fail across filesystems; fall back to copy + unlink.
                        shutil.copy2(str(old_docx), str(new_docx_path))
                        old_docx.unlink(missing_ok=True)
                    item["docxPath"] = str(new_docx_path)
                    item["workspacePath"] = new_workspace_path
                    renamed = True
                else:
                    # Path already matches the new ID — just pin metadata.
                    item["docxPath"] = str(new_docx_path)
                    item["workspacePath"] = new_workspace_path
                    renamed = True
            elif old_docx_valid and old_id == new_id:
                # ID unchanged (re-numbering produced the same value) — keep file as-is.
                renamed = True
            item["id"] = new_id
            if not renamed:
                item["docxPath"] = ""
                item.pop("workspacePath", None)
        prepared.append(materialize_appendix_docx(project_id, item, profile=profile))
    return prepared


def _prepare_commitment_letter_outputs(
    project_id: str,
    letters: list[dict[str, Any]],
    *,
    renumber: bool,
    profile: ParseProfile = BUSINESS_PARSE_PROFILE,
    project_name: str = "",
    tenderer_name: str = "",
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, letter in enumerate(letters, start=1):
        item = copy.deepcopy(letter)
        if renumber:
            item["id"] = f"CL-{index:04d}"
            item["docxPath"] = ""
            item.pop("workspacePath", None)
        prepared.append(
            materialize_business_commitment_letter_docx(
                project_id,
                item,
                profile=profile,
                project_name=project_name,
                tenderer_name=tenderer_name,
            )
        )
    return prepared


def materialize_parse_appendix_docx_assets(
    project_id: str,
    parse_result: dict[str, Any],
    *,
    bid_type: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(parse_result)
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return payload
    appendices = structured.get("appendices")
    if not isinstance(appendices, list):
        return payload
    profile = resolve_parse_profile(bid_type)
    structured["appendices"] = _prepare_appendix_outputs(project_id, appendices, renumber=False, profile=profile)
    return payload


def materialize_parse_business_commitment_letter_docx_assets(
    project_id: str,
    parse_result: dict[str, Any],
    *,
    bid_type: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(parse_result)
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return payload
    if resolve_parse_profile(bid_type).key != "business":
        return payload
    letters = structured.get("commitmentLetters")
    if not isinstance(letters, list):
        return payload
    project_name = _business_project_name_from_structured(structured)
    tenderer_name = _business_tenderer_name_from_structured(structured)
    structured["commitmentLetters"] = _prepare_commitment_letter_outputs(
        project_id,
        letters,
        renumber=False,
        profile=BUSINESS_PARSE_PROFILE,
        project_name=project_name,
        tenderer_name=tenderer_name,
    )
    return payload


def _is_appendix_heading(text: str, *, include_attachments: bool = False) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    if re.match(r"^(?:技术)?[附副]表(?:\s*[A-Za-z0-9一二三四五六七八九十]+)?(?:[：:、.．\s]|$)", normalized):
        return True
    if include_attachments and re.match(r"^附件\s*[A-Za-z0-9一二三四五六七八九十]+(?:[：:、.．\s]|$)", normalized):
        return True
    return False


def _is_scoring_appendix_heading(text: str) -> bool:
    return any(keyword in text for keyword in ("评分标准", "评分细则", "评标办法", "符合性审查", "投标报价评分", "度电成本评分"))


BUSINESS_ATTACHMENT_TEMPLATE_TOPICS = (
    "投标函", "法定代表人", "单位负责人", "身份证明", "授权书", "授权委托书",
    "廉洁", "投标专用章", "效力说明", "投标价格", "开标价格", "商务偏差",
    "货物规格", "规格表", "供货范围", "投标保证金", "履约保证函", "履约承诺",
    "资格证明", "合格投标人", "资格履行合同", "业绩情况", "业绩表",
    "财务状况", "制造商授权", "联合体协议", "分包", "其他内容", "其他说明",
    "否决项", "承诺书", "承诺函",
)

BUSINESS_ATTACHMENT_TEMPLATE_CONTEXT_TOKENS = (
    "投标文件格式",
    "响应文件格式",
    "商务文件格式",
    "投标文件组成",
    "第六章",
    "第6章",
)

BUSINESS_FORMAT_START_KEYWORDS = (
    "投标文件格式",
    "响应文件格式",
    "商务文件格式",
    "商务标格式",
    "商务响应文件格式",
)
BUSINESS_FORMAT_END_KEYWORDS = (
    "评标办法",
    "评审办法",
    "合同条款",
    "技术要求",
    "技术规范",
    "供货要求",
    "用户需求",
)

BUSINESS_ATTACHMENT_TEMPLATE_TYPE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("bid_letter", "投标函", ("投标函",)),
    ("legal_rep_id", "法定代表人身份证明", ("法定代表人（单位负责人）身份证明", "法定代表人身份证明", "单位负责人身份证明", "身份证明")),
    ("authorization", "授权书", ("法定代表人授权委托书", "法定代表人授权书", "授权委托书", "授权书")),
    ("integrity_commitment", "廉洁承诺", ("投标人廉洁自律承诺书", "廉洁自律承诺书", "廉洁承诺书", "廉洁承诺")),
    ("seal_validity", "投标专用章效力说明", ("投标专用章效力说明", "专用章效力说明", "投标专用章")),
    ("bid_price", "投标价格表", ("投标价格表", "投标价格")),
    ("opening_price", "开标价格表", ("开标价格表", "开标报价表")),
    ("commercial_deviation", "商务偏差表", ("商务偏差表", "商务偏差", "商务偏离表", "偏差表", "偏离表")),
    ("specification", "货物规格表", ("货物规格表", "货物规格", "规格表")),
    ("supply_scope", "供货范围表", ("供货范围表", "供货范围", "供货清单")),
    ("bid_security", "投标保证金", ("投标保证金", "保证金", "投标保函", "保函")),
    ("performance_bond", "履约保证", ("履约保证函格式承诺书", "履约保证函", "履约承诺书", "履约承诺", "履约保证")),
    ("qualification", "资格证明文件", ("资格证明", "合格投标人", "资格履行合同")),
    ("performance_table", "业绩情况表", ("业绩情况表", "业绩表", "业绩证明")),
    ("financial", "财务状况表", ("财务状况", "财务报表", "审计报告")),
    ("manufacturer_authorization", "制造商授权", ("制造商授权", "厂家授权")),
    ("joint_venture", "联合体协议", ("联合体协议",)),
    ("other_notes", "其他说明", ("投标人需要说明的其他内容", "其他内容", "其他说明")),
    ("commitment", "承诺函/承诺书", ("承诺函", "承诺书")),
)

BUSINESS_TEMPLATE_COMPLETENESS_TOKENS = (
    "盖章",
    "签字",
    "签章",
    "签名",
    "年月日",
    "年  月  日",
    "身份证号",
    "报价",
    "金额",
    "偏差",
    "保证金",
    "开户行",
    "账号",
)
BUSINESS_TEMPLATE_PLACEHOLDER_TOKENS = ("____", "＿＿", "（盖章）", "(盖章)", "签字", "日期", "年  月  日")
BUSINESS_TEMPLATE_SEMANTIC_REVIEW_MAX_ITEMS = 16

BUSINESS_TABLE_FINGERPRINTS: tuple[tuple[str, str, tuple[tuple[str, ...], ...]], ...] = (
    ("opening_price", "开标价格表", (("序号",), ("投标报价", "报价", "总价", "合价", "单价"), ("项目名称", "名称", "货物名称"))),
    ("bid_price", "投标价格表", (("序号",), ("投标报价", "报价", "总价", "合价", "单价"), ("备注", "说明", "项目名称"))),
    ("specification", "货物规格表", (("序号",), ("货物名称", "设备名称", "名称"), ("规格", "规格型号", "型号"))),
    ("commercial_deviation", "商务偏差表", (("序号",), ("条款", "招标文件"), ("偏差", "响应"))),
    ("supply_scope", "供货范围表", (("序号",), ("名称", "设备", "货物"), ("数量", "单位"))),
    ("performance_table", "业绩情况表", (("序号",), ("项目名称", "工程名称"), ("合同", "容量", "投运", "业主"))),
    ("legal_rep_id", "法定代表人身份证明", (("姓名",), ("身份证", "证件"), ("职务", "职称"))),
    ("authorization", "授权书", (("姓名",), ("身份证", "证件"), ("授权", "代理人", "委托"))),
    ("bid_security", "投标保证金", (("保证金", "保函"), ("金额", "账号", "开户行", "银行"))),
)


def _is_business_template_section_heading(text: str) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    if not normalized:
        return False
    if _looks_like_toc_or_directory_line(normalized):
        return False
    if _looks_like_business_template_body_sentence(normalized):
        return False
    if any(token in normalized for token in BUSINESS_FORMAT_START_KEYWORDS):
        return True
    return bool(re.match(r"^第[六6]章", normalized)) and any(
        token in normalized for token in ("格式", "投标文件", "响应文件", "商务文件")
    )


def _is_business_format_end_heading(text: str) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    if not normalized or _looks_like_toc_or_directory_line(normalized):
        return False
    return any(keyword in normalized for keyword in BUSINESS_FORMAT_END_KEYWORDS)


def _block_heading_rank(block: dict[str, Any], text: str) -> int | None:
    raw_level = block.get("headingLevel")
    if isinstance(raw_level, int):
        return raw_level
    normalized = str(text or "").strip().lstrip("#").strip()
    if re.match(r"^第[一二三四五六七八九十0-9]+章", normalized):
        return 0
    if re.match(r"^(?:[一二三四五六七八九十0-9]+[、.．]|[（(][一二三四五六七八九十0-9]+[）)])", normalized):
        return 1
    if bool(block.get("isLikelyHeading")):
        return 2
    return None


def _is_business_major_section_heading(text: str) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    return bool(re.match(r"^第[一二三四五六七八九十0-9]+章", normalized))


def _has_business_attachment_topic(text: str) -> bool:
    normalized = str(text or "").strip()
    return any(keyword in normalized for keyword in BUSINESS_ATTACHMENT_TEMPLATE_TOPICS)


def _business_template_type(title: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", "", str(title or ""))
    for key, label, keywords in BUSINESS_ATTACHMENT_TEMPLATE_TYPE_RULES:
        if any(keyword and keyword in normalized for keyword in keywords):
            return key, label
    return "generic_attachment", "商务附件模板"


def _business_template_type_label(template_type: str) -> str:
    normalized = str(template_type or "").strip()
    for key, label, _ in BUSINESS_ATTACHMENT_TEMPLATE_TYPE_RULES:
        if key == normalized:
            return label
    return "商务附件模板"


def _business_template_type_label_for_key(template_type: str) -> str:
    normalized = str(template_type or "").strip()
    for key, label, _ in BUSINESS_ATTACHMENT_TEMPLATE_TYPE_RULES:
        if key == normalized:
            return label
    for key, label, _ in BUSINESS_TABLE_FINGERPRINTS:
        if key == normalized:
            return label
    return "商务附件模板"


def _flatten_table_text(rows: list[list[str]]) -> str:
    return re.sub(r"\s+", "", " ".join(str(cell or "") for row in rows for cell in row))


def _classify_business_table(rows: list[list[str]], title_hint: str = "") -> tuple[str, str, float, list[str]]:
    table_text = _flatten_table_text(rows)
    title_text = re.sub(r"\s+", "", str(title_hint or ""))
    combined = f"{title_text}{table_text}"
    if not combined:
        return "", "", 0.0, []
    candidates: list[tuple[float, str, str, list[str]]] = []
    for key, label, groups in BUSINESS_TABLE_FINGERPRINTS:
        matched_groups = []
        for group in groups:
            matched = next((token for token in group if token and token in combined), "")
            if matched:
                matched_groups.append(matched)
        if len(matched_groups) >= max(2, len(groups) - 1):
            confidence = min(0.98, 0.62 + 0.12 * len(matched_groups))
            if any(token in title_text for token in (label, label.replace("表", ""), "报价", "规格", "偏差", "供货", "业绩")):
                confidence = min(0.99, confidence + 0.04)
            candidates.append((confidence, key, label, matched_groups))
    if candidates:
        confidence, key, label, matched_groups = max(candidates, key=lambda item: (item[0], len(item[3])))
        return key, label, confidence, matched_groups
    if any(token in combined for token in BUSINESS_TEMPLATE_PLACEHOLDER_TOKENS):
        return "generic_attachment", "商务附件模板", 0.58, ["placeholder"]
    return "", "", 0.0, []


def _business_template_title_allowed(text: str, *, in_template_section: bool = False) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    if _looks_like_toc_or_directory_line(normalized):
        return False
    if not _looks_like_business_attachment_template_title(normalized, in_template_section=in_template_section):
        return False
    if in_template_section:
        return True
    has_explicit_template = any(token in normalized for token in ("格式", "模板", "样式"))
    return has_explicit_template and _is_appendix_heading(normalized, include_attachments=True)


def _looks_like_business_attachment_template_title(text: str, *, in_template_section: bool = False) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    if _looks_like_business_template_body_sentence(normalized):
        return False
    if _is_scoring_appendix_heading(normalized):
        return False
    has_appendix_prefix = _is_appendix_heading(normalized, include_attachments=True)
    has_template_suffix = any(token in normalized for token in ("格式", "模板", "样式"))
    has_response_format_title = _is_business_template_section_heading(normalized)
    if has_response_format_title:
        return False
    has_numbered_business_prefix = bool(
        re.match(r"^(?:[一二三四五六七八九十0-9]+[、.．]|[（(][一二三四五六七八九十0-9]+[）)])", normalized)
    )
    has_business_topic = _has_business_attachment_topic(normalized)
    if has_appendix_prefix and (has_business_topic or has_template_suffix or in_template_section):
        return True
    if in_template_section and has_business_topic and (has_numbered_business_prefix or has_template_suffix or len(normalized) <= 24):
        return True
    return has_business_topic and has_template_suffix


def _business_template_quality(
    *,
    title: str,
    rows: list[list[str]],
    content_blocks: list[dict[str, Any]],
    extraction_mode: str,
    template_section_title: str,
) -> dict[str, Any]:
    paragraph_text = " ".join(
        str(block.get("text") or "").strip()
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "paragraph"
    )
    table_count = sum(
        1
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "table" and isinstance(block.get("rows"), list) and block.get("rows")
    )
    row_count = len(rows) if rows else sum(
        len(block.get("rows") or [])
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "table" and isinstance(block.get("rows"), list)
    )
    text_for_quality = f"{title} {paragraph_text} " + " ".join(" ".join(row) for row in rows if isinstance(row, list))
    issues: list[str] = []
    if not template_section_title:
        issues.append("未定位到投标文件格式/响应文件格式章节")
    if not _appendix_has_material_content(rows, content_blocks):
        issues.append("正文内容过少")
    if extraction_mode != "source_docx_slice" and str(extraction_mode).startswith("source_docx"):
        issues.append("原 DOCX 切片未成功")
    has_placeholder = any(token in text_for_quality for token in BUSINESS_TEMPLATE_PLACEHOLDER_TOKENS)
    has_completeness_token = any(token in text_for_quality for token in BUSINESS_TEMPLATE_COMPLETENESS_TOKENS)
    if issues:
        quality = "title_only" if "正文内容过少" in issues else "needs_review"
    elif table_count > 0 or row_count > 0 or (len(paragraph_text) >= 20 and (has_placeholder or has_completeness_token)):
        quality = "complete"
    else:
        quality = "probably_incomplete"
        issues.append("未识别到明显表格、签章栏或待填写占位")
    return {
        "extractionQuality": quality,
        "qualityIssues": issues,
        "needsReview": quality != "complete" or bool(issues),
        "contentStats": {
            "paragraphTextLength": len(paragraph_text),
            "tableCount": table_count,
            "rowCount": row_count,
            "hasPlaceholder": has_placeholder,
        },
    }


def _business_template_metadata(
    *,
    title: str,
    source_file: str,
    evidence: str,
    evidence_location: str,
    template_section_title: str,
    source_start: str,
    source_end: str,
    rows: list[list[str]],
    content_blocks: list[dict[str, Any]],
    extraction_mode: str,
) -> dict[str, Any]:
    template_type, template_type_label = _business_template_type(title)
    table_type, table_type_label, table_confidence, matched_tokens = _classify_business_table(rows, title)
    if table_type and template_type == "generic_attachment":
        template_type, template_type_label = table_type, table_type_label
    quality = _business_template_quality(
        title=title,
        rows=rows,
        content_blocks=content_blocks,
        extraction_mode=extraction_mode,
        template_section_title=template_section_title,
    )
    return {
        "artifactType": "business_attachment_template",
        "sourceMode": "parsed_from_tender_attachment_template",
        "templateType": template_type,
        "templateTypeLabel": template_type_label,
        "tableFingerprint": {
            "type": table_type,
            "typeLabel": table_type_label,
            "confidence": table_confidence,
            "matchedTokens": matched_tokens,
        },
        "templateSectionTitle": template_section_title,
        "templateSectionDetected": bool(template_section_title),
        "sourceFile": source_file,
        "evidence": evidence,
        "evidenceLocation": evidence_location,
        "sourceStart": source_start,
        "sourceEnd": source_end,
        "extractionMode": extraction_mode,
        "assetReviewStatus": "pending_review",
        "assetSyncStatus": "pending",
        "previewType": "onlyoffice",
        **quality,
    }


def _build_business_template_review_prompt(appendices: list[dict[str, Any]]) -> str:
    records = []
    for item in appendices[:BUSINESS_TEMPLATE_SEMANTIC_REVIEW_MAX_ITEMS]:
        content_blocks = item.get("contentBlocks") if isinstance(item.get("contentBlocks"), list) else []
        text_preview_parts: list[str] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "paragraph":
                text_preview_parts.append(str(block.get("text") or "").strip())
            elif block.get("type") == "table":
                rows = block.get("rows") if isinstance(block.get("rows"), list) else []
                text_preview_parts.append(" | ".join(" / ".join(str(cell) for cell in row) for row in rows[:3] if isinstance(row, list)))
        records.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "templateType": str(item.get("templateType") or ""),
                "templateSectionTitle": str(item.get("templateSectionTitle") or ""),
                "sourceStart": str(item.get("sourceStart") or ""),
                "sourceEnd": str(item.get("sourceEnd") or ""),
                "extractionMode": str(item.get("extractionMode") or ""),
                "extractionQuality": str(item.get("extractionQuality") or ""),
                "qualityIssues": item.get("qualityIssues") if isinstance(item.get("qualityIssues"), list) else [],
                "textPreview": "\n".join(part for part in text_preview_parts if part)[:1200],
            }
        )
    return (
        "你在做商务标解析阶段的附件模板语义校验。请判断每个候选是否确实是投标文件格式章节中可用于后续商务投标文件的模板/表格/承诺书格式。\n"
        "只输出 JSON，格式为：\n"
        "{\n"
        '  "decisions": [\n'
        '    {"id":"APPX-0001","action":"accept|review|reject","templateType":"bid_letter","quality":"complete|probably_incomplete|title_only","reason":"一句简短原因"}\n'
        "  ]\n"
        "}\n"
        "判断规则：\n"
        "1. 第六章、投标文件格式、响应文件格式、商务文件格式中的投标函、授权书、廉洁承诺、报价表、偏差表、资格/业绩表等通常 action=accept。\n"
        "2. 只有标题没有正文或表格的候选 action=review，quality=title_only，不要直接 reject。\n"
        "3. 普通条款、目录页、评分标准、技术参数承诺、非投标文件模板正文 action=reject。\n"
        "4. templateType 可按语义修正，例如 bid_letter、authorization、opening_price、commercial_deviation、performance_table、commitment、generic_attachment。\n\n"
        f"候选列表：\n{json.dumps(records, ensure_ascii=False, indent=2)}"
    )


def _review_business_attachment_templates_semantically(appendices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    candidates = [item for item in appendices if isinstance(item, dict) and item.get("artifactType") == "business_attachment_template"]
    if not candidates:
        return {}
    try:
        # 默认引擎经 AgentEngineFactory 取（默认恒为 opencode，行为不变）。
        result = _run_coroutine_blocking(AgentEngineFactory.create().review_business_attachment_templates_with_trace(
            _build_business_template_review_prompt(candidates)
        ))
    except RuntimeError:
        return {}
    decisions = result.get("decisions")
    if not isinstance(decisions, list):
        return {}
    reviewed: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        item_id = str(decision.get("id") or "").strip()
        if item_id:
            reviewed[item_id] = decision
    return reviewed


def _apply_business_template_semantic_review(
    appendices: list[dict[str, Any]],
    *,
    run_semantic_review: bool,
) -> list[dict[str, Any]]:
    if not appendices:
        return appendices
    reviewed = _review_business_attachment_templates_semantically(appendices) if run_semantic_review else {}
    prepared: list[dict[str, Any]] = []
    for item in appendices:
        if not isinstance(item, dict) or item.get("artifactType") != "business_attachment_template":
            prepared.append(item)
            continue
        result = copy.deepcopy(item)
        decision = reviewed.get(str(result.get("id") or ""))
        if isinstance(decision, dict):
            action = str(decision.get("action") or "").strip().lower()
            if action == "reject":
                result["semanticReviewStatus"] = "rejected"
                result["needsReview"] = True
                issues = result.get("qualityIssues") if isinstance(result.get("qualityIssues"), list) else []
                result["qualityIssues"] = [*issues, str(decision.get("reason") or "AI 判断该候选不是可用商务附件模板")]
                continue
            if action in {"accept", "review"}:
                result["semanticReviewStatus"] = action
                if str(decision.get("templateType") or "").strip():
                    result["templateType"] = str(decision.get("templateType") or "").strip()
                    result["templateTypeLabel"] = _business_template_type_label(str(result.get("templateType") or ""))
                if str(decision.get("quality") or "").strip():
                    result["extractionQuality"] = str(decision.get("quality") or "").strip()
                if action == "review" or result.get("extractionQuality") != "complete":
                    result["needsReview"] = True
                    issues = result.get("qualityIssues") if isinstance(result.get("qualityIssues"), list) else []
                    reason = str(decision.get("reason") or "").strip()
                    result["qualityIssues"] = [*issues, reason] if reason and reason not in issues else issues
                else:
                    result["needsReview"] = False
        else:
            result.setdefault("semanticReviewStatus", "not_run" if not run_semantic_review else "unavailable")
        prepared.append(result)
    return prepared


def _business_template_source_end_from_lines(lines: list[str], next_index: int) -> str:
    if 0 <= next_index < len(lines):
        return f"L{next_index + 1}: {str(lines[next_index]).strip()}"
    return "EOF"


def _business_template_source_start(section_title: str, location: str, text: str) -> str:
    start = f"{location}: {str(text or '').strip()}"
    section = str(section_title or "").strip()
    return f"{section} / {start}" if section else start


def _business_template_source_end_from_blocks(blocks: list[dict[str, Any]], next_index: int) -> str:
    if 0 <= next_index < len(blocks):
        block = blocks[next_index]
        return f"B{next_index + 1}: {str(block.get('text') or '').strip()}"
    return "EOF"


def _business_template_previous_state(blocks: list[dict[str, Any]], start_index: int) -> tuple[bool, str]:
    in_template_section = False
    template_section_title = ""
    for previous in range(0, min(start_index + 1, len(blocks))):
        block = blocks[previous]
        if block.get("type") != "paragraph":
            continue
        text = str(block.get("text") or "").strip()
        if _is_business_template_section_heading(text):
            in_template_section = True
            template_section_title = text
        elif in_template_section and _is_business_major_section_heading(text):
            in_template_section = False
            template_section_title = ""
    return in_template_section, template_section_title


def _detect_business_format_regions(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for index, block in enumerate(blocks):
        if block.get("type") != "paragraph":
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        rank = _block_heading_rank(block, text)
        is_start = _is_business_template_section_heading(text)
        if is_start:
            if active is not None:
                active["end"] = max(active["start"] + 1, index)
                regions.append(active)
            active = {
                "start": index,
                "end": len(blocks),
                "title": text,
                "rank": rank if rank is not None else 0,
            }
            continue
        if active is None:
            continue
        active_rank = int(active.get("rank") if isinstance(active.get("rank"), int) else 0)
        same_or_higher_heading = rank is not None and rank <= active_rank
        if same_or_higher_heading and (_is_business_format_end_heading(text) or _is_business_major_section_heading(text)):
            active["end"] = index
            regions.append(active)
            active = None
    if active is not None:
        regions.append(active)
    return regions


def _business_region_for_index(regions: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    for region in regions:
        start = region.get("start")
        end = region.get("end")
        if isinstance(start, int) and isinstance(end, int) and start <= index < end:
            return region
    return None


def _is_business_toc_or_directory_context(blocks: list[dict[str, Any]], index: int) -> bool:
    line = str(blocks[index].get("text") or "").strip()
    if _looks_like_toc_or_directory_line(line):
        return True

    for previous in range(index - 1, max(-1, index - 9), -1):
        previous_block = blocks[previous]
        if previous_block.get("type") != "paragraph":
            continue
        text = str(previous_block.get("text") or "").strip()
        if not text:
            continue
        if _is_business_template_section_heading(text) or _is_business_major_section_heading(text):
            return False
        if re.fullmatch(r"(?:目\s*录|目录|contents)", text, flags=re.IGNORECASE):
            return True
    return False


def _last_body_index_before(blocks: list[dict[str, Any]], end_index: int, fallback: int | None) -> int | None:
    for previous in range(min(end_index, len(blocks)) - 1, -1, -1):
        raw_body_index = blocks[previous].get("body_index")
        if isinstance(raw_body_index, int):
            return raw_body_index
    return fallback


def _is_relevant_appendix_heading(text: str, profile: ParseProfile) -> bool:
    if profile.key == "business":
        return _business_template_title_allowed(text)
    return _is_appendix_heading(text)


def _next_appendix_heading_index(blocks: list[dict[str, Any]], start_index: int, profile: ParseProfile) -> int:
    in_template_section = False
    if profile.key == "business":
        in_template_section, _ = _business_template_previous_state(blocks, start_index)
    for lookahead in range(start_index + 1, len(blocks)):
        next_block = blocks[lookahead]
        if next_block.get("type") != "paragraph":
            continue
        next_text = str(next_block.get("text") or "")
        if profile.key == "business":
            if _is_business_template_section_heading(next_text) or _is_business_major_section_heading(next_text):
                return lookahead
            if _business_template_title_allowed(next_text, in_template_section=in_template_section):
                return lookahead
        elif _is_relevant_appendix_heading(next_text, profile):
            return lookahead
    return len(blocks)


def _slice_content_blocks(blocks: list[dict[str, Any]], start_index: int, end_index: int) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for block in blocks[start_index + 1:end_index]:
        if block.get("type") == "paragraph":
            text = str(block.get("text") or "").strip()
            if text:
                content.append({"type": "paragraph", "text": text})
        elif block.get("type") == "table":
            rows = block.get("rows") if isinstance(block.get("rows"), list) else []
            if rows:
                content.append({"type": "table", "rows": rows})
    return content


def _previous_business_title_block_index(blocks: list[dict[str, Any]], table_index: int, region: dict[str, Any] | None) -> int | None:
    start = int(region.get("start")) if isinstance(region, dict) and isinstance(region.get("start"), int) else 0
    for previous in range(table_index - 1, max(start, table_index - 8) - 1, -1):
        block = blocks[previous]
        if block.get("type") != "paragraph":
            continue
        text = str(block.get("text") or "").strip()
        if not text or _looks_like_toc_or_directory_line(text):
            continue
        if _business_template_title_allowed(text, in_template_section=True):
            return previous
        if bool(block.get("isLikelyHeading")) and _has_business_attachment_topic(text):
            return previous
        if len(re.sub(r"\s+", "", text)) <= 36 and not _looks_like_business_template_body_sentence(text):
            return previous
    return None


def _appendix_title_has_trailing_page_number(text: str) -> bool:
    title = _appendix_title_for_match(text)
    return bool(re.search(r"\D\d{2,4}$", title))


def _is_docx_appendix_toc_artifact(blocks: list[dict[str, Any]], index: int) -> bool:
    line = str(blocks[index].get("text") or "").strip()
    if not _appendix_title_has_trailing_page_number(line):
        return False

    for lookahead in range(index + 1, min(len(blocks), index + 8)):
        next_block = blocks[lookahead]
        if next_block.get("type") == "table":
            return False
        if next_block.get("type") == "paragraph" and _is_appendix_heading(str(next_block.get("text") or "")):
            break

    nearby_headings = 0
    for nearby in range(max(0, index - 3), min(len(blocks), index + 4)):
        if nearby == index:
            continue
        block = blocks[nearby]
        if block.get("type") == "paragraph" and _is_appendix_heading(str(block.get("text") or "")):
            nearby_headings += 1

    return nearby_headings >= 1


def _extract_markdown_appendices(
    project_id: str,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    *,
    start_index: int = 0,
    profile: ParseProfile = TECHNICAL_PARSE_PROFILE,
) -> list[dict[str, Any]]:
    appendices: list[dict[str, Any]] = []
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".md":
            continue
        lines = texts_by_id.get(document_id, "").splitlines()
        index = 0
        in_template_section = False
        template_section_title = ""
        while index < len(lines):
            line = lines[index].strip()
            if profile.key == "business" and _is_business_template_section_heading(line):
                in_template_section = True
                template_section_title = line.strip(" #")
                index += 1
                continue
            if profile.key == "business" and in_template_section and _is_business_major_section_heading(line):
                in_template_section = False
                template_section_title = ""
            if profile.key == "business":
                is_heading = _business_template_title_allowed(
                    line,
                    in_template_section=in_template_section,
                )
            else:
                is_heading = _is_relevant_appendix_heading(line, profile)
            if not is_heading:
                index += 1
                continue
            if profile.key == "business" and not in_template_section:
                index += 1
                continue
            if _is_scoring_appendix_heading(line):
                index += 1
                continue

            title = line.strip(" #")
            table_start = index + 1
            while table_start < len(lines) and not MARKDOWN_TABLE_LINE_PATTERN.match(lines[table_start]):
                if profile.key != "business" and lines[table_start].strip() and not _is_relevant_appendix_heading(lines[table_start], profile):
                    break
                if (
                    profile.key == "business"
                    and lines[table_start].strip()
                    and (
                        _is_business_major_section_heading(lines[table_start])
                        or _business_template_title_allowed(
                            lines[table_start],
                            in_template_section=in_template_section,
                        )
                    )
                ):
                    break
                table_start += 1
            if profile.key == "business":
                next_heading = len(lines)
                for lookahead in range(index + 1, len(lines)):
                    lookahead_line = lines[lookahead].strip()
                    if (
                        _is_business_template_section_heading(lookahead_line)
                        or _is_business_major_section_heading(lookahead_line)
                        or _business_template_title_allowed(
                            lookahead_line,
                            in_template_section=in_template_section,
                        )
                    ):
                        next_heading = lookahead
                        break
            else:
                next_heading = table_start + 1 if table_start < len(lines) else index + 1
            if table_start >= len(lines) or not MARKDOWN_TABLE_LINE_PATTERN.match(lines[table_start]):
                content_blocks = [
                    {"type": "paragraph", "text": text.strip()}
                    for text in lines[index + 1:next_heading]
                    if text.strip()
                ]
                metadata = {}
                if profile.key == "business":
                    metadata = _business_template_metadata(
                        title=title,
                        source_file=source_file,
                        evidence=line,
                        evidence_location=f"L{index + 1}",
                        template_section_title=template_section_title,
                        source_start=_business_template_source_start(template_section_title, f"L{index + 1}", line),
                        source_end=_business_template_source_end_from_lines(lines, next_heading),
                        rows=[],
                        content_blocks=content_blocks,
                        extraction_mode="markdown_slice",
                    )
                    if not _business_template_should_materialize(metadata, [], content_blocks):
                        index = max(index + 1, next_heading)
                        continue
                appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
                appendices.append(materialize_appendix_docx(
                    project_id,
                    {
                        "id": appendix_id,
                        "title": title,
                        "status": "generated",
                        "rows": [],
                        "contentBlocks": content_blocks,
                        "rowCount": 0,
                        "docxPath": "",
                        **metadata,
                    },
                    profile=profile,
                ))
                index = max(index + 1, next_heading)
                continue

            rows: list[list[str]] = []
            table_end = table_start
            table_limit = next_heading if profile.key == "business" else len(lines)
            while table_end < table_limit and MARKDOWN_TABLE_LINE_PATTERN.match(lines[table_end]):
                cells = _parse_markdown_table_row(lines[table_end])
                if not _is_markdown_separator_row(cells):
                    rows.append(cells)
                table_end += 1
            content_blocks = [
                {"type": "paragraph", "text": text.strip()}
                for text in lines[index + 1:table_start]
                if text.strip()
            ]
            if rows:
                content_blocks.append({"type": "table", "rows": rows})
            if profile.key == "business":
                content_blocks.extend(
                    {"type": "paragraph", "text": text.strip()}
                    for text in lines[table_end:next_heading]
                    if text.strip()
                )
            metadata = (
                _business_template_metadata(
                    title=title,
                    source_file=source_file,
                    evidence=line,
                    evidence_location=f"L{index + 1}",
                    template_section_title=template_section_title,
                    source_start=_business_template_source_start(template_section_title, f"L{index + 1}", line),
                    source_end=_business_template_source_end_from_lines(lines, next_heading),
                    rows=rows,
                    content_blocks=content_blocks,
                    extraction_mode="markdown_slice",
                )
                if profile.key == "business"
                else {}
            )
            if profile.key == "business" and not _business_template_should_materialize(metadata, rows, content_blocks):
                index = max(table_end, next_heading)
                continue

            appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
            appendices.append(materialize_appendix_docx(
                project_id,
                {
                    "id": appendix_id,
                    "title": title,
                    "status": "generated",
                    "rows": rows,
                    "contentBlocks": content_blocks,
                    "rowCount": len(rows),
                    "docxPath": "",
                    **metadata,
                },
                profile=profile,
            ))
            index = max(table_end, next_heading)
    return appendices


def _docx_paragraph_text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(f"{WORD_NAMESPACE}t")).strip()


def _docx_xml_attr(element: Any, name: str) -> str:
    if element is None:
        return ""
    return str(element.get(f"{WORD_NAMESPACE}{name}") or element.get(name) or "").strip()


def _docx_paragraph_xml_outline_level(element: Any) -> int | None:
    p_pr = element.find(f"{WORD_NAMESPACE}pPr")
    if p_pr is None:
        return None
    outline = p_pr.find(f"{WORD_NAMESPACE}outlineLvl")
    if outline is not None:
        raw = _docx_xml_attr(outline, "val")
        if raw.isdigit():
            return int(raw)
    p_style = p_pr.find(f"{WORD_NAMESPACE}pStyle")
    raw_style = _docx_xml_attr(p_style, "val")
    match = re.search(r"(?:Heading|标题)\s*([1-9])", raw_style, flags=re.IGNORECASE)
    if match:
        return max(0, int(match.group(1)) - 1)
    return None


def _docx_paragraph_alignment_value(element: Any, paragraph: Any) -> str:
    alignment = getattr(paragraph, "alignment", None) if paragraph is not None else None
    if alignment is not None:
        value = getattr(alignment, "value", alignment)
        if str(value) in {"1", "CENTER", "WD_ALIGN_PARAGRAPH.CENTER"}:
            return "center"
    p_pr = element.find(f"{WORD_NAMESPACE}pPr")
    jc = p_pr.find(f"{WORD_NAMESPACE}jc") if p_pr is not None else None
    raw = _docx_xml_attr(jc, "val").lower()
    return raw


def _docx_paragraph_style_level(style_name: str) -> int | None:
    normalized = str(style_name or "").strip()
    match = re.search(r"(?:Heading|标题)\s*([1-9])", normalized, flags=re.IGNORECASE)
    if match:
        return max(0, int(match.group(1)) - 1)
    return None


def _docx_paragraph_metadata(element: Any, paragraph: Any, text: str) -> dict[str, Any]:
    style_name = str(getattr(getattr(paragraph, "style", None), "name", "") or "")
    outline_level = _docx_paragraph_xml_outline_level(element)
    style_level = _docx_paragraph_style_level(style_name)
    heading_level = outline_level if outline_level is not None else style_level
    alignment = _docx_paragraph_alignment_value(element, paragraph)
    runs = list(getattr(paragraph, "runs", []) or []) if paragraph is not None else []
    non_empty_runs = [run for run in runs if str(getattr(run, "text", "") or "").strip()]
    bold_runs = [run for run in non_empty_runs if bool(getattr(getattr(run, "font", None), "bold", False) or getattr(run, "bold", False))]
    font_sizes = []
    for run in non_empty_runs:
        size = getattr(getattr(run, "font", None), "size", None)
        if size is not None and getattr(size, "pt", None):
            font_sizes.append(float(size.pt))
    bold_ratio = (len(bold_runs) / len(non_empty_runs)) if non_empty_runs else 0.0
    normalized = re.sub(r"\s+", "", str(text or ""))
    is_short = 0 < len(normalized) <= 48
    is_likely_heading = bool(
        heading_level is not None
        or style_name.lower().startswith("heading")
        or "标题" in style_name
        or (alignment == "center" and is_short)
        or (bold_ratio >= 0.6 and is_short)
    )
    return {
        "styleName": style_name,
        "outlineLevel": outline_level,
        "styleLevel": style_level,
        "headingLevel": heading_level,
        "alignment": alignment,
        "isCentered": alignment == "center",
        "boldRatio": round(bold_ratio, 3),
        "fontSizeMax": max(font_sizes) if font_sizes else None,
        "isLikelyHeading": is_likely_heading,
    }


def _docx_table_rows(table: Any) -> list[list[str]]:
    return [[cell.text.strip() for cell in row.cells] for row in table.rows]


def _docx_table_has_cell_merges(table_element: Any) -> bool:
    return (
        table_element.find(f".//{WORD_NAMESPACE}gridSpan") is not None
        or table_element.find(f".//{WORD_NAMESPACE}vMerge") is not None
    )


def _iter_docx_blocks(path: Path) -> list[dict[str, Any]]:
    """Walk the docx body and yield {paragraph,table} blocks.

    Each block records ``body_index`` — its position among ``body.iterchildren()`` —
    so callers can map a block back to the original ``<w:p>`` / ``<w:tbl>`` element
    when slicing the source docx (see ``_slice_appendix_from_source``)."""

    doc = Document(str(path))
    tables = iter(doc.tables)
    paragraphs = iter(doc.paragraphs)
    blocks: list[dict[str, Any]] = []
    for body_index, child in enumerate(doc.element.body.iterchildren()):
        if child.tag == f"{WORD_NAMESPACE}p":
            paragraph = next(paragraphs, None)
            text = _docx_paragraph_text(child)
            blocks.append(
                {
                    "type": "paragraph",
                    "text": text,
                    "body_index": body_index,
                    **_docx_paragraph_metadata(child, paragraph, text),
                }
            )
        elif child.tag == f"{WORD_NAMESPACE}tbl":
            table = next(tables, None)
            if table is not None:
                blocks.append(
                    {
                        "type": "table",
                        "rows": _docx_table_rows(table),
                        "body_index": body_index,
                        "hasCellMerges": _docx_table_has_cell_merges(child),
                    }
                )
    return blocks


def _extract_docx_appendices(
    project_id: str,
    documents: list[dict[str, Any]],
    *,
    start_index: int = 0,
    profile: ParseProfile = TECHNICAL_PARSE_PROFILE,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    appendices: list[dict[str, Any]] = []
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".docx" or not source_path.exists():
            continue

        source_file = str(document.get("name") or source_path.name or "招标文件")
        def report_docx_appendix_scanning(metadata: dict[str, Any] | None = None) -> None:
            if progress_callback:
                payload = {"fileName": source_file}
                payload.update(metadata or {})
                progress_callback("docx_appendix_scanning", payload)

        report_docx_appendix_scanning()
        blocks = _run_with_progress_heartbeat(
            lambda: _iter_docx_blocks(source_path),
            heartbeat=report_docx_appendix_scanning,
            cancel_check=cancel_check,
        )
        _raise_if_parse_cancelled(cancel_check)
        business_regions = _detect_business_format_regions(blocks) if profile.key == "business" else []
        if profile.key == "technical":
            docx_appendix_total = sum(
                1
                for candidate_index, candidate in enumerate(blocks)
                if candidate.get("type") == "paragraph"
                and _is_relevant_appendix_heading(str(candidate.get("text") or "").strip(), profile)
                and not _is_scoring_appendix_heading(str(candidate.get("text") or "").strip())
                and not _is_docx_appendix_toc_artifact(blocks, candidate_index)
            )
        else:
            docx_appendix_total = 0
        generated_count = 0

        def report_docx_appendix_progress(title: str) -> None:
            nonlocal generated_count
            generated_count += 1
            if progress_callback:
                progress_callback(
                    "docx_appendix_progress",
                    {
                        "fileName": source_file,
                        "title": title,
                        "current": generated_count,
                        "total": max(docx_appendix_total, generated_count),
                    },
                )

        def report_docx_appendix_materializing(title: str, metadata: dict[str, Any] | None = None) -> None:
            if progress_callback:
                next_count = generated_count + 1
                payload = {
                    "fileName": source_file,
                    "title": title,
                    "current": next_count,
                    "total": max(docx_appendix_total, next_count),
                }
                payload.update(metadata or {})
                progress_callback("docx_appendix_materializing", payload)

        if progress_callback:
            progress_callback(
                "docx_appendix_started",
                {
                    "fileName": source_file,
                    "total": docx_appendix_total,
                },
            )
        # Build the expensive source slice cache only if an appendix really
        # needs verbatim DOCX slicing (for example, merged cells).
        source_state: dict[str, Any] | None = None

        def ensure_source_state() -> dict[str, Any] | None:
            nonlocal source_state
            if source_state is None:
                source_state = _run_with_progress_heartbeat(
                    lambda: _build_appendix_slice_state(source_path),
                    heartbeat=report_docx_appendix_scanning,
                    cancel_check=cancel_check,
                )
                _raise_if_parse_cancelled(cancel_check)
            return source_state

        used_tables: set[int] = set()
        in_template_section = False
        template_section_title = ""
        for index, block in enumerate(blocks):
            if block.get("type") != "paragraph":
                continue
            line = str(block.get("text") or "").strip()
            region = _business_region_for_index(business_regions, index) if profile.key == "business" else None
            if profile.key == "business" and _is_business_template_section_heading(line):
                in_template_section = True
                template_section_title = line
                continue
            if profile.key == "business" and in_template_section and _is_business_major_section_heading(line):
                in_template_section = False
                template_section_title = ""
            if profile.key == "business":
                is_heading = _business_template_title_allowed(
                    line,
                    in_template_section=in_template_section or region is not None,
                )
            else:
                is_heading = _is_relevant_appendix_heading(line, profile)
            if not is_heading:
                continue
            if _is_scoring_appendix_heading(line):
                continue
            if profile.key == "business":
                if not in_template_section and region is None:
                    continue
                if _is_business_toc_or_directory_context(blocks, index):
                    continue
            elif _is_docx_appendix_toc_artifact(blocks, index):
                continue

            title = line.strip(" #") or "附表"
            table_index = -1
            table_has_cell_merges = False
            rows: list[list[str]] = []
            table_body_index: int | None = None
            next_heading_index = _next_appendix_heading_index(blocks, index, profile)
            if profile.key == "business" and isinstance(region, dict) and isinstance(region.get("end"), int):
                next_heading_index = min(next_heading_index, int(region["end"]))
            search_limit = next_heading_index if profile.key == "business" else min(len(blocks), index + 8)
            for lookahead in range(index + 1, min(search_limit, index + 12)):
                next_block = blocks[lookahead]
                if next_block.get("type") == "table" and lookahead not in used_tables:
                    table_index = lookahead
                    table_has_cell_merges = bool(next_block.get("hasCellMerges"))
                    rows = next_block.get("rows") or []
                    raw_body_index = next_block.get("body_index")
                    table_body_index = raw_body_index if isinstance(raw_body_index, int) else None
                    break
            content_blocks = _slice_content_blocks(blocks, index, next_heading_index)

            appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
            heading_body_index_raw = block.get("body_index")
            heading_body_index = heading_body_index_raw if isinstance(heading_body_index_raw, int) else None
            slice_end_body_index = _last_body_index_before(blocks, next_heading_index, heading_body_index)
            metadata: dict[str, Any] = {}
            if profile.key == "business":
                section_title = template_section_title or str((region or {}).get("title") or "")
                metadata = _business_template_metadata(
                    title=title,
                    source_file=source_file,
                    evidence=line,
                    evidence_location=f"B{index + 1}",
                    template_section_title=section_title,
                    source_start=_business_template_source_start(section_title, f"B{index + 1}", line),
                    source_end=_business_template_source_end_from_blocks(blocks, next_heading_index),
                    rows=rows,
                    content_blocks=content_blocks,
                    extraction_mode="source_docx_slice",
                )
                if not _business_template_should_materialize(metadata, rows, content_blocks):
                    continue

            if table_index == -1 or not rows:
                appendix_payload = {
                    "id": appendix_id,
                    "title": title,
                    "status": "generated",
                    "sourceFile": source_file,
                    "evidence": line,
                    "evidenceLocation": f"B{index + 1}",
                    "rows": [],
                    "contentBlocks": content_blocks,
                    "rowCount": 0,
                    "docxPath": "",
                    **metadata,
                }
                if (
                    profile.key == "business"
                    and heading_body_index is not None
                    and slice_end_body_index is not None
                ):
                    source_state_for_slice = ensure_source_state()
                    appendix_payload["_slice"] = {
                        "sourcePath": str(source_path),
                        "keepStart": heading_body_index,
                        "keepEnd": slice_end_body_index,
                        "sourceState": source_state_for_slice,
                    }
                report_docx_appendix_materializing(title)
                appendices.append(
                    _run_with_progress_heartbeat(
                        lambda: materialize_appendix_docx(project_id, appendix_payload, profile=profile),
                        heartbeat=lambda metadata: report_docx_appendix_materializing(title, metadata),
                        cancel_check=cancel_check,
                    )
                )
                report_docx_appendix_progress(title)
                continue

            used_tables.add(table_index)
            appendix_payload: dict[str, Any] = {
                "id": appendix_id,
                "title": title,
                "status": "generated",
                "sourceFile": source_file,
                "evidence": line,
                "evidenceLocation": f"B{index + 1}",
                "rows": rows,
                "contentBlocks": content_blocks,
                "rowCount": len(rows),
                "docxPath": "",
                **metadata,
            }
            slice_keep_end = slice_end_body_index if profile.key == "business" else table_body_index
            should_use_source_slice = profile.key == "business" or table_has_cell_merges
            if heading_body_index is not None and slice_keep_end is not None and should_use_source_slice:
                source_state_for_slice = ensure_source_state()
                appendix_payload["_slice"] = {
                    "sourcePath": str(source_path),
                    "keepStart": heading_body_index,
                    "keepEnd": slice_keep_end,
                    "sourceState": source_state_for_slice,
                }
            report_docx_appendix_materializing(title)
            appendices.append(
                _run_with_progress_heartbeat(
                    lambda: materialize_appendix_docx(project_id, appendix_payload, profile=profile),
                    heartbeat=lambda metadata: report_docx_appendix_materializing(title, metadata),
                    cancel_check=cancel_check,
                )
            )
            report_docx_appendix_progress(title)
        if profile.key == "business":
            used_heading_indices = {
                int(str(item.get("evidenceLocation") or "B0").lstrip("B") or "0") - 1
                for item in appendices
                if isinstance(item, dict) and str(item.get("evidenceLocation") or "").startswith("B")
            }
            for table_index, table_block in enumerate(blocks):
                if table_index in used_tables or table_block.get("type") != "table":
                    continue
                region = _business_region_for_index(business_regions, table_index)
                if region is None:
                    continue
                rows = table_block.get("rows") if isinstance(table_block.get("rows"), list) else []
                table_type, table_label, table_confidence, matched_tokens = _classify_business_table(rows)
                if not table_type or table_confidence < 0.62:
                    continue
                title_index = _previous_business_title_block_index(blocks, table_index, region)
                heading_index = title_index if title_index is not None else table_index
                if title_index is not None and title_index in used_heading_indices:
                    continue
                title = (
                    str(blocks[title_index].get("text") or "").strip()
                    if title_index is not None
                    else table_label
                ) or table_label
                content_blocks = _slice_content_blocks(blocks, heading_index, min(table_index + 1, len(blocks)))
                if not any(block.get("type") == "table" for block in content_blocks if isinstance(block, dict)):
                    content_blocks.append({"type": "table", "rows": rows})
                section_title = str(region.get("title") or "")
                metadata = _business_template_metadata(
                    title=title,
                    source_file=source_file,
                    evidence=title,
                    evidence_location=f"B{heading_index + 1}",
                    template_section_title=section_title,
                    source_start=_business_template_source_start(section_title, f"B{heading_index + 1}", title),
                    source_end=_business_template_source_end_from_blocks(blocks, min(table_index + 1, len(blocks))),
                    rows=rows,
                    content_blocks=content_blocks,
                    extraction_mode="source_docx_table_fingerprint",
                )
                metadata["templateType"] = table_type
                metadata["templateTypeLabel"] = _business_template_type_label_for_key(table_type)
                metadata["tableFingerprint"] = {
                    "type": table_type,
                    "typeLabel": table_label,
                    "confidence": table_confidence,
                    "matchedTokens": matched_tokens,
                }
                if not _business_template_should_materialize(metadata, rows, content_blocks):
                    continue
                appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
                heading_body_index_raw = blocks[heading_index].get("body_index") if 0 <= heading_index < len(blocks) else table_block.get("body_index")
                table_body_index_raw = table_block.get("body_index")
                heading_body_index = heading_body_index_raw if isinstance(heading_body_index_raw, int) else None
                table_body_index = table_body_index_raw if isinstance(table_body_index_raw, int) else None
                payload: dict[str, Any] = {
                    "id": appendix_id,
                    "title": title,
                    "status": "generated",
                    "sourceFile": source_file,
                    "evidence": title,
                    "evidenceLocation": f"B{heading_index + 1}",
                    "rows": rows,
                    "contentBlocks": content_blocks,
                    "rowCount": len(rows),
                    "docxPath": "",
                    **metadata,
                }
                if heading_body_index is not None and table_body_index is not None:
                    source_state_for_slice = ensure_source_state()
                    payload["_slice"] = {
                        "sourcePath": str(source_path),
                        "keepStart": heading_body_index,
                        "keepEnd": table_body_index,
                        "sourceState": source_state_for_slice,
                    }
                used_tables.add(table_index)
                report_docx_appendix_materializing(title)
                appendices.append(
                    _run_with_progress_heartbeat(
                        lambda: materialize_appendix_docx(project_id, payload, profile=profile),
                        heartbeat=lambda metadata: report_docx_appendix_materializing(title, metadata),
                        cancel_check=cancel_check,
                    )
                )
                report_docx_appendix_progress(title)
        if progress_callback:
            progress_callback(
                "docx_appendix_finished",
                {
                    "fileName": source_file,
                    "current": generated_count,
                    "total": max(docx_appendix_total, generated_count),
                },
            )
    return appendices


# parsing-01 接缝：parse_business_fields 的 3 处函数体经模块全局引用
# `_iter_docx_blocks`、`_detect_business_format_regions`。两模块互有引用
# （本模块自 parse_business_fields import 表格行工具），反向直接 import 会成环，
# 故在本模块装配完成后注入其模块全局，被引用函数体保持逐字不变。
import app.services.parse_business_fields as _parse_business_fields  # noqa: E402

_parse_business_fields._iter_docx_blocks = _iter_docx_blocks
_parse_business_fields._detect_business_format_regions = _detect_business_format_regions
