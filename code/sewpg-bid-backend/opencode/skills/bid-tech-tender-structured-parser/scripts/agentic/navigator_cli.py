from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import nav_store
from .checklist import checklist_for_shard, shard_by_key
from .paths import nav_store_path


# 预检索：把清单「具体内容」里的名词短语直接拿去检索，命中结果随分片清单一起下发。
# 目的是省掉模型逐个关键词试探的 LLM 往返，纯 Python 计算、无模型成本。
HINT_SPLIT_PATTERN = r"[、，,；;。/／()（）\s]+"
HINT_STOPWORDS = frozenset(
    {
        "要求", "适配", "配置", "设计", "方案", "标准", "规则", "责任", "界定", "提供",
        "保障", "能力", "情况", "内容", "相关", "以及", "及其", "包括", "等", "的",
        "合规性", "全流程", "定义", "流程", "措施", "范围",
    }
)
HINT_TRAILING_SUFFIXES = ("要求", "配置", "设计", "责任", "适配", "标准", "规则")


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


def _fetch_all_evidence_rows(conn) -> list[dict[str, Any]]:
    return nav_store.fetch_all(
        conn,
        """
        SELECT id, document_id AS documentId, kind, body_index AS bodyIndex, page_no AS pageNo,
               table_id AS tableId,
               row_index AS rowIndex, col_index AS colIndex, text
        FROM evidence
        ORDER BY document_id, body_index, COALESCE(row_index, 0), COALESCE(col_index, 0)
        """,
    )


def _build_fuzzy_index(rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, str]]:
    """预先算好每行的规整文本。

    打分本身按 (行数 × 关键词数) 增长，而文本规整是其中最贵的一步。批量场景下
    每个关键词都重算一遍会主导整体耗时，所以按行只算一次并复用。
    """
    index = []
    for row in rows:
        text = str(row.get("text") or "")
        index.append((row, re.sub(r"\s+", "", text).lower(), text.lower()))
    return index


def _ranked_search(
    conn,
    query: str,
    limit: int,
    *,
    index: list[tuple[dict[str, Any], str, str]] | None = None,
) -> list[dict[str, Any]]:
    """模糊回退打分。

    整张 evidence 表要拉进 Python 打分，成本随文档规模线性增长。批量场景（预检索）
    必须传入 index 复用同一份快照，否则每个未命中词都会重新全表拉取并重算一遍。
    """
    tokens = _query_tokens(query)
    chars = _query_chars(query)
    if not tokens and not chars:
        return []
    if index is None:
        index = _build_fuzzy_index(_fetch_all_evidence_rows(conn))
    compact_query = re.sub(r"\s+", "", query.strip()).lower()
    lowered_tokens = [token.lower() for token in tokens]
    lowered_chars = [char.lower() for char in chars]
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row, compact_text, lower_text in index:
        score = 0
        if compact_query and compact_query in compact_text:
            score += 100
        for token in lowered_tokens:
            if token in lower_text:
                score += 30
        if lowered_chars:
            matched = sum(1 for char in lowered_chars if char in compact_text)
            coverage = matched / len(lowered_chars)
            if coverage >= 0.65:
                score += int(coverage * 60)
            if _ordered_subsequence(lowered_chars, compact_text):
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
        SELECT id, evidence_id AS evidenceId, document_id AS documentId, body_index AS bodyIndex,
               page_no AS pageNo, block_type AS type, text, heading_level AS headingLevel,
               heading_path AS headingPath, table_id AS tableId
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
        SELECT id, evidence_id AS evidenceId, document_id AS documentId, body_index AS bodyIndex,
               page_no AS pageNo, title, heading_path AS headingPath, row_count AS rowCount,
               col_count AS colCount, header_text AS headerText, preview_text AS previewText
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


