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
        level = int(value) + 1
    except ValueError:
        return None
    return level if 1 <= level <= 6 else None


def explicit_style_heading_level(style):
    style_text = style.lower()
    match = re.search(r"heading\s*([1-6])", style_text)
    if match:
        return int(match.group(1))
    match = re.search(r"标题\s*([1-6])", style)
    if match:
        return int(match.group(1))
    return None


def heading_level(text, style, outline_level=None):
    style_level = explicit_style_heading_level(style)
    if style_level:
        return style_level
    return outline_level


def update_heading_path(path, level, title):
    next_path = path[:]
    while len(next_path) >= level:
        next_path.pop()
    next_path.append(title)
    return next_path


def parse_checklist(path):
    if not path:
        return []
    checklist_path = Path(path)
    if not checklist_path.exists():
        return []
    items = []
    current = None
    in_hints = False
    for raw_line in checklist_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            if current:
                items.append(current)
            current = {"title": line[3:].strip(), "scan_hints": []}
            in_hints = False
        elif current and line.strip() == "scan_hints:":
            in_hints = True
        elif current and in_hints and line.strip().startswith("- "):
            current["scan_hints"].append(line.strip()[2:].strip())
        elif current and in_hints and line and not line.startswith("-") and not line.startswith(" "):
            in_hints = False
    if current:
        items.append(current)
    return items


def normalize(text):
    return re.sub(r"\s+", "", text or "").lower()


ZONE_ANCHOR_TERMS = {
    normalize(term)
    for term in [
        "投标人须知前附表",
        "符合性审查",
        "响应性审查",
        "初步评审",
        "资格审查",
        "资格要求",
        "投标人资格",
        "商务评分",
        "商务评审",
        "评分标准",
        "否决投标",
        "废标条款",
        "废标",
        "实质性要求",
    ]
}

HIGH_VALUE_ZONE_TERMS = {
    normalize(term)
    for term in [
        "投标人资格要求",
        "投标人资格",
        "资格审查资料",
        "资格审查",
        "初步评审",
        "响应和偏差",
        "商务偏差",
        "实质性要求",
        "否决投标",
        "废标条款",
        "符合性审查",
        "商务评分",
        "商务评审",
    ]
}

BROAD_HIT_TERMS = {
    normalize(term)
    for term in [
        "提交",
        "承诺",
        "盖章",
        "签署",
        "证明材料",
        "业绩",
        "资质",
        "财务",
        "信誉",
        "认证",
        "响应",
        "偏差",
        "要求",
        "规定",
    ]
}


def matched_terms_for_text(text, terms):
    normalized_text = normalize(text)
    return sorted({term for term in terms if term and normalize(term) in normalized_text})


def matched_checklist_items(text, checklist):
    matches = []
    for item in checklist:
        terms = [item["title"], *item.get("scan_hints", [])]
        hit_terms = matched_terms_for_text(text, terms)
        if hit_terms:
            matches.append({"title": item["title"], "matched_terms": hit_terms})
    return matches


def iter_body_elements(document_xml):
    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        return []
    return list(body)


def parse_docx(path):
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    return iter_body_elements(document_xml)


