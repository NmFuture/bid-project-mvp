import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
MAX_SOURCE_BLOCKS = 80


def qn(name):
    prefix, local = name.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


def text_from_element(element):
    parts = []
    for node in element.iter():
        if node.tag == qn("w:t") and node.text:
            parts.append(node.text)
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag in {qn("w:br"), qn("w:cr")}:
            parts.append("\n")
    return "".join(parts).strip()


def visible_text_from_element(element):
    parts = []
    for node in element.iter():
        if node.tag == qn("w:instrText"):
            continue
        if node.tag == qn("w:t") and node.text:
            parts.append(node.text)
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag in {qn("w:br"), qn("w:cr")}:
            parts.append("\n")
    return "".join(parts).strip()


def paragraph_style(paragraph):
    p_style = paragraph.find("w:pPr/w:pStyle", NS)
    if p_style is None:
        return ""
    return p_style.attrib.get(qn("w:val"), "")


def paragraph_outline_level(paragraph):
    outline = paragraph.find("w:pPr/w:outlineLvl", NS)
    if outline is None:
        return None
    value = outline.attrib.get(qn("w:val"))
    if value is None:
        return None
    try:
        return int(value) + 1
    except ValueError:
        return None


def explicit_style_heading_level(style):
    style_text = style.lower()
    match = re.search(r"heading\s*([1-6])", style_text)
    if match:
        return int(match.group(1))
    match = re.search(r"标题\s*([1-6])", style)
    if match:
        return int(match.group(1))
    return None


def heading_level(paragraph):
    style_level = explicit_style_heading_level(paragraph_style(paragraph))
    if style_level:
        return style_level
    return paragraph_outline_level(paragraph)


def compact_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize(text):
    return re.sub(r"\s+", "", text or "").lower()


def parse_document_xml(path):
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    return root, list(body) if body is not None else []


def parse_style_names(path):
    try:
        with zipfile.ZipFile(path) as archive:
            styles_xml = archive.read("word/styles.xml")
    except (KeyError, FileNotFoundError, zipfile.BadZipFile):
        return {}
    root = ET.fromstring(styles_xml)
    names = {}
    for style in root.findall(".//w:style", NS):
        style_id = style.attrib.get(qn("w:styleId"))
        name = style.find("w:name", NS)
        if style_id and name is not None:
            names[style_id] = name.attrib.get(qn("w:val"), "")
    return names


def update_heading_path(path, level, title):
    next_path = path[:]
    while len(next_path) >= level:
        next_path.pop()
    next_path.append(title)
    return next_path


def bookmark_name_in_paragraph(paragraph):
    bookmark = paragraph.find(".//w:bookmarkStart", NS)
    if bookmark is None:
        return None
    return bookmark.attrib.get(qn("w:name"))


def build_blocks(body_elements):
    blocks = []
    heading_path = []
    paragraph_index = 0
    for element in body_elements:
        paragraphs = element.findall(".//w:p", NS) if element.tag == qn("w:sdt") else [element]
        for paragraph in paragraphs:
            if paragraph.tag != qn("w:p"):
                continue
            paragraph_index += 1
            text = visible_text_from_element(paragraph)
            if not text:
                continue
            style = paragraph_style(paragraph)
            level = heading_level(paragraph)
            if level:
                heading_path = update_heading_path(heading_path, level, text)
            block = {
                "block_id": f"hb-{len(blocks) + 1:04d}",
                "type": "paragraph",
                "text": text,
                "paragraph_index": paragraph_index,
                "heading_path": heading_path[:],
            }
            if style:
                block["style"] = style
            if level:
                block["heading_level"] = level
            bookmark_name = bookmark_name_in_paragraph(paragraph)
            if bookmark_name:
                block["bookmark_name"] = bookmark_name
            blocks.append(block)
    return blocks


def is_auto_toc_sdt(element):
    if element.tag != qn("w:sdt"):
        return False
    gallery = element.find(".//w:docPartGallery", NS)
    if gallery is not None and gallery.attrib.get(qn("w:val")) == "Table of Contents":
        return True
    return any("TOC" in (node.text or "") for node in element.findall(".//w:instrText", NS))


def paragraph_instr_text(paragraph):
    return " ".join(node.text or "" for node in paragraph.findall(".//w:instrText", NS))


def toc_style_level(style, style_names=None):
    candidates = [style]
    if style_names and style in style_names:
        candidates.append(style_names[style])
    for candidate in candidates:
        match = re.search(r"toc\s*([1-9])", candidate, re.I)
        if match:
            return int(match.group(1))
        match = re.search(r"目录\s*([1-9])", candidate)
        if match:
            return int(match.group(1))
    return None


