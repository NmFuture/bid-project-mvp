from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.document_nav import build_document_nav


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _first_json(output_dir: Path) -> Path | None:
    preferred = output_dir / "docling_document.json"
    if preferred.is_file():
        return preferred
    candidates = sorted(path for path in output_dir.rglob("*.json") if path.name != "parse_quality.json")
    return candidates[0] if candidates else None


def _first_markdown(output_dir: Path) -> Path | None:
    preferred = output_dir / "docling.md"
    if preferred.is_file():
        return preferred
    candidates = sorted(output_dir.rglob("*.md"))
    return candidates[0] if candidates else None


def _bbox(raw_bbox: Any) -> list[Any]:
    if isinstance(raw_bbox, list):
        return raw_bbox
    if not isinstance(raw_bbox, dict):
        return []
    keys = ("l", "t", "r", "b")
    if all(key in raw_bbox for key in keys):
        return [raw_bbox[key] for key in keys]
    alternatives = ("x1", "y1", "x2", "y2")
    if all(key in raw_bbox for key in alternatives):
        return [raw_bbox[key] for key in alternatives]
    return []


def _first_prov(raw: dict[str, Any]) -> dict[str, Any]:
    prov = raw.get("prov")
    if isinstance(prov, list) and prov and isinstance(prov[0], dict):
        return prov[0]
    return {}


def _page_no(raw: dict[str, Any]) -> int:
    prov = _first_prov(raw)
    value = prov.get("page_no") or raw.get("pageNo") or raw.get("page")
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _pages_from_docling(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_pages = payload.get("pages")
    pages: list[dict[str, Any]] = []
    if isinstance(raw_pages, dict):
        def sort_key(item: tuple[Any, Any]) -> int:
            raw_key = str(item[0])
            return int(raw_key) if raw_key.isdigit() else 0

        for raw_page_no, raw_page in sorted(raw_pages.items(), key=sort_key):
            page = raw_page if isinstance(raw_page, dict) else {}
            size = page.get("size") if isinstance(page.get("size"), dict) else {}
            page_no = int(raw_page_no) if str(raw_page_no).isdigit() else len(pages) + 1
            pages.append(
                {
                    "pageNo": page_no,
                    "width": size.get("width") or page.get("width"),
                    "height": size.get("height") or page.get("height"),
                    "textDensity": 0,
                }
            )
    elif isinstance(raw_pages, list):
        for index, raw_page in enumerate(raw_pages, start=1):
            page = raw_page if isinstance(raw_page, dict) else {}
            size = page.get("size") if isinstance(page.get("size"), dict) else {}
            pages.append(
                {
                    "pageNo": int(page.get("pageNo") or page.get("page") or index),
                    "width": size.get("width") or page.get("width"),
                    "height": size.get("height") or page.get("height"),
                    "textDensity": 0,
                }
            )
    return pages


def _blocks_from_docling_texts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_texts = payload.get("texts") if isinstance(payload.get("texts"), list) else []
    blocks: list[dict[str, Any]] = []
    for raw in raw_texts:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or raw.get("orig") or "").strip()
        if not text:
            continue
        label = str(raw.get("label") or "").lower()
        block_type = "heading" if label in {"section_header", "title", "heading"} else "paragraph"
        prov = _first_prov(raw)
        blocks.append(
            {
                "pageNo": _page_no(raw),
                "type": block_type,
                "text": text,
                "bbox": _bbox(prov.get("bbox") or raw.get("bbox")),
            }
        )
    return blocks


def _rows_from_table_cells(cells: list[Any]) -> list[list[str]]:
    normalized_cells = [cell for cell in cells if isinstance(cell, dict)]
    row_count = 0
    col_count = 0
    for cell in normalized_cells:
        row_count = max(row_count, int(cell.get("end_row_offset_idx") or 0))
        col_count = max(col_count, int(cell.get("end_col_offset_idx") or 0))
    rows = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in normalized_cells:
        try:
            row_index = int(cell.get("start_row_offset_idx") or 0)
            col_index = int(cell.get("start_col_offset_idx") or 0)
        except (TypeError, ValueError):
            continue
        if 0 <= row_index < row_count and 0 <= col_index < col_count:
            rows[row_index][col_index] = str(cell.get("text") or "").strip()
    return rows


