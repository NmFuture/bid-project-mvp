from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import nav_store
from .paths import nav_store_path


def _limit_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _connect(manifest_path: Path, manifest: dict[str, Any]):
    path = nav_store_path(manifest_path, manifest)
    if not path.is_file():
        raise RuntimeError("nav store is missing; run s1parse prepare first")
    return nav_store.connect(path)


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.split(r"\s+", query.strip()) if token]


def _query_chars(query: str) -> list[str]:
    chars: list[str] = []
    seen: set[str] = set()
    for char in re.sub(r"\s+", "", query.strip()):
        if char in seen:
            continue
        if char.isalnum() or ord(char) > 127:
            chars.append(char)
            seen.add(char)
    return chars


def _ordered_subsequence(needles: list[str], haystack: str) -> bool:
    if not needles:
        return False
    start = 0
    for char in needles:
        found = haystack.find(char, start)
        if found < 0:
            return False
        start = found + 1
    return True


def _ranked_search(conn, query: str, limit: int) -> list[dict[str, Any]]:
    tokens = _query_tokens(query)
    chars = _query_chars(query)
    if not tokens and not chars:
        return []
    rows = nav_store.fetch_all(
        conn,
        """
        SELECT id, document_id AS documentId, kind, body_index AS bodyIndex, table_id AS tableId,
               row_index AS rowIndex, col_index AS colIndex, text
        FROM evidence
        ORDER BY document_id, body_index, COALESCE(row_index, 0), COALESCE(col_index, 0)
        """,
    )
    compact_query = re.sub(r"\s+", "", query.strip()).lower()
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        text = str(row.get("text") or "")
        compact_text = re.sub(r"\s+", "", text).lower()
        score = 0
        if compact_query and compact_query in compact_text:
            score += 100
        for token in tokens:
            if token.lower() in text.lower():
                score += 30
        if chars:
            matched = sum(1 for char in chars if char.lower() in compact_text)
            coverage = matched / len(chars)
            if coverage >= 0.65:
                score += int(coverage * 60)
            if _ordered_subsequence([char.lower() for char in chars], compact_text):
                score += 25
        if score > 0:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1].get("documentId") or "", item[1].get("bodyIndex") or 0))
    return [row for _, row in ranked[: max(1, min(80, limit))]]


def overview(manifest_path: Path, manifest: dict[str, Any], *, page: int = 1, page_size: int = 30) -> dict[str, Any]:
    conn = _connect(manifest_path, manifest)
    page = max(1, page)
    page_size = max(1, min(80, page_size))
    offset = (page - 1) * page_size
    total = conn.execute("SELECT COUNT(*) AS c FROM blocks").fetchone()["c"]
    rows = nav_store.fetch_all(
        conn,
        """
        SELECT id, document_id AS documentId, body_index AS bodyIndex, block_type AS type,
               text, heading_level AS headingLevel, heading_path AS headingPath, table_id AS tableId
        FROM blocks
        ORDER BY document_id, body_index
        LIMIT ? OFFSET ?
        """,
        (page_size, offset),
    )
    for row in rows:
        row["text"] = _limit_text(row.get("text") or "", 220)
    tables = nav_store.fetch_all(
        conn,
        """
        SELECT id, document_id AS documentId, body_index AS bodyIndex, title, heading_path AS headingPath,
               row_count AS rowCount, col_count AS colCount, header_text AS headerText, preview_text AS previewText
        FROM tables ORDER BY document_id, body_index LIMIT 20
        """,
    )
    for table in tables:
        table["previewText"] = _limit_text(table.get("previewText") or "", 220)
    return {
        "schemaVersion": nav_store.SCHEMA_VERSION,
        "page": page,
        "pageSize": page_size,
        "totalBlocks": total,
        "blocks": rows,
        "tablesPreview": tables,
    }


