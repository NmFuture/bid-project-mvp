from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "bid-business-agentic-nav-v1"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            text_path TEXT NOT NULL DEFAULT '',
            block_count INTEGER NOT NULL DEFAULT 0,
            table_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS blocks (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            body_index INTEGER NOT NULL,
            block_type TEXT NOT NULL,
            text TEXT NOT NULL,
            heading_level INTEGER NOT NULL DEFAULT 0,
            heading_path TEXT NOT NULL DEFAULT '',
            table_id TEXT NOT NULL DEFAULT '',
            prev_text TEXT NOT NULL DEFAULT '',
            next_text TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tables (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            body_index INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            heading_path TEXT NOT NULL DEFAULT '',
            row_count INTEGER NOT NULL,
            col_count INTEGER NOT NULL,
            header_text TEXT NOT NULL DEFAULT '',
            preview_text TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS table_rows (
            id TEXT PRIMARY KEY,
            table_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            body_index INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS table_cells (
            id TEXT PRIMARY KEY,
            table_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            body_index INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            col_index INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            body_index INTEGER NOT NULL,
            table_id TEXT NOT NULL DEFAULT '',
            row_index INTEGER,
            col_index INTEGER,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_blocks_doc_body ON blocks(document_id, body_index);
        CREATE INDEX IF NOT EXISTS idx_tables_doc_body ON tables(document_id, body_index);
        CREATE INDEX IF NOT EXISTS idx_rows_table_row ON table_rows(table_id, row_index);
        CREATE INDEX IF NOT EXISTS idx_cells_table_row_col ON table_cells(table_id, row_index, col_index);
        CREATE INDEX IF NOT EXISTS idx_evidence_doc_body ON evidence(document_id, body_index);
        """
    )
    set_meta(conn, "schemaVersion", SCHEMA_VERSION)


def reset_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS meta;
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS blocks;
        DROP TABLE IF EXISTS tables;
        DROP TABLE IF EXISTS table_rows;
        DROP TABLE IF EXISTS table_cells;
        DROP TABLE IF EXISTS evidence;
        """
    )
    init_db(conn)


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    raw = row["value"]
    try:
        return json.loads(raw)
    except Exception:
        return raw


def insert_document(conn: sqlite3.Connection, doc: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO documents(id, name, source_path, text_path, block_count, table_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            doc["id"],
            doc.get("name") or doc["id"],
            doc.get("sourcePath") or "",
            doc.get("textPath") or "",
            int(doc.get("blockCount") or 0),
            int(doc.get("tableCount") or 0),
        ),
    )


def insert_block(conn: sqlite3.Connection, block: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO blocks(
            id, document_id, body_index, block_type, text, heading_level,
            heading_path, table_id, prev_text, next_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            block["id"],
            block["documentId"],
            int(block["bodyIndex"]),
            block["type"],
            block.get("text") or "",
            int(block.get("headingLevel") or 0),
            block.get("headingPath") or "",
            block.get("tableId") or "",
            block.get("prevText") or "",
            block.get("nextText") or "",
        ),
    )
    insert_evidence(
        conn,
        {
            "id": block["tableId"] if block.get("type") == "table" and block.get("tableId") else block["id"],
            "documentId": block["documentId"],
            "kind": block["type"],
            "bodyIndex": block["bodyIndex"],
            "tableId": block.get("tableId") or "",
            "text": block.get("text") or "",
        },
    )


def insert_table(conn: sqlite3.Connection, table: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tables(
            id, document_id, body_index, title, heading_path, row_count,
            col_count, header_text, preview_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            table["id"],
            table["documentId"],
            int(table["bodyIndex"]),
            table.get("title") or "",
            table.get("headingPath") or "",
            int(table.get("rowCount") or 0),
            int(table.get("colCount") or 0),
            table.get("headerText") or "",
            table.get("previewText") or "",
        ),
    )
    insert_evidence(
        conn,
        {
            "id": table["id"],
            "documentId": table["documentId"],
            "kind": "table",
            "bodyIndex": table["bodyIndex"],
            "tableId": table["id"],
            "text": " ".join(part for part in [table.get("title") or "", table.get("previewText") or ""] if part),
        },
    )


def insert_table_row(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO table_rows(id, table_id, document_id, body_index, row_index, text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["tableId"],
            row["documentId"],
            int(row["bodyIndex"]),
            int(row["rowIndex"]),
            row.get("text") or "",
        ),
    )
    insert_evidence(
        conn,
        {
            "id": row["id"],
            "documentId": row["documentId"],
            "kind": "table_row",
            "bodyIndex": row["bodyIndex"],
            "tableId": row["tableId"],
            "rowIndex": row["rowIndex"],
            "text": row.get("text") or "",
        },
    )


def insert_table_cell(conn: sqlite3.Connection, cell: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO table_cells(
            id, table_id, document_id, body_index, row_index, col_index, text
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cell["id"],
            cell["tableId"],
            cell["documentId"],
            int(cell["bodyIndex"]),
            int(cell["rowIndex"]),
            int(cell["colIndex"]),
            cell.get("text") or "",
        ),
    )
    insert_evidence(
        conn,
        {
            "id": cell["id"],
            "documentId": cell["documentId"],
            "kind": "table_cell",
            "bodyIndex": cell["bodyIndex"],
            "tableId": cell["tableId"],
            "rowIndex": cell["rowIndex"],
            "colIndex": cell["colIndex"],
            "text": cell.get("text") or "",
        },
    )


def insert_evidence(conn: sqlite3.Connection, evidence: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO evidence(
            id, document_id, kind, body_index, table_id, row_index, col_index, text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence["id"],
            evidence["documentId"],
            evidence["kind"],
            int(evidence["bodyIndex"]),
            evidence.get("tableId") or "",
            evidence.get("rowIndex"),
            evidence.get("colIndex"),
            evidence.get("text") or "",
        ),
    )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def fetch_all(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def evidence_exists(conn: sqlite3.Connection, evidence_id: str) -> bool:
    return conn.execute("SELECT 1 FROM evidence WHERE id = ? LIMIT 1", (evidence_id,)).fetchone() is not None
