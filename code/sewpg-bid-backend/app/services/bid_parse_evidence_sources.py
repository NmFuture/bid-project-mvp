"""解析结果 evidence 可读来源物化：从 s1_nav.sqlite 取证据，回填人读来源字段。

从 bid_parse_service.py 拆分搬迁（原 :1046-1798），含结构化结果文件加载/NUL 清洗、
商务 evidence 可读来源族（``_business_*``）与技术 evidence 族（``_technical_*``）。

两族结构性平行但语义已分叉，按对取舍如下（不为合并而合并）：
- nav 存储路径解析（``_resolve_*_nav_store_path``）与来源文本拼接
  （``_*_source_text``）两版逐字节相同，合并为 ``_resolve_nav_store_path`` /
  ``_evidence_source_text``，原名保留为别名；
- 其余按对函数（evidence_ids / evidence_location / source_value_needs_refresh /
  fetch_evidence_records / apply_readable_source / materialize）定位文案、刷新判定
  正则、record 字段集与回填结构各不相同，保留两份并在函数处互指；
- ``_technical_evidence_caption`` 历史上就转调 ``_business_evidence_caption``，维持现状。

bid_parse_service 门面 re-export 本模块全部符号，外部调用方与 patch 目标
保持 ``app.services.bid_parse_service.<符号>`` 可解析。
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.bid_runtime_state import now_iso, read_json_file
from app.services.business_template_extractor import convert_extractor_appendices
from app.services.parse_profiles import BUSINESS_PARSE_PROFILE

def _load_structured_result_file(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return None
    items = payload.get("items")
    return copy.deepcopy(items if isinstance(items, list) else []), copy.deepcopy(structured)


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _strip_nul_chars(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul_chars(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_nul_chars(item) for key, item in value.items()}
    return value


def _business_recoverable_parse_dirs(project_id: str, parse_storage: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for raw in (
        parse_storage.get("parseDir"),
        Path(str(parse_storage.get("structuredResultPath") or "")).parent if parse_storage.get("structuredResultPath") else "",
        settings.parsed_dir / project_id,
        settings.documents_dir / project_id / BUSINESS_PARSE_PROFILE.workspace_dirname / "parse",
    ):
        if not raw:
            continue
        candidates.append(Path(str(raw)))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _recover_business_parse_artifact(
    project_id: str,
    parse_storage: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for parse_dir in _business_recoverable_parse_dirs(project_id, parse_storage):
        structured_path = parse_dir / "s1_structured_result.json"
        loaded = _load_structured_result_file(structured_path)
        if loaded is None:
            continue
        structured_payload = read_json_file(structured_path)
        items, structured = loaded
        items = _strip_nul_chars(items)
        structured = _strip_nul_chars(structured)
        summary = structured_payload.get("summary") if isinstance(structured_payload.get("summary"), dict) else {}
        summary = _strip_nul_chars(summary)
        manifest = read_json_file(parse_dir / "manifest.json")
        recovered_result = {
            "status": "completed",
            "parsedAt": now_iso(),
            "sourceFiles": [],
            "items": items,
            "structured": structured,
            "summary": summary
            or {
                "fileCount": 0,
                "extractedCount": len(items),
                "textLength": 0,
                "textPreview": "",
                "warnings": ["解析结果已从 S1 产物自动恢复。"],
            },
        }
        recovered_storage = copy.deepcopy(parse_storage)
        recovered_storage.update(
            {
                "projectDir": str(parse_dir.parent) if parse_dir.exists() else "",
                "parseDir": str(parse_dir),
                "combinedTextPath": str(parse_dir / "combined.txt") if (parse_dir / "combined.txt").exists() else "",
                "manifestPath": str(parse_dir / "manifest.json") if (parse_dir / "manifest.json").exists() else "",
                "structuredResultPath": str(structured_path),
                "skillManifestPath": str(parse_dir / "s1_parse_manifest.json") if (parse_dir / "s1_parse_manifest.json").exists() else "",
                "documents": _strip_nul_chars(list(manifest.get("documents") or [])) if isinstance(manifest.get("documents"), list) else [],
                "items": copy.deepcopy(items),
                "structured": copy.deepcopy(structured),
            }
        )
        recovered_result = _strip_nul_chars(recovered_result)
        recovered_storage = _strip_nul_chars(recovered_storage)
        return recovered_result, recovered_storage
    return None


def _business_template_extraction_candidates(parse_storage: dict[str, Any], structured_path: Path) -> list[Path]:
    candidates: list[Path] = []

    direct_path = str(parse_storage.get("businessTemplateExtractionPath") or "").strip()
    if direct_path:
        candidates.append(Path(direct_path))

    skill_manifest_path = Path(str(parse_storage.get("skillManifestPath") or ""))
    skill_manifest = _load_json_file(skill_manifest_path)
    manifest_path = str((skill_manifest or {}).get("businessTemplateExtractionPath") or "").strip()
    if manifest_path:
        candidates.append(Path(manifest_path))

    if structured_path:
        candidates.append(structured_path.parent / "business_template_extraction" / "business_template_extraction.json")

    project_dir = str(parse_storage.get("projectDir") or "").strip()
    if project_dir:
        candidates.append(Path(project_dir) / "business_template_extraction" / "business_template_extraction.json")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _load_business_template_appendices(
    parse_storage: dict[str, Any],
    structured_path: Path,
) -> tuple[list[dict[str, Any]], Path | None]:
    for candidate in _business_template_extraction_candidates(parse_storage, structured_path):
        payload = _load_json_file(candidate)
        if not payload:
            continue
        appendices = convert_extractor_appendices(payload)
        if appendices:
            return appendices, candidate
    return [], None


def _hydrate_business_template_appendices(
    structured: dict[str, Any],
    parse_storage: dict[str, Any],
    structured_path: Path,
) -> tuple[dict[str, Any], Path | None]:
    if isinstance(structured.get("appendices"), list) and structured.get("appendices"):
        return structured, None
    appendices, extraction_path = _load_business_template_appendices(parse_storage, structured_path)
    if not appendices:
        return structured, None
    hydrated = copy.deepcopy(structured)
    hydrated["appendices"] = copy.deepcopy(appendices)
    return hydrated, extraction_path


def _compact_source_text(value: Any) -> str:
    return "".join(str(value or "").split())


def _source_documents_by_id(structured: dict[str, Any]) -> dict[str, dict[str, Any]]:
    documents = structured.get("sourceDocuments") if isinstance(structured, dict) else []
    if isinstance(documents, dict):
        documents = [documents]
    if not isinstance(documents, list):
        return {}
    return {
        str(document.get("id") or ""): document
        for document in documents
        if isinstance(document, dict) and str(document.get("id") or "").strip()
    }


def _resolve_nav_store_path(structured: dict[str, Any], structured_path: Path | None = None) -> Path | None:
    workflow = structured.get("workflow") if isinstance(structured, dict) else {}
    raw_path = str(workflow.get("navStorePath") or "").strip() if isinstance(workflow, dict) else ""
    if raw_path:
        return Path(raw_path)
    if structured_path is not None:
        return structured_path.parent / "s1_nav.sqlite"
    return None


# 原 _resolve_business_nav_store_path / _resolve_technical_nav_store_path 两版实现
# 逐字节相同，合并为上面的 _resolve_nav_store_path；保留原别名兼容既有引用与 patch。
_resolve_business_nav_store_path = _resolve_nav_store_path


def _readable_business_section(heading_path: Any, evidence_text: str) -> str:
    parts = [part.strip() for part in str(heading_path or "").split(">") if part.strip()]
    if not parts:
        return ""
    evidence_compact = _compact_source_text(evidence_text)
    if evidence_compact and len(parts) > 1:
        last_compact = _compact_source_text(parts[-1])
        if last_compact and (last_compact in evidence_compact or evidence_compact in last_compact):
            parts = parts[:-1]
    filtered_parts = []
    for index, part in enumerate(parts):
        if index > 0 and len(part) > 80:
            continue
        if index > 0 and part.startswith(("(", "（")):
            continue
        if index > 0 and part.endswith(("。", "；", ";")):
            continue
        filtered_parts.append(part)
    return " > ".join(filtered_parts or parts[:1])


_BUSINESS_CLAUSE_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\s*(.+)$")
_BUSINESS_LIST_PREFIX_RE = re.compile(r"^\s*[（(]\s*[0-9一二三四五六七八九十]+\s*[）)]\s*(.+)$")
_BUSINESS_PHYSICAL_LOCATION_RE = re.compile(r"(正文第\d+段|表格第\d+行(?:第\d+列)?|表格第\d+列)")


def _strip_business_source_caption(value: Any) -> str:
    return str(value or "").strip().strip(" \t\r\n|:：,，;；。")


def _short_business_source_caption(value: Any, max_length: int = 56) -> str:
    text = " ".join(str(value or "").replace("\u3000", " ").split())
    text = _strip_business_source_caption(text)
    if len(text) <= max_length:
        return text
    return _strip_business_source_caption(text[: max_length - 3]) + "..."


def _business_caption_head(value: Any) -> str:
    text = " ".join(str(value or "").replace("\u3000", " ").split())
    for separator in ("：", ":", "；", ";", "。", "，", ",", "\n"):
        if separator in text:
            text = text.split(separator, 1)[0]
            break
    return _short_business_source_caption(text)


def _business_evidence_caption(evidence_text: Any) -> str:
    text = " ".join(str(evidence_text or "").replace("\u3000", " ").split())
    if not text:
        return ""

    if "|" in text:
        parts = [_strip_business_source_caption(part) for part in text.split("|")]
        parts = [part for part in parts if part and part not in {":", "："}]
        if len(parts) >= 2:
            if re.fullmatch(r"\d+(?:\.\d+)+", parts[0]):
                return _short_business_source_caption(f"{parts[0]} {_business_caption_head(parts[1])}")
            return _business_caption_head(parts[0])

    clause_match = _BUSINESS_CLAUSE_PREFIX_RE.match(text)
    if clause_match:
        clause_no, clause_text = clause_match.groups()
        return _short_business_source_caption(f"{clause_no} {_business_caption_head(clause_text)}")

    list_match = _BUSINESS_LIST_PREFIX_RE.match(text)
    if list_match:
        return _business_caption_head(list_match.group(1))

    return _business_caption_head(text)


def _business_evidence_location(record: dict[str, Any], evidence_text: str) -> str:
    # 与技术族 _technical_evidence_location 互指：商务优先返回 caption、兜底粗粒度文案；
    # 技术返回「表格第N行/正文第N段」物理定位，语义不同，不合并。
    caption = _business_evidence_caption(evidence_text)
    if caption:
        return caption
    kind = str(record.get("kind") or "")
    row_index = record.get("row_index")
    col_index = record.get("col_index")
    if kind in {"table_row", "table_cell"} or row_index is not None:
        return "表格内容" if col_index is None else "表格单元格"
    return "正文内容"


def _evidence_source_text(parts: list[str]) -> str:
    return " / ".join(part for part in parts if str(part or "").strip())


# 原 _business_source_text / _technical_source_text 两版实现逐字节相同，合并为上面的
# _evidence_source_text；保留原别名兼容既有引用与 patch。
_business_source_text = _evidence_source_text


def _looks_like_business_evidence_id(value: Any) -> bool:
    text = str(value or "").strip()
    return ":B" in text or ":T" in text or text.startswith("TEN-") or text.startswith("DOC-")


def _business_source_value_needs_refresh(value: Any) -> bool:
    # 与技术族 _technical_source_value_needs_refresh 互指：刷新判定正则不同
    # （商务认 evidence-id 形态，技术认「原文」与 B/L 编号），不合并。
    text = str(value or "").strip()
    return not text or _looks_like_business_evidence_id(text) or bool(_BUSINESS_PHYSICAL_LOCATION_RE.search(text))


def _business_evidence_ids(row: dict[str, Any]) -> list[str]:
    # 与技术族 _technical_evidence_ids 互指：商务只读 evidenceIds；技术额外读 evidenceRefs，不合并。
    raw_ids = row.get("evidenceIds")
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in raw_ids if str(item or "").strip()))


def _fetch_business_evidence_records(
    conn: sqlite3.Connection,
    evidence_ids: list[str],
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    # 与技术族 _fetch_technical_evidence_records 互指：record 字段集不同
    # （商务 evidence/经 _readable_business_section 清洗的 section；技术 id/text/原始 heading_path），不合并。
    records: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        evidence_row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if evidence_row is None:
            continue
        record = dict(evidence_row)
        document_id = str(record.get("document_id") or "")
        table_id = str(record.get("table_id") or "")
        heading_path = ""
        if table_id:
            table_row = conn.execute("SELECT * FROM tables WHERE id = ?", (table_id,)).fetchone()
            if table_row is not None:
                table_record = dict(table_row)
                heading_path = str(table_record.get("heading_path") or table_record.get("title") or "")
        if not heading_path:
            block_row = conn.execute(
                "SELECT * FROM blocks WHERE document_id = ? AND body_index = ? LIMIT 1",
                (document_id, record.get("body_index")),
            ).fetchone()
            if block_row is not None:
                block_record = dict(block_row)
                heading_path = str(block_record.get("heading_path") or "")
        document = documents_by_id.get(document_id) or {}
        evidence_text = str(record.get("text") or "")
        records.append(
            {
                "sourceDocumentId": document_id,
                "sourceFile": str(document.get("name") or document_id or "招标文件"),
                "section": _readable_business_section(heading_path, evidence_text),
                "evidence": evidence_text,
                "evidenceLocation": _business_evidence_location(record, evidence_text),
            }
        )
    return records


def _apply_business_readable_source(row: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    # 与技术族 _apply_technical_readable_source 互指：刷新判定走商务版 needs_refresh，
    # 回填 evidence 取 record["evidence"]，返回是否变更；技术版语义不同，不合并。
    if not records:
        return False
    changed = False
    first = records[0]
    for key in ("sourceFile", "sourceDocumentId", "section", "evidenceLocation"):
        current = str(row.get(key) or "").strip()
        if _business_source_value_needs_refresh(current) and str(first.get(key) or "").strip():
            row[key] = first[key]
            changed = True

    evidence_text = "；".join(
        dict.fromkeys(str(record.get("evidence") or "").strip() for record in records if str(record.get("evidence") or "").strip())
    )
    if evidence_text and not str(row.get("evidence") or "").strip():
        row["evidence"] = evidence_text
        changed = True

    source_text = _business_source_text(
        [
            str(first.get("sourceFile") or ""),
            str(first.get("section") or ""),
            str(first.get("evidenceLocation") or ""),
        ]
    )
    if source_text:
        for key in ("sourceText", "sourceLabel", "source"):
            current = str(row.get(key) or "").strip()
            if _business_source_value_needs_refresh(current):
                row[key] = source_text
                changed = True
    return changed


def _materialize_business_readable_sources(
    structured: dict[str, Any],
    *,
    structured_path: Path | None = None,
) -> dict[str, Any]:
    # 与技术族 _materialize_technical_evidence_refs 互指：商务只回填
    # fieldGroups.projectBasics / qualificationRequirements；技术还维护
    # technicalInterpretation、projectFactFields 与 categories 同步，结构不同，不合并。
    if not isinstance(structured, dict):
        return structured
    nav_path = _resolve_business_nav_store_path(structured, structured_path)
    if nav_path is None or not nav_path.is_file():
        return structured
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    target_group_keys = ("projectBasics", "qualificationRequirements")
    rows_by_group = {
        key: field_groups.get(key)
        for key in target_group_keys
        if isinstance(field_groups.get(key), list)
    }
    if not rows_by_group:
        return structured

    materialized = copy.deepcopy(structured)
    materialized_field_groups = materialized.get("fieldGroups") if isinstance(materialized.get("fieldGroups"), dict) else {}
    documents_by_id = _source_documents_by_id(materialized)
    try:
        conn = sqlite3.connect(str(nav_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return structured
    try:
        for group_key in target_group_keys:
            rows = materialized_field_groups.get(group_key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                records = _fetch_business_evidence_records(conn, _business_evidence_ids(row), documents_by_id)
                _apply_business_readable_source(row, records)
    except sqlite3.Error:
        return structured
    finally:
        conn.close()
    return materialized


# 技术版与商务版（见上方 _resolve_nav_store_path 注释）实现相同，指向同一合并实现。
_resolve_technical_nav_store_path = _resolve_nav_store_path


def _technical_evidence_ids(item: dict[str, Any]) -> list[str]:
    # 与商务族 _business_evidence_ids 互指：技术额外兼容 evidenceRefs（dict/str），不合并。
    ids: list[str] = []
    raw_ids = item.get("evidenceIds")
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if isinstance(raw_ids, list):
        ids.extend(str(value).strip() for value in raw_ids if str(value or "").strip())
    raw_refs = item.get("evidenceRefs")
    if isinstance(raw_refs, list):
        for ref in raw_refs:
            if isinstance(ref, dict):
                value = str(ref.get("id") or ref.get("evidenceId") or "").strip()
                if value:
                    ids.append(value)
            elif str(ref or "").strip():
                ids.append(str(ref).strip())
    return list(dict.fromkeys(ids))


def _technical_heading_path_for_record(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    table_id = str(record.get("table_id") or "").strip()
    if table_id:
        table_row = conn.execute("SELECT heading_path, title FROM tables WHERE id = ?", (table_id,)).fetchone()
        if table_row is not None:
            table_record = dict(table_row)
            return str(table_record.get("heading_path") or table_record.get("title") or "").strip()
    block_row = conn.execute(
        "SELECT heading_path FROM blocks WHERE document_id = ? AND body_index = ? LIMIT 1",
        (record.get("document_id"), record.get("body_index")),
    ).fetchone()
    if block_row is not None:
        return str(dict(block_row).get("heading_path") or "").strip()
    return ""


def _technical_evidence_location(record: dict[str, Any]) -> str:
    # 与商务族 _business_evidence_location 互指：技术输出物理定位文案，不合并。
    kind = str(record.get("kind") or "").strip()
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
    return "正文内容"


def _fetch_technical_evidence_records(
    conn: sqlite3.Connection,
    evidence_ids: list[str],
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    # 与商务族 _fetch_business_evidence_records 互指：record 字段集不同，不合并。
    records: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        evidence_row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if evidence_row is None:
            continue
        record = dict(evidence_row)
        document_id = str(record.get("document_id") or "").strip()
        document = documents_by_id.get(document_id) or {}
        records.append(
            {
                "id": evidence_id,
                "sourceDocumentId": document_id,
                "sourceFile": str(document.get("name") or document_id or "招标文件"),
                "section": _technical_heading_path_for_record(conn, record),
                "evidenceLocation": _technical_evidence_location(record),
                "text": str(record.get("text") or ""),
            }
        )
    return records


def _merge_technical_evidence_refs(existing_refs: Any, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    existing_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(existing_refs, list):
        for ref in existing_refs:
            if not isinstance(ref, dict):
                continue
            ref_id = str(ref.get("id") or ref.get("evidenceId") or "").strip()
            copied = copy.deepcopy(ref)
            if ref_id:
                copied["id"] = ref_id
                existing_by_id[ref_id] = copied
            merged.append(copied)

    seen_ids = {str(ref.get("id") or "").strip() for ref in merged if isinstance(ref, dict)}
    for record in records:
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            continue
        current = existing_by_id.get(record_id)
        if current is None:
            merged.append(copy.deepcopy(record))
            seen_ids.add(record_id)
            continue
        for key, value in record.items():
            if str(value or "").strip() and not str(current.get(key) or "").strip():
                current[key] = value
        if record_id not in seen_ids:
            merged.append(current)
            seen_ids.add(record_id)
    return merged


_TECHNICAL_APPENDIX_RUNTIME_FIELDS = (
    "selectedForMaterial",
    "assetMaterialId",
    "assetSyncStatus",
)


def _merge_technical_appendix_runtime_state(
    structured: dict[str, Any],
    current_structured: dict[str, Any],
) -> dict[str, Any]:
    """原始解析文件不承载审核后的附表选择，刷新时必须保留运行态字段。"""

    merged = copy.deepcopy(structured)
    current_appendices = (
        current_structured.get("appendices")
        if isinstance(current_structured.get("appendices"), list)
        else []
    )
    current_by_id = {
        str(item.get("id") or ""): item
        for item in current_appendices
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    appendices = merged.get("appendices") if isinstance(merged.get("appendices"), list) else []
    for appendix in appendices:
        if not isinstance(appendix, dict):
            continue
        current = current_by_id.get(str(appendix.get("id") or ""))
        if current is not None:
            for field in _TECHNICAL_APPENDIX_RUNTIME_FIELDS:
                if field in current:
                    appendix[field] = copy.deepcopy(current[field])
        appendix.setdefault("selectedForMaterial", True)

    sync_state = current_structured.get("technicalAppendixMaterialSync")
    if isinstance(sync_state, dict):
        merged["technicalAppendixMaterialSync"] = copy.deepcopy(sync_state)
    return merged


# 技术版与商务版（见上方 _evidence_source_text 注释）实现相同，指向同一合并实现。
_technical_source_text = _evidence_source_text


_TECHNICAL_PHYSICAL_LOCATION_RE = re.compile(
    r"(正文第\d+段|表格第\d+行(?:第\d+列)?|表格第\d+列|(?:^|[/\s])(?:B|L)\d+(?:$|[/\s]))"
)


def _technical_source_value_needs_refresh(value: Any) -> bool:
    # 与商务族 _business_source_value_needs_refresh 互指：刷新判定正则不同，不合并。
    text = str(value or "").strip()
    return not text or "原文" in text or bool(_TECHNICAL_PHYSICAL_LOCATION_RE.search(text))


def _technical_evidence_caption(value: Any) -> str:
    return _business_evidence_caption(value)


def _technical_readable_source_text(row: dict[str, Any], records: list[dict[str, Any]] | None = None) -> str:
    first = records[0] if records else {}
    source_file = str(row.get("sourceFile") or first.get("sourceFile") or "").strip()
    section = str(row.get("section") or first.get("section") or "").strip()
    evidence_location = str(row.get("evidenceLocation") or first.get("evidenceLocation") or "").strip()
    return _technical_source_text(
        [
            source_file,
            section,
            evidence_location,
        ]
    )


def _apply_existing_technical_readable_source(row: dict[str, Any]) -> None:
    caption = _technical_evidence_caption(row.get("evidence"))
    if caption and _technical_source_value_needs_refresh(row.get("evidenceLocation")):
        row["evidenceLocation"] = caption
    source_text = _technical_readable_source_text(row)
    if not source_text:
        return
    for key in ("sourceText", "sourceLabel", "source"):
        if _technical_source_value_needs_refresh(row.get(key)):
            row[key] = source_text


def _apply_technical_readable_source(row: dict[str, Any], records: list[dict[str, Any]]) -> None:
    # 与商务族 _apply_business_readable_source 互指：回填 evidence 取 record["text"]，
    # caption 可覆盖 evidenceLocation，无返回值；商务版语义不同，不合并。
    if not records:
        return
    first = records[0]
    for key in ("sourceFile", "sourceDocumentId", "section", "evidenceLocation"):
        if not str(row.get(key) or "").strip() and str(first.get(key) or "").strip():
            row[key] = first[key]

    evidence_text = "；".join(
        dict.fromkeys(str(record.get("text") or "").strip() for record in records if str(record.get("text") or "").strip())
    )
    if evidence_text and not str(row.get("evidence") or "").strip():
        row["evidence"] = evidence_text

    caption = _technical_evidence_caption(row.get("evidence") or first.get("text"))
    if caption and _technical_source_value_needs_refresh(row.get("evidenceLocation")):
        row["evidenceLocation"] = caption

    source_text = _technical_readable_source_text(row, records)
    if source_text:
        for key in ("sourceText", "sourceLabel", "source"):
            if _technical_source_value_needs_refresh(row.get(key)):
                row[key] = source_text


def _sync_technical_categories_from_items(interpretation: dict[str, Any]) -> None:
    items = interpretation.get("items") if isinstance(interpretation.get("items"), list) else []
    categories = interpretation.get("categories") if isinstance(interpretation.get("categories"), list) else []
    if not items or not categories:
        return
    by_id = {str(item.get("id") or ""): item for item in items if isinstance(item, dict) and str(item.get("id") or "")}
    by_row = {str(item.get("rowNo") or ""): item for item in items if isinstance(item, dict) and str(item.get("rowNo") or "")}
    for category in categories:
        if not isinstance(category, dict) or not isinstance(category.get("items"), list):
            continue
        synced_items = []
        for item in category["items"]:
            if not isinstance(item, dict):
                synced_items.append(item)
                continue
            replacement = by_id.get(str(item.get("id") or "")) or by_row.get(str(item.get("rowNo") or ""))
            synced_items.append(copy.deepcopy(replacement or item))
        category["items"] = synced_items


def _materialize_technical_evidence_refs(
    structured: dict[str, Any],
    *,
    structured_path: Path | None = None,
) -> dict[str, Any]:
    # 与商务族 _materialize_business_readable_sources 互指：回填目标结构不同，不合并。
    if not isinstance(structured, dict):
        return structured
    interpretation = structured.get("technicalInterpretation")
    items = interpretation.get("items") if isinstance(interpretation, dict) and isinstance(interpretation.get("items"), list) else []
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups.get("projectBasics"), list) else []
    if not items and not project_basics:
        return structured

    materialized = copy.deepcopy(structured)
    materialized_interpretation = materialized.get("technicalInterpretation")
    materialized_items = (
        materialized_interpretation.get("items")
        if isinstance(materialized_interpretation, dict) and isinstance(materialized_interpretation.get("items"), list)
        else []
    )
    materialized_field_groups = materialized.get("fieldGroups") if isinstance(materialized.get("fieldGroups"), dict) else {}
    materialized_project_basics = (
        materialized_field_groups.get("projectBasics")
        if isinstance(materialized_field_groups.get("projectBasics"), list)
        else []
    )
    for row in materialized_project_basics:
        if isinstance(row, dict):
            _apply_existing_technical_readable_source(row)
    if materialized_project_basics and isinstance(materialized.get("projectFactFields"), list):
        materialized["projectFactFields"] = copy.deepcopy(materialized_project_basics)

    nav_path = _resolve_technical_nav_store_path(structured, structured_path)
    if nav_path is None or not nav_path.is_file():
        return materialized if materialized_project_basics else structured

    documents_by_id = _source_documents_by_id(materialized)
    try:
        conn = sqlite3.connect(str(nav_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return materialized if materialized_project_basics else structured
    try:
        for row in materialized_project_basics:
            if not isinstance(row, dict):
                continue
            evidence_ids = _technical_evidence_ids(row)
            if not evidence_ids:
                continue
            records = _fetch_technical_evidence_records(conn, evidence_ids, documents_by_id)
            if not records:
                continue
            row["evidenceRefs"] = _merge_technical_evidence_refs(row.get("evidenceRefs"), records)
            _apply_technical_readable_source(row, records)
        if materialized_project_basics and isinstance(materialized.get("projectFactFields"), list):
            materialized["projectFactFields"] = copy.deepcopy(materialized_project_basics)

        for item in materialized_items:
            if not isinstance(item, dict):
                continue
            evidence_ids = _technical_evidence_ids(item)
            if not evidence_ids:
                continue
            records = _fetch_technical_evidence_records(conn, evidence_ids, documents_by_id)
            if not records:
                continue
            item["evidenceRefs"] = _merge_technical_evidence_refs(item.get("evidenceRefs"), records)
            if not str(item.get("evidenceSummary") or "").strip():
                first_text = str(records[0].get("text") or "").strip()
                if first_text:
                    item["evidenceSummary"] = first_text[:180]
        if isinstance(materialized_interpretation, dict):
            _sync_technical_categories_from_items(materialized_interpretation)
    except sqlite3.Error:
        return structured
    finally:
        conn.close()
    return materialized