def _exact_search(conn, query: str, limit: int) -> list[dict[str, Any]]:
    tokens = _query_tokens(query)
    if not tokens:
        return []
    conditions = " AND ".join(["text LIKE ?" for _ in tokens])
    params = [f"%{token}%" for token in tokens]
    sql = f"""
        SELECT id, document_id AS documentId, kind, body_index AS bodyIndex, page_no AS pageNo,
               table_id AS tableId,
               row_index AS rowIndex, col_index AS colIndex, text
        FROM evidence
        WHERE {conditions}
        ORDER BY document_id, body_index, COALESCE(row_index, 0), COALESCE(col_index, 0)
        LIMIT ?
    """
    return nav_store.fetch_all(conn, sql, (*params, max(1, min(80, limit))))


def _search_with_conn(
    conn,
    query: str,
    limit: int,
    *,
    fuzzy_index: list[tuple[dict[str, Any], str, str]] | None = None,
) -> list[dict[str, Any]]:
    rows = _exact_search(conn, query, limit)
    if not rows:
        rows = _ranked_search(conn, query, limit, index=fuzzy_index)
    # 复制后再截断：模糊回退命中的是共享快照里的行对象，就地改写会把快照
    # 的正文永久截短，污染后续关键词的检索结果。
    return [{**row, "text": _limit_text(row.get("text") or "", 260)} for row in rows]


def search(manifest_path: Path, manifest: dict[str, Any], query: str, *, limit: int = 20) -> dict[str, Any]:
    conn = _connect(manifest_path, manifest)
    try:
        if not _query_tokens(query):
            return {"schemaVersion": nav_store.SCHEMA_VERSION, "query": query, "matchCount": 0, "matches": []}
        rows = _search_with_conn(conn, query, limit)
        return {"schemaVersion": nav_store.SCHEMA_VERSION, "query": query, "matchCount": len(rows), "matches": rows}
    finally:
        conn.close()