def hyperlink_anchor(paragraph):
    hyperlink = paragraph.find(".//w:hyperlink", NS)
    if hyperlink is None:
        return None
    return hyperlink.attrib.get(qn("w:anchor"))


def hyperlink_text(paragraph):
    hyperlink = paragraph.find(".//w:hyperlink", NS)
    if hyperlink is None:
        return ""
    return visible_text_from_element(hyperlink)


def pageref_bookmark(paragraph):
    match = re.search(r"PAGEREF\s+(_Toc\S+)", paragraph_instr_text(paragraph))
    return match.group(1).strip(' "') if match else None


def auto_toc_paragraphs(body_elements):
    paragraphs = []
    for element in body_elements:
        if not is_auto_toc_sdt(element):
            continue
        paragraphs.extend(element.findall(".//w:p", NS))
    if paragraphs:
        return paragraphs

    in_toc = False
    for element in body_elements:
        if element.tag != qn("w:p"):
            continue
        instr_text = paragraph_instr_text(element)
        if "TOC" in instr_text:
            in_toc = True
            paragraphs.append(element)
            continue
        if in_toc:
            paragraphs.append(element)
            if element.find(".//w:fldChar[@w:fldCharType='end']", NS) is not None and "PAGEREF" not in instr_text and "HYPERLINK" not in instr_text:
                break
    return paragraphs


def extract_field_result_title(paragraph):
    texts = []
    collecting = False
    for node in paragraph:
        if node.tag == qn("w:r"):
            fld = node.find("w:fldChar", NS)
            if fld is not None:
                fld_type = fld.attrib.get(qn("w:fldCharType"))
                if fld_type == "separate":
                    collecting = True
                    continue
                if fld_type == "end":
                    if collecting:
                        break
                    continue
            if node.find("w:instrText", NS) is not None:
                continue
            if collecting:
                for child in node.iter():
                    if child.tag == qn("w:t") and child.text:
                        texts.append(child.text)
                    elif child.tag == qn("w:tab"):
                        texts.append("\t")
                    elif child.tag in {qn("w:br"), qn("w:cr")}:
                        texts.append("\n")
        elif node.tag == qn("w:hyperlink") and collecting:
            texts.append(visible_text_from_element(node))
    value = "".join(texts).strip()
    value = strip_page_number(value).strip()
    return value


def auto_toc_title(paragraph):
    return hyperlink_text(paragraph) or extract_field_result_title(paragraph)


def body_bookmark_metadata(blocks):
    result = {}
    for block in blocks:
        bookmark = block.get("bookmark_name")
        if not bookmark:
            continue
        item = {"block_id": block.get("block_id")}
        if block.get("heading_level"):
            item["level"] = block.get("heading_level")
        if block.get("paragraph_index"):
            item["paragraph_index"] = block.get("paragraph_index")
        result[bookmark] = item
    return result


def extract_auto_toc_candidates(body_elements, blocks, style_names=None):
    paragraphs = auto_toc_paragraphs(body_elements)
    if not paragraphs:
        return [], []
    bookmark_metadata = body_bookmark_metadata(blocks)
    candidates = []
    source_blocks = []
    for paragraph in paragraphs:
        visible = visible_text_from_element(paragraph)
        if visible:
            source_blocks.append({"text": visible})
        title = auto_toc_title(paragraph)
        bookmark = hyperlink_anchor(paragraph) or pageref_bookmark(paragraph)
        if not title or not bookmark:
            continue
        style = paragraph_style(paragraph)
        body_meta = bookmark_metadata.get(bookmark, {})
        number, title_hint = split_heading_number(title)
        level = infer_level_from_number(number) or toc_style_level(style, style_names) or paragraph_outline_level(paragraph) or body_meta.get("level") or 1
        candidate = {
            "candidate_id": f"hist-cand-{len(candidates) + 1:03d}",
            "title_hint": title_hint,
            "number": number,
            "level": level,
            "source_text": visible or title,
            "source_type": "history_bid_auto_toc",
            "bookmark_name": bookmark,
        }
        matched_block_id = body_meta.get("block_id")
        if matched_block_id:
            candidate["matched_body_block_id"] = matched_block_id
        matched_paragraph_index = body_meta.get("paragraph_index")
        if matched_paragraph_index:
            candidate["matched_body_paragraph_index"] = matched_paragraph_index
        candidates.append(candidate)
    return candidates, source_blocks


def is_toc_title(text):
    return normalize(text) in {"目录", "目次", "contents"}


