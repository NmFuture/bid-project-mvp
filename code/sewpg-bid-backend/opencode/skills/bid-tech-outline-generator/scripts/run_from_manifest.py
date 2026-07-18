from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import review_workflow


AGENTIC_COMMANDS = {
    "prepare",
    "template",
    "headings",
    "next",
    "next-batch",
    "read",
    "window",
    "table",
    "tables",
    "review-chunk",
    "review-batch",
    "validate",
    "status",
    "finalize",
}
ALLOWED_SUGGESTION_ACTIONS = {"必要", "建议增加", "建议删除", "待确认"}
NODE_KEYS = {
    "number",
    "title",
    "suggestion_action",
    "suggestion_reason",
    "tender_basis",
    "children",
}
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WORD_NS}}}"
TOC_TITLE_PATTERN = re.compile(r"^\s*(?:目\s*录|目\s*次)\s*$")
TOC_STYLE_PATTERN = re.compile(r"^(?:toc|目录)\s*([1-9])$", re.IGNORECASE)
HEADING_STYLE_PATTERN = re.compile(r"^(?:heading|标题)\s*([1-9])$", re.IGNORECASE)
CHAPTER_PATTERN = re.compile(
    r"^\s*(?P<number>第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*章)\s*[、.:：-]?\s*(?P<title>.+?)\s*$"
)
DECIMAL_PATTERN = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)+|\d+)\s*[、.:：-]?\s+(?P<title>.+?)\s*$"
)
CHINESE_LIST_PATTERN = re.compile(
    r"^\s*(?P<number>[（(]?[一二三四五六七八九十百]+[）)、.．])\s*(?P<title>.+?)\s*$"
)
TOC_PAGE_SUFFIX_PATTERN = re.compile(r"(?:\.{2,}|…+|\t+|\s{2,})\s*\d+\s*$")
APPENDIX_HEADING_PATTERN = re.compile(
    r"^\s*(?P<number>(?:技术\s*)?附\s*表\s*[A-Za-zＡ-Ｚａ-ｚ]+(?:\s*[.．-]\s*\d+)*)"
    r"\s*[、.:：-]?\s*(?P<title>[\u4e00-\u9fffA-Za-z].+?)\s*$"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and validate S2 technical outline artifacts.")
    parser.add_argument("args", nargs="*")
    parser.add_argument("--manifest", dest="manifest_option")
    parser.add_argument("--response", choices=("summary", "review"), default="summary")
    parsed_args, command_options = parser.parse_known_args()

    command, manifest_text, command_args = resolve_invocation(
        parsed_args.manifest_option,
        [*parsed_args.args, *command_options],
    )
    manifest_path = Path(str(manifest_text or "")).expanduser()
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = load_json_dict(manifest_path, "manifest")

    result = dispatch_command(command, manifest, manifest_path, command_args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def resolve_invocation(manifest_option: str | None, positional_args: list[str]) -> tuple[str, str, list[str]]:
    args = list(positional_args or [])
    command = "prepare"
    if args and args[0] in AGENTIC_COMMANDS:
        command = args.pop(0)
    elif args and args[0] not in AGENTIC_COMMANDS and len(args) > 1:
        raise SystemExit(
            "usage: s2outline [prepare|template|headings|next|next-batch|read|window|table|tables|review-chunk|review-batch|validate|status|finalize] <manifest> [...]"
        )
    manifest_text = str(manifest_option or (args[0] if args else "")).strip()
    if args and not manifest_option:
        args.pop(0)
    return command, manifest_text, args


def _option_value(args: list[str], name: str, default: str) -> str:
    try:
        index = args.index(name)
    except ValueError:
        return default
    if index + 1 >= len(args):
        raise SystemExit(f"{name} requires a value")
    return str(args[index + 1])


def _required_arg(args: list[str], index: int, label: str) -> str:
    if index >= len(args) or not str(args[index]).strip():
        raise SystemExit(f"{label} is required")
    return str(args[index]).strip()


def dispatch_command(
    command: str,
    manifest: dict[str, Any],
    manifest_path: Path,
    command_args: list[str],
) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    if command in {"prepare", "template"}:
        return write_template_structure(manifest, manifest_path)
    if command == "headings":
        return review_workflow.tender_headings(work_dir)
    if command == "next":
        return review_workflow.next_review_chunk(work_dir)
    if command == "next-batch":
        max_chunks = int(_option_value(command_args, "--max-chunks", "8"))
        max_chars = int(_option_value(command_args, "--max-chars", "24000"))
        return review_workflow.next_review_batch(
            work_dir,
            max_chunks=max_chunks,
            max_chars=max_chars,
        )
    if command == "read":
        evidence_id = _required_arg(command_args, 0, "evidenceId")
        max_chars = int(_option_value(command_args, "--max-chars", "4000"))
        return review_workflow.read_evidence(work_dir, evidence_id, max_chars=max_chars)
    if command == "window":
        evidence_id = _required_arg(command_args, 0, "evidenceId")
        before = int(_option_value(command_args, "--before", "4"))
        after = int(_option_value(command_args, "--after", "6"))
        return review_workflow.read_window(work_dir, evidence_id, before=before, after=after)
    if command == "table":
        table_id = _required_arg(command_args, 0, "tableId")
        rows_text = _option_value(command_args, "--rows", "1-24")
        match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", rows_text)
        if not match:
            raise SystemExit("--rows must use start-end")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        max_chars = int(_option_value(command_args, "--max-chars", "8000"))
        return review_workflow.read_table(work_dir, table_id, start=start, end=end, max_chars=max_chars)
    if command == "tables":
        table_ids_text = _required_arg(command_args, 0, "tableIds JSON")
        try:
            table_ids = json.loads(table_ids_text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"tableIds JSON is invalid: {exc}") from exc
        if not isinstance(table_ids, list):
            raise SystemExit("tableIds JSON must be a list")
        rows_text = _option_value(command_args, "--rows", "1-24")
        match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", rows_text)
        if not match:
            raise SystemExit("--rows must use start-end")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        max_chars = int(_option_value(command_args, "--max-chars", "8000"))
        return review_workflow.read_tables(
            work_dir,
            table_ids,
            start=start,
            end=end,
            max_chars=max_chars,
        )
    if command == "review-chunk":
        chunk_id = _required_arg(command_args, 0, "chunkId")
        review_text = _required_arg(command_args, 1, "review JSON")
        try:
            review = json.loads(review_text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"review JSON is invalid: {exc}") from exc
        if not isinstance(review, dict):
            raise SystemExit("review JSON must be an object")
        return review_workflow.submit_chunk_review(work_dir, chunk_id, review)
    if command == "review-batch":
        review_text = _required_arg(command_args, 0, "review JSON")
        try:
            review = json.loads(review_text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"review JSON is invalid: {exc}") from exc
        if not isinstance(review, dict):
            raise SystemExit("review JSON must be an object")
        chunk_ids = review.pop("chunk_ids", None)
        if not isinstance(chunk_ids, list):
            raise SystemExit("review JSON chunk_ids must be a list")
        return review_workflow.submit_batch_review(work_dir, chunk_ids, review)
    if command in {"validate", "status"}:
        return review_workflow.review_status(work_dir)
    if command == "finalize":
        return finalize_manifest(manifest, manifest_path)
    return run_manifest(manifest, manifest_path)["summary"]


def run_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    template_file = existing_path(manifest.get("templateFile"), "templateFile")
    tender_files = tender_inputs(manifest)
    output_file = Path(str(manifest.get("outputFile") or work_dir / "technical_outline.json")).expanduser()
    summary = {
        "schema_version": "technical-outline-inputs.v1",
        "skill": "bid-tech-outline-generator",
        "status": "inputs_validated",
        "manifestPath": str(manifest_path),
        "workDir": str(work_dir),
        "templateFile": str(template_file),
        "tenderFileCount": len(tender_files),
        "tenderFiles": [source_file_payload(item) for item in tender_files],
        "outputFile": str(output_file),
    }
    return {"summary": summary, "review": summary}


def write_template_structure(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    template_file = existing_path(manifest.get("templateFile"), "templateFile")
    structure = extract_template_structure(template_file)
    output_path = work_dir / "template_structure.json"
    output_path.write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
    appendix_inventory = extract_tender_appendix_inventory(tender_inputs(manifest))
    appendix_inventory_path = work_dir / "tender_appendix_inventory.json"
    appendix_inventory_path.write_text(
        json.dumps(appendix_inventory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    review_workspace = review_workflow.build_review_workspace(tender_inputs(manifest), work_dir)
    return {
        "schema_version": "template-structure.v1",
        "source": structure["source"],
        "item_count": len(structure["items"]),
        "templateStructureFile": str(output_path),
        "tenderAppendixItemCount": len(appendix_inventory["items"]),
        "tenderAppendixInventoryFile": str(appendix_inventory_path),
        **review_workspace,
    }


def extract_template_structure(path: Path) -> dict[str, Any]:
    paragraphs = read_docx_paragraphs(path)
    automatic_toc = automatic_toc_items(paragraphs)
    if automatic_toc:
        source = "automatic_toc"
        items = supplement_automatic_toc_with_body_level_three(
            automatic_toc,
            body_heading_items(paragraphs),
        )
    else:
        toc_page = toc_page_items(paragraphs)
        if toc_page:
            source = "toc_page"
            items = toc_page
        else:
            source = "body_headings"
            items = body_heading_items(paragraphs)
    if not items:
        raise SystemExit(f"no usable outline structure found in templateFile: {path}")
    return {
        "schema_version": "template-structure.v1",
        "source": source,
        "template_file": str(path),
        "items": items,
    }


def supplement_automatic_toc_with_body_level_three(
    automatic_toc: list[dict[str, Any]],
    body_headings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    level_two_records: list[tuple[int, dict[str, Any], dict[str, Any] | None]] = []
    automatic_level_one: dict[str, Any] | None = None
    for index, item in enumerate(automatic_toc):
        level = int(item.get("level") or 1)
        if level == 1:
            automatic_level_one = item
        elif level == 2:
            level_two_records.append((index, item, automatic_level_one))
    if not level_two_records:
        return automatic_toc

    body_level_three: dict[int, list[dict[str, Any]]] = {}
    body_level_one: dict[str, Any] | None = None
    anchor_index: int | None = None
    for item in body_headings:
        level = int(item.get("level") or 1)
        if level == 1:
            body_level_one = item
            anchor_index = None
        elif level == 2:
            anchor_index = match_level_two_anchor(item, body_level_one, level_two_records)
        elif level == 3 and anchor_index is not None:
            seen = body_level_three.setdefault(anchor_index, [])
            if any(headings_match(item, existing) for existing in seen):
                continue
            seen.append(item)
    if not body_level_three:
        return automatic_toc

    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(automatic_toc):
        item = automatic_toc[index]
        merged.append(item)
        if int(item.get("level") or 1) != 2:
            index += 1
            continue
        next_index = index + 1
        while next_index < len(automatic_toc) and int(automatic_toc[next_index].get("level") or 1) > 2:
            next_index += 1
        merged.extend(
            merge_level_three_descendants(
                automatic_toc[index + 1 : next_index],
                body_level_three.get(index, []),
            )
        )
        index = next_index
    return merged


def merge_level_three_descendants(
    automatic_descendants: list[dict[str, Any]],
    body_level_three: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not body_level_three:
        return automatic_descendants

    prefix: list[dict[str, Any]] = []
    automatic_groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] | None = None
    for item in automatic_descendants:
        if int(item.get("level") or 1) == 3:
            if current_group:
                automatic_groups.append(current_group)
            current_group = [item]
        elif current_group is None:
            prefix.append(item)
        else:
            current_group.append(item)
    if current_group:
        automatic_groups.append(current_group)

    merged = list(prefix)
    used_group_indexes: set[int] = set()
    for body_item in body_level_three:
        matching_index = next(
            (
                index
                for index, group in enumerate(automatic_groups)
                if index not in used_group_indexes and headings_match(body_item, group[0])
            ),
            None,
        )
        if matching_index is None:
            merged.append(body_item)
            continue
        merged.extend(automatic_groups[matching_index])
        used_group_indexes.add(matching_index)
    for index, group in enumerate(automatic_groups):
        if index not in used_group_indexes:
            merged.extend(group)
    return merged


def match_level_two_anchor(
    body_level_two: dict[str, Any],
    body_level_one: dict[str, Any] | None,
    automatic_records: list[tuple[int, dict[str, Any], dict[str, Any] | None]],
) -> int | None:
    candidates = [record for record in automatic_records if headings_match(body_level_two, record[1])]
    if body_level_one is not None:
        candidates = [
            record
            for record in candidates
            if record[2] is None or headings_match(body_level_one, record[2])
        ]
    return candidates[0][0] if len(candidates) == 1 else None


def headings_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_number = normalize_outline_identity(left.get("number"))
    right_number = normalize_outline_identity(right.get("number"))
    if left_number and right_number:
        return left_number == right_number
    left_title = normalize_outline_identity(left.get("title"))
    right_title = normalize_outline_identity(right.get("title"))
    return bool(left_title and right_title and left_title == right_title)


def extract_tender_appendix_inventory(tender_files: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    item_indexes: dict[tuple[str, str, str], int] = {}
    for source in tender_files:
        file_id = str(source.get("id") or "")
        file_name = str(source.get("name") or "")
        path = Path(str(source.get("path") or ""))
        for heading in read_docx_appendix_headings(path):
            raw_text = str(heading["raw_text"])
            number = str(heading["number"])
            title = str(heading["title"])
            identity = (file_id, number, title)
            item = {
                "file_id": file_id,
                "file_name": file_name,
                "number": number,
                "title": title,
                "raw_text": raw_text,
                "paragraph_index": int(heading.get("paragraph_index") or 0),
                "following_table_count": int(heading.get("following_table_count") or 0),
                "following_text_count": int(heading.get("following_text_count") or 0),
            }
            if identity in item_indexes:
                items[item_indexes[identity]] = item
            else:
                item_indexes[identity] = len(items)
                items.append(item)
    items.sort(key=lambda item: (str(item.get("file_id") or ""), int(item.get("paragraph_index") or 0)))
    return {
        "schema_version": "tender-appendix-inventory.v1",
        "items": items,
    }


def read_docx_appendix_headings(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() != ".docx":
        raise SystemExit(f"tenderFile must be DOCX: {path}")
    with zipfile.ZipFile(path) as archive:
        try:
            root = ET.fromstring(archive.read("word/document.xml"))
        except KeyError as exc:
            raise SystemExit(f"tenderFile has no word/document.xml: {path}") from exc
    body = root.find(f".//{W}body")
    if body is None:
        return []
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    paragraph_index = 0
    for element in body:
        if element.tag == f"{W}p":
            paragraph_index += 1
            raw_text = normalize_space(paragraph_text(element))
            match = APPENDIX_HEADING_PATTERN.match(raw_text)
            if match:
                if current:
                    items.append(current)
                current = {
                    "number": re.sub(r"\s+", "", match.group("number")),
                    "title": re.sub(r"\s+\d+\s*$", "", normalize_space(match.group("title"))).strip(),
                    "raw_text": raw_text,
                    "paragraph_index": paragraph_index,
                    "following_table_count": 0,
                    "following_text_count": 0,
                }
            elif current and raw_text:
                current["following_text_count"] += 1
        elif element.tag == f"{W}tbl" and current:
            current["following_table_count"] += 1
    if current:
        items.append(current)
    return items


def read_docx_paragraphs(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() != ".docx":
        raise SystemExit(f"templateFile must be DOCX: {path}")
    with zipfile.ZipFile(path) as archive:
        styles = read_docx_styles(archive)
        try:
            document_xml = archive.open("word/document.xml")
        except KeyError as exc:
            raise SystemExit(f"templateFile has no word/document.xml: {path}") from exc
        paragraphs: list[dict[str, Any]] = []
        paragraph_index = 0
        with document_xml:
            for _, element in ET.iterparse(document_xml, events=("end",)):
                if element.tag != f"{W}p":
                    continue
                paragraph_index += 1
                text = paragraph_text(element)
                style_id = paragraph_style_id(element)
                style = styles.get(style_id, {})
                outline_level = paragraph_outline_level(element)
                if outline_level is None:
                    outline_level = style.get("outline_level")
                if text.strip():
                    paragraphs.append(
                        {
                            "text": text.strip(),
                            "style_id": style_id,
                            "style_name": str(style.get("name") or style_id),
                            "outline_level": outline_level,
                            "paragraph_index": paragraph_index,
                        }
                    )
                element.clear()
    return paragraphs


def read_docx_styles(archive: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    try:
        root = ET.fromstring(archive.read("word/styles.xml"))
    except KeyError:
        return {}
    styles: dict[str, dict[str, Any]] = {}
    for style in root.findall(f".//{W}style"):
        style_id = str(style.attrib.get(f"{W}styleId") or "")
        if not style_id:
            continue
        name_element = style.find(f"{W}name")
        name = str(name_element.attrib.get(f"{W}val") or "") if name_element is not None else ""
        outline_element = style.find(f".//{W}outlineLvl")
        outline_level = word_level(outline_element.attrib.get(f"{W}val")) if outline_element is not None else None
        styles[style_id] = {"name": name, "outline_level": outline_level}
    return styles


def paragraph_text(element: ET.Element) -> str:
    parts: list[str] = []
    for child in element.iter():
        if child.tag == f"{W}t":
            parts.append(child.text or "")
        elif child.tag == f"{W}tab":
            parts.append("\t")
        elif child.tag in {f"{W}br", f"{W}cr"}:
            parts.append(" ")
    return "".join(parts)


def paragraph_style_id(element: ET.Element) -> str:
    style = element.find(f"./{W}pPr/{W}pStyle")
    return str(style.attrib.get(f"{W}val") or "") if style is not None else ""


def paragraph_outline_level(element: ET.Element) -> int | None:
    outline = element.find(f"./{W}pPr/{W}outlineLvl")
    return word_level(outline.attrib.get(f"{W}val")) if outline is not None else None


def word_level(value: Any) -> int | None:
    try:
        return int(str(value)) + 1
    except (TypeError, ValueError):
        return None


def automatic_toc_items(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        style_match = TOC_STYLE_PATTERN.match(normalize_style_name(paragraph.get("style_name")))
        if not style_match:
            continue
        parsed = parse_heading_text(str(paragraph.get("text") or ""), toc_line=True)
        if not parsed:
            continue
        result.append(structure_item(paragraph, parsed, level=int(style_match.group(1))))
    return result


def toc_page_items(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start_index = next(
        (index for index, paragraph in enumerate(paragraphs) if TOC_TITLE_PATTERN.match(str(paragraph.get("text") or ""))),
        None,
    )
    if start_index is None:
        return []
    result: list[dict[str, Any]] = []
    misses = 0
    for paragraph in paragraphs[start_index + 1 : start_index + 401]:
        text = str(paragraph.get("text") or "")
        if not TOC_PAGE_SUFFIX_PATTERN.search(text):
            if result:
                misses += 1
                if misses >= 5:
                    break
            continue
        parsed = parse_heading_text(text, toc_line=True)
        if not parsed:
            continue
        misses = 0
        result.append(structure_item(paragraph, parsed))
    return result


def body_heading_items(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        style_match = HEADING_STYLE_PATTERN.match(normalize_style_name(paragraph.get("style_name")))
        level = paragraph.get("outline_level")
        if level is None and style_match:
            level = int(style_match.group(1))
        if level is None:
            continue
        parsed = parse_heading_text(str(paragraph.get("text") or ""), default_level=int(level))
        if not parsed:
            title = normalize_space(str(paragraph.get("text") or ""))
            parsed = {"number": "", "title": title, "level": int(level)} if title else None
        if parsed:
            result.append(structure_item(paragraph, parsed, level=int(level)))
    return result


def parse_heading_text(text: str, *, toc_line: bool = False, default_level: int | None = None) -> dict[str, Any] | None:
    clean = text.strip()
    if toc_line:
        clean = TOC_PAGE_SUFFIX_PATTERN.sub("", clean).strip()
    for pattern in (CHAPTER_PATTERN, DECIMAL_PATTERN, CHINESE_LIST_PATTERN):
        match = pattern.match(clean)
        if not match:
            continue
        number = normalize_space(match.group("number"))
        title = normalize_space(match.group("title"))
        if not title:
            return None
        level = default_level or level_from_number(number)
        return {"number": number, "title": title, "level": level}
    return None


def structure_item(paragraph: dict[str, Any], parsed: dict[str, Any], *, level: int | None = None) -> dict[str, Any]:
    return {
        "number": str(parsed.get("number") or ""),
        "title": str(parsed.get("title") or ""),
        "level": max(1, int(level or parsed.get("level") or 1)),
        "paragraph_index": int(paragraph.get("paragraph_index") or 0),
    }


def level_from_number(number: str) -> int:
    compact = re.sub(r"\s+", "", number)
    if compact.startswith("第") and compact.endswith("章"):
        return 1
    if re.fullmatch(r"\d+(?:\.\d+)+", compact):
        return compact.count(".") + 1
    return 1


def normalize_style_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def finalize_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    output_file = Path(str(manifest.get("outputFile") or work_dir / "technical_outline.json")).expanduser()
    outline = load_json_dict(output_file, "outputFile")
    if outline.get("schema_version") != "technical-outline.v1":
        raise SystemExit("outputFile schema_version must be technical-outline.v1")
    nodes = outline.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise SystemExit("outputFile nodes must be a non-empty list")

    action_counts: Counter[str] = Counter()
    total_nodes = validate_nodes(nodes, action_counts=action_counts)
    validate_tender_search_texts(nodes, manifest)
    validate_technical_appendix(nodes, work_dir=work_dir)
    review_summary = (
        review_workflow.validate_review_completion(work_dir, nodes)
        if manifest.get("tenderFiles")
        else {"reviewCoverage": 1.0, "requirementCount": 0, "unfinishedTableCount": 0}
    )
    return {
        "schema_version": "technical-outline.v1",
        "outputFile": str(output_file),
        "summary": {
            "workflowStage": "finalized",
            "total_nodes": total_nodes,
            "action_counts": dict(action_counts),
            **review_summary,
        },
    }


def validate_nodes(
    nodes: list[Any],
    *,
    action_counts: Counter[str],
    path: str = "nodes",
    depth: int = 1,
) -> int:
    total = 0
    for index, raw_node in enumerate(nodes):
        node_path = f"{path}[{index}]"
        if depth > 3:
            raise SystemExit(f"技术标目录最多三级，{node_path} 为第{depth}级目录节点")
        if not isinstance(raw_node, dict):
            raise SystemExit(f"{node_path} must be an object")
        node = raw_node
        extra_keys = set(node) - NODE_KEYS
        if extra_keys:
            raise SystemExit(f"{node_path} has unsupported fields: {', '.join(sorted(extra_keys))}")
        for key in ("number", "title", "suggestion_action", "suggestion_reason", "children"):
            if key not in node:
                raise SystemExit(f"{node_path}.{key} is required")
        if not isinstance(node["number"], str):
            raise SystemExit(f"{node_path}.number must be a string")
        if not isinstance(node["title"], str) or not node["title"].strip():
            raise SystemExit(f"{node_path}.title must be a non-empty string")
        action = str(node["suggestion_action"])
        if action not in ALLOWED_SUGGESTION_ACTIONS:
            raise SystemExit(f"{node_path}.suggestion_action is invalid: {action}")
        if not isinstance(node["suggestion_reason"], str):
            raise SystemExit(f"{node_path}.suggestion_reason must be a string")
        if action != "必要" and not node["suggestion_reason"].strip():
            raise SystemExit(f"{node_path}.suggestion_reason is required for {action}")
        validate_tender_basis(node.get("tender_basis"), node_path)
        if not isinstance(node["children"], list):
            raise SystemExit(f"{node_path}.children must be a list")
        action_counts[action] += 1
        total += 1 + validate_nodes(
            node["children"],
            action_counts=action_counts,
            path=f"{node_path}.children",
            depth=depth + 1,
        )
    return total


def validate_tender_basis(value: Any, node_path: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"file_id", "search_text"}:
        raise SystemExit(f"{node_path}.tender_basis must contain only file_id and search_text")
    if not str(value.get("file_id") or "").strip():
        raise SystemExit(f"{node_path}.tender_basis.file_id must be non-empty")
    if not str(value.get("search_text") or "").strip():
        raise SystemExit(f"{node_path}.tender_basis.search_text must be non-empty")


def validate_tender_search_texts(nodes: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    if not manifest.get("tenderFiles"):
        return
    text_by_file_id: dict[str, list[str]] = {}
    for source in tender_inputs(manifest):
        file_id = str(source.get("id") or "").strip()
        if not file_id:
            continue
        text_by_file_id[file_id] = [
            normalize_space(paragraph.get("text"))
            for paragraph in read_docx_paragraphs(Path(str(source.get("path") or "")))
        ]

    def validate(items: list[dict[str, Any]], path: str) -> None:
        for index, node in enumerate(items):
            node_path = f"{path}[{index}]"
            basis = node.get("tender_basis")
            if isinstance(basis, dict):
                file_id = str(basis.get("file_id") or "").strip()
                search_text = normalize_space(basis.get("search_text"))
                paragraphs = text_by_file_id.get(file_id)
                if paragraphs is None:
                    raise SystemExit(f"{node_path}.tender_basis.file_id 未对应 manifest tenderFile: {file_id}")
                if not any(search_text in paragraph for paragraph in paragraphs):
                    raise SystemExit(f"{node_path}.tender_basis.search_text 无法在 tenderFile 定位: {search_text}")
            validate(node.get("children") or [], f"{node_path}.children")

    validate(nodes, "nodes")


def validate_technical_appendix(nodes: list[dict[str, Any]], *, work_dir: Path) -> None:
    indexes = [index for index, node in enumerate(nodes) if str(node.get("title") or "").strip() == "技术附表"]
    appendix_inventory_path = work_dir / "tender_appendix_inventory.json"
    inventory_items: list[dict[str, Any]] = []
    if appendix_inventory_path.exists():
        appendix_inventory = load_json_dict(appendix_inventory_path, "tenderAppendixInventoryFile")
        raw_inventory_items = appendix_inventory.get("items")
        if not isinstance(raw_inventory_items, list):
            raise SystemExit("tenderAppendixInventoryFile.items must be a list")
        inventory_items = [item for item in raw_inventory_items if isinstance(item, dict)]
    positive_inventory_items = [
        item for item in inventory_items if int(item.get("following_table_count") or 0) > 0
    ]
    if not indexes:
        if positive_inventory_items:
            labels = ", ".join(str(item.get("number") or item.get("title") or "") for item in positive_inventory_items)
            raise SystemExit(f"技术附表遗漏实际表单: {labels}")
        return
    if indexes != [len(nodes) - 1]:
        raise SystemExit("技术附表 must be the single last root node")
    appendix = nodes[indexes[0]]
    for index, child in enumerate(appendix.get("children") or []):
        if child.get("children"):
            raise SystemExit(f"技术附表.children[{index}] must not contain table-field descendants")

    template_structure_path = work_dir / "template_structure.json"
    if not template_structure_path.exists():
        return
    template_structure = load_json_dict(template_structure_path, "templateStructureFile")
    template_items = template_structure.get("items")
    if not isinstance(template_items, list):
        raise SystemExit("templateStructureFile.items must be a list")
    template_numbers = {
        normalize_outline_identity(item.get("number"))
        for item in template_items
        if isinstance(item, dict) and normalize_outline_identity(item.get("number"))
    }
    template_titles = {
        normalize_outline_identity(item.get("title"))
        for item in template_items
        if isinstance(item, dict) and normalize_outline_identity(item.get("title"))
    }
    appendix_nodes = [("技术附表", appendix)]
    appendix_nodes.extend(
        (f"技术附表.children[{index}]", child)
        for index, child in enumerate(appendix.get("children") or [])
    )
    for path, node in appendix_nodes:
        number = normalize_outline_identity(node.get("number"))
        title = normalize_outline_identity(node.get("title"))
        exists_in_template = (number and number in template_numbers) or (title and title in template_titles)
        if not exists_in_template and node.get("suggestion_action") != "建议增加":
            raise SystemExit(f"{path} 在模板目录不存在，suggestion_action 必须为 建议增加")

    if not appendix_inventory_path.exists():
        return
    if not positive_inventory_items:
        return
    for index, child in enumerate(appendix.get("children") or []):
        number = normalize_outline_identity(child.get("number"))
        title = normalize_outline_identity(child.get("title"))
        matches = [
            item
            for item in inventory_items
            if isinstance(item, dict)
            and (
                (number and normalize_outline_identity(item.get("number")) == number)
                or (title and normalize_outline_identity(item.get("title")) == title)
            )
        ]
        if matches and not any(int(item.get("following_table_count") or 0) > 0 for item in matches):
            raise SystemExit(f"技术附表.children[{index}] 没有独立填写表格，不应作为附表节点输出")

    appendix_children = [item for item in appendix.get("children") or [] if isinstance(item, dict)]
    missing_items = []
    for item in positive_inventory_items:
        number = normalize_outline_identity(item.get("number"))
        title = normalize_outline_identity(item.get("title"))
        if not any(
            (number and normalize_outline_identity(child.get("number")) == number)
            or (title and normalize_outline_identity(child.get("title")) == title)
            for child in appendix_children
        ):
            missing_items.append(str(item.get("number") or item.get("title") or ""))
    if missing_items:
        raise SystemExit("技术附表遗漏实际表单: " + ", ".join(missing_items))


def normalize_outline_identity(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def load_json_dict(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} must be a JSON object: {path}")
    return payload


def existing_path(value: Any, label: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if not str(value or "").strip() or not path.exists():
        raise SystemExit(f"{label} not found: {value}")
    return path


def tender_inputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in manifest.get("tenderFiles") or []:
        raw_path = item.get("path") if isinstance(item, dict) else item
        path = Path(str(raw_path or "")).expanduser()
        if not path.exists():
            continue
        result.append(
            {
                "id": str(item.get("id") or "") if isinstance(item, dict) else "",
                "name": str(item.get("name") or path.name) if isinstance(item, dict) else path.name,
                "path": str(path),
                "originalPath": str(item.get("originalPath") or "") if isinstance(item, dict) else "",
            }
        )
    if not result:
        raise SystemExit("no tender files found in manifest")
    return result


def source_file_payload(item: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "path": str(item.get("path") or ""),
        "originalPath": str(item.get("originalPath") or ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
