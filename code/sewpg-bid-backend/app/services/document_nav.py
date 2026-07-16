from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "business-document-nav-v1"


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_no(item: dict[str, Any]) -> int:
    return max(1, _int_value(item.get("pageNo") or item.get("page") or item.get("page_number"), 1))


def _evidence_id(document_id: str, page_no: int, prefix: str, index: int) -> str:
    return f"{document_id}:P{page_no:04d}:{prefix}{index:06d}"


def _text_from_table(table: dict[str, Any]) -> str:
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    row_text = "\n".join(" | ".join(str(cell or "") for cell in row) for row in rows if isinstance(row, list))
    return "\n".join(part for part in (str(table.get("title") or "").strip(), row_text.strip()) if part)


def _evidence(
    *,
    evidence_id: str,
    document_id: str,
    page_no: int,
    kind: str,
    source_engine: str,
    source_text: str,
    bbox: Any = None,
    block_id: str = "",
    table_id: str = "",
    image_id: str = "",
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "documentId": document_id,
        "pageNo": page_no,
        "kind": kind,
        "blockId": block_id,
        "tableId": table_id,
        "imageId": image_id,
        "bbox": bbox if isinstance(bbox, list) else [],
        "sourceText": source_text,
        "sourceEngine": source_engine,
    }


def _with_document_defaults(document_id: str, source_path: str, source_engine: str) -> dict[str, Any]:
    path = Path(source_path)
    return {
        "id": document_id,
        "name": path.name,
        "sourcePath": source_path,
        "sourceEngine": source_engine,
    }


def nav_to_text(document_nav: dict[str, Any]) -> str:
    parts: list[str] = []
    blocks = document_nav.get("blocks") if isinstance(document_nav.get("blocks"), list) else []
    tables_by_id = {
        str(table.get("id") or ""): table
        for table in (document_nav.get("tables") if isinstance(document_nav.get("tables"), list) else [])
        if isinstance(table, dict)
    }
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if text:
            parts.append(text)
        table_id = str(block.get("tableId") or "")
        table = tables_by_id.get(table_id)
        if table:
            table_text = _text_from_table(table)
            if table_text and table_text != text:
                parts.append(table_text)
    return "\n\n".join(parts).strip()


def build_document_nav(
    *,
    document_id: str,
    source_path: str,
    source_engine: str,
    pages: list[dict],
    blocks: list[dict],
    tables: list[dict],
    images: list[dict] | None = None,
    quality: dict | None = None,
) -> dict:
    evidence: list[dict[str, Any]] = []
    block_counts: defaultdict[int, int] = defaultdict(int)
    table_counts: defaultdict[int, int] = defaultdict(int)
    image_counts: defaultdict[int, int] = defaultdict(int)

    normalized_pages: list[dict[str, Any]] = []
    for raw_page in pages:
        if not isinstance(raw_page, dict):
            continue
        page_no = _page_no(raw_page)
        normalized_pages.append(
            {
                **raw_page,
                "pageNo": page_no,
                "sourceEngine": str(raw_page.get("sourceEngine") or source_engine),
                "lowQuality": bool(raw_page.get("lowQuality") or raw_page.get("isLowQuality")),
            }
        )

    normalized_blocks: list[dict[str, Any]] = []
    for raw_block in blocks:
        if not isinstance(raw_block, dict):
            continue
        page_no = _page_no(raw_block)
        block_counts[page_no] += 1
        block_id = str(raw_block.get("id") or f"{document_id}:B{sum(block_counts.values()):06d}")
        evidence_id = str(raw_block.get("evidenceId") or _evidence_id(document_id, page_no, "B", block_counts[page_no]))
        block = {
            **raw_block,
            "id": block_id,
            "documentId": document_id,
            "pageNo": page_no,
            "type": str(raw_block.get("type") or "paragraph"),
            "text": str(raw_block.get("text") or ""),
            "evidenceId": evidence_id,
            "sourceEngine": str(raw_block.get("sourceEngine") or source_engine),
        }
        normalized_blocks.append(block)
        evidence.append(
            _evidence(
                evidence_id=evidence_id,
                document_id=document_id,
                page_no=page_no,
                kind=block["type"],
                source_engine=block["sourceEngine"],
                source_text=block["text"],
                bbox=block.get("bbox"),
                block_id=block_id,
            )
        )

    normalized_tables: list[dict[str, Any]] = []
    for raw_table in tables:
        if not isinstance(raw_table, dict):
            continue
        page_no = _page_no(raw_table)
        table_counts[page_no] += 1
        table_id = str(raw_table.get("id") or f"{document_id}:T{sum(table_counts.values()):04d}")
        evidence_id = str(raw_table.get("evidenceId") or _evidence_id(document_id, page_no, "T", table_counts[page_no]))
        rows = raw_table.get("rows") if isinstance(raw_table.get("rows"), list) else []
        table = {
            **raw_table,
            "id": table_id,
            "documentId": document_id,
            "pageNo": page_no,
            "title": str(raw_table.get("title") or ""),
            "rows": rows,
            "rowCount": int(raw_table.get("rowCount") or len(rows)),
            "colCount": int(raw_table.get("colCount") or max((len(row) for row in rows if isinstance(row, list)), default=0)),
            "evidenceId": evidence_id,
            "sourceEngine": str(raw_table.get("sourceEngine") or source_engine),
        }
        normalized_tables.append(table)
        evidence.append(
            _evidence(
                evidence_id=evidence_id,
                document_id=document_id,
                page_no=page_no,
                kind="table",
                source_engine=table["sourceEngine"],
                source_text=_text_from_table(table),
                bbox=table.get("bbox"),
                table_id=table_id,
            )
        )

    normalized_images: list[dict[str, Any]] = []
    for raw_image in images or []:
        if not isinstance(raw_image, dict):
            continue
        page_no = _page_no(raw_image)
        image_counts[page_no] += 1
        image_id = str(raw_image.get("id") or f"{document_id}:I{sum(image_counts.values()):04d}")
        evidence_id = str(raw_image.get("evidenceId") or _evidence_id(document_id, page_no, "I", image_counts[page_no]))
        image = {
            **raw_image,
            "id": image_id,
            "documentId": document_id,
            "pageNo": page_no,
            "sourcePath": str(raw_image.get("sourcePath") or raw_image.get("path") or ""),
            "evidenceId": evidence_id,
            "sourceEngine": str(raw_image.get("sourceEngine") or source_engine),
        }
        normalized_images.append(image)
        evidence.append(
            _evidence(
                evidence_id=evidence_id,
                document_id=document_id,
                page_no=page_no,
                kind="image",
                source_engine=image["sourceEngine"],
                source_text=str(image.get("caption") or image.get("sourcePath") or ""),
                bbox=image.get("bbox"),
                image_id=image_id,
            )
        )

    normalized_quality = dict(quality or {})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceEngine": source_engine,
        "documents": [_with_document_defaults(document_id, source_path, source_engine)],
        "pages": normalized_pages,
        "blocks": normalized_blocks,
        "tables": normalized_tables,
        "images": normalized_images,
        "evidence": evidence,
        "quality": normalized_quality,
    }
