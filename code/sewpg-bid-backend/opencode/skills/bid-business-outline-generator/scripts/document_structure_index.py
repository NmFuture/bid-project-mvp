from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


TOC_LINE_RE = re.compile(r"(?:\.{2,}|…{2,}|\s{2,}|\t)\s*\d+\s*$")
SIMPLE_PAGE_LINE_RE = re.compile(r"^.{2,90}\s+\d{1,4}\s*$")
FORMAT_HEADING_RE = re.compile(r"(投标文件格式|响应文件格式|商务文件格式|格式及附件|格式文件|附件\s*\d+|附表\s*\d+)")

HIGH_VALUE_CATEGORIES = [
    ("submission_requirement", ["投标文件组成", "提交要求", "递交要求", "投标文件包括", "组成"]),
    ("qualification_requirement", ["资格要求", "资格审查", "投标人资格", "资质", "信誉"]),
    ("scoring_response", ["评标办法", "评分标准", "商务评分", "商务评审", "评分"]),
    ("rejection_clause", ["否决投标", "废标", "符合性审查", "响应性审查", "实质性响应", "实质性要求"]),
    ("bid_bond", ["投标保证金", "保证金"]),
    ("contract_clause", ["合同条款", "履约保证", "合同生效"]),
]


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def compact(text: Any) -> str:
    value = re.sub(r"\s+", "", str(text or "")).lower()
    return re.sub(r"[，。；：、,.\-—_:;()（）\[\]【】《》\"'“”‘’/\\|]", "", value)