def is_toc_line(text, style="", style_names=None):
    stripped = compact_text(text)
    if not stripped or len(stripped) > 140:
        return False
    if toc_style_level(style, style_names):
        return True
    if re.search(r"\t\s*\d+\s*$", stripped):
        return True
    if re.search(r"[·.]{2,}\s*\d+\s*$", stripped):
        return True
    if re.search(r"\s+\d+\s*$", stripped) and re.search(r"(附件|[一二三四五六七八九十]+[、．.]|[（(][一二三四五六七八九十]+[）)]|\d+[、．.]|\d+\.\d+)", stripped):
        return True
    return False


def find_plain_toc_blocks(blocks, style_names=None):
    for index, block in enumerate(blocks):
        if not is_toc_title(block.get("text", "")):
            continue
        candidates = []
        for next_block in blocks[index + 1:index + 1 + MAX_SOURCE_BLOCKS]:
            text = next_block.get("text", "")
            if is_toc_line(text, next_block.get("style", ""), style_names):
                candidates.append(next_block)
                continue
            if candidates and next_block.get("heading_level") == 1:
                break
            if len(candidates) >= 2:
                break
        if len(candidates) >= 2:
            return candidates
    return []


def strip_page_number(text):
    value = compact_text(text)
    value = re.sub(r"[·.]{2,}\s*\d+\s*$", "", value)
    return re.sub(r"(?:\t|\s+)\d+\s*$", "", value).strip()


NUMBER_PATTERNS = [
    r"^(?P<number>[一二三四五六七八九十百]+[、．.])\s*(?P<title>\S.*)$",
    r"^(?P<number>[（(][一二三四五六七八九十百]+[）)])\s*(?P<title>\S.*)$",
    r"^(?P<number>[（(]\d+[）)])\s*(?P<title>\S.*)$",
    r"^(?P<number>\d+(?:\.\d+)+)\s*(?P<title>\S.*)$",
    r"^(?P<number>\d+)\s+(?P<title>\S.*)$",
    r"^(?P<number>\d+[、．.])\s*(?P<title>\S.*)$",
    r"^(?P<number>附件\s*\d+[A-Z]?(?:[-－]?\d+)?)\s*(?P<title>\S.*)$",
]


def split_heading_number(text):
    value = strip_page_number(text)
    for pattern in NUMBER_PATTERNS:
        match = re.match(pattern, value)
        if match:
            return match.group("number").strip(), match.group("title").strip()
    return None, value


def infer_toc_level(text, style="", style_names=None):
    style_level = toc_style_level(style, style_names)
    stripped = strip_page_number(text)
    number, _ = split_heading_number(stripped)
    number_level = infer_level_from_number(number)
    if number_level:
        return number_level
    if style_level:
        return style_level
    if re.match(r"^[一二三四五六七八九十]+[、．.]", stripped):
        return 1
    if re.match(r"^附件\s*\d+[A-Z]?(?:[-－]?\d+)?", stripped):
        return 1
    if re.match(r"^[（(][一二三四五六七八九十]+[）)]", stripped):
        return 2
    if re.match(r"^\d+[、．.]", stripped):
        return 2
    return 2


def infer_level_from_number(number):
    clean = str(number or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)+", clean):
        return max(1, min(clean.count(".") + 1, 9))
    if re.fullmatch(r"\d+", clean):
        return 1
    return None


def title_from_toc_line(text):
    _, title = split_heading_number(text)
    return title.strip() or strip_page_number(text)


def title_from_heading(text):
    _, title = split_heading_number(text)
    return title.strip() or compact_text(text)


def candidate_from_block(block, index, source_type, title_hint, level, number=None):
    result = {
        "candidate_id": f"hist-cand-{index:03d}",
        "title_hint": title_hint,
        "number": number,
        "level": level,
        "source_text": block.get("text", ""),
        "source_type": source_type,
        "block_id": block.get("block_id"),
        "paragraph_index": block.get("paragraph_index"),
        "heading_path": block.get("heading_path", []),
    }
    if block.get("bookmark_name"):
        result["bookmark_name"] = block.get("bookmark_name")
    return result


def candidates_from_toc(toc_blocks, style_names=None):
    candidates = []
    for index, block in enumerate(toc_blocks, start=1):
        number, title_hint = split_heading_number(block.get("text", ""))
        candidates.append(candidate_from_block(
            block,
            index,
            "history_bid_toc",
            title_hint,
            infer_toc_level(block.get("text", ""), block.get("style", ""), style_names),
            number,
        ))
    return candidates


def candidates_from_headings(blocks):
    heading_blocks = [block for block in blocks if block.get("heading_level")]
    if not heading_blocks:
        return []
    min_level = min(block.get("heading_level") for block in heading_blocks)
    candidates = []
    for index, block in enumerate(heading_blocks, start=1):
        level = max(1, block.get("heading_level") - min_level + 1)
        number, title_hint = split_heading_number(block.get("text", ""))
        candidates.append(candidate_from_block(
            block,
            index,
            "history_bid_headings",
            title_hint,
            level,
            number,
        ))
    return candidates