def search(manifest_path: Path, manifest: dict[str, Any], query: str, *, limit: int = 20) -> dict[str, Any]:
    conn = _connect(manifest_path, manifest)
    tokens = _query_tokens(query)
    if not tokens:
        return {"schemaVersion": nav_store.SCHEMA_VERSION, "query": query, "matchCount": 0, "matches": []}
    conditions = " AND ".join(["text LIKE ?" for _ in tokens])
    params = [f"%{token}%" for token in tokens]
    sql = f"""
        SELECT id, document_id AS documentId, kind, body_index AS bodyIndex, table_id AS tableId,
               row_index AS rowIndex, col_index AS colIndex, text
        FROM evidence
        WHERE {conditions}
        ORDER BY document_id, body_index, COALESCE(row_index, 0), COALESCE(col_index, 0)
        LIMIT ?
    """
    rows = nav_store.fetch_all(conn, sql, (*params, max(1, min(80, limit))))
    if not rows:
        rows = _ranked_search(conn, query, limit)
    for row in rows:
        row["text"] = _limit_text(row.get("text") or "", 260)
    return {"schemaVersion": nav_store.SCHEMA_VERSION, "query": query, "matchCount": len(rows), "matches": rows}


def read(manifest_path: Path, manifest: dict[str, Any], evidence_id: str, *, mode: str = "summary", max_chars: int = 2000) -> dict[str, Any]:
    conn = _connect(manifest_path, manifest)
    row = nav_store.row_to_dict(conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone())
    if row is None:
        raise RuntimeError(f"evidence id not found: {evidence_id}")
    if row.get("kind") == "table":
        table = nav_store.row_to_dict(conn.execute("SELECT * FROM tables WHERE id = ?", (evidence_id,)).fetchone()) or {}
        rows = nav_store.fetch_all(
            conn,
            "SELECT id, row_index AS rowIndex, text FROM table_rows WHERE table_id = ? ORDER BY row_index LIMIT ?",
            (evidence_id, 8 if mode == "summary" else 200),
        )
        payload = {**table, "rows": rows}
    else:
        payload = row
    text = payload.get("text") or payload.get("preview_text") or ""
    payload["text"] = _limit_text(text, max_chars)
    return {"schemaVersion": nav_store.SCHEMA_VERSION, "id": evidence_id, "mode": mode, "record": payload}


def window(manifest_path: Path, manifest: dict[str, Any], evidence_id: str, *, before: int = 3, after: int = 3) -> dict[str, Any]:
    conn = _connect(manifest_path, manifest)
    row = conn.execute("SELECT document_id, body_index FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"evidence id not found: {evidence_id}")
    start = max(1, int(row["body_index"]) - max(0, before))
    end = int(row["body_index"]) + max(0, after)
    rows = nav_store.fetch_all(
        conn,
        """
        SELECT id, document_id AS documentId, body_index AS bodyIndex, block_type AS type,
               text, heading_path AS headingPath, table_id AS tableId
        FROM blocks
        WHERE document_id = ? AND body_index BETWEEN ? AND ?
        ORDER BY body_index
        """,
        (row["document_id"], start, end),
    )
    for item in rows:
        item["text"] = _limit_text(item.get("text") or "", 280)
    return {"schemaVersion": nav_store.SCHEMA_VERSION, "center": evidence_id, "blocks": rows}


def table(manifest_path: Path, manifest: dict[str, Any], table_id: str, *, rows_range: str = "1-12", max_chars: int = 4000) -> dict[str, Any]:
    conn = _connect(manifest_path, manifest)
    table_row = nav_store.row_to_dict(conn.execute("SELECT * FROM tables WHERE id = ?", (table_id,)).fetchone())
    if table_row is None:
        raise RuntimeError(f"table id not found: {table_id}")
    match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", rows_range or "")
    start = int(match.group(1)) if match else 1
    end = int(match.group(2) or start) if match else min(int(table_row["row_count"]), 12)
    start = max(1, start)
    end = max(start, min(end, int(table_row["row_count"])))
    rows = nav_store.fetch_all(
        conn,
        "SELECT id, row_index AS rowIndex, text FROM table_rows WHERE table_id = ? AND row_index BETWEEN ? AND ? ORDER BY row_index",
        (table_id, start, end),
    )
    text_budget = max_chars
    compact_rows = []
    for item in rows:
        text = item.get("text") or ""
        limited = _limit_text(text, max(80, text_budget // max(1, len(rows))))
        compact_rows.append({**item, "text": limited})
    return {
        "schemaVersion": nav_store.SCHEMA_VERSION,
        "table": {
            "id": table_row["id"],
            "documentId": table_row["document_id"],
            "bodyIndex": table_row["body_index"],
            "title": table_row["title"],
            "headingPath": table_row["heading_path"],
            "rowCount": table_row["row_count"],
            "colCount": table_row["col_count"],
            "headerText": table_row["header_text"],
        },
        "rows": compact_rows,
    }
