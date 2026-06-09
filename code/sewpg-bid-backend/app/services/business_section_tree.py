from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
SECTION_TREE_SCHEMA = "bid-business-section-tree-v1"
MAX_SECTION_LEVEL = 3

QUALIFICATION_TITLE_KEYWORDS = (
    "投标人资格要求",
    "供应商资格要求",
    "框架供应商资格要求",
    "资格能力要求",
    "资格条件",
    "通用资格条件",
    "专用资格条件",
)
BIDDER_INSTRUCTION_TITLE_KEYWORDS = (
    "投标人须知前附表",
    "供应商须知前附表",
    "框架供应商须知前附表",
    "谈判采购供应商须知前附表",
)
SCORING_TITLE_KEYWORDS = ("商务评分标准", "商务评分", "评分标准", "评审办法", "评标办法")
GENERAL_SECTION_TITLE_KEYWORDS = (
    "招标公告",
    "采购公告",
    "投标人须知",
    "供应商须知",
    "评标办法",
    "评审办法",
    "投标文件格式",
    "响应文件格式",
    "合同条款",
)
REGEX_HEADING_EXCLUDE_CUES = (
    "须",
    "应",
    "需",
    "具有",
    "具备",
    "提供",
    "不得",
    "不接受",
    "见",
    "证明",
    "评分",
    "得分",
    "加分",
    "规定",
    "下列",
    "如下",
    "遵守",
    "程序",
    "接受",
)


def _w_attr(name: str) -> str:
    return f"{W}{name}"


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def _paragraph_text(element: ET.Element) -> str:
    pieces: list[str] = []
    for node in element.iter():
        if node.tag == f"{W}t":
            pieces.append(node.text or "")
        elif node.tag == f"{W}tab":
            pieces.append("\t")
        elif node.tag in {f"{W}br", f"{W}cr"}:
            pieces.append("\n")
    return _clean("".join(pieces))


def _style_id(element: ET.Element) -> str:
    p_pr = element.find(f"{W}pPr")
    if p_pr is None:
        return ""
    p_style = p_pr.find(f"{W}pStyle")
    if p_style is None:
        return ""
    return str(p_style.attrib.get(_w_attr("val")) or "").strip()