def numeric_number_tuple(number):
    text = str(number or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)*", text):
        return None
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return None


def candidate_identity(candidate):
    number = str(candidate.get("number") or "").strip()
    title = normalize(str(candidate.get("title_hint") or ""))
    return number, title


def candidate_body_order(candidate):
    for key in ("matched_body_paragraph_index", "paragraph_index"):
        value = candidate.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def should_backfill_deep_heading(candidate, existing_identities):
    number_tuple = numeric_number_tuple(candidate.get("number"))
    if not number_tuple or len(number_tuple) < 4:
        return False
    if candidate_identity(candidate) in existing_identities:
        return False
    # Only use headings backed by Word heading/outline evidence. Plain body
    # paragraphs such as "7.9.2.100 ..." must not become directory nodes.
    if str(candidate.get("source_type") or "") != "history_bid_headings":
        return False
    return True


def insert_candidate_by_number_or_body_order(candidates, candidate):
    candidate_tuple = numeric_number_tuple(candidate.get("number"))
    candidate_order = candidate_body_order(candidate)
    if candidate_tuple:
        for index, current in enumerate(candidates):
            current_tuple = numeric_number_tuple(current.get("number"))
            if current_tuple and current_tuple > candidate_tuple:
                candidates.insert(index, candidate)
                return
    if candidate_order is not None:
        for index, current in enumerate(candidates):
            current_order = candidate_body_order(current)
            if current_order is not None and current_order > candidate_order:
                candidates.insert(index, candidate)
                return
    candidates.append(candidate)


def merge_auto_toc_with_deep_body_headings(auto_candidates, heading_candidates):
    if not auto_candidates:
        return heading_candidates
    result = [dict(candidate) for candidate in auto_candidates]
    existing = {candidate_identity(candidate) for candidate in result}
    additions = [
        dict(candidate)
        for candidate in heading_candidates
        if should_backfill_deep_heading(candidate, existing)
    ]
    additions.sort(key=lambda candidate: (
        numeric_number_tuple(candidate.get("number")) or (999999,),
        candidate_body_order(candidate) or 999999,
    ))
    for candidate in additions:
        insert_candidate_by_number_or_body_order(result, candidate)
        existing.add(candidate_identity(candidate))
    return result


def make_outline_source(document_name, source_type, source_blocks, candidates):
    source_text = "\n".join(block.get("text", "") for block in source_blocks) if source_blocks else ""
    if source_type in {"history_bid_auto_toc", "history_bid_toc"}:
        section_title = "历史商务标投标文件目录"
    elif source_type == "history_bid_headings":
        section_title = "历史商务标投标文件标题结构"
    else:
        section_title = "未识别到可靠历史商务标目录"
    return {
        "section_title": section_title,
        "source_text": source_text,
        "confidence": "high" if source_type in {"history_bid_auto_toc", "history_bid_toc"} else ("medium" if candidates else "low"),
        "source_type": source_type,
        "history_document_name": document_name,
    }


def build_output(docx_path):
    _, body_elements = parse_document_xml(docx_path)
    style_names = parse_style_names(docx_path)
    blocks = build_blocks(body_elements)
    auto_candidates, auto_source_blocks = extract_auto_toc_candidates(body_elements, blocks, style_names)
    if auto_candidates:
        source_type = "history_bid_auto_toc"
        source_blocks = auto_source_blocks
        candidates = merge_auto_toc_with_deep_body_headings(auto_candidates, candidates_from_headings(blocks))
    else:
        toc_blocks = find_plain_toc_blocks(blocks, style_names)
        if toc_blocks:
            source_type = "history_bid_toc"
            source_blocks = toc_blocks
            candidates = candidates_from_toc(toc_blocks, style_names)
        else:
            candidates = candidates_from_headings(blocks)
            if candidates:
                source_type = "history_bid_headings"
                source_blocks = [block for block in blocks if block.get("heading_level")]
            else:
                source_type = "history_bid_unknown"
                source_blocks = []
    return {
        "document_name": docx_path.name,
        "blocks": blocks,
        "outline_source": make_outline_source(docx_path.name, source_type, source_blocks, candidates),
        "outline_candidates": candidates,
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare historical business bid outline candidates from a DOCX file.")
    parser.add_argument("docx", help="Historical business bid .docx file")
    parser.add_argument("--output", default="history_bid_outline_inputs.json", help="Output JSON path")
    args = parser.parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"ERROR: file not found: {docx_path}", file=sys.stderr)
        return 2
    output = build_output(docx_path)
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: wrote {args.output} with {len(output['outline_candidates'])} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