def build_inputs(docx_path, checklist):
    blocks = []
    tables = []
    heading_path = []
    paragraph_index = 0
    table_index = 0
    last_paragraph_text = ""

    for element in parse_docx(docx_path):
        if element.tag == qn("w:p"):
            paragraph_index += 1
            text = text_from_element(element)
            if not text:
                continue
            style = paragraph_style(element)
            outline_level = paragraph_outline_level(element)
            level = heading_level(text, style, outline_level)
            if level:
                heading_path = update_heading_path(heading_path, level, text)
            block = {
                "block_id": f"b-{len(blocks) + 1:04d}",
                "type": "paragraph",
                "text": text,
                "heading_path": heading_path[:],
                "paragraph_index": paragraph_index,
            }
            if style:
                block["style"] = style
            if outline_level:
                block["outline_level"] = outline_level
            if level:
                block["heading_level"] = level
                block["heading_evidence"] = "style" if explicit_style_heading_level(style) else "outline"
            blocks.append(block)
            last_paragraph_text = text
        elif element.tag == qn("w:tbl"):
            table_index += 1
            table_id = f"t-{table_index:03d}"
            nearby_heading = " / ".join(heading_path)
            nearby_caption = last_paragraph_text
            rows = []
            for row_index, row in enumerate(element.findall("w:tr", NS), start=1):
                cells = []
                for col_index, cell in enumerate(row.findall("w:tc", NS), start=1):
                    cell_text = text_from_element(cell)
                    cells.append({"col_index": col_index, "text": cell_text})
                    if cell_text:
                        blocks.append({
                            "block_id": f"b-{len(blocks) + 1:04d}",
                            "type": "table_cell_marker",
                            "text": cell_text,
                            "heading_path": heading_path[:],
                            "table_id": table_id,
                            "row_index": row_index,
                            "col_index": col_index,
                        })
                row_text = " | ".join(cell["text"] for cell in cells if cell["text"])
                rows.append({"row_index": row_index, "row_text": row_text, "cells": cells})
                if row_text:
                    blocks.append({
                        "block_id": f"b-{len(blocks) + 1:04d}",
                        "type": "table_row",
                        "text": row_text,
                        "heading_path": heading_path[:],
                        "table_id": table_id,
                        "row_index": row_index,
                    })
            tables.append({
                "table_id": table_id,
                "nearby_heading": nearby_heading,
                "nearby_caption": nearby_caption,
                "rows": rows,
            })
    return blocks, tables


def numbered_heading_like(text):
    stripped = text.strip()
    patterns = [
        r"^第[一二三四五六七八九十百]+[章节篇卷]\b",
        r"^[一二三四五六七八九十]+[、．.]\s*\S+",
        r"^\(?[一二三四五六七八九十]+\)\s*\S+",
        r"^\d+(?:\.\d+)*[、．.]?\s*\S+",
    ]
    return any(re.match(pattern, stripped) for pattern in patterns)


def looks_like_section_title(text):
    stripped = text.strip()
    if not stripped or len(stripped) > 100:
        return False
    if stripped.endswith(("。", "；", ";", "，", ",")):
        return False
    return numbered_heading_like(stripped) or not re.search(r"[。；;，,]", stripped)


def match_has_high_value_anchor(match):
    matched_terms = {normalize(term) for term in match.get("matched_terms", [])}
    title = normalize(match["title"])
    return title in matched_terms or bool(matched_terms & HIGH_VALUE_ZONE_TERMS)


def conservative_window_boundary(blocks, start_index, max_blocks=8, max_chars=2500):
    end_index = start_index
    total_chars = 0
    for index in range(start_index, len(blocks)):
        if index > start_index and block_heading_level(blocks[index]) is not None:
            break
        total_chars += len(blocks[index].get("text", ""))
        if index - start_index >= max_blocks or total_chars > max_chars:
            break
        end_index = index
    return end_index


def zone_has_readable_context(blocks, start_index, end_index):
    zone_blocks = [block for block in blocks[start_index:end_index + 1] if block.get("text")]
    if len(zone_blocks) >= 2:
        return True
    if not zone_blocks:
        return False
    text = zone_blocks[0].get("text", "").strip()
    return len(text) >= 80 or zone_blocks[0].get("table_id") is not None


def block_heading_level(block):
    return block.get("heading_level")


def next_heading_boundary(blocks, start_index, level):
    end_index = len(blocks) - 1
    for index in range(start_index + 1, len(blocks)):
        next_level = block_heading_level(blocks[index])
        if next_level is not None and next_level <= level:
            end_index = index - 1
            break
    return end_index


def make_zone(zone_index, blocks, tables_by_id, start_index, end_index, checklist_match, zone_type):
    zone_blocks = blocks[start_index:end_index + 1]
    block_ids = [block["block_id"] for block in zone_blocks]
    table_ids = sorted({block["table_id"] for block in zone_blocks if block.get("table_id")})
    title = zone_blocks[0]["text"] if zone_blocks else checklist_match["title"]
    text = "\n".join(block["text"] for block in zone_blocks if block.get("text"))
    return {
        "zone_id": f"z-{zone_index:03d}",
        "title": title,
        "zone_type": zone_type,
        "matched_checklist_item": checklist_match["title"],
        "matched_terms": checklist_match.get("matched_terms", []),
        "is_probable_toc": is_probable_toc_zone(zone_blocks),
        "start_block_id": zone_blocks[0]["block_id"] if zone_blocks else None,
        "end_block_id": zone_blocks[-1]["block_id"] if zone_blocks else None,
        "heading_path": zone_blocks[0].get("heading_path", []) if zone_blocks else [],
        "block_ids": block_ids,
        "table_ids": [table_id for table_id in table_ids if table_id in tables_by_id],
        "text": text,
    }