def _outline_level(element: ET.Element) -> int | None:
    p_pr = element.find(f"{W}pPr")
    if p_pr is None:
        return None
    outline = p_pr.find(f"{W}outlineLvl")
    if outline is None:
        return None
    raw = str(outline.attrib.get(_w_attr("val")) or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _read_xml(archive: zipfile.ZipFile, member: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(member))
    except Exception:
        return None


def _style_level_from_name(name: str) -> int | None:
    text = str(name or "")
    match = re.search(r"(?:Heading|标题)\s*([1-9])|Heading([1-9])", text, flags=re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    if not raw or not raw.isdigit():
        return None
    level = int(raw)
    return level if 1 <= level <= MAX_SECTION_LEVEL else None


def _load_paragraph_styles(archive: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    root = _read_xml(archive, "word/styles.xml")
    if root is None:
        return {}
    styles: dict[str, dict[str, Any]] = {}
    for style in root.iter(f"{W}style"):
        if str(style.attrib.get(_w_attr("type")) or "") != "paragraph":
            continue
        style_id = str(style.attrib.get(_w_attr("styleId")) or "").strip()
        if not style_id:
            continue
        name_node = style.find(f"{W}name")
        name = str(name_node.attrib.get(_w_attr("val")) or "").strip() if name_node is not None else ""
        outline = _outline_level(style)
        styles[style_id] = {
            "name": name,
            "outlineLevel": outline,
            "headingLevel": _style_level_from_name(f"{style_id} {name}"),
        }
    return styles


def _looks_like_toc_heading(text: str) -> bool:
    cleaned = _clean(text)
    compact = re.sub(r"\s+", "", cleaned)
    return compact == "目录" or (len(compact) <= 10 and "目录" in compact)


def _strip_toc_page_suffix(text: str) -> str:
    cleaned = _clean(text)
    cleaned = re.sub(r"(?:\.{2,}|…{2,}|·{2,}|\t+)\s*\d+\s*$", "", cleaned).strip()
    return re.sub(r"\s+\d{1,4}\s*$", "", cleaned).strip()


def _toc_title_from_line(text: str) -> str:
    cleaned = _clean(text)
    if not cleaned or _looks_like_toc_heading(cleaned):
        return ""
    if not (
        re.search(r"(?:\.{2,}|…{2,}|·{2,}|\t+)\s*\d+\s*$", cleaned)
        or re.search(r"\s+\d{1,4}\s*$", cleaned)
    ):
        return ""
    title = _strip_toc_page_suffix(cleaned)
    if _looks_like_toc_heading(title):
        return ""
    if title == cleaned and not re.match(r"^(?:第.+章|\d+(?:\.\d+)*[.．、]?\s+|[一二三四五六七八九十]+[、.．])", cleaned):
        return ""
    return title if 2 <= len(title) <= 90 else ""


def _looks_like_toc_line(text: str) -> bool:
    return bool(_toc_title_from_line(text))


def _toc_item_title(text: str) -> str:
    cleaned = _clean(text)
    title = _toc_title_from_line(cleaned)
    if title:
        return title
    if _looks_like_plain_toc_item(cleaned):
        return cleaned
    return ""


def _looks_like_plain_toc_item(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned or len(cleaned) > 90 or _looks_like_toc_heading(cleaned):
        return False
    if _looks_like_toc_line(cleaned):
        return True
    return bool(
        re.match(r"^第[一二三四五六七八九十百千0-9]+章(?:\s|[、.．：:]|$)", cleaned)
        or re.match(r"^第[一二三四五六七八九十百千0-9]+节(?:\s|[、.．：:]|$)", cleaned)
        or re.match(r"^(?:附件|附表)\s*\d+\s*\S+", cleaned)
        or re.match(r"^表\s*\d+\s*\S+", cleaned)
        or re.match(r"^\d+(?:\.\d+)*[.．、]\s*\S+", cleaned)
        or re.match(r"^[一二三四五六七八九十百]+[、.．]\s*\S+", cleaned)
    )


def _extract_number(text: str) -> str:
    cleaned = _clean(text)
    compact = re.sub(r"\s+", "", cleaned)
    match = re.match(r"^(第[一二三四五六七八九十百千0-9]+[章节卷篇])", compact)
    if match:
        return match.group(1)
    match = re.match(r"^(\d+(?:\.\d+)*[.．、]?)", cleaned)
    if match:
        return match.group(1)
    match = re.match(r"^([一二三四五六七八九十百千]+[、.．])", cleaned)
    return match.group(1) if match else ""


def _is_top_level_toc_title(text: str) -> bool:
    compact = re.sub(r"\s+", "", _clean(text))
    return bool(re.match(r"^第[一二三四五六七八九十百千0-9]+(?:章|卷|篇|部分)(?:[、.．：:]|$|.+)", compact))


def _is_section_toc_title(text: str) -> bool:
    compact = re.sub(r"\s+", "", _clean(text))
    return bool(re.match(r"^第[一二三四五六七八九十百千0-9]+节(?:[、.．：:]|$|.+)", compact))


def _is_plain_toc_container_title(text: str) -> bool:
    cleaned = _clean(text)
    if _extract_number(cleaned):
        return False
    return 2 <= len(cleaned) <= 40 and any(keyword in cleaned for keyword in ("文件", "前附表", "总说明"))


def _is_attachment_toc_title(text: str) -> bool:
    cleaned = _clean(text)
    return bool(re.match(r"^(?:附件|附表)\s*\d+|^表\s*\d+", cleaned))


def _toc_level_from_title(text: str, *, has_chapter_entries: bool) -> int:
    cleaned = _clean(text)
    if _is_top_level_toc_title(cleaned):
        return 1
    if _is_section_toc_title(cleaned):
        return 2
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[.．、]|\s+)", cleaned)
    if match:
        part_count = len(match.group(1).split("."))
        if has_chapter_entries:
            return min(MAX_SECTION_LEVEL, part_count + 1)
        return min(MAX_SECTION_LEVEL, part_count)
    if has_chapter_entries and re.match(r"^表\s*\d+", cleaned):
        return 3
    if re.match(r"^[一二三四五六七八九十百千]+[、.．]\s*\S+", cleaned):
        return 2 if has_chapter_entries else 1
    return 1


def _assign_toc_entry_levels(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_chapter_entries = any(_is_top_level_toc_title(str(entry.get("title") or "")) for entry in entries)
    leveled: list[dict[str, Any]] = []
    has_seen_top_level = False
    previous_plain_container_level = 0
    for entry in entries:
        updated = dict(entry)
        title = str(entry.get("title") or "")
        level = _toc_level_from_title(title, has_chapter_entries=has_chapter_entries)
        if has_chapter_entries:
            if _is_top_level_toc_title(title):
                level = 1
                has_seen_top_level = True
                previous_plain_container_level = 0
            elif _is_attachment_toc_title(title) and has_seen_top_level:
                level = 2
                previous_plain_container_level = 2
            elif _is_plain_toc_container_title(title) and has_seen_top_level:
                level = 2
                previous_plain_container_level = 2
            elif re.match(r"^[一二三四五六七八九十百千]+[、.．]\s*\S+", _clean(title)) and previous_plain_container_level == 2:
                level = 3
            elif re.match(r"^表\s*\d+", _clean(title)):
                level = 3
                previous_plain_container_level = 0
            else:
                previous_plain_container_level = 0
        updated["level"] = level
        leveled.append(updated)
    return leveled


def _is_detailed_toc(entries: list[dict[str, Any]], located_count: int) -> bool:
    if len(entries) < 5:
        return False
    levels = [int(entry.get("level") or 1) for entry in entries]
    has_deep_entries = any(level >= 3 for level in levels)
    has_many_sub_entries = sum(1 for level in levels if level >= 2) >= 4
    if not (has_deep_entries or has_many_sub_entries):
        return False
    return located_count >= max(3, int(len(entries) * 0.6))


def _is_usable_body_structure(headings: list[dict[str, Any]]) -> bool:
    if len(headings) >= 12:
        return True
    level_one_count = sum(1 for heading in headings if int(heading.get("level") or 0) == 1)
    return len(headings) >= 4 and level_one_count >= 2


def _keyword_heading_level(text: str, *, has_level_one: bool) -> int | None:
    cleaned = _clean(text)
    if len(cleaned) > 45 or cleaned.endswith(("。", "；", ";", "：", ":")):
        return None
    if any(keyword in cleaned for keyword in BIDDER_INSTRUCTION_TITLE_KEYWORDS):
        return 2 if has_level_one else 1
    if any(keyword in cleaned for keyword in QUALIFICATION_TITLE_KEYWORDS):
        return 2 if has_level_one else 1
    if any(keyword in cleaned for keyword in SCORING_TITLE_KEYWORDS):
        return 2 if has_level_one else 1
    if any(keyword in cleaned for keyword in GENERAL_SECTION_TITLE_KEYWORDS):
        return 1
    return None


def _looks_like_non_heading_text(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned:
        return True
    if re.fullmatch(r"20\d{2}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?", cleaned):
        return True
    if re.match(r"^[^:：]{2,60}[:：]\s*\S+", cleaned):
        return True
    if cleaned.endswith(("。", "；", ";", "：", ":")) and not re.match(
        r"^第[一二三四五六七八九十百千0-9]+[章节](?:\s|[、.．：:]|$)", cleaned
    ):
        return True
    return False


def _regex_heading_level(text: str, *, has_level_one: bool) -> int | None:
    cleaned = _clean(text)
    if not cleaned or len(cleaned) > 70 or _looks_like_toc_heading(cleaned) or _looks_like_toc_line(cleaned):
        return None
    if re.search(r"[=＝×%％]|万元|元|费率|金额", cleaned):
        return None
    if _looks_like_non_heading_text(cleaned):
        return None
    if re.match(r"^第[一二三四五六七八九十百千0-9]+章(?:\s|[、.．：:]|$)", cleaned):
        return 1
    if re.match(r"^第[一二三四五六七八九十百千0-9]+节(?:\s|[、.．：:]|$)", cleaned):
        return 2
    keyword_level = _keyword_heading_level(cleaned, has_level_one=has_level_one)
    if keyword_level is not None:
        return keyword_level
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[．、]|\s+|[.](?!\d))\s*(.+)$", cleaned)
    if match:
        title_tail = match.group(2).strip()
        part_count = len(match.group(1).split("."))
        if part_count > MAX_SECTION_LEVEL:
            return None
        if len(title_tail) <= 45 and not any(cue in title_tail for cue in REGEX_HEADING_EXCLUDE_CUES):
            if part_count == 1:
                return 2 if has_level_one else 1
            return min(MAX_SECTION_LEVEL, part_count + (1 if has_level_one else 0))
    if re.match(r"^[一二三四五六七八九十百]+[、.．]\s*\S+", cleaned):
        return 2 if has_level_one else 1
    return None


def _heading_from_block(
    block: dict[str, Any],
    styles: dict[str, dict[str, Any]],
    *,
    has_level_one: bool,
    in_toc: bool = False,
    allow_regex: bool = True,
) -> dict[str, Any] | None:
    if block.get("type") != "paragraph":
        return None
    text = _clean(block.get("text"))
    if not text or _looks_like_toc_heading(text) or (in_toc and _looks_like_toc_line(text)):
        return None
    if _looks_like_non_heading_text(text):
        return None
    direct_outline = block.get("outlineLevel")
    if isinstance(direct_outline, int) and 0 <= direct_outline < MAX_SECTION_LEVEL:
        return {"level": direct_outline + 1, "source": "outline", "confidence": 0.98}
    style = styles.get(str(block.get("styleId") or "")) or {}
    style_outline = style.get("outlineLevel")
    if isinstance(style_outline, int) and 0 <= style_outline < MAX_SECTION_LEVEL:
        return {"level": style_outline + 1, "source": "style-outline", "confidence": 0.96}
    style_level = style.get("headingLevel")
    if isinstance(style_level, int) and 1 <= style_level <= MAX_SECTION_LEVEL:
        return {"level": style_level, "source": "heading-style", "confidence": 0.95}
    if not allow_regex:
        return None
    regex_level = _regex_heading_level(text, has_level_one=has_level_one)
    if regex_level is not None:
        return {"level": regex_level, "source": "regex", "confidence": 0.72}
    return None


def _has_structural_heading_format(block: dict[str, Any], styles: dict[str, dict[str, Any]]) -> bool:
    direct_outline = block.get("outlineLevel")
    if isinstance(direct_outline, int) and 0 <= direct_outline < MAX_SECTION_LEVEL:
        return True
    style = styles.get(str(block.get("styleId") or "")) or {}
    style_outline = style.get("outlineLevel")
    if isinstance(style_outline, int) and 0 <= style_outline < MAX_SECTION_LEVEL:
        return True
    style_level = style.get("headingLevel")
    return isinstance(style_level, int) and 1 <= style_level <= MAX_SECTION_LEVEL


def _table_text(element: ET.Element) -> str:
    rows: list[str] = []
    for tr in element.iter(f"{W}tr"):
        cells = [_paragraph_text(tc) for tc in tr.iter(f"{W}tc")]
        row = " | ".join(cell for cell in cells if cell)
        if row:
            rows.append(row)
    return _clean(" / ".join(rows))


def _append_extract_docx_text_pieces(element: ET.Element, pieces: list[str]) -> None:
    for child in list(element):
        _append_extract_docx_text_pieces(child, pieces)
    if element.tag == f"{W}t":
        pieces.append(element.text or "")
    elif element.tag == f"{W}tab":
        pieces.append("\t")
    elif element.tag in {f"{W}br", f"{W}cr"}:
        pieces.append("\n")
    elif element.tag == f"{W}p":
        pieces.append("\n")


def _append_raw_line_piece(raw_lines: list[dict[str, Any]], text: str, block_index: int) -> None:
    parts = text.split("\n")
    for index, part in enumerate(parts):
        if part:
            raw_lines[-1]["text"] += part
            raw_lines[-1]["blocks"].add(block_index)
        if index < len(parts) - 1:
            raw_lines.append({"text": "", "blocks": set()})


def _iter_docx_content_blocks(element: ET.Element) -> list[ET.Element]:
    blocks: list[ET.Element] = []
    for child in list(element):
        if child.tag in {f"{W}p", f"{W}tbl"}:
            blocks.append(child)
            continue
        blocks.extend(_iter_docx_content_blocks(child))
    return blocks


def _docx_block_line_ranges(body: ET.Element) -> dict[int, dict[str, int]]:
    raw_lines: list[dict[str, Any]] = [{"text": "", "blocks": set()}]
    for block_index, child in enumerate(_iter_docx_content_blocks(body), start=1):
        pieces: list[str] = []
        _append_extract_docx_text_pieces(child, pieces)
        for piece in pieces:
            _append_raw_line_piece(raw_lines, piece, block_index)

    compact: list[dict[str, Any]] = []
    previous_blank = False
    for raw_line in raw_lines:
        text = str(raw_line.get("text") or "").rstrip()
        blank = not text.strip()
        if blank and previous_blank:
            continue
        compact.append({"text": text, "blocks": set(raw_line.get("blocks") or set())})
        previous_blank = blank

    first_content_index = next((index for index, line in enumerate(compact) if str(line.get("text") or "").strip()), None)
    if first_content_index is None:
        return {}
    last_content_index = next(
        index
        for index in range(len(compact) - 1, -1, -1)
        if str(compact[index].get("text") or "").strip()
    )

    ranges: dict[int, dict[str, int]] = {}
    for line_number, line in enumerate(compact[first_content_index : last_content_index + 1], start=1):
        if not str(line.get("text") or "").strip():
            continue
        for block in line.get("blocks") or set():
            if not int(block):
                continue
            block_range = ranges.setdefault(int(block), {"startLine": line_number, "endLine": line_number})
            block_range["endLine"] = line_number
    return ranges


def _docx_blocks(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            document_root = _read_xml(archive, "word/document.xml")
            styles = _load_paragraph_styles(archive)
    except Exception as exc:
        return [], {}, [f"docx 读取失败：{exc}"]
    if document_root is None:
        return [], styles, ["docx 缺少 word/document.xml，无法解析章节树。"]
    body = document_root.find(f"{W}body")
    if body is None:
        return [], styles, ["docx 正文为空，无法解析章节树。"]
    blocks: list[dict[str, Any]] = []
    line_ranges = _docx_block_line_ranges(body)
    for child in _iter_docx_content_blocks(body):
        if child.tag == f"{W}p":
            text = _paragraph_text(child)
            block_index = len(blocks) + 1
            line_range = line_ranges.get(block_index, {})
            blocks.append(
                {
                    "type": "paragraph",
                    "blockIndex": block_index,
                    "lineNumber": line_range.get("startLine"),
                    "endLine": line_range.get("endLine"),
                    "text": text,
                    "styleId": _style_id(child),
                    "outlineLevel": _outline_level(child),
                }
            )
        elif child.tag == f"{W}tbl":
            text = _table_text(child)
            block_index = len(blocks) + 1
            line_range = line_ranges.get(block_index, {})
            blocks.append(
                {
                    "type": "table",
                    "blockIndex": block_index,
                    "lineNumber": line_range.get("startLine"),
                    "endLine": line_range.get("endLine"),
                    "text": text,
                    "styleId": "",
                    "outlineLevel": None,
                }
            )
    return blocks, styles, warnings


def _collect_toc_entries(
    document_id: str,
    blocks: list[dict[str, Any]],
    styles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    in_toc = False
    has_seen_body_heading = False
    for block in blocks:
        if block.get("type") != "paragraph":
            if in_toc:
                break
            continue
        text = _clean(block.get("text"))
        if not in_toc and _has_structural_heading_format(block, styles):
            has_seen_body_heading = True
        if _looks_like_toc_heading(text):
            if has_seen_body_heading:
                break
            in_toc = True
            continue
        if not in_toc:
            continue
        title = _toc_title_from_line(text)
        if title:
            entries.append(
                {
                    "documentId": document_id,
                    "title": title,
                    "rawText": text,
                    "blockIndex": int(block.get("blockIndex") or 0),
                    "line": int(block.get("lineNumber") or 0),
                }
            )
            continue
        if _looks_like_toc_heading(_strip_toc_page_suffix(text)):
            continue
        if _looks_like_plain_toc_item(text):
            if entries:
                break
            entries.append(
                {
                    "documentId": document_id,
                    "title": text,
                    "rawText": text,
                    "blockIndex": int(block.get("blockIndex") or 0),
                    "line": int(block.get("lineNumber") or 0),
                }
            )
            continue
        if text:
            break
    return entries


def _looks_like_chapter_list_intro(text: str) -> bool:
    cleaned = _clean(text)
    return "章节组成" in cleaned or "由以下章节组成" in cleaned


def _collect_chapter_list_entries(document_id: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    started = False
    for block in blocks[:120]:
        if block.get("type") != "paragraph":
            if started:
                break
            continue
        text = _clean(block.get("text"))
        if not text:
            continue
        if _looks_like_chapter_list_intro(text):
            started = True
            continue
        if not started:
            continue
        if not re.match(r"^第[一二三四五六七八九十百千0-9]+章(?:\s|[、.．：:]|$)", text):
            if entries:
                break
            continue
        entries.append(
            {
                "documentId": document_id,
                "title": text,
                "rawText": text,
                "blockIndex": int(block.get("blockIndex") or 0),
                "line": int(block.get("lineNumber") or 0),
                "level": 1,
            }
        )
    return entries if len(entries) >= 4 else []


def _entry_block_indexes(entries: list[dict[str, Any]]) -> set[int]:
    return {int(entry.get("blockIndex") or 0) for entry in entries if int(entry.get("blockIndex") or 0) > 0}


def _title_key(text: str) -> str:
    cleaned = _clean(text)
    cleaned = re.sub(r"(?:\.{2,}|…{2,}|·{2,}|\t+)\s*\d+\s*$", "", cleaned)
    cleaned = re.sub(r"\s+\d{1,4}\s*$", "", cleaned)
    return re.sub(r"[\s:：、.．]+", "", cleaned)


def _validation_for_toc(entries: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        return {
            "status": "not_applicable",
            "tocEntryCount": 0,
            "matchedTocEntryCount": 0,
            "unmatchedTocTitles": [],
        }
    node_keys = [_title_key(str(node.get("title") or "")) for node in nodes]
    unmatched: list[str] = []
    matched = 0
    for entry in entries:
        key = _title_key(str(entry.get("title") or ""))
        if key and any(key == node_key or key in node_key or node_key in key for node_key in node_keys):
            matched += 1
        else:
            unmatched.append(str(entry.get("title") or ""))
    return {
        "status": "passed" if not unmatched else "partial",
        "tocEntryCount": len(entries),
        "matchedTocEntryCount": matched,
        "unmatchedTocTitles": unmatched[:50],
    }


def _first_line_for_block(blocks: list[dict[str, Any]], start_block: int, end_block: int, default: int) -> int:
    values = [
        int(block.get("lineNumber") or 0)
        for block in blocks
        if start_block <= int(block.get("blockIndex") or 0) <= end_block and int(block.get("lineNumber") or 0) > 0
    ]
    return min(values) if values else default


def _last_line_for_block(blocks: list[dict[str, Any]], start_block: int, end_block: int, default: int) -> int:
    values = [
        int(block.get("endLine") or block.get("lineNumber") or 0)
        for block in blocks
        if start_block <= int(block.get("blockIndex") or 0) <= end_block
        and int(block.get("endLine") or block.get("lineNumber") or 0) > 0
    ]
    return max(values) if values else default


def _title_match_key(text: str) -> str:
    cleaned = _clean(text)
    cleaned = re.sub(r"(?:\.{2,}|…{2,}|·{2,}|\t+)\s*\d+\s*$", "", cleaned)
    cleaned = re.sub(r"\s+\d{1,4}\s*$", "", cleaned)
    cleaned = re.sub(r"^(\d+(?:\.\d+)*)(?:[.．、]|\s+)\s*", r"\1", cleaned)
    return re.sub(r"[\s:：、.．，,；;。]+", "", cleaned)


def _titles_match(expected: str, actual: str) -> bool:
    expected_key = _title_match_key(expected)
    actual_key = _title_match_key(actual)
    return bool(expected_key and actual_key and (expected_key == actual_key or expected_key in actual_key or actual_key in expected_key))


def _is_local_toc_item_block(block: dict[str, Any], styles: dict[str, dict[str, Any]], *, in_local_toc: bool) -> bool:
    if block.get("type") != "paragraph" or not in_local_toc:
        return False
    text = _clean(block.get("text"))
    if not text:
        return False
    return _looks_like_plain_toc_item(text) and not _has_structural_heading_format(block, styles)


CHINESE_ORDER_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _local_toc_sequence_key(text: str) -> tuple[str, int] | None:
    cleaned = _clean(text)
    match = re.match(r"^(附件|附表)\s*(\d+)", cleaned)
    if match:
        return match.group(1), int(match.group(2))
    match = re.match(r"^(表)\s*(\d+)", cleaned)
    if match:
        return match.group(1), int(match.group(2))
    match = re.match(r"^([一二三四五六七八九十])[、.．]", cleaned)
    if match:
        return "cn", CHINESE_ORDER_MAP.get(match.group(1), 0)
    match = re.match(r"^(\d+)(?:[.．、]|\s+)", cleaned)
    if match:
        return "num", int(match.group(1))
    return None


def _locate_toc_headings(
    document_id: str,
    entries: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    styles: dict[str, dict[str, Any]],
    *,
    allow_entry_block: bool = False,
) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    cursor = 0
    for entry in entries:
        title = str(entry.get("title") or "")
        entry_block = int(entry.get("blockIndex") or 0)
        search_start = max(cursor, entry_block + (0 if allow_entry_block else 1))
        matched_block: dict[str, Any] | None = None
        in_local_toc = False
        local_toc_seen_keys: set[str] = set()
        last_local_toc_sequence: tuple[str, int] | None = None
        for block in blocks:
            block_index = int(block.get("blockIndex") or 0)
            if block_index < search_start or block.get("type") != "paragraph":
                continue
            block_text = _clean(block.get("text"))
            if _looks_like_toc_heading(block_text):
                in_local_toc = True
                local_toc_seen_keys = set()
                last_local_toc_sequence = None
                continue
            if _is_local_toc_item_block(block, styles, in_local_toc=in_local_toc):
                block_key = _title_match_key(block_text)
                sequence_key = _local_toc_sequence_key(block_text)
                sequence_restarted = (
                    sequence_key is not None
                    and last_local_toc_sequence is not None
                    and sequence_key[0] == last_local_toc_sequence[0]
                    and sequence_key[1] <= last_local_toc_sequence[1]
                )
                if (block_key and block_key in local_toc_seen_keys) or sequence_restarted:
                    in_local_toc = False
                else:
                    if block_key:
                        local_toc_seen_keys.add(block_key)
                    if sequence_key is not None:
                        last_local_toc_sequence = sequence_key
                    continue
            if in_local_toc and block_text:
                in_local_toc = False
            if _titles_match(title, str(block.get("text") or "")):
                matched_block = block
                break
        if matched_block is None:
            continue
        start_block = int(matched_block.get("blockIndex") or 0)
        headings.append(
            {
                "documentId": document_id,
                "level": int(entry.get("level") or 1),
                "number": _extract_number(title),
                "title": title,
                "source": "toc",
                "confidence": 0.99,
                "startBlockIndex": start_block,
                "startLine": int(matched_block.get("lineNumber") or 0),
            }
        )
        cursor = start_block + 1
    return headings


def _collect_body_headings(
    document_id: str,
    blocks: list[dict[str, Any]],
    styles: dict[str, dict[str, Any]],
    *,
    allow_regex: bool,
    excluded_blocks: set[int] | None = None,
) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    has_level_one = False
    in_toc = False
    in_chapter_list = False
    excluded_blocks = excluded_blocks or set()
    for block in blocks:
        if int(block.get("blockIndex") or 0) in excluded_blocks:
            continue
        text = _clean(block.get("text"))
        if block.get("type") == "paragraph" and _looks_like_toc_heading(text):
            in_toc = True
            continue
        if block.get("type") == "paragraph" and _looks_like_chapter_list_intro(text):
            in_chapter_list = True
            continue
        if in_chapter_list:
            if block.get("type") == "paragraph" and _looks_like_plain_toc_item(text):
                continue
            if text:
                in_chapter_list = False
        if in_toc:
            toc_item = _looks_like_plain_toc_item(text) if has_level_one else _looks_like_toc_line(text)
            if (
                block.get("type") == "paragraph"
                and toc_item
                and not _has_structural_heading_format(block, styles)
            ):
                continue
            if text:
                in_toc = False
        heading = _heading_from_block(
            block,
            styles,
            has_level_one=has_level_one,
            in_toc=in_toc,
            allow_regex=allow_regex,
        )
        if not heading:
            continue
        level = int(heading["level"])
        text = _clean(block.get("text"))
        if (
            allow_regex
            and str(heading.get("source") or "") == "regex"
            and headings
            and level == int(headings[-1].get("level") or 0)
            and int(block.get("blockIndex") or 0) <= int(headings[-1].get("startBlockIndex") or 0) + 3
            and 0 < len(_title_match_key(text)) < len(_title_match_key(str(headings[-1].get("title") or "")))
            and _title_match_key(text) in _title_match_key(str(headings[-1].get("title") or ""))
        ):
            continue
        headings.append(
            {
                "documentId": document_id,
                "level": level,
                "number": _extract_number(text),
                "title": text,
                "source": str(heading["source"]),
                "confidence": float(heading["confidence"]),
                "startBlockIndex": int(block.get("blockIndex") or 0),
                "startLine": int(block.get("lineNumber") or 0),
            }
        )
        if level == 1:
            has_level_one = True
    return headings


def _merge_missing_top_level_regex_headings(
    structural_headings: list[dict[str, Any]],
    regex_headings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    structural_keys = {_title_match_key(str(heading.get("title") or "")) for heading in structural_headings}
    first_structural_block = min(
        (int(heading.get("startBlockIndex") or 0) for heading in structural_headings),
        default=0,
    )
    missing_by_key: dict[str, dict[str, Any]] = {}
    for heading in regex_headings:
        if int(heading.get("level") or 0) != 1:
            continue
        key = _title_match_key(str(heading.get("title") or ""))
        if not key or key in structural_keys:
            continue
        block_index = int(heading.get("startBlockIndex") or 0)
        current = missing_by_key.get(key)
        if current is None:
            missing_by_key[key] = heading
            continue
        current_block = int(current.get("startBlockIndex") or 0)
        if first_structural_block and block_index < first_structural_block:
            if not current_block or current_block >= first_structural_block or block_index > current_block:
                missing_by_key[key] = heading
        elif not current_block or current_block >= first_structural_block:
            if block_index < current_block:
                missing_by_key[key] = heading
    return sorted(structural_headings + list(missing_by_key.values()), key=lambda item: int(item.get("startBlockIndex") or 0))


def _nodes_from_headings(document_id: str, headings: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not headings:
        return []
    last_block = max((int(block.get("blockIndex") or 0) for block in blocks), default=0)
    stack: dict[int, str] = {}
    nodes: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        level = min(MAX_SECTION_LEVEL, max(1, int(heading["level"])))
        start_block = int(heading["startBlockIndex"])
        end_block = last_block
        for next_heading in headings[index + 1 :]:
            if int(next_heading["level"]) <= level:
                end_block = max(start_block, int(next_heading["startBlockIndex"]) - 1)
                break
        start_line = int(heading.get("startLine") or 0)
        content_start_block = min(end_block, start_block + 1) if end_block >= start_block else start_block
        content_start_line = _first_line_for_block(blocks, content_start_block, end_block, start_line)
        end_line = _last_line_for_block(blocks, start_block, end_block, start_line)
        stack[level] = str(heading["title"])
        for stale_level in list(stack):
            if stale_level > level:
                stack.pop(stale_level, None)
        path = [stack[item] for item in sorted(stack) if item <= level and stack.get(item)]
        nodes.append(
            {
                "id": f"{document_id or 'DOC'}-S{len(nodes) + 1:04d}",
                "documentId": document_id,
                "level": level,
                "number": str(heading.get("number") or ""),
                "title": str(heading.get("title") or ""),
                "path": path,
                "source": str(heading.get("source") or ""),
                "confidence": round(float(heading.get("confidence") or 0), 3),
                "startBlockIndex": start_block,
                "contentStartBlockIndex": content_start_block,
                "endBlockIndex": end_block,
                "startLine": start_line,
                "contentStartLine": content_start_line,
                "endLine": end_line,
            }
        )
    return nodes


def _build_nodes_for_document(
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    styles: dict[str, dict[str, Any]],
    toc_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    document_id = str(document.get("id") or "")
    toc_headings = _locate_toc_headings(document_id, toc_entries, blocks, styles)
    if _is_detailed_toc(toc_entries, len(toc_headings)):
        return _nodes_from_headings(document_id, toc_headings, blocks), "detailed_toc"

    chapter_entries = _collect_chapter_list_entries(document_id, blocks)
    chapter_entry_blocks = _entry_block_indexes(chapter_entries)
    structural_headings = _collect_body_headings(
        document_id,
        blocks,
        styles,
        allow_regex=False,
        excluded_blocks=chapter_entry_blocks,
    )
    if _is_usable_body_structure(structural_headings):
        regex_headings = _collect_body_headings(
            document_id,
            blocks,
            styles,
            allow_regex=True,
            excluded_blocks=chapter_entry_blocks,
        )
        merged_headings = _merge_missing_top_level_regex_headings(structural_headings, regex_headings)
        return _nodes_from_headings(document_id, merged_headings, blocks), "body_structure"

    regex_headings = _collect_body_headings(
        document_id,
        blocks,
        styles,
        allow_regex=True,
        excluded_blocks=chapter_entry_blocks,
    )
    chapter_headings = _locate_toc_headings(document_id, chapter_entries, blocks, styles)
    regex_keys = {_title_match_key(str(heading.get("title") or "")) for heading in regex_headings}
    missing_chapter_headings = [
        heading for heading in chapter_headings if _title_match_key(str(heading.get("title") or "")) not in regex_keys
    ]
    merged_headings = sorted(regex_headings + missing_chapter_headings, key=lambda item: int(item.get("startBlockIndex") or 0))
    return _nodes_from_headings(document_id, merged_headings, blocks), "regex_fallback"


def build_business_section_tree(documents: list[dict[str, Any]]) -> dict[str, Any]:
    payload_documents: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    toc_entries: list[dict[str, Any]] = []
    source_modes: dict[str, str] = {}
    warnings: list[str] = []

    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".docx":
            continue
        document_id = str(document.get("id") or "")
        payload_documents.append(
            {
                "id": document_id,
                "name": str(document.get("name") or source_path.name),
                "sourcePath": str(source_path),
            }
        )
        if not source_path.is_file():
            warnings.append(f"{document.get('name') or source_path.name} 不存在，未解析章节树。")
            continue
        blocks, styles, doc_warnings = _docx_blocks(source_path)
        warnings.extend(f"{document.get('name') or source_path.name}：{warning}" for warning in doc_warnings)
        doc_toc_entries = _assign_toc_entry_levels(_collect_toc_entries(document_id, blocks, styles))
        toc_entries.extend(doc_toc_entries)
        doc_nodes, source_mode = _build_nodes_for_document(document, blocks, styles, doc_toc_entries)
        source_modes[document_id] = source_mode
        nodes.extend(doc_nodes)

    validation = _validation_for_toc(toc_entries, nodes)
    return {
        "schemaVersion": SECTION_TREE_SCHEMA,
        "maxLevel": MAX_SECTION_LEVEL,
        "documents": payload_documents,
        "nodes": nodes,
        "toc": {
            "detected": bool(toc_entries),
            "entries": toc_entries,
        },
        "validation": validation,
        "summary": {
            "documentCount": len(payload_documents),
            "nodeCount": len(nodes),
            "tocEntryCount": len(toc_entries),
            "validationStatus": validation["status"],
            "sourceModes": source_modes,
            "warnings": warnings,
        },
    }


def write_business_section_tree(documents: list[dict[str, Any]], project_dir: Path) -> tuple[Path, dict[str, Any]]:
    project_dir.mkdir(parents=True, exist_ok=True)
    payload = build_business_section_tree(documents)
    output_path = project_dir / "business_section_tree.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, payload