def _tables_from_docling(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    tables: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    for raw in raw_tables:
        if not isinstance(raw, dict):
            continue
        table_id = f"DOCLING-T{len(tables) + 1:04d}"
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        cells = data.get("table_cells") if isinstance(data.get("table_cells"), list) else []
        rows = _rows_from_table_cells(cells)
        title = str(raw.get("caption_text") or raw.get("title") or raw.get("text") or "").strip()
        prov = _first_prov(raw)
        page_no = _page_no(raw)
        bbox = _bbox(prov.get("bbox") or raw.get("bbox"))
        tables.append({"id": table_id, "pageNo": page_no, "title": title, "rows": rows, "bbox": bbox})
        blocks.append({"pageNo": page_no, "type": "table", "text": title or "表格", "bbox": bbox, "tableId": table_id})
    return tables, blocks


def _numeric_bbox(block: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bbox = block.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    try:
        return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    except (TypeError, ValueError):
        return None


def _page_y_axes_from_text_blocks(blocks: list[dict[str, Any]]) -> dict[int, str]:
    by_page: dict[int, list[tuple[int, float]]] = {}
    for order, block in enumerate(blocks):
        bbox = _numeric_bbox(block)
        if bbox is None:
            continue
        _, y1, _, y2 = bbox
        by_page.setdefault(_page_no(block), []).append((order, (y1 + y2) / 2))

    axes: dict[int, str] = {}
    for page_no, ordered_centers in by_page.items():
        ordered_centers.sort(key=lambda item: item[0])
        increasing = 0
        decreasing = 0
        for (_, previous_y), (_, current_y) in zip(ordered_centers, ordered_centers[1:]):
            delta = current_y - previous_y
            if abs(delta) < 1:
                continue
            if delta > 0:
                increasing += 1
            else:
                decreasing += 1
        axes[page_no] = "bottom-left" if decreasing >= increasing else "top-left"
    return axes


def _merge_blocks_in_reading_order(
    text_blocks: list[dict[str, Any]],
    table_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_y_axes = _page_y_axes_from_text_blocks(text_blocks)
    ordered_blocks = [
        (block, order)
        for order, block in enumerate([*text_blocks, *table_blocks])
    ]

    def sort_key(item: tuple[dict[str, Any], int]) -> tuple[int, int, float, float, int]:
        block, original_order = item
        page_no = _page_no(block)
        bbox = _numeric_bbox(block)
        if bbox is None:
            return (page_no, 1, 0, 0, original_order)
        left, y1, right, y2 = bbox
        axis = page_y_axes.get(page_no, "bottom-left")
        top_order = -max(y1, y2) if axis == "bottom-left" else min(y1, y2)
        return (page_no, 0, top_order, min(left, right), original_order)

    return [block for block, _ in sorted(ordered_blocks, key=sort_key)]


def _caption_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or "").strip())
        return " ".join(part for part in parts if part)
    return ""


def _image_source_path(raw: dict[str, Any], output_dir: Path) -> str:
    image = raw.get("image") if isinstance(raw.get("image"), dict) else {}
    source = str(
        image.get("uri")
        or image.get("path")
        or raw.get("uri")
        or raw.get("path")
        or raw.get("sourcePath")
        or ""
    ).strip()
    if not source:
        return ""
    resolved = Path(source)
    if not resolved.is_absolute():
        resolved = output_dir / source
    return resolved.as_posix()


def _images_from_docling(payload: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    raw_pictures = payload.get("pictures") if isinstance(payload.get("pictures"), list) else []
    images: list[dict[str, Any]] = []
    for raw in raw_pictures:
        if not isinstance(raw, dict):
            continue
        source_path = _image_source_path(raw, output_dir)
        prov = _first_prov(raw)
        bbox = _bbox(prov.get("bbox") or raw.get("bbox"))
        caption = _caption_text(raw.get("caption_text") or raw.get("caption") or raw.get("captions") or raw.get("text"))
        if not source_path and not bbox and not caption:
            continue
        images.append(
            {
                "pageNo": _page_no(raw),
                "sourcePath": source_path,
                "bbox": bbox,
                "caption": caption,
            }
        )
    return images


def _markdown_fallback_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("|"):
            continue
        text = line.lstrip("#").strip()
        if text:
            blocks.append({"pageNo": 1, "type": "heading" if line.startswith("#") else "paragraph", "text": text})
    return blocks


def _apply_text_density(pages: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text_by_page: dict[int, int] = {}
    for block in blocks:
        try:
            page_no = int(block.get("pageNo") or 1)
        except (TypeError, ValueError):
            page_no = 1
        text_by_page[page_no] = text_by_page.get(page_no, 0) + len(str(block.get("text") or "").strip())
    if not pages:
        pages = [{"pageNo": page_no, "textDensity": 0} for page_no in sorted(text_by_page)] or [{"pageNo": 1, "textDensity": 0}]
    for page in pages:
        try:
            page_no = int(page.get("pageNo") or 1)
        except (TypeError, ValueError):
            page_no = 1
        page["textDensity"] = 1 if text_by_page.get(page_no, 0) else 0
    return pages


def convert_docling_output_to_document_nav(
    *,
    document_id: str,
    source_path: Path,
    docling_output_dir: Path,
) -> dict[str, Any]:
    json_path = _first_json(docling_output_dir)
    markdown_path = _first_markdown(docling_output_dir)
    payload = _read_json_file(json_path) if json_path else {}

    pages = _pages_from_docling(payload)
    blocks = _blocks_from_docling_texts(payload)
    tables, table_blocks = _tables_from_docling(payload)
    images = _images_from_docling(payload, docling_output_dir)
    blocks = _merge_blocks_in_reading_order(blocks, table_blocks)
    if not blocks and markdown_path and markdown_path.is_file():
        blocks = _markdown_fallback_blocks(markdown_path.read_text(encoding="utf-8", errors="replace"))
    pages = _apply_text_density(pages, blocks)

    warnings: list[str] = []
    if any(block.get("text") and not block.get("bbox") for block in blocks):
        warnings.append("Docling 输出存在缺失 bbox 的文本块，需要结合原文复核定位。")
    quality = {
        "engine": "docling",
        "status": "completed",
        "pageCount": len(pages),
        "lowQualityPages": [page["pageNo"] for page in pages if not page.get("textDensity")],
        "tableCount": len(tables),
        "fallbackUsed": False,
        "warnings": warnings,
    }
    return build_document_nav(
        document_id=document_id,
        source_path=str(source_path),
        source_engine="docling",
        pages=pages,
        blocks=blocks,
        tables=tables,
        images=images,
        quality=quality,
    )