def is_probable_toc_block(block):
    if block.get("table_id"):
        return False
    text = block.get("text", "").strip()
    if not text:
        return False
    if "\t" in text and re.search(r"\t\s*\d+\s*$", text):
        return True
    return len(text) <= 120 and bool(re.search(r"\s+\d+\s*$", text))


def is_probable_toc_zone(zone_blocks):
    if not zone_blocks:
        return False
    if any(block.get("table_id") for block in zone_blocks):
        return False
    return sum(1 for block in zone_blocks if is_probable_toc_block(block)) >= max(1, len(zone_blocks) // 2)


def best_checklist_match(text, checklist):
    matches = matched_checklist_items(text, checklist)
    if not matches:
        return None
    normalized_text = normalize(text)

    def score(match):
        title_hit = 1 if normalize(match["title"]) in normalized_text else 0
        return (title_hit, len(match.get("matched_terms", [])), len(match["title"]))

    return max(matches, key=score)


def zone_worthy_match(match):
    matched_terms = {normalize(term) for term in match.get("matched_terms", [])}
    title = normalize(match["title"])
    return title in matched_terms or bool(matched_terms & ZONE_ANCHOR_TERMS)


def is_cross_reference(text, checklist_title):
    normalized_text = normalize(text)
    normalized_title = normalize(checklist_title)
    if not normalized_title or normalized_title not in normalized_text:
        return False
    if normalized_text.startswith(normalized_title):
        return False
    if checklist_title == "投标人须知前附表":
        return True
    cross_reference_markers = ["见", "详见", "规定", "按照", "根据", "另有规定"]
    title_index = normalized_text.find(normalized_title)
    prefix = normalized_text[max(0, title_index - 8):title_index]
    suffix = normalized_text[title_index + len(normalized_title):title_index + len(normalized_title) + 8]
    return any(marker in prefix or marker in suffix for marker in cross_reference_markers)


def zone_anchor_block(block, match):
    if block.get("table_id") or is_probable_toc_block(block):
        return False
    if not zone_worthy_match(match):
        return False
    text = block.get("text", "")
    if is_cross_reference(text, match["title"]):
        return False
    if block.get("heading_level") is not None:
        return True
    return match_has_high_value_anchor(match) and looks_like_section_title(text)


def build_zones(blocks, tables, checklist):
    zones = []
    used_ranges = set()
    covered_by_table_zones = set()
    tables_by_id = {table["table_id"]: table for table in tables}
    table_block_indexes = {}
    for index, block in enumerate(blocks):
        table_id = block.get("table_id")
        if table_id:
            table_block_indexes.setdefault(table_id, []).append(index)

    # Prefer one aggregated zone per important table. This keeps full row/cell
    # structure together and avoids hundreds of per-cell checklist zones.
    for table in tables:
        table_id = table["table_id"]
        indexes = table_block_indexes.get(table_id, [])
        if not indexes:
            continue
        table_text = "\n".join(row.get("row_text", "") for row in table.get("rows", []))
        match_text = "\n".join([
            table.get("nearby_heading", ""),
            table.get("nearby_caption", ""),
            table_text,
        ])
        match = best_checklist_match(match_text, checklist)
        if not match or not zone_worthy_match(match):
            continue
        if is_cross_reference(table.get("nearby_caption", ""), match["title"]) and normalize(match["title"]) not in normalize(table_text):
            continue
        start_index = min(indexes)
        end_index = max(indexes)
        # Include a nearby caption such as "投标人须知前附表" when it sits
        # immediately before the table. It improves context without rereading docx.
        if start_index > 0 and table.get("nearby_caption") and normalize(table.get("nearby_caption")) in normalize(blocks[start_index - 1].get("text", "")):
            start_index -= 1
        key = (start_index, end_index, table_id)
        if key not in used_ranges:
            used_ranges.add(key)
            covered_by_table_zones.update(range(start_index, end_index + 1))
            zones.append(make_zone(len(zones) + 1, blocks, tables_by_id, start_index, end_index, match, "table_scope"))

    for index, block in enumerate(blocks):
        if index in covered_by_table_zones:
            continue
        text = block.get("text", "")
        match = best_checklist_match(text, checklist)
        if not match or not zone_anchor_block(block, match):
            continue
        level = block_heading_level(block)
        if level is None:
            end_index = conservative_window_boundary(blocks, index)
        else:
            end_index = next_heading_boundary(blocks, index, level)
        if not zone_has_readable_context(blocks, index, end_index):
            continue
        zone_type = "heading_scope"
        key = (index, end_index, match["title"])
        if key in used_ranges:
            continue
        used_ranges.add(key)
        zones.append(make_zone(len(zones) + 1, blocks, tables_by_id, index, end_index, match, zone_type))
    return zones


def hit_quality_fields(text, item, matched_terms, *, location, table_caption_text="", table_content_text=""):
    normalized_title = normalize(item["title"])
    normalized_text = normalize(text)
    normalized_caption = normalize(table_caption_text)
    normalized_content = normalize(table_content_text)
    normalized_terms = {normalize(term) for term in matched_terms}
    title_hit = bool(normalized_title and normalized_title in normalized_text)
    table_caption_hit = bool(normalized_terms and any(term in normalized_caption for term in normalized_terms))
    table_content_hit = bool(normalized_terms and any(term in normalized_content for term in normalized_terms))
    broad_term_hit = not title_hit and bool(normalized_terms) and all(term in BROAD_HIT_TERMS for term in normalized_terms)
    return {
        "title_hit": title_hit,
        "table_caption_hit": table_caption_hit,
        "table_content_hit": table_content_hit,
        "body_hit": location == "body",
        "broad_term_hit": broad_term_hit,
        "cross_reference_hit": is_cross_reference(text, item["title"]),
    }


def build_checklist_hits(blocks, tables, zones, checklist):
    hits = []
    for item in checklist:
        block_hits = []
        table_hits = []
        zone_hits = []
        terms = [item["title"], *item.get("scan_hints", [])]
        for block in blocks:
            matched_terms = matched_terms_for_text(block.get("text", ""), terms)
            if matched_terms:
                hit = {"block_id": block["block_id"], "matched_terms": matched_terms}
                if block.get("table_id"):
                    hit["table_id"] = block["table_id"]
                    hit.update(hit_quality_fields(
                        block.get("text", ""),
                        item,
                        matched_terms,
                        location="table",
                        table_content_text=block.get("text", ""),
                    ))
                else:
                    hit.update(hit_quality_fields(block.get("text", ""), item, matched_terms, location="body"))
                block_hits.append(hit)
        for table in tables:
            table_text = "\n".join(row.get("row_text", "") for row in table.get("rows", []))
            caption_text = "\n".join([table.get("nearby_heading", ""), table.get("nearby_caption", "")])
            table_match_text = "\n".join([caption_text, table_text])
            matched_terms = matched_terms_for_text(table_match_text, terms)
            if matched_terms:
                hit = {"table_id": table["table_id"], "matched_terms": matched_terms}
                hit.update(hit_quality_fields(
                    table_match_text,
                    item,
                    matched_terms,
                    location="table",
                    table_caption_text=caption_text,
                    table_content_text=table_text,
                ))
                table_hits.append(hit)
        for zone in zones:
            if zone.get("matched_checklist_item") == item["title"]:
                zone_hits.append(zone["zone_id"])
        if block_hits or table_hits or zone_hits:
            hits.append({
                "checklist_item": item["title"],
                "block_hits": block_hits,
                "table_hits": table_hits,
                "zone_hits": zone_hits,
            })
    return hits


def main():
    parser = argparse.ArgumentParser(description="Prepare structured source inputs for tender_map analysis.")
    parser.add_argument("docx", help="Tender .docx file")
    parser.add_argument("--expert-checklist", default=None, help="Path to references/expert-checklist.md")
    parser.add_argument("--output", default="tender_map_inputs.json", help="Output JSON path")
    args = parser.parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"ERROR: file not found: {docx_path}", file=sys.stderr)
        return 2
    checklist = parse_checklist(args.expert_checklist)
    blocks, tables = build_inputs(docx_path, checklist)
    zones = build_zones(blocks, tables, checklist)
    result = {
        "document_name": docx_path.name,
        "blocks": blocks,
        "tables": tables,
        "zones": zones,
        "expert_checklist_hits": build_checklist_hits(blocks, tables, zones, checklist),
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