def search_many(
    manifest_path: Path,
    manifest: dict[str, Any],
    queries: list[str],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """一次执行多个检索。

    与逐条调用等价，只是把 N 次 LLM 往返压成 1 次——模型一轮就能把一条清单行
    需要的所有关键词发出去。
    """
    conn = _connect(manifest_path, manifest)
    results = []
    total = 0
    fuzzy_index: list[tuple[dict[str, Any], str, str]] | None = None
    try:
        for query in queries:
            text = str(query or "").strip()
            if not text or not _query_tokens(text):
                continue
            rows = _exact_search(conn, text, limit)
            if not rows:
                if fuzzy_index is None:
                    fuzzy_index = _build_fuzzy_index(_fetch_all_evidence_rows(conn))
                rows = _ranked_search(conn, text, limit, index=fuzzy_index)
            matches = [{**row, "text": _limit_text(row.get("text") or "", 260)} for row in rows]
            total += len(matches)
            results.append(
                {
                    "query": text,
                    "matchCount": len(matches),
                    "matches": matches,
                }
            )
    finally:
        conn.close()
    return {
        "schemaVersion": nav_store.SCHEMA_VERSION,
        "queryCount": len(results),
        "matchCount": total,
        "results": results,
    }


def _hint_terms(specific_content: str, *, max_terms: int) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.split(HINT_SPLIT_PATTERN, str(specific_content or "")):
        term = raw.strip()
        if not term:
            continue
        for suffix in HINT_TRAILING_SUFFIXES:
            if len(term) > len(suffix) + 1 and term.endswith(suffix):
                term = term[: -len(suffix)]
                break
        if len(term) < 2 or term in HINT_STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def shard_checklist(
    manifest_path: Path,
    manifest: dict[str, Any],
    shard_key: str,
    *,
    with_hints: bool = True,
    max_terms: int = 5,
    per_term_limit: int = 3,
    hint_limit: int = 8,
) -> dict[str, Any]:
    shard = shard_by_key(shard_key)
    conn = _connect(manifest_path, manifest) if with_hints else None
    # 全表快照只拉一次并预先规整，供本分片所有关键词的模糊回退复用。
    fuzzy_index = _build_fuzzy_index(_fetch_all_evidence_rows(conn)) if conn is not None else None
    rows = []
    for item in checklist_for_shard(shard_key):
        row = {
            "rowNo": item["rowNo"],
            "displayGroup": item["displayGroup"],
            "primaryCategory": item["primaryCategory"],
            "secondaryCategory": item["secondaryCategory"],
            "specificContent": item["specificContent"],
        }
        if with_hints:
            hints: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for term in _hint_terms(item["specificContent"], max_terms=max_terms):
                matches = _search_with_conn(conn, term, per_term_limit, fuzzy_index=fuzzy_index)
                for match in matches:
                    evidence_id = str(match.get("id") or "")
                    if not evidence_id or evidence_id in seen_ids:
                        continue
                    seen_ids.add(evidence_id)
                    hints.append(
                        {
                            "term": term,
                            "id": evidence_id,
                            "documentId": match.get("documentId"),
                            "pageNo": match.get("pageNo"),
                            "tableId": match.get("tableId"),
                            "text": _limit_text(str(match.get("text") or ""), 140),
                        }
                    )
                    if len(hints) >= hint_limit:
                        break
                if len(hints) >= hint_limit:
                    break
            row["hints"] = hints
        rows.append(row)
    return {
        "schemaVersion": nav_store.SCHEMA_VERSION,
        "shard": shard["key"],
        "shardLabel": shard["label"],
        "rowCount": len(rows),
        "rowNos": list(shard["rowNos"]),
        "hintsIncluded": bool(with_hints),
        "rows": rows,
    }


def read(manifest_path: Path, manifest: dict[str, Any], evidence_id: str, *, mode: str = "summary", max_chars: int = 2000) -> dict[str, Any]:
    conn = _connect(manifest_path, manifest)
    row = nav_store.row_to_dict(conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone())
    if row is None:
        raise RuntimeError(f"evidence id not found: {evidence_id}")
    if row.get("kind") == "table":
        table_id = str(row.get("table_id") or evidence_id)
        table = nav_store.row_to_dict(conn.execute("SELECT * FROM tables WHERE id = ?", (table_id,)).fetchone()) or {}
        rows = nav_store.fetch_all(
            conn,
            "SELECT id, row_index AS rowIndex, text FROM table_rows WHERE table_id = ? ORDER BY row_index LIMIT ?",
            (table_id, 8 if mode == "summary" else 200),
        )
        payload = {**table, "rows": rows}
    else:
        payload = row
    payload["pageNo"] = int(payload.get("page_no") or row.get("page_no") or 0)
    payload["evidenceId"] = str(payload.get("evidence_id") or row.get("id") or evidence_id)
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
        SELECT id, evidence_id AS evidenceId, document_id AS documentId, body_index AS bodyIndex,
               page_no AS pageNo, block_type AS type, text, heading_path AS headingPath, table_id AS tableId
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
    table_row = nav_store.row_to_dict(
        conn.execute("SELECT * FROM tables WHERE id = ? OR evidence_id = ?", (table_id, table_id)).fetchone()
    )
    if table_row is None:
        raise RuntimeError(f"table id not found: {table_id}")
    match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", rows_range or "")
    start = int(match.group(1)) if match else 1
    end = int(match.group(2) or start) if match else min(int(table_row["row_count"]), 12)
    start = max(1, start)
    end = max(start, min(end, int(table_row["row_count"])))
    resolved_table_id = str(table_row["id"])
    rows = nav_store.fetch_all(
        conn,
        "SELECT id, row_index AS rowIndex, text FROM table_rows WHERE table_id = ? AND row_index BETWEEN ? AND ? ORDER BY row_index",
        (resolved_table_id, start, end),
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
            "evidenceId": table_row["evidence_id"],
            "documentId": table_row["document_id"],
            "bodyIndex": table_row["body_index"],
            "pageNo": table_row["page_no"],
            "title": table_row["title"],
            "headingPath": table_row["heading_path"],
            "rowCount": table_row["row_count"],
            "colCount": table_row["col_count"],
            "headerText": table_row["header_text"],
        },
        "rows": compact_rows,
    }
