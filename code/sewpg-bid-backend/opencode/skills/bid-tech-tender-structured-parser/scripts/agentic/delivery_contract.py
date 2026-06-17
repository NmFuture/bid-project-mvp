from __future__ import annotations

import copy
import sqlite3
from pathlib import Path
from typing import Any

from . import nav_store
from .checklist import CHECKLIST_VERSION, DISPLAY_GROUPS, checklist_by_row_no, clean, load_checklist
from .paths import nav_store_path


ALLOWED_STATUSES = {"found", "partial", "missing", "needs_spec"}
POSITIVE_STATUSES = {"found", "partial"}


def as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [copy.deepcopy(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [copy.deepcopy(value)]
    return []


def evidence_ids_from_value(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, str):
        if value.strip():
            ids.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            ids.extend(evidence_ids_from_value(item))
    elif isinstance(value, dict):
        for key in ("id", "evidenceId"):
            text = clean(value.get(key))
            if text:
                ids.append(text)
        for key in ("evidenceIds", "ids", "evidenceRefs", "evidence"):
            ids.extend(evidence_ids_from_value(value.get(key)))
    return list(dict.fromkeys(ids))


def _submitted_by_row(value: Any) -> dict[int, dict[str, Any]]:
    by_row: dict[int, dict[str, Any]] = {}
    for row in as_list(value):
        try:
            row_no = int(row.get("rowNo") or row.get("row") or row.get("excelRow") or 0)
        except (TypeError, ValueError):
            continue
        if row_no:
            by_row[row_no] = row
    return by_row


def _source_documents_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    documents = manifest.get("documents") if isinstance(manifest.get("documents"), list) else []
    result: dict[str, dict[str, Any]] = {}
    for document in documents:
        if not isinstance(document, dict):
            continue
        document_id = clean(document.get("id"))
        if document_id:
            result[document_id] = document
    return result


def _heading_path_for_record(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    table_id = clean(record.get("table_id"))
    if table_id:
        table_row = conn.execute("SELECT heading_path, title FROM tables WHERE id = ?", (table_id,)).fetchone()
        if table_row is not None:
            return clean(table_row["heading_path"]) or clean(table_row["title"])
    block_row = conn.execute(
        "SELECT heading_path FROM blocks WHERE document_id = ? AND body_index = ? LIMIT 1",
        (record.get("document_id"), record.get("body_index")),
    ).fetchone()
    if block_row is not None:
        return clean(block_row["heading_path"])
    return ""


def _evidence_location(record: dict[str, Any]) -> str:
    kind = clean(record.get("kind"))
    body_index = record.get("body_index")
    row_index = record.get("row_index")
    col_index = record.get("col_index")
    if kind == "table_cell" and row_index is not None and col_index is not None:
        return f"表格第{row_index}行第{col_index}列"
    if kind == "table_row" and row_index is not None:
        return f"表格第{row_index}行"
    if kind == "table":
        return "表格"
    if body_index is not None:
        return f"正文第{body_index}段"
    return ""


def evidence_refs(
    manifest_path: Path,
    manifest: dict[str, Any],
    evidence_ids: list[str],
) -> list[dict[str, Any]]:
    path = nav_store_path(manifest_path, manifest)
    if not path.is_file() or not evidence_ids:
        return []
    documents = _source_documents_by_id(manifest)
    refs: list[dict[str, Any]] = []
    conn = nav_store.connect(path)
    try:
        for evidence_id in evidence_ids:
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            if row is None:
                continue
            record = dict(row)
            document_id = clean(record.get("document_id"))
            document = documents.get(document_id) or {}
            refs.append(
                {
                    "id": evidence_id,
                    "sourceDocumentId": document_id,
                    "sourceFile": clean(document.get("name")) or document_id or "招标文件",
                    "section": _heading_path_for_record(conn, record),
                    "evidenceLocation": _evidence_location(record),
                    "text": clean(record.get("text")),
                }
            )
    finally:
        conn.close()
    return refs


def normalize_items(
    submitted_value: Any,
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    submitted = _submitted_by_row(submitted_value)
    items: list[dict[str, Any]] = []
    for checklist_item in load_checklist():
        row_no = int(checklist_item["rowNo"])
        row = submitted.get(row_no) or {}
        status = clean(row.get("status")) or "missing"
        if status not in ALLOWED_STATUSES:
            status = "missing"
        ids = evidence_ids_from_value(row.get("evidenceIds") or row.get("evidence") or row.get("evidenceRefs"))
        refs = evidence_refs(manifest_path, manifest, ids)
        conclusion = clean(row.get("conclusion") or row.get("解析结果") or row.get("result"))
        if not conclusion:
            if status == "missing":
                conclusion = "当前已上传招标文件未识别到直接对应要求。"
            elif status == "needs_spec":
                source_name = clean(row.get("neededSourceName"))
                conclusion = f"当前已上传招标文件需结合{source_name or '相关技术规范或附件'}进一步核对。"
            else:
                conclusion = clean(row.get("evidenceSummary")) or "已根据原文证据形成解读。"
        evidence_summary = clean(row.get("evidenceSummary"))
        if not evidence_summary and refs:
            evidence_summary = refs[0]["text"][:180]
        item = {
            "id": f"TECH-INT-{row_no:03d}",
            **checklist_item,
            "status": status,
            "conclusion": conclusion,
            "evidenceSummary": evidence_summary,
            "neededSourceName": clean(row.get("neededSourceName")),
            "evidenceIds": ids,
            "evidenceRefs": refs,
        }
        items.append(item)
    return items


def build_categories(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    for group in DISPLAY_GROUPS:
        rows = [item for item in items if item.get("displayGroup") == group]
        if rows:
            categories.append({"name": group, "count": len(rows), "items": rows})
    extra_groups = sorted({clean(item.get("displayGroup")) for item in items} - set(DISPLAY_GROUPS))
    for group in extra_groups:
        rows = [item for item in items if item.get("displayGroup") == group]
        if rows:
            categories.append({"name": group, "count": len(rows), "items": rows})
    return categories


def summary_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(items), "found": 0, "partial": 0, "missing": 0, "needs_spec": 0}
    for item in items:
        status = clean(item.get("status"))
        if status in summary:
            summary[status] += 1
    return summary


def valid_row_numbers() -> set[int]:
    return set(checklist_by_row_no())


def technical_interpretation_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "technical-interpretation-v1",
        "checklistVersion": CHECKLIST_VERSION,
        "summary": summary_counts(items),
        "categories": build_categories(items),
        "items": items,
    }
