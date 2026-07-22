from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


CHUNKS_SCHEMA_VERSION = "tender-review-chunks.v1"
STATE_SCHEMA_VERSION = "tender-review-state.v1"
LEDGER_SCHEMA_VERSION = "tender-requirement-ledger.v1"
HEADINGS_STATE_SCHEMA_VERSION = "tender-headings-state.v1"
DEFAULT_CHUNK_CHAR_LIMIT = 12_000
STRUCTURAL_TITLE_PATTERN = re.compile(
    r"^(?:第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*[章节篇卷]|\d+(?:\.\d+)*[.、]?\s+)\S+"
)
ALLOWED_DISPOSITIONS = {
    "map_existing",
    "suggest_add",
    "covered_by_parent",
    "reference_only",
    "not_applicable",
    "pending_confirmation",
}


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def _payload_digest(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tender_input_fingerprint(tender_files: list[dict[str, Any]]) -> str:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, source in enumerate(tender_files):
        if not isinstance(source, dict):
            raise SystemExit(f"tenderFiles[{index}] must be an object")
        file_id = clean_text(source.get("id"))
        path = Path(str(source.get("path") or "")).expanduser()
        if not file_id or not path.is_file():
            raise SystemExit(f"tenderFile must be a readable file with id: {path}")
        if file_id in seen_ids:
            raise SystemExit(f"duplicate tenderFile id: {file_id}")
        seen_ids.add(file_id)
        records.append(
            {
                "id": file_id,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if not records:
        raise SystemExit("no tender files found in manifest")
    return _payload_digest(sorted(records, key=lambda item: item["id"]))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _iter_docx_body(document: DocxDocument) -> Iterator[Paragraph | Table]:
    table_iter = iter(document.tables)
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            table = next(table_iter, None)
            if table is not None:
                yield table


def _heading_level(paragraph: Paragraph) -> int:
    style_name = str(getattr(paragraph.style, "name", "") or "")
    match = re.search(r"(?:Heading|标题)\s*(\d+)", style_name, re.IGNORECASE)
    return max(1, min(9, int(match.group(1)))) if match else 0


def _toc_level(paragraph: Paragraph) -> int:
    style_name = str(getattr(paragraph.style, "name", "") or "")
    match = re.search(r"(?:TOC|目录)\s*(\d+)", style_name, re.IGNORECASE)
    return max(1, min(9, int(match.group(1)))) if match else 0


def _structural_title_level(text: str) -> int:
    value = clean_text(text)
    if not STRUCTURAL_TITLE_PATTERN.match(value):
        return 0
    decimal = re.match(r"^(\d+(?:\.\d+)*)", value)
    return min(9, decimal.group(1).count(".") + 1) if decimal else 1


def _table_rows(table: Table, *, file_id: str, table_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(table.rows, start=1):
        cells = [clean_text(cell.text) for cell in row.cells]
        rows.append(
            {
                "evidence_id": f"{table_id}:R{row_index:04d}",
                "row_index": row_index,
                "file_id": file_id,
                "cells": cells,
                "text": " | ".join(cells),
            }
        )
    return rows


def _source_blocks(source: dict[str, Any]) -> list[dict[str, Any]]:
    file_id = clean_text(source.get("id"))
    path = Path(str(source.get("path") or ""))
    if not file_id or not path.is_file() or path.suffix.lower() != ".docx":
        raise SystemExit(f"tenderFile must be a readable DOCX with id: {path}")

    document = Document(str(path))
    blocks: list[dict[str, Any]] = []
    table_no = 0
    for body_index, item in enumerate(_iter_docx_body(document), start=1):
        if isinstance(item, Paragraph):
            text = clean_text(item.text)
            if not text:
                continue
            blocks.append(
                {
                    "evidence_id": f"{file_id}:B{body_index:06d}",
                    "file_id": file_id,
                    "body_index": body_index,
                    "type": "paragraph",
                    "text": text,
                    "heading_level": _heading_level(item),
                    "toc_level": _toc_level(item),
                    "structural_title_level": _structural_title_level(text),
                }
            )
            continue

        table_no += 1
        table_id = f"{file_id}:T{table_no:04d}"
        rows = _table_rows(item, file_id=file_id, table_id=table_id)
        blocks.append(
            {
                "evidence_id": table_id,
                "file_id": file_id,
                "body_index": body_index,
                "type": "table",
                "table_id": table_id,
                "row_count": len(rows),
                "text": " || ".join(row["text"] for row in rows[:4]),
                "rows": rows,
            }
        )
    return blocks


def _chunks_for_source(
    source: dict[str, Any],
    blocks: list[dict[str, Any]],
    *,
    char_limit: int,
) -> list[dict[str, Any]]:
    file_id = clean_text(source.get("id"))
    file_name = clean_text(source.get("name")) or file_id
    chunks: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    pending_chars = 0

    def flush() -> None:
        nonlocal pending, pending_chars
        if not pending:
            return
        chunks.append(
            {
                "chunk_id": f"{file_id}:C{len(chunks) + 1:04d}",
                "file_id": file_id,
                "file_name": file_name,
                "kind": "table" if len(pending) == 1 and pending[0]["type"] == "table" else "text",
                "start_body_index": pending[0]["body_index"],
                "end_body_index": pending[-1]["body_index"],
                "content_chars": pending_chars,
                "blocks": pending,
            }
        )
        pending = []
        pending_chars = 0

    for block in blocks:
        block_chars = len(clean_text(block.get("text")))
        if block["type"] == "table":
            flush()
            pending = [block]
            pending_chars = block_chars
            flush()
            continue
        if block.get("heading_level") and pending:
            flush()
        if pending and pending_chars + block_chars > char_limit:
            flush()
        pending.append(block)
        pending_chars += block_chars
    flush()
    return chunks


def build_review_workspace(
    tender_files: list[dict[str, Any]],
    work_dir: Path,
    *,
    char_limit: int = DEFAULT_CHUNK_CHAR_LIMIT,
) -> dict[str, Any]:
    input_fingerprint = tender_input_fingerprint(tender_files)
    chunks: list[dict[str, Any]] = []
    source_block_count = 0
    for source in tender_files:
        blocks = _source_blocks(source)
        source_block_count += len(blocks)
        chunks.extend(_chunks_for_source(source, blocks, char_limit=max(1_000, char_limit)))

    chunks_path = work_dir / "tender_review_chunks.json"
    state_path = work_dir / "tender_review_state.json"
    ledger_path = work_dir / "requirement_ledger.json"
    headings_state_path = work_dir / "tender_headings_state.json"
    chunks_payload = {
        "schema_version": CHUNKS_SCHEMA_VERSION,
        "input_fingerprint": input_fingerprint,
        "source_files": [
            {
                "file_id": clean_text(source.get("id")),
                "file_name": clean_text(source.get("name"))
                or Path(str(source.get("path") or "")).name,
            }
            for source in tender_files
        ],
        "source_block_count": source_block_count,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }
    write_json(chunks_path, chunks_payload)
    heading_files, _ = _collect_heading_files(chunks_payload)
    headings_catalog_digest = _heading_catalog_digest(
        heading_files,
        _appendix_catalog_items(work_dir),
    )
    write_json(
        state_path,
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "chunk_count": len(chunks),
            "reviewed_chunk_count": 0,
            "pending_chunk_count": len(chunks),
            "active_batch": {"chunk_ids": []},
            "chunks": [
                {
                    "chunk_id": chunk["chunk_id"],
                    "status": "pending",
                    "review_summary": "",
                    "table_read_ranges": [],
                    "table_truncated_rows": [],
                }
                for chunk in chunks
            ],
        },
    )
    write_json(
        ledger_path,
        {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "requirement_count": 0,
            "requirements": [],
        },
    )
    write_json(
        headings_state_path,
        {
            "schema_version": HEADINGS_STATE_SCHEMA_VERSION,
            "input_fingerprint": input_fingerprint,
            "next_cursor": 0,
            "headings_exhausted": False,
            "headings_catalog_digest": headings_catalog_digest,
            "source_heading_count": 0,
            "appendix_count": 0,
            "requires_full_review": False,
            "full_review_file_ids": [],
            "complete": False,
        },
    )
    return {
        "tenderReviewChunksFile": str(chunks_path),
        "tenderReviewStateFile": str(state_path),
        "requirementLedgerFile": str(ledger_path),
        "tenderReviewChunkCount": len(chunks),
        "tenderReviewBlockCount": source_block_count,
    }


def _load_payload(path: Path, schema_version: str) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"review artifact is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"review artifact is invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        raise SystemExit(f"review artifact schema is invalid: {path}")
    return payload


def _review_artifacts(work_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    chunks = _load_payload(work_dir / "tender_review_chunks.json", CHUNKS_SCHEMA_VERSION)
    state = _load_payload(work_dir / "tender_review_state.json", STATE_SCHEMA_VERSION)
    ledger = _load_payload(work_dir / "requirement_ledger.json", LEDGER_SCHEMA_VERSION)
    return chunks, state, ledger


def _collect_heading_files(
    chunks: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    files_by_id: dict[str, dict[str, Any]] = {
        clean_text(source.get("file_id")): {
            "file_id": clean_text(source.get("file_id")),
            "file_name": clean_text(source.get("file_name")) or clean_text(source.get("file_id")),
            "toc_items": [],
            "body_items": [],
        }
        for source in chunks.get("source_files") or []
        if isinstance(source, dict) and clean_text(source.get("file_id"))
    }
    paragraph_locations: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in chunks.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        file_id = clean_text(chunk.get("file_id"))
        if not file_id:
            continue
        file_entry = files_by_id.setdefault(
            file_id,
            {
                "file_id": file_id,
                "file_name": clean_text(chunk.get("file_name")) or file_id,
                "toc_items": [],
                "body_items": [],
            },
        )
        for block in chunk.get("blocks") or []:
            if not isinstance(block, dict) or block.get("type") != "paragraph":
                continue
            paragraph_locations.setdefault(
                (file_id, clean_text(block.get("text"))),
                {
                    "evidence_id": clean_text(block.get("evidence_id")),
                    "body_index": int(block.get("body_index") or 0),
                },
            )
            toc_level = int(block.get("toc_level") or 0)
            heading_level = int(block.get("heading_level") or 0)
            title_level = int(block.get("structural_title_level") or 0)
            if not toc_level and not heading_level and not title_level:
                continue
            item = {
                "kind": "toc" if toc_level else "heading" if heading_level else "title",
                "level": toc_level or heading_level or title_level,
                "text": clean_text(block.get("text")),
                "evidence_id": clean_text(block.get("evidence_id")),
                "body_index": int(block.get("body_index") or 0),
            }
            destination = "toc_items" if toc_level else "body_items"
            file_entry[destination].append(item)
    return files_by_id, paragraph_locations


def _paged_heading_files(
    files_by_id: dict[str, dict[str, Any]],
    *,
    cursor: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int, bool, int]:
    flattened: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    for file_entry in files_by_id.values():
        selected = file_entry["toc_items"] or file_entry["body_items"]
        source = "toc" if file_entry["toc_items"] else "body_headings"
        flattened.extend((file_entry, source, item) for item in selected)

    page = flattened[cursor : cursor + page_size]
    next_cursor = cursor + len(page)
    complete = next_cursor >= len(flattened)
    paged_files_by_id: dict[str, dict[str, Any]] = {}
    for file_entry, source, item in page:
        paged_files_by_id.setdefault(
            file_entry["file_id"],
            {
                "file_id": file_entry["file_id"],
                "file_name": file_entry["file_name"],
                "source": source,
                "items": [],
            },
        )["items"].append(item)
    return list(paged_files_by_id.values()), next_cursor, complete, len(flattened)


def _appendix_catalog_items(work_dir: Path) -> list[dict[str, Any]]:
    inventory_path = work_dir / "tender_appendix_inventory.json"
    if not inventory_path.is_file():
        return []
    inventory = _load_payload(inventory_path, "tender-appendix-inventory.v1")
    return [item for item in inventory.get("items") or [] if isinstance(item, dict)]


def _heading_catalog_digest(
    files_by_id: dict[str, dict[str, Any]],
    appendices: list[dict[str, Any]],
) -> str:
    files = []
    for file_id in sorted(files_by_id):
        file_entry = files_by_id[file_id]
        source = "toc" if file_entry["toc_items"] else "body_headings"
        selected = file_entry["toc_items"] or file_entry["body_items"]
        files.append(
            {
                "file_id": file_id,
                "source": source if selected else "none",
                "items": [
                    {
                        "kind": clean_text(item.get("kind")),
                        "level": int(item.get("level") or 0),
                        "text": clean_text(item.get("text")),
                        "evidence_id": clean_text(item.get("evidence_id")),
                        "body_index": int(item.get("body_index") or 0),
                    }
                    for item in selected
                ],
            }
        )
    appendix_catalog = [
        {
            "file_id": clean_text(item.get("file_id")),
            "number": clean_text(item.get("number")),
            "title": clean_text(item.get("title")),
            "raw_text": clean_text(item.get("raw_text")),
            "following_table_count": int(item.get("following_table_count") or 0),
        }
        for item in appendices
    ]
    return _payload_digest({"files": files, "appendices": appendix_catalog})


def decision_comparison_context(work_dir: Path) -> dict[str, Any]:
    appendices = decision_appendix_items(work_dir)
    chunks_path = work_dir / "tender_review_chunks.json"
    if not chunks_path.is_file():
        return {
            "schema_version": "outline-comparison-context.v1",
            "heading_count": 0,
            "files": [],
            "appendices": appendices,
        }
    chunks = _load_payload(chunks_path, CHUNKS_SCHEMA_VERSION)
    files_by_id, _ = _collect_heading_files(chunks)
    files: list[dict[str, Any]] = []
    for file_entry in files_by_id.values():
        source = "toc" if file_entry["toc_items"] else "body_headings"
        selected = file_entry["toc_items"] or file_entry["body_items"]
        files.append(
            {
                "file_id": file_entry["file_id"],
                "file_name": file_entry["file_name"],
                "source": source,
                "items": [
                    {
                        "evidence_id": item["evidence_id"],
                        "level": item["level"],
                        "text": item["text"],
                    }
                    for item in selected
                ],
            }
        )
    return {
        "schema_version": "outline-comparison-context.v1",
        "heading_count": sum(len(item["items"]) for item in files),
        "files": files,
        "appendices": appendices,
    }


def decision_appendix_items(work_dir: Path) -> list[dict[str, Any]]:
    inventory_path = work_dir / "tender_appendix_inventory.json"
    if not inventory_path.is_file():
        return []
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"tender appendix inventory is invalid: {inventory_path}: {exc}") from exc
    if (
        not isinstance(inventory, dict)
        or inventory.get("schema_version") != "tender-appendix-inventory.v1"
    ):
        raise SystemExit(f"tender appendix inventory schema is invalid: {inventory_path}")
    return decision_appendix_items_from_inventory(inventory)


def decision_appendix_items_from_inventory(
    inventory: dict[str, Any],
) -> list[dict[str, Any]]:
    if (
        not isinstance(inventory, dict)
        or inventory.get("schema_version") != "tender-appendix-inventory.v1"
    ):
        raise SystemExit("tender appendix inventory schema is invalid")
    result: list[dict[str, Any]] = []
    for item in inventory.get("items") or []:
        if not isinstance(item, dict) or int(item.get("following_table_count") or 0) < 1:
            continue
        result.append(
            {
                "appendix_id": f"APP-{len(result) + 1:04d}",
                "file_id": clean_text(item.get("file_id")),
                "number": clean_text(item.get("number")),
                "title": clean_text(item.get("title")),
                "following_table_count": int(item.get("following_table_count") or 0),
            }
        )
    return result


def tender_headings(
    work_dir: Path,
    *,
    cursor: int = 0,
    page_size: int = 200,
) -> dict[str, Any]:
    if cursor < 0:
        raise SystemExit("headings cursor must be zero or greater")
    if page_size < 1 or page_size > 500:
        raise SystemExit("headings page_size must be between 1 and 500")
    chunks = _load_payload(work_dir / "tender_review_chunks.json", CHUNKS_SCHEMA_VERSION)
    files_by_id, paragraph_locations = _collect_heading_files(chunks)

    appendices: list[dict[str, Any]] = []
    inventory_path = work_dir / "tender_appendix_inventory.json"
    if inventory_path.is_file():
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"tender appendix inventory is invalid: {inventory_path}: {exc}") from exc
        if not isinstance(inventory, dict) or inventory.get("schema_version") != "tender-appendix-inventory.v1":
            raise SystemExit(f"tender appendix inventory schema is invalid: {inventory_path}")
        for item in inventory.get("items") or []:
            if not isinstance(item, dict):
                continue
            public_item = deepcopy(item)
            location = paragraph_locations.get(
                (clean_text(item.get("file_id")), clean_text(item.get("raw_text")))
            )
            if location:
                public_item.update(location)
            appendices.append(public_item)

    state_path = work_dir / "tender_headings_state.json"
    state = _load_payload(state_path, HEADINGS_STATE_SCHEMA_VERSION)
    chunks_fingerprint = clean_text(chunks.get("input_fingerprint"))
    if not chunks_fingerprint or clean_text(state.get("input_fingerprint")) != chunks_fingerprint:
        raise SystemExit("headings state does not match the prepared tender inputs")
    headings_catalog_digest = _heading_catalog_digest(files_by_id, appendices)
    if clean_text(state.get("headings_catalog_digest")) != headings_catalog_digest:
        raise SystemExit("headings catalog does not match the prepared tender inputs")
    source_heading_count = sum(
        len(item["toc_items"] or item["body_items"])
        for item in files_by_id.values()
    )

    appendix_file_ids = {
        clean_text(item.get("file_id"))
        for item in appendices
        if clean_text(item.get("file_id"))
        and int(item.get("following_table_count") or 0) > 0
        and clean_text(item.get("raw_text") or item.get("number") or item.get("title"))
    }
    full_review_file_ids = sorted(
        file_id
        for file_id, file_entry in files_by_id.items()
        if not file_entry["toc_items"]
        and not file_entry["body_items"]
        and file_id not in appendix_file_ids
    )
    headings_exhausted = bool(state.get("headings_exhausted"))
    if headings_exhausted:
        if cursor != 0:
            raise SystemExit("headings cursor must be 0 after headings are exhausted")
        files: list[dict[str, Any]] = []
        next_cursor_value = 0
        pagination_complete = True
    else:
        expected_cursor = int(state.get("next_cursor") or 0)
        if source_heading_count and cursor != expected_cursor:
            raise SystemExit(f"headings cursor must be {expected_cursor}")
        files, next_cursor_value, pagination_complete, source_heading_count = (
            _paged_heading_files(files_by_id, cursor=cursor, page_size=page_size)
        )

    full_review_complete, full_review_pending_count, _ = _full_review_progress(
        work_dir,
        chunks,
        full_review_file_ids,
    )
    complete = pagination_complete and full_review_complete
    full_review_files = [
        {
            "file_id": file_id,
            "file_name": files_by_id[file_id]["file_name"],
            "source": "full_text_review",
            "items": [],
        }
        for file_id in full_review_file_ids
    ]
    files.extend(full_review_files)
    write_json(
        state_path,
        {
            "schema_version": HEADINGS_STATE_SCHEMA_VERSION,
            "input_fingerprint": chunks_fingerprint,
            "next_cursor": next_cursor_value if not pagination_complete else 0,
            "headings_exhausted": pagination_complete,
            "headings_catalog_digest": headings_catalog_digest,
            "source_heading_count": source_heading_count,
            "appendix_count": len(appendices),
            "requires_full_review": bool(full_review_file_ids),
            "full_review_file_ids": full_review_file_ids,
            "complete": complete,
        },
    )
    return {
        "schema_version": "tender-headings.v1",
        "file_count": len(files_by_id),
        "heading_count": source_heading_count,
        "returned_heading_count": sum(len(item["items"]) for item in files),
        "appendix_count": len(appendices),
        "cursor": str(cursor),
        "next_cursor": "" if pagination_complete else str(next_cursor_value),
        "requires_full_review": bool(full_review_file_ids),
        "full_review_pending_chunk_count": full_review_pending_count,
        "complete": complete,
        "files": files,
    }


def headings_complete(work_dir: Path) -> bool:
    state = _load_payload(
        work_dir / "tender_headings_state.json",
        HEADINGS_STATE_SCHEMA_VERSION,
    )
    return bool(state.get("complete"))


def _full_review_progress(
    work_dir: Path,
    chunks: dict[str, Any],
    file_ids: list[str],
) -> tuple[bool, int, list[dict[str, Any]]]:
    if not file_ids:
        return True, 0, []
    review_state = _load_payload(work_dir / "tender_review_state.json", STATE_SCHEMA_VERSION)
    state_by_id = _state_by_chunk_id(review_state)
    file_id_set = set(file_ids)
    target_chunks = [
        chunk
        for chunk in chunks.get("chunks") or []
        if isinstance(chunk, dict) and clean_text(chunk.get("file_id")) in file_id_set
    ]
    present_file_ids = {clean_text(chunk.get("file_id")) for chunk in target_chunks}
    missing_file_count = len(file_id_set - present_file_ids)
    proof_entries: list[dict[str, Any]] = []
    pending_count = missing_file_count
    for chunk in target_chunks:
        chunk_id = clean_text(chunk.get("chunk_id"))
        entry = state_by_id.get(chunk_id) or {}
        if entry.get("status") != "reviewed":
            pending_count += 1
        proof_entries.append(
            {
                "chunk_id": chunk_id,
                "status": clean_text(entry.get("status")),
                "review_summary": clean_text(entry.get("review_summary")),
                "table_read_ranges": entry.get("table_read_ranges") or [],
                "table_truncated_rows": entry.get("table_truncated_rows") or [],
            }
        )
    return pending_count == 0, pending_count, proof_entries


def require_headings_complete(
    work_dir: Path,
    tender_files: list[dict[str, Any]],
) -> dict[str, str]:
    chunks = _load_payload(work_dir / "tender_review_chunks.json", CHUNKS_SCHEMA_VERSION)
    state = _load_payload(work_dir / "tender_headings_state.json", HEADINGS_STATE_SCHEMA_VERSION)
    expected_fingerprint = tender_input_fingerprint(tender_files)
    if clean_text(chunks.get("input_fingerprint")) != expected_fingerprint:
        raise SystemExit("tender review workspace does not match the current tender inputs")
    if clean_text(state.get("input_fingerprint")) != expected_fingerprint:
        raise SystemExit("headings state does not match the current tender inputs")

    files_by_id, _ = _collect_heading_files(chunks)
    appendices = _appendix_catalog_items(work_dir)
    headings_catalog_digest = _heading_catalog_digest(files_by_id, appendices)
    if clean_text(state.get("headings_catalog_digest")) != headings_catalog_digest:
        raise SystemExit("headings catalog does not match the prepared tender inputs")
    appendix_file_ids = {
        clean_text(item.get("file_id"))
        for item in appendices
        if clean_text(item.get("file_id"))
        and int(item.get("following_table_count") or 0) > 0
        and clean_text(item.get("raw_text") or item.get("number") or item.get("title"))
    }
    source_heading_count = sum(
        len(item["toc_items"] or item["body_items"])
        for item in files_by_id.values()
    )
    full_review_file_ids = sorted(
        file_id
        for file_id, file_entry in files_by_id.items()
        if not file_entry["toc_items"]
        and not file_entry["body_items"]
        and file_id not in appendix_file_ids
    )
    if not state.get("headings_exhausted") or int(state.get("next_cursor") or 0) != 0:
        raise SystemExit("必须先完整读取招标目录或分页 headings")
    if int(state.get("source_heading_count") or 0) != source_heading_count:
        raise SystemExit("headings state source heading count is stale")
    if int(state.get("appendix_count") or 0) != len(appendices):
        raise SystemExit("headings state appendix count is stale")
    if list(state.get("full_review_file_ids") or []) != full_review_file_ids:
        raise SystemExit("headings state full-review scope is stale")

    full_review_complete, _, full_review_entries = _full_review_progress(
        work_dir,
        chunks,
        full_review_file_ids,
    )
    if not full_review_complete or not state.get("complete"):
        raise SystemExit("无可靠目录的招标文件必须先完成受控全文审阅")
    proof_payload = {
        "schema_version": HEADINGS_STATE_SCHEMA_VERSION,
        "input_fingerprint": expected_fingerprint,
        "headings_catalog_digest": headings_catalog_digest,
        "source_heading_count": source_heading_count,
        "appendix_count": len(appendices),
        "headings_exhausted": True,
        "requires_full_review": bool(full_review_file_ids),
        "full_review_file_ids": full_review_file_ids,
        "full_review_state_digest": _payload_digest(full_review_entries),
        "complete": True,
    }
    return {
        "tenderInputsDigest": expected_fingerprint,
        "headingsStateDigest": _payload_digest(proof_payload),
    }


def _state_by_chunk_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("chunk_id") or ""): item
        for item in state.get("chunks") or []
        if isinstance(item, dict) and str(item.get("chunk_id") or "")
    }


def _chunk_by_id(chunks: dict[str, Any], chunk_id: str) -> dict[str, Any] | None:
    return next(
        (
            chunk
            for chunk in chunks.get("chunks") or []
            if isinstance(chunk, dict) and str(chunk.get("chunk_id") or "") == chunk_id
        ),
        None,
    )


def _public_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(chunk)
    for block in result.get("blocks") or []:
        if isinstance(block, dict) and block.get("type") == "table":
            block.pop("rows", None)
    return result


def _public_chunk_with_state(
    chunk: dict[str, Any],
    state_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result = _public_chunk(chunk)
    state_entry = state_by_id.get(clean_text(chunk.get("chunk_id"))) or {}
    if chunk.get("kind") != "table":
        return result
    for block in result.get("blocks") or []:
        if isinstance(block, dict) and block.get("type") == "table":
            block["read_ranges"] = deepcopy(state_entry.get("table_read_ranges") or [])
            block["truncated_rows"] = list(state_entry.get("table_truncated_rows") or [])
            block["fully_read"] = _table_is_fully_read(chunk, state_entry)
    return result


def _refresh_state_counts(state: dict[str, Any]) -> None:
    entries = [item for item in state.get("chunks") or [] if isinstance(item, dict)]
    reviewed = sum(1 for item in entries if item.get("status") == "reviewed")
    state["chunk_count"] = len(entries)
    state["reviewed_chunk_count"] = reviewed
    state["pending_chunk_count"] = len(entries) - reviewed


def next_review_chunk(work_dir: Path) -> dict[str, Any]:
    chunks, state, _ = _review_artifacts(work_dir)
    state_by_id = _state_by_chunk_id(state)
    pending = next(
        (
            chunk
            for chunk in chunks.get("chunks") or []
            if isinstance(chunk, dict)
            and (state_by_id.get(str(chunk.get("chunk_id") or "")) or {}).get("status") != "reviewed"
        ),
        None,
    )
    _refresh_state_counts(state)
    return {
        "schema_version": "tender-review-next.v1",
        "chunk": _public_chunk(pending) if pending else None,
        "reviewed_chunk_count": state["reviewed_chunk_count"],
        "remaining_chunk_count": state["pending_chunk_count"],
    }


def next_review_batch(
    work_dir: Path,
    *,
    max_chunks: int = 8,
    max_chars: int = 24_000,
) -> dict[str, Any]:
    chunks, state, _ = _review_artifacts(work_dir)
    state_by_id = _state_by_chunk_id(state)
    active_batch = state.get("active_batch") if isinstance(state.get("active_batch"), dict) else {}
    active_ids = [
        clean_text(value)
        for value in active_batch.get("chunk_ids") or []
        if clean_text(value)
    ]
    active_chunks = [_chunk_by_id(chunks, chunk_id) for chunk_id in active_ids]
    if active_ids and all(
        chunk is not None and (state_by_id.get(chunk_id) or {}).get("status") != "reviewed"
        for chunk_id, chunk in zip(active_ids, active_chunks)
    ):
        selected = [
            _public_chunk_with_state(chunk, state_by_id)
            for chunk in active_chunks
            if chunk is not None
        ]
        selected_chars = len(json.dumps(selected, ensure_ascii=False))
        _refresh_state_counts(state)
        return {
            "schema_version": "tender-review-next-batch.v1",
            "chunks": selected,
            "chunk_ids": active_ids,
            "batch_chunk_count": len(selected),
            "batch_chars": selected_chars,
            "reviewed_chunk_count": state["reviewed_chunk_count"],
            "remaining_chunk_count": state["pending_chunk_count"],
        }

    pending_chunks = [
        chunk
        for chunk in chunks.get("chunks") or []
        if isinstance(chunk, dict)
        and (state_by_id.get(clean_text(chunk.get("chunk_id"))) or {}).get("status") != "reviewed"
    ]
    selected: list[dict[str, Any]] = []
    selected_chars = 0
    for chunk in pending_chunks:
        if len(selected) >= max(1, int(max_chunks)):
            break
        public_chunk = _public_chunk_with_state(chunk, state_by_id)
        chunk_chars = len(json.dumps(public_chunk, ensure_ascii=False))
        if selected and selected_chars + chunk_chars > max(1_000, int(max_chars)):
            break
        selected.append(public_chunk)
        selected_chars += chunk_chars

    _refresh_state_counts(state)
    selected_ids = [clean_text(chunk.get("chunk_id")) for chunk in selected]
    state["active_batch"] = {"chunk_ids": selected_ids}
    write_json(work_dir / "tender_review_state.json", state)
    return {
        "schema_version": "tender-review-next-batch.v1",
        "chunks": selected,
        "chunk_ids": selected_ids,
        "batch_chunk_count": len(selected),
        "batch_chars": selected_chars,
        "reviewed_chunk_count": state["reviewed_chunk_count"],
        "remaining_chunk_count": state["pending_chunk_count"],
    }


def _merge_ranges(ranges: list[dict[str, Any]], start: int, end: int) -> list[dict[str, int]]:
    normalized = [(int(item.get("start") or 0), int(item.get("end") or 0)) for item in ranges]
    normalized.append((start, end))
    merged: list[list[int]] = []
    for range_start, range_end in sorted(normalized):
        if range_start <= 0 or range_end < range_start:
            continue
        if not merged or range_start > merged[-1][1] + 1:
            merged.append([range_start, range_end])
        else:
            merged[-1][1] = max(merged[-1][1], range_end)
    return [{"start": item[0], "end": item[1]} for item in merged]


def _find_table(chunks: dict[str, Any], table_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for chunk in chunks.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        for block in chunk.get("blocks") or []:
            if isinstance(block, dict) and block.get("type") == "table" and block.get("table_id") == table_id:
                return chunk, block
    raise SystemExit(f"table id not found: {table_id}")


def _find_evidence(chunks: dict[str, Any], evidence_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for chunk in chunks.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        for block in chunk.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if clean_text(block.get("evidence_id")) == evidence_id:
                return chunk, block
            for row in block.get("rows") or []:
                if isinstance(row, dict) and clean_text(row.get("evidence_id")) == evidence_id:
                    return chunk, {**row, "type": "table_row", "body_index": block.get("body_index")}
    raise SystemExit(f"evidence id not found: {evidence_id}")


def _limit_text(value: Any, max_chars: int) -> tuple[str, bool]:
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[: max(0, max_chars - 1)] + "…", True


def read_evidence(work_dir: Path, evidence_id: str, *, max_chars: int = 4_000) -> dict[str, Any]:
    chunks, _, _ = _review_artifacts(work_dir)
    chunk, record = _find_evidence(chunks, evidence_id)
    result = deepcopy(record)
    result.pop("rows", None)
    result["text"], truncated = _limit_text(result.get("text"), max_chars)
    return {
        "schema_version": "tender-review-read.v1",
        "chunk_id": chunk.get("chunk_id") or "",
        "truncated": truncated,
        "record": result,
    }


def read_window(
    work_dir: Path,
    evidence_id: str,
    *,
    before: int = 4,
    after: int = 6,
) -> dict[str, Any]:
    chunks, _, _ = _review_artifacts(work_dir)
    _, center = _find_evidence(chunks, evidence_id)
    file_id = clean_text(center.get("file_id"))
    body_index = int(center.get("body_index") or 0)
    start = max(1, body_index - max(0, int(before)))
    end = body_index + max(0, int(after))
    blocks: list[dict[str, Any]] = []
    for chunk in chunks.get("chunks") or []:
        if not isinstance(chunk, dict) or clean_text(chunk.get("file_id")) != file_id:
            continue
        for block in chunk.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            index = int(block.get("body_index") or 0)
            if start <= index <= end:
                item = deepcopy(block)
                item.pop("rows", None)
                blocks.append(item)
    blocks.sort(key=lambda item: int(item.get("body_index") or 0))
    return {
        "schema_version": "tender-review-window.v1",
        "center": evidence_id,
        "blocks": blocks,
    }


def read_table(
    work_dir: Path,
    table_id: str,
    *,
    start: int = 1,
    end: int = 24,
    max_chars: int = 8_000,
) -> dict[str, Any]:
    chunks, state, _ = _review_artifacts(work_dir)
    chunk, table = _find_table(chunks, table_id)
    row_count = int(table.get("row_count") or 0)
    start = max(1, min(int(start), max(1, row_count)))
    end = max(start, min(int(end), row_count))
    rows = [
        row
        for row in table.get("rows") or []
        if isinstance(row, dict) and start <= int(row.get("row_index") or 0) <= end
    ]
    per_row_limit = max(40, int(max_chars) // max(1, len(rows)))
    output_rows: list[dict[str, Any]] = []
    truncated_rows: list[int] = []
    for row in rows:
        text = str(row.get("text") or "")
        limited = text if len(text) <= per_row_limit else text[: per_row_limit - 1] + "…"
        row_index = int(row.get("row_index") or 0)
        if limited != text:
            truncated_rows.append(row_index)
        output_rows.append(
            {
                "evidence_id": row.get("evidence_id") or "",
                "row_index": row_index,
                "text": limited,
            }
        )

    state_entry = _state_by_chunk_id(state).get(str(chunk.get("chunk_id") or ""))
    if state_entry is None:
        raise SystemExit(f"review state has no table chunk: {table_id}")
    state_entry["table_read_ranges"] = _merge_ranges(state_entry.get("table_read_ranges") or [], start, end)
    previous_truncated = {int(value) for value in state_entry.get("table_truncated_rows") or []}
    for row in rows:
        previous_truncated.discard(int(row.get("row_index") or 0))
    previous_truncated.update(truncated_rows)
    state_entry["table_truncated_rows"] = sorted(value for value in previous_truncated if value > 0)
    _refresh_state_counts(state)
    write_json(work_dir / "tender_review_state.json", state)

    returned_end = int(output_rows[-1]["row_index"]) if output_rows else end
    has_more = returned_end < row_count
    span = max(1, end - start + 1)
    next_range = f"{returned_end + 1}-{min(row_count, returned_end + span)}" if has_more else ""
    return {
        "schema_version": "tender-review-table.v1",
        "table": {"table_id": table_id, "row_count": row_count},
        "returned_range": {"start": start, "end": returned_end},
        "has_more": has_more,
        "next_range": next_range,
        "truncated": bool(truncated_rows),
        "truncated_rows": truncated_rows,
        "rows": output_rows,
    }


def read_tables(
    work_dir: Path,
    table_ids: list[str],
    *,
    start: int = 1,
    end: int = 24,
    max_chars: int = 8_000,
) -> dict[str, Any]:
    normalized_ids = list(dict.fromkeys(clean_text(value) for value in table_ids if clean_text(value)))
    if not normalized_ids:
        raise SystemExit("tableIds must be a non-empty list")
    tables = [
        read_table(work_dir, table_id, start=start, end=end, max_chars=max_chars)
        for table_id in normalized_ids
    ]
    return {
        "schema_version": "tender-review-tables.v1",
        "table_count": len(tables),
        "tables": tables,
    }


def _table_is_fully_read(chunk: dict[str, Any], state_entry: dict[str, Any]) -> bool:
    if chunk.get("kind") != "table":
        return True
    table = next((block for block in chunk.get("blocks") or [] if block.get("type") == "table"), {})
    row_count = int(table.get("row_count") or 0)
    ranges = state_entry.get("table_read_ranges") or []
    fully_ranged = bool(ranges) and int(ranges[0].get("start") or 0) == 1 and int(ranges[-1].get("end") or 0) >= row_count
    return fully_ranged and not state_entry.get("table_truncated_rows")


def _chunk_evidence_ids(chunk: dict[str, Any]) -> set[str]:
    evidence_ids: set[str] = set()
    for block in chunk.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        evidence_id = clean_text(block.get("evidence_id"))
        if evidence_id:
            evidence_ids.add(evidence_id)
        for row in block.get("rows") or []:
            if isinstance(row, dict) and clean_text(row.get("evidence_id")):
                evidence_ids.add(clean_text(row.get("evidence_id")))
    return evidence_ids


def _known_template_targets(work_dir: Path) -> set[str]:
    path = work_dir / "template_structure.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        clean_text(value).casefold()
        for item in payload.get("items") or []
        if isinstance(item, dict)
        for value in (item.get("number"), item.get("title"))
        if clean_text(value)
    }


def _normalize_requirement(
    raw: Any,
    *,
    chunk: dict[str, Any] | None = None,
    chunks: list[dict[str, Any]] | None = None,
    known_target_nodes: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SystemExit("each requirement must be an object")
    obligation = clean_text(raw.get("obligation"))
    if not obligation:
        raise SystemExit("requirement obligation is required")
    disposition = clean_text(raw.get("disposition"))
    if disposition not in ALLOWED_DISPOSITIONS:
        raise SystemExit(f"unsupported requirement disposition: {disposition}")
    raw_evidence_ids = raw.get("evidence_ids")
    if not isinstance(raw_evidence_ids, list):
        raise SystemExit("requirement evidence_ids must be a non-empty list")
    evidence_ids = list(dict.fromkeys(clean_text(value) for value in raw_evidence_ids if clean_text(value)))
    if not evidence_ids:
        raise SystemExit("requirement evidence_ids must be a non-empty list")
    allowed_chunks = chunks if chunks is not None else ([chunk] if chunk is not None else [])
    allowed_evidence_ids = {
        evidence_id
        for allowed_chunk in allowed_chunks
        for evidence_id in _chunk_evidence_ids(allowed_chunk)
    }
    foreign_ids = [value for value in evidence_ids if value not in allowed_evidence_ids]
    if foreign_ids:
        raise SystemExit("requirement evidence_id 不属于当前分块: " + ", ".join(foreign_ids))
    source_chunk_id = next(
        (
            clean_text(allowed_chunk.get("chunk_id"))
            for allowed_chunk in allowed_chunks
            if evidence_ids[0] in _chunk_evidence_ids(allowed_chunk)
        ),
        "",
    )

    target_node = clean_text(raw.get("target_node"))
    proposed_title = clean_text(raw.get("proposed_title"))
    reason = clean_text(raw.get("reason"))
    if disposition in {"map_existing", "covered_by_parent"} and not target_node:
        raise SystemExit(f"{disposition} requires target_node")
    if (
        disposition in {"map_existing", "covered_by_parent"}
        and target_node.casefold() not in (known_target_nodes or set())
        and re.search(r"[/、；;+]", target_node)
    ):
        raise SystemExit("target_node 必须是单一目录节点；跨节点义务请拆成多条 requirement")
    if disposition == "suggest_add":
        if not proposed_title:
            raise SystemExit("suggest_add requires proposed_title")
        if not reason:
            raise SystemExit("suggest_add requires reason")
    if disposition == "pending_confirmation":
        if not (target_node or proposed_title):
            raise SystemExit("pending_confirmation requires target_node or proposed_title")
        if not reason:
            raise SystemExit("pending_confirmation requires reason")
    if disposition in {"reference_only", "not_applicable"} and not reason:
        raise SystemExit(f"{disposition} requires reason")
    return {
        "chunk_id": source_chunk_id,
        "evidence_ids": evidence_ids,
        "obligation": obligation,
        "condition": clean_text(raw.get("condition")),
        "disposition": disposition,
        "target_node": target_node,
        "proposed_title": proposed_title,
        "reason": reason,
    }


def submit_chunk_review(work_dir: Path, chunk_id: str, review: dict[str, Any]) -> dict[str, Any]:
    chunks, state, ledger = _review_artifacts(work_dir)
    chunk = _chunk_by_id(chunks, chunk_id)
    state_entry = _state_by_chunk_id(state).get(chunk_id)
    if chunk is None or state_entry is None:
        raise SystemExit(f"chunk id not found: {chunk_id}")
    summary = clean_text(review.get("review_summary"))
    if not summary:
        raise SystemExit("review_summary is required")
    requirements = review.get("requirements")
    if not isinstance(requirements, list):
        raise SystemExit("requirements must be a list")
    if not _table_is_fully_read(chunk, state_entry):
        raise SystemExit(f"table chunk must be fully read before review: {chunk_id}")
    known_targets = _known_template_targets(work_dir)
    normalized_requirements = [
        _normalize_requirement(item, chunk=chunk, known_target_nodes=known_targets)
        for item in requirements
    ]
    ledger_items = ledger.get("requirements")
    if not isinstance(ledger_items, list):
        raise SystemExit("requirement ledger requirements must be a list")
    existing_keys = {
        (tuple(item.get("evidence_ids") or []), clean_text(item.get("obligation")))
        for item in ledger_items
        if isinstance(item, dict)
    }
    added_count = 0
    for requirement in normalized_requirements:
        key = (tuple(requirement["evidence_ids"]), requirement["obligation"])
        if key in existing_keys:
            continue
        requirement["requirement_id"] = f"REQ-{len(ledger_items) + 1:05d}"
        ledger_items.append(requirement)
        existing_keys.add(key)
        added_count += 1
    ledger["requirement_count"] = len(ledger_items)
    state_entry["status"] = "reviewed"
    state_entry["review_summary"] = summary
    _refresh_state_counts(state)
    write_json(work_dir / "tender_review_state.json", state)
    write_json(work_dir / "requirement_ledger.json", ledger)
    return {
        "schema_version": "tender-review-submit.v1",
        "chunk_id": chunk_id,
        "status": "reviewed",
        "reviewed_chunk_count": state["reviewed_chunk_count"],
        "pending_chunk_count": state["pending_chunk_count"],
        "added_requirement_count": added_count,
    }


def submit_batch_review(
    work_dir: Path,
    chunk_ids: list[str],
    review: dict[str, Any],
) -> dict[str, Any]:
    chunks, state, ledger = _review_artifacts(work_dir)
    normalized_ids = list(dict.fromkeys(clean_text(value) for value in chunk_ids if clean_text(value)))
    if not normalized_ids:
        raise SystemExit("chunk_ids must be a non-empty list")

    state_by_id = _state_by_chunk_id(state)
    active_batch = state.get("active_batch") if isinstance(state.get("active_batch"), dict) else {}
    active_ids = [
        clean_text(value)
        for value in active_batch.get("chunk_ids") or []
        if clean_text(value)
    ]
    if normalized_ids != active_ids:
        raise SystemExit("chunk_ids 必须与当前受控批次完全一致；请重新调用 next-batch")
    pending_chunks = [
        chunk
        for chunk in chunks.get("chunks") or []
        if isinstance(chunk, dict)
        and (state_by_id.get(clean_text(chunk.get("chunk_id"))) or {}).get("status") != "reviewed"
    ]
    expected_ids = [clean_text(chunk.get("chunk_id")) for chunk in pending_chunks[: len(normalized_ids)]]
    if normalized_ids != expected_ids:
        raise SystemExit("chunk_ids 必须是连续的待审阅前缀，不得跳过或重排分块")
    selected_chunks = pending_chunks[: len(normalized_ids)]

    summary = clean_text(review.get("review_summary"))
    if not summary:
        raise SystemExit("review_summary is required")
    requirements = review.get("requirements")
    if not isinstance(requirements, list):
        raise SystemExit("requirements must be a list")
    for chunk in selected_chunks:
        state_entry = state_by_id.get(clean_text(chunk.get("chunk_id"))) or {}
        if not _table_is_fully_read(chunk, state_entry):
            raise SystemExit(f"table chunk must be fully read before review: {chunk.get('chunk_id')}")

    known_targets = _known_template_targets(work_dir)
    normalized_requirements = [
        _normalize_requirement(item, chunks=selected_chunks, known_target_nodes=known_targets)
        for item in requirements
    ]
    ledger_items = ledger.get("requirements")
    if not isinstance(ledger_items, list):
        raise SystemExit("requirement ledger requirements must be a list")
    existing_keys = {
        (tuple(item.get("evidence_ids") or []), clean_text(item.get("obligation")))
        for item in ledger_items
        if isinstance(item, dict)
    }
    added_count = 0
    for requirement in normalized_requirements:
        key = (tuple(requirement["evidence_ids"]), requirement["obligation"])
        if key in existing_keys:
            continue
        requirement["requirement_id"] = f"REQ-{len(ledger_items) + 1:05d}"
        ledger_items.append(requirement)
        existing_keys.add(key)
        added_count += 1

    for chunk_id in normalized_ids:
        state_entry = state_by_id[chunk_id]
        state_entry["status"] = "reviewed"
        state_entry["review_summary"] = summary
    state["active_batch"] = {"chunk_ids": []}
    ledger["requirement_count"] = len(ledger_items)
    _refresh_state_counts(state)
    write_json(work_dir / "tender_review_state.json", state)
    write_json(work_dir / "requirement_ledger.json", ledger)
    return {
        "schema_version": "tender-review-submit-batch.v1",
        "chunk_ids": normalized_ids,
        "status": "reviewed",
        "reviewed_batch_chunk_count": len(normalized_ids),
        "reviewed_chunk_count": state["reviewed_chunk_count"],
        "pending_chunk_count": state["pending_chunk_count"],
        "added_requirement_count": added_count,
    }


def review_status(work_dir: Path) -> dict[str, Any]:
    chunks, state, ledger = _review_artifacts(work_dir)
    _refresh_state_counts(state)
    unfinished_tables: list[str] = []
    state_by_id = _state_by_chunk_id(state)
    for chunk in chunks.get("chunks") or []:
        if isinstance(chunk, dict) and chunk.get("kind") == "table":
            entry = state_by_id.get(str(chunk.get("chunk_id") or "")) or {}
            if not _table_is_fully_read(chunk, entry):
                unfinished_tables.append(str(chunk.get("chunk_id") or ""))
    return {
        "schema_version": "tender-review-status.v1",
        "chunk_count": state["chunk_count"],
        "reviewed_chunk_count": state["reviewed_chunk_count"],
        "pending_chunk_count": state["pending_chunk_count"],
        "review_coverage": (
            round(state["reviewed_chunk_count"] / state["chunk_count"], 6) if state["chunk_count"] else 1.0
        ),
        "requirement_count": len(ledger.get("requirements") or []),
        "unfinished_table_count": len(unfinished_tables),
        "unfinished_table_chunks": unfinished_tables,
    }


def _flatten_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        flattened.append(node)
        flattened.extend(_flatten_nodes(node.get("children") or []))
    return flattened


def _node_matches(nodes: list[dict[str, Any]], identity: str) -> list[dict[str, Any]]:
    normalized = clean_text(identity).casefold()
    compact = re.sub(r"\s+", "", normalized)
    return [
        node
        for node in nodes
        if compact
        and compact
        in {
            re.sub(r"\s+", "", clean_text(node.get("number")).casefold()),
            re.sub(r"\s+", "", clean_text(node.get("title")).casefold()),
        }
    ]


def _evidence_texts(chunks: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for chunk in chunks.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        for block in chunk.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            evidence_id = clean_text(block.get("evidence_id"))
            if evidence_id:
                result[evidence_id] = clean_text(block.get("text"))
            for row in block.get("rows") or []:
                if isinstance(row, dict) and clean_text(row.get("evidence_id")):
                    result[clean_text(row.get("evidence_id"))] = clean_text(row.get("text"))
    return result


def validate_review_completion(work_dir: Path, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    chunks, state, ledger = _review_artifacts(work_dir)
    status = review_status(work_dir)

    flat_nodes = _flatten_nodes(nodes)
    evidence_by_id = _evidence_texts(chunks)
    for requirement in ledger.get("requirements") or []:
        if not isinstance(requirement, dict):
            raise SystemExit("requirement ledger contains invalid item")
        requirement_id = clean_text(requirement.get("requirement_id")) or "unknown requirement"
        evidence_ids = requirement.get("evidence_ids") or []
        if not evidence_ids or any(clean_text(value) not in evidence_by_id for value in evidence_ids):
            raise SystemExit(f"{requirement_id} 引用了无效 evidenceId")
        disposition = clean_text(requirement.get("disposition"))
        if disposition in {"map_existing", "covered_by_parent"}:
            target = clean_text(requirement.get("target_node"))
            if not _node_matches(flat_nodes, target):
                raise SystemExit(f"{requirement_id} 的承接节点不存在: {target}")
        elif disposition == "suggest_add":
            title = clean_text(requirement.get("proposed_title"))
            matches = _node_matches(flat_nodes, title)
            if not any(node.get("suggestion_action") == "建议增加" for node in matches):
                raise SystemExit(f"{requirement_id} 未落实到最终目录: {title}")
        elif disposition == "pending_confirmation":
            identity = clean_text(requirement.get("proposed_title") or requirement.get("target_node"))
            matches = _node_matches(flat_nodes, identity)
            if not any(node.get("suggestion_action") == "待确认" for node in matches):
                raise SystemExit(f"{requirement_id} 未落实为待确认目录节点: {identity}")

    for node in flat_nodes:
        basis = node.get("tender_basis")
        if not isinstance(basis, dict):
            continue
        search_text = clean_text(basis.get("search_text"))
        if search_text and not any(search_text in text for text in evidence_by_id.values()):
            raise SystemExit(f"目录依据未来自已审阅 evidenceId: {search_text}")

    return {
        "reviewCoverage": status["review_coverage"],
        "requirementCount": status["requirement_count"],
        "unfinishedTableCount": status["unfinished_table_count"],
    }
