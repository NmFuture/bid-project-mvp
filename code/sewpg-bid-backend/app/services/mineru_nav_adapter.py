from __future__ import annotations

import json
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import Any

from app.services.document_nav import build_document_nav


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag.lower() == "tr":
            self._current_row = []
        elif tag.lower() in {"td", "th"}:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif normalized == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_content_list(output_dir: Path) -> Path | None:
    candidates = sorted(
        path
        for path in output_dir.rglob("*_content_list.json")
        if path.name != "parse_quality.json" and "content_list_v2" not in path.name
    )
    return candidates[0] if candidates else None


def _first_json(output_dir: Path) -> Path | None:
    candidates = sorted(
        path
        for path in output_dir.rglob("*.json")
        if path.name != "parse_quality.json" and "content_list" not in path.name
    )
    return candidates[0] if candidates else None


def _first_markdown(output_dir: Path) -> Path | None:
    candidates = sorted(output_dir.rglob("*.md"))
    return candidates[0] if candidates else None


def _markdown_rows(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    index = start
    while index < len(lines) and lines[index].strip().startswith("|") and lines[index].strip().endswith("|"):
        line = lines[index].strip()
        index += 1
        if re.fullmatch(r"\|?[-:\s|]+\|?", line):
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows, index


def _blocks_from_markdown(markdown: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocks: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index].strip()
        if not raw:
            index += 1
            continue
        if raw.startswith("|") and raw.endswith("|"):
            rows, index = _markdown_rows(lines, index)
            if rows:
                title = ""
                for previous in reversed(blocks):
                    if str(previous.get("text") or "").strip():
                        title = str(previous["text"])
                        break
                table_id = f"MD-T{len(tables) + 1:04d}"
                tables.append(
                    {
                        "id": table_id,
                        "pageNo": 1,
                        "title": title,
                        "rows": rows,
                        "markdown": "\n".join("| " + " | ".join(row) + " |" for row in rows),
                    }
                )
                blocks.append({"pageNo": 1, "type": "table", "text": title or "表格", "tableId": table_id})
            continue
        index += 1
        text = raw.lstrip("#").strip()
        block_type = "heading" if raw.startswith("#") else "paragraph"
        blocks.append({"pageNo": 1, "type": block_type, "text": text})
    return blocks, tables


def _normalize_block(raw: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(raw.get("type") or raw.get("blockType") or "").lower()
    block_type = "heading" if raw_type in {"title", "heading", "header"} else "paragraph"
    return {
        "pageNo": raw.get("pageNo") or raw.get("page") or 1,
        "type": block_type,
        "text": raw.get("text") or raw.get("content") or "",
        "bbox": raw.get("bbox") or [],
    }


def _normalize_table(raw: dict[str, Any]) -> dict[str, Any]:
    rows = raw.get("rows") if isinstance(raw.get("rows"), list) else []
    return {
        "pageNo": raw.get("pageNo") or raw.get("page") or 1,
        "title": raw.get("title") or raw.get("caption") or "",
        "rows": rows,
        "bbox": raw.get("bbox") or [],
        "html": raw.get("html") or "",
        "markdown": raw.get("markdown") or "",
    }


def _normalize_image(raw: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    source = str(raw.get("sourcePath") or raw.get("path") or "")
    resolved = Path(source)
    if source and not resolved.is_absolute():
        resolved = output_dir / source
    return {
        "pageNo": raw.get("pageNo") or raw.get("page") or 1,
        "sourcePath": resolved.as_posix() if source else "",
        "bbox": raw.get("bbox") or [],
        "caption": raw.get("caption") or "",
    }


def _page_from_content_item(raw: dict[str, Any]) -> int:
    try:
        return int(raw.get("page_idx")) + 1
    except (TypeError, ValueError):
        return 1


def _caption_text(raw_caption: Any) -> str:
    if isinstance(raw_caption, str):
        return raw_caption.strip()
    if isinstance(raw_caption, list):
        parts: list[str] = []
        for item in raw_caption:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict):
                parts.append(str(item.get("content") or item.get("text") or "").strip())
        return " ".join(part for part in parts if part)
    return ""


def _rows_from_html_table(html: str) -> list[list[str]]:
    parser = _HtmlTableParser()
    parser.feed(html or "")
    return parser.rows


def _content_list_to_nav_parts(items: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    max_page = 0
    blocks: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        page_no = _page_from_content_item(raw)
        max_page = max(max_page, page_no)
        raw_type = str(raw.get("type") or "").lower()
        bbox = raw.get("bbox") or []
        if raw_type in {"text", "header", "page_number"}:
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            block_type = "heading" if raw_type == "text" and raw.get("text_level") else "paragraph"
            blocks.append({"pageNo": page_no, "type": block_type, "text": text, "bbox": bbox})
        elif raw_type == "table":
            table_id = f"MINERU-T{len(tables) + 1:04d}"
            title = _caption_text(raw.get("table_caption"))
            rows = _rows_from_html_table(str(raw.get("table_body") or raw.get("html") or ""))
            table = {
                "id": table_id,
                "pageNo": page_no,
                "title": title,
                "rows": rows,
                "bbox": bbox,
                "html": str(raw.get("table_body") or raw.get("html") or ""),
            }
            tables.append(table)
            blocks.append(
                {
                    "pageNo": page_no,
                    "type": "table",
                    "text": title or "表格",
                    "bbox": bbox,
                    "tableId": table_id,
                }
            )
        elif raw_type in {"chart", "image", "equation"}:
            source_path = str(raw.get("img_path") or raw.get("path") or "")
            caption = _caption_text(raw.get("chart_caption")) or _caption_text(raw.get("table_caption"))
            if raw_type == "equation":
                text = str(raw.get("text") or "").strip()
                if text:
                    blocks.append({"pageNo": page_no, "type": "paragraph", "text": text, "bbox": bbox})
            if source_path:
                images.append({"pageNo": page_no, "sourcePath": source_path, "bbox": bbox, "caption": caption})
    pages = [{"pageNo": page_no, "textDensity": 1} for page_no in range(1, max_page + 1)]
    return pages, blocks, tables, images


def convert_mineru_output_to_document_nav(
    *,
    document_id: str,
    source_path: Path,
    mineru_output_dir: Path,
) -> dict:
    content_list_path = _first_content_list(mineru_output_dir)
    json_path = _first_json(mineru_output_dir)
    markdown_path = _first_markdown(mineru_output_dir)
    payload = _read_json_file(json_path) if json_path else {}

    content_list = _read_json_payload(content_list_path) if content_list_path else []
    if isinstance(content_list, list):
        pages, blocks, tables, images = _content_list_to_nav_parts(content_list)
    else:
        pages, blocks, tables, images = [], [], [], []

    if not pages:
        pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    if not pages:
        pages = [{"pageNo": 1, "textDensity": 0}]

    raw_blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    raw_tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    raw_images = payload.get("images") if isinstance(payload.get("images"), list) else []
    if not blocks and (raw_blocks or raw_tables or raw_images):
        blocks.extend(_normalize_block(block) for block in raw_blocks if isinstance(block, dict))
        for table in raw_tables:
            if isinstance(table, dict):
                normalized = _normalize_table(table)
                normalized_id = f"JSON-T{len(tables) + 1:04d}"
                normalized["id"] = normalized_id
                tables.append(normalized)
                blocks.append(
                    {
                        "pageNo": normalized["pageNo"],
                        "type": "table",
                        "text": normalized["title"] or "表格",
                        "bbox": normalized.get("bbox") or [],
                        "tableId": normalized_id,
                    }
                )
        images.extend(_normalize_image(image, mineru_output_dir) for image in raw_images if isinstance(image, dict))
    elif not blocks and markdown_path and markdown_path.is_file():
        markdown_blocks, markdown_tables = _blocks_from_markdown(markdown_path.read_text(encoding="utf-8", errors="replace"))
        blocks.extend(markdown_blocks)
        tables.extend(markdown_tables)

    warnings: list[str] = []
    if any(not block.get("bbox") for block in blocks):
        warnings.append("MinerU 输出存在缺失 bbox 的文本块。")

    quality = {
        "engine": "mineru",
        "status": "completed",
        "pageCount": len(pages),
        "lowQualityPages": [],
        "tableCount": len(tables),
        "warnings": warnings,
    }
    return build_document_nav(
        document_id=document_id,
        source_path=str(source_path),
        source_engine="mineru",
        pages=pages,
        blocks=blocks,
        tables=tables,
        images=images,
        quality=quality,
    )
