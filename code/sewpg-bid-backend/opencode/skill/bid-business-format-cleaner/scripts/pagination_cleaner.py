#!/usr/bin/env python3
"""清理多余空白页，并在小节正文后补齐分页符。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

try:
    from outline_matcher import flatten_outline, load_outline
except ImportError:  # pragma: no cover
    from .outline_matcher import flatten_outline, load_outline


def clean_section_page_breaks(docx_path: str | Path, outline_file: str | Path | None = None) -> dict[str, Any]:
    """按标题边界清理分页。

    该步骤依赖正文标题已被提升为 Word Heading 样式。outline_file 作为命令行语义保留，
    当前判断以文档中的 Heading 段落为准，避免在缺失标题处插入或移动正文。
    """
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"docx 不存在: {path}")
    if outline_file is not None and not Path(outline_file).exists():
        raise FileNotFoundError(f"outlineFile 不存在: {outline_file}")

    doc = Document(str(path))
    outline_items = _load_outline_items(outline_file)
    result = _clean_until_stable(doc, outline_items)
    if any(result.values()):
        doc.save(str(path))
    return result


def _load_outline_items(outline_file: str | Path | None) -> list[dict[str, Any]]:
    if outline_file is None:
        return []
    return flatten_outline(load_outline(outline_file))


def _body_children(doc: Document):
    return [child for child in list(doc.element.body) if child.tag != qn("w:sectPr")]


def _clean_until_stable(doc: Document, outline_items: list[dict[str, Any]]) -> dict[str, int]:
    result = {
        "insertedPageBreaks": 0,
        "removedBlankParagraphs": 0,
        "removedBlankPageBreaks": 0,
    }

    for _ in range(8):
        iteration = _clean_once(doc, outline_items)
        result["insertedPageBreaks"] += iteration["insertedPageBreaks"]
        result["removedBlankParagraphs"] += iteration["removedBlankParagraphs"]
        result["removedBlankPageBreaks"] += iteration["removedBlankPageBreaks"]
        if not any(iteration.values()):
            break

    return result


def _clean_once(doc: Document, outline_items: list[dict[str, Any]]) -> dict[str, int]:
    first_cleanup = _collapse_redundant_blank_pages(doc)
    toc_cleanup = _remove_toc_trailing_blank_page(doc)
    section_cleanup = _remove_internal_section_page_breaks(doc, outline_items)
    inserted = _insert_missing_section_breaks(doc, outline_items)
    second_cleanup = _collapse_redundant_blank_pages(doc)

    return {
        "insertedPageBreaks": inserted,
        "removedBlankParagraphs": (
            first_cleanup["removedBlankParagraphs"]
            + toc_cleanup["removedBlankParagraphs"]
            + second_cleanup["removedBlankParagraphs"]
        ),
        "removedBlankPageBreaks": (
            first_cleanup["removedBlankPageBreaks"]
            + section_cleanup["removedInternalPageBreaks"]
            + section_cleanup["removedHeadingPageBreaks"]
            + toc_cleanup["removedBlankPageBreaks"]
            + second_cleanup["removedBlankPageBreaks"]
        ),
    }


def _collapse_redundant_blank_pages(doc: Document) -> dict[str, int]:
    removed_blank_paragraphs = 0
    removed_blank_page_breaks = 0
    page_break_seen_since_content = False

    for child in list(_body_children(doc)):
        if _is_transparent_element(child):
            continue

        if _is_blank_paragraph(child):
            if page_break_seen_since_content:
                _remove_element(child)
                removed_blank_paragraphs += 1
            continue

        if _is_page_break_only_paragraph(child):
            _keep_single_page_break(child)
            if page_break_seen_since_content:
                _remove_element(child)
                removed_blank_page_breaks += 1
            else:
                page_break_seen_since_content = True
            continue

        if _element_has_page_break(child):
            page_break_seen_since_content = True
            continue

        page_break_seen_since_content = False

    return {
        "removedBlankParagraphs": removed_blank_paragraphs,
        "removedBlankPageBreaks": removed_blank_page_breaks,
    }


def _remove_toc_trailing_blank_page(doc: Document) -> dict[str, int]:
    removed_blank_paragraphs = 0
    removed_blank_page_breaks = 0
    children = _body_children(doc)
    toc_index = next((index for index, child in enumerate(children) if _element_has_toc_field(child)), None)
    if toc_index is None:
        return {"removedBlankParagraphs": 0, "removedBlankPageBreaks": 0}

    stop_index = _next_visible_content_index(children, toc_index + 1)
    if stop_index is None:
        return {"removedBlankParagraphs": 0, "removedBlankPageBreaks": 0}

    for child in children[toc_index + 1 : stop_index]:
        if _element_has_section_properties(child):
            continue
        if _is_blank_paragraph(child):
            _remove_element(child)
            removed_blank_paragraphs += 1
        elif _is_page_break_only_paragraph(child):
            _remove_element(child)
            removed_blank_page_breaks += 1

    return {
        "removedBlankParagraphs": removed_blank_paragraphs,
        "removedBlankPageBreaks": removed_blank_page_breaks,
    }


def _next_visible_content_index(children: list[Any], start_index: int) -> int | None:
    for index in range(start_index, len(children)):
        child = children[index]
        if _is_transparent_element(child) or _is_blank_paragraph(child) or _is_page_break_only_paragraph(child):
            continue
        return index
    return None


def _insert_missing_section_breaks(doc: Document, outline_items: list[dict[str, Any]]) -> int:
    inserted = 0
    children = _body_children(doc)
    heading_indexes = _heading_indexes(children, outline_items)

    for pos, heading_index in enumerate(heading_indexes[:-1]):
        next_heading_index = heading_indexes[pos + 1]
        segment = children[heading_index + 1 : next_heading_index]
        last_content_offset = _last_content_offset(segment)
        if last_content_offset is None:
            continue

        if _segment_has_boundary_page_break(segment, last_content_offset):
            continue

        children[next_heading_index].addprevious(_make_page_break_paragraph())
        inserted += 1

    return inserted


def _remove_internal_section_page_breaks(doc: Document, outline_items: list[dict[str, Any]]) -> dict[str, int]:
    removed = 0
    removed_heading_page_breaks = 0
    children = _body_children(doc)
    heading_indexes = _heading_indexes(children, outline_items)

    for pos, heading_index in enumerate(heading_indexes[:-1]):
        next_heading_index = heading_indexes[pos + 1]
        segment = children[heading_index + 1 : next_heading_index]
        last_content_offset = _last_content_offset(segment)
        if last_content_offset is None:
            continue

        if not _segment_has_boundary_page_break(segment, last_content_offset):
            continue

        removed_heading_page_breaks += _remove_leading_page_breaks(children[next_heading_index])

        for child in segment[:last_content_offset]:
            if not _is_page_break_only_paragraph(child):
                continue
            _remove_element(child)
            removed += 1

    return {
        "removedInternalPageBreaks": removed,
        "removedHeadingPageBreaks": removed_heading_page_breaks,
    }


def _remove_leading_page_breaks(paragraph) -> int:
    if paragraph.tag != qn("w:p"):
        return 0

    removed = 0
    for child in list(paragraph):
        if _is_ignorable_paragraph_prefix(child):
            continue
        if child.tag != qn("w:r"):
            break
        if _run_is_page_break_only(child):
            _remove_element(child)
            removed += 1
            continue
        break
    return removed


def _is_ignorable_paragraph_prefix(element) -> bool:
    return element.tag == qn("w:pPr") or _is_transparent_element(element)


def _run_is_page_break_only(run) -> bool:
    if run.tag != qn("w:r"):
        return False
    has_page_break = False
    for child in run:
        if child.tag == qn("w:rPr"):
            continue
        if child.tag == qn("w:br") and child.get(qn("w:type")) == "page":
            has_page_break = True
            continue
        return False
    return has_page_break


def _segment_has_boundary_page_break(segment: list[Any], last_content_offset: int) -> bool:
    if _element_has_page_break(segment[last_content_offset]):
        return True
    tail = segment[last_content_offset + 1 :]
    return any(_element_has_page_break(child) for child in tail if _is_page_boundary_tail_element(child))


def _heading_indexes(children: list[Any], outline_items: list[dict[str, Any]]) -> list[int]:
    outline_indexes = _outline_heading_indexes(children, outline_items)
    if outline_indexes:
        return outline_indexes
    return [index for index, child in enumerate(children) if _is_heading_paragraph(child)]


def _outline_heading_indexes(children: list[Any], outline_items: list[dict[str, Any]]) -> list[int]:
    if not outline_items:
        return []

    indexes: list[int] = []
    cursor = 0
    for item in outline_items:
        found = _find_outline_heading(children, item, cursor)
        if found is None:
            continue
        indexes.append(found)
        cursor = found + 1
    return indexes


def _find_outline_heading(children: list[Any], item: dict[str, Any], start_index: int) -> int | None:
    full_key = _normalize_match_text(_format_heading_text(item)) if item.get("number") else ""
    title_key = _normalize_match_text(str(item.get("title") or ""))
    for index in range(start_index, len(children)):
        child = children[index]
        if child.tag != qn("w:p"):
            continue
        text_key = _normalize_match_text(_paragraph_text(child))
        if not text_key:
            continue
        if full_key and text_key == full_key:
            return index
        if title_key and text_key == title_key:
            return index
    return None


def _format_heading_text(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    number = str(item.get("number") or "").strip()
    return f"{number} {title}".strip() if number else title


def _normalize_match_text(text: str) -> str:
    normalized = str(text or "").strip().replace("\u3000", " ")
    return re.sub(r"\s+", "", normalized)


def _last_content_offset(elements: list[Any]) -> int | None:
    for offset in range(len(elements) - 1, -1, -1):
        if _is_section_body_content(elements[offset]):
            return offset
    return None


def _is_section_body_content(element) -> bool:
    if _is_transparent_element(element):
        return False
    if element.tag == qn("w:tbl"):
        return True
    if element.tag != qn("w:p"):
        return _has_visible_payload(element)
    if _is_heading_paragraph(element):
        return False
    if _is_blank_paragraph(element) or _is_page_break_only_paragraph(element):
        return False
    return _has_visible_payload(element)


def _is_heading_paragraph(element) -> bool:
    if element.tag != qn("w:p"):
        return False
    p_style = element.find(qn("w:pPr") + "/" + qn("w:pStyle"))
    if p_style is None:
        return False
    value = p_style.get(qn("w:val")) or ""
    compact = value.replace(" ", "")
    return compact.startswith("Heading") and compact[7:].isdigit()


def _is_blank_paragraph(element) -> bool:
    if element.tag != qn("w:p"):
        return False
    return not _paragraph_text(element).strip() and not _element_has_page_break(element) and not _has_non_text_payload(element)


def _is_page_break_only_paragraph(element) -> bool:
    if element.tag != qn("w:p"):
        return False
    return _element_has_page_break(element) and not _paragraph_text(element).strip() and not _has_non_text_payload(element)


def _is_page_boundary_tail_element(element) -> bool:
    return _is_transparent_element(element) or _is_blank_paragraph(element) or _element_has_page_break(element)


def _is_transparent_element(element) -> bool:
    transparent_tags = {
        qn("w:bookmarkStart"),
        qn("w:bookmarkEnd"),
        qn("w:commentRangeStart"),
        qn("w:commentRangeEnd"),
        qn("w:moveFromRangeStart"),
        qn("w:moveFromRangeEnd"),
        qn("w:moveToRangeStart"),
        qn("w:moveToRangeEnd"),
        qn("w:customXmlInsRangeStart"),
        qn("w:customXmlInsRangeEnd"),
        qn("w:customXmlDelRangeStart"),
        qn("w:customXmlDelRangeEnd"),
        qn("w:customXmlMoveFromRangeStart"),
        qn("w:customXmlMoveFromRangeEnd"),
        qn("w:customXmlMoveToRangeStart"),
        qn("w:customXmlMoveToRangeEnd"),
        qn("w:permStart"),
        qn("w:permEnd"),
        qn("w:proofErr"),
    }
    return element.tag in transparent_tags


def _element_has_toc_field(element) -> bool:
    return any("TOC" in (node.text or "").upper() for node in element.iter(qn("w:instrText")))


def _element_has_section_properties(element) -> bool:
    return element.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None


def _element_has_page_break(element) -> bool:
    return any(br.get(qn("w:type")) == "page" for br in element.iter(qn("w:br")))


def _paragraph_text(element) -> str:
    return "".join(node.text or "" for node in element.iter(qn("w:t")))


def _has_visible_payload(element) -> bool:
    return bool(_paragraph_text(element).strip()) or _has_non_text_payload(element)


def _has_non_text_payload(element) -> bool:
    payload_tags = {
        qn("w:drawing"),
        qn("w:pict"),
        qn("w:object"),
        qn("w:fldChar"),
        qn("w:instrText"),
    }
    return any(node.tag in payload_tags for node in element.iter())


def _keep_single_page_break(paragraph) -> None:
    kept = False
    for br in list(paragraph.iter(qn("w:br"))):
        if br.get(qn("w:type")) != "page":
            continue
        if not kept:
            kept = True
            continue
        _remove_element(br)


def _make_page_break_paragraph():
    paragraph = OxmlElement("w:p")
    run = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run.append(br)
    paragraph.append(run)
    return paragraph


def _remove_element(element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清理商务标 DOCX 多余空白页，并补齐小节正文后分页符")
    parser.add_argument("docx")
    parser.add_argument("--outline")
    args = parser.parse_args(argv)

    result = clean_section_page_breaks(args.docx, args.outline)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