def strip_numbering(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    patterns = [
        r"^第[一二三四五六七八九十百千万\d]+章\s*",
        r"^[一二三四五六七八九十百千万]+[、．.\s]+",
        r"^\d+(?:\.\d+)+[、．.\s]*",
        r"^附件\s*\d+[A-Za-z]?(?:[-－]?\d+)?[\s、．.]*",
        r"^附表\s*\d*[A-Za-z]?[\s、．.]*",
        r"^表\s*\d+[A-Za-z]?[\s、．.]*",
        r"^[（(](?:\d+|[一二三四五六七八九十百千万]+)[）)]\s*",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            new_value = re.sub(pattern, "", value, flags=re.I).strip()
            if new_value != value:
                value = new_value
                changed = True
    return value or str(text or "")


def key_terms(text: Any) -> list[str]:
    result: list[str] = []
    for part in re.split(r"[、，,；;及和与/\\\s]+", strip_numbering(text)):
        token = compact(part)
        if len(token) >= 2 and token not in result:
            result.append(token)
    core = compact(strip_numbering(text))
    if core and core not in result:
        result.insert(0, core)
    return result


def has_any(text: Any, terms: list[str]) -> bool:
    value = compact(text)
    return any(compact(term) in value for term in terms)


def is_toc_text(text: str, heading_path: list[str] | None = None) -> bool:
    path_text = " ".join(heading_path or [])
    if compact(path_text) in {"目录", "目次"} or has_any(path_text, ["目录", "目次"]):
        return True
    stripped = (text or "").strip()
    if compact(stripped) in {"目录", "目次"}:
        return True
    return bool(TOC_LINE_RE.search(stripped) or SIMPLE_PAGE_LINE_RE.match(stripped))


def source_kind_for(block: dict[str, Any], fallback: str = "paragraph") -> str:
    block_type = str(block.get("type") or block.get("block_type") or fallback)
    if block_type == "table_cell_marker":
        return "table_cell"
    if block_type == "table_row":
        return "table_row"
    if block_type in {"zone", "table_cell", "table_row"}:
        return block_type
    return "paragraph"


def high_value_category(text: str, heading_path: list[str] | None = None) -> str | None:
    combined = " ".join([text or "", " ".join(heading_path or [])])
    for category, terms in HIGH_VALUE_CATEGORIES:
        if has_any(combined, terms):
            return category
    return None


def scope_hint(text: str, heading_path: list[str] | None = None) -> str:
    if high_value_category(text, heading_path):
        return "high_value_area"
    combined = " ".join([text or "", " ".join(heading_path or [])])
    if has_any(combined, ["投标文件格式", "响应文件格式", "商务文件格式", "格式及附件", "格式文件"]):
        return "format_area"
    if FORMAT_HEADING_RE.search(text or ""):
        return "format_area"
    return "broad_clause"


def make_source_ref(tender: dict[str, Any], block: dict[str, Any], source_kind: str) -> dict[str, Any]:
    return {
        "source_file": str(tender.get("document_name") or ""),
        "source_path": str(tender.get("source_path") or ""),
        "block_id": block.get("block_id"),
        "table_id": block.get("table_id"),
        "row_index": block.get("row_index"),
        "col_index": block.get("col_index"),
        "source_kind": source_kind,
        "heading_path": block.get("heading_path", []) or [],
    }


def normalize_ref(ref: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in ref.items() if value not in (None, "", [])}


def block_record(tender: dict[str, Any], block: dict[str, Any], order: int, text_key: str = "text") -> dict[str, Any]:
    text = str(block.get(text_key) or "")
    heading_path = block.get("heading_path", []) or []
    kind = source_kind_for(block)
    category = high_value_category(text, heading_path)
    return {
        "order": order,
        "block_id": block.get("block_id"),
        "source_text": text,
        "normalized_text": compact(text),
        "title_key": compact(strip_numbering(text)),
        "key_terms": key_terms(text),
        "source_kind": kind,
        "source_type": kind,
        "block_type": block.get("type") or block.get("block_type"),
        "heading_path": heading_path,
        "heading_level": block.get("heading_level"),
        "table_id": block.get("table_id"),
        "row_index": block.get("row_index"),
        "col_index": block.get("col_index"),
        "is_toc": is_toc_text(text, heading_path),
        "scope_hint": scope_hint(text, heading_path),
        "high_value_category": category,
        "source_ref": normalize_ref(make_source_ref(tender, block, kind)),
    }


def contiguous_ranges(blocks: list[dict[str, Any]], predicate, category_key: str = "category") -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in blocks:
        category = predicate(block)
        if category:
            if current and current.get(category_key) == category and block["order"] <= current["end_order"] + 1:
                current["end_order"] = block["order"]
                current["block_ids"].append(block.get("block_id"))
            else:
                current = {
                    category_key: category,
                    "start_order": block["order"],
                    "end_order": block["order"],
                    "block_ids": [block.get("block_id")],
                }
                ranges.append(current)
        else:
            current = None
    return ranges


def build_document_structure_index(tender_map_inputs: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    records: list[dict[str, Any]] = []
    for block in tender_map_inputs.get("blocks", []) or []:
        if isinstance(block, dict):
            records.append(block_record(tender_map_inputs, block, len(records)))

    known_refs = {
        (item.get("table_id"), item.get("row_index"), item.get("col_index"), item.get("source_text"))
        for item in records
        if item.get("table_id")
    }
    for table in tender_map_inputs.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        heading_path = [part.strip() for part in str(table.get("nearby_heading") or "").split("/") if part.strip()]
        for row in table.get("rows", []) or []:
            if not isinstance(row, dict):
                continue
            row_block = {
                "block_id": f"{table.get('table_id')}-r{row.get('row_index')}",
                "type": "table_row",
                "text": row.get("row_text", ""),
                "heading_path": heading_path,
                "table_id": table.get("table_id"),
                "row_index": row.get("row_index"),
            }
            row_key = (row_block.get("table_id"), row_block.get("row_index"), None, row_block.get("text"))
            if row_block["text"] and row_key not in known_refs:
                records.append(block_record(tender_map_inputs, row_block, len(records)))
            for cell in row.get("cells", []) or []:
                if not isinstance(cell, dict):
                    continue
                cell_block = {
                    "block_id": f"{table.get('table_id')}-r{row.get('row_index')}-c{cell.get('col_index')}",
                    "type": "table_cell_marker",
                    "text": cell.get("text", ""),
                    "heading_path": heading_path,
                    "table_id": table.get("table_id"),
                    "row_index": row.get("row_index"),
                    "col_index": cell.get("col_index"),
                }
                cell_key = (cell_block.get("table_id"), cell_block.get("row_index"), cell_block.get("col_index"), cell_block.get("text"))
                if cell_block["text"] and cell_key not in known_refs:
                    records.append(block_record(tender_map_inputs, cell_block, len(records)))

    format_ranges = contiguous_ranges(
        records,
        lambda item: "format_area" if item.get("scope_hint") == "format_area" and not item.get("is_toc") else None,
    )
    high_value_ranges = contiguous_ranges(records, lambda item: item.get("high_value_category") if not item.get("is_toc") else None)
    inverted: dict[str, list[int]] = {}
    for item in records:
        for term in item.get("key_terms", [])[:8]:
            inverted.setdefault(term[:2], []).append(item["order"])
            inverted.setdefault(term, []).append(item["order"])
    elapsed = round(time.perf_counter() - start, 3)
    summary = {
        "blocks": len(records),
        "tables": len(tender_map_inputs.get("tables", []) or []),
        "format_ranges": len(format_ranges),
        "high_value_ranges": len(high_value_ranges),
        "toc_blocks": sum(1 for item in records if item.get("is_toc")),
        "table_cells": sum(1 for item in records if item.get("source_kind") == "table_cell"),
        "elapsed_seconds": elapsed,
    }
    return {
        "schema_version": "document_structure_index.v1",
        "document_name": str(tender_map_inputs.get("document_name") or ""),
        "source_path": str(tender_map_inputs.get("source_path") or ""),
        "blocks": records,
        "format_ranges": format_ranges,
        "high_value_ranges": high_value_ranges,
        "inverted_index": inverted,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a searchable structure index from tender_map_inputs.json.")
    parser.add_argument("tender_map_inputs")
    parser.add_argument("--output", default="document_structure_index.json")
    args = parser.parse_args()

    payload = build_document_structure_index(load_json(args.tender_map_inputs))
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
