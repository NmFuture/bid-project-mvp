from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.core.config import settings
from app.services.bid_runtime_state import now_iso, read_json_file, write_json_file_atomic
from app.services.material_raw_file_filter import raw_file_matches_bid_type
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.minio_client import minio_client
from app.services.ocr_service import IMAGE_SUFFIXES, ocr_service
from app.services.parsing import extract_docx_text, extract_pdf_text
from app.services.peripheral import PeripheralError


SUPPORTED_SUFFIXES = {".pdf", ".docx", *IMAGE_SUFFIXES}
CERTIFICATE_TIME_CONFIG_PATH = (
    settings.documents_dir / "_runtime" / "materials" / "technical_certificate_time_config.json"
)
CERTIFICATE_SCOPE_KEYWORDS = (
    "证书", "认证", "型式", "检测", "检验", "试验", "测试", "报告", "证明", "合格",
    "资质", "许可证", "许可", "符合", "鉴定", "校准", "校验", "计量",
    "cnas", "cqc", "ce", "iec",
)
DATE_TOKEN_RE = re.compile(
    r"(?P<year>(?:19|20)\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?"
)
ISO_DATE_RE = re.compile(r"^(?:19|20)\d{2}-\d{2}-\d{2}$")
FIELD_DATE_RE = re.compile(
    r"(?P<label>发证日期|签发日期|颁发日期|发证时间|签发时间|颁发时间|"
    r"有效期至|有效期到|有效期截止|有效期|有效日期至|有效至|截止日期)"
    r"\s*[:：]?\s*(?P<date>(?:19|20)\d{2}\s*(?:年|[-/.])\s*\d{1,2}\s*(?:月|[-/.])\s*\d{1,2}\s*日?)"
)


@dataclass(frozen=True)
class CertificateDateCandidate:
    value: str
    source_text: str
    score: int


def _raw_file_id(item: RawFile) -> str:
    return f"RAW-{int(item.id):04d}"


def _raw_file_numeric_id(file_id: Any) -> int:
    text = str(file_id or "").strip().upper().replace("RAW-", "")
    return int(text)


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _parent_path(value: Any) -> str:
    parts = [part for part in _normalize_path(value).split("/") if part]
    return "/".join(parts[:-1])


def _looks_like_certificate(value: Any) -> bool:
    text = str(value or "").casefold()
    return any(keyword.casefold() in text for keyword in CERTIFICATE_SCOPE_KEYWORDS)


def _supported_file_name(name: Any) -> bool:
    return Path(str(name or "")).suffix.lower() in SUPPORTED_SUFFIXES


def _normalize_scopes(scopes: Any, *, bid_type: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in scopes or []:
        source = item if isinstance(item, dict) else {"path": item}
        path = _normalize_path(source.get("path"))
        if not path or path in seen:
            continue
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3 or parts[0] != bid_type:
            continue
        seen.add(path)
        normalized.append({
            "path": path,
            "name": str(source.get("name") or parts[-1]),
            "enabled": bool(source.get("enabled", True)),
            "source": str(source.get("source") or "manual"),
            "updatedAt": str(source.get("updatedAt") or now_iso()),
        })
    return normalized


def _read_scope_config(*, bid_type: str) -> dict[str, Any]:
    payload = read_json_file(CERTIFICATE_TIME_CONFIG_PATH)
    scopes = _normalize_scopes(payload.get("scopes") or [], bid_type=bid_type)
    return {
        "bidType": bid_type,
        "updatedAt": str(payload.get("updatedAt") or ""),
        "scopes": scopes,
    }


def _write_scope_config(*, bid_type: str, scopes: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "bidType": bid_type,
        "updatedAt": now_iso(),
        "scopes": _normalize_scopes(scopes, bid_type=bid_type),
    }
    write_json_file_atomic(CERTIFICATE_TIME_CONFIG_PATH, payload)
    return payload


def _configured_scope_paths(*, bid_type: str) -> list[str]:
    config = _read_scope_config(bid_type=bid_type)
    return [
        str(scope.get("path") or "")
        for scope in config.get("scopes") or []
        if scope.get("enabled") and scope.get("path")
    ]


def _file_in_scope(item: RawFile, scope_paths: list[str]) -> bool:
    folder_path = _normalize_path(item.folder.path if item.folder else "")
    return any(folder_path == scope or folder_path.startswith(f"{scope}/") for scope in scope_paths)


def _certificate_unique_key(*, folder_path: Any, name: Any) -> str:
    return f"{_normalize_path(folder_path).casefold()}/{str(name or '').strip().casefold()}"


def _certificate_item_unique_key(item: RawFile) -> str:
    return _certificate_unique_key(
        folder_path=item.folder.path if item.folder else "",
        name=item.name,
    )


def _is_retryable_stale_not_found_meta(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    return (
        str(meta.get("status") or "") == "not_found"
        and str(meta.get("source") or "") == "pdf_text"
        and not meta.get("issueDate")
        and not meta.get("expiryDate")
        and not meta.get("dates")
    )


def _certificate_row_rank(row: dict[str, Any]) -> tuple[int, str, str]:
    status = str(row.get("status") or "")
    score = 0
    if row.get("expiryDate"):
        score += 40
    if row.get("issueDate"):
        score += 20
    if status == "manual":
        score += 12
    elif status == "extracted":
        score += 10
    elif status == "not_found":
        score += 3
    elif status == "failed":
        score += 1
    return (score, str(row.get("updatedAt") or ""), str(row.get("fileId") or ""))


def dedupe_certificate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _certificate_unique_key(folder_path=row.get("folderPath"), name=row.get("name"))
        if not key:
            continue
        grouped.setdefault(key, []).append(row)

    deduped: list[dict[str, Any]] = []
    for group in grouped.values():
        ordered = sorted(group, key=_certificate_row_rank, reverse=True)
        primary = dict(ordered[0])
        primary["duplicateCount"] = len(group)
        primary["duplicateFileIds"] = [str(item.get("fileId") or "") for item in ordered[1:] if item.get("fileId")]
        deduped.append(primary)
    return deduped


def _normalize_date(value: str) -> str:
    match = DATE_TOKEN_RE.search(str(value or ""))
    if not match:
        return ""
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _line_window(lines: list[str], index: int) -> str:
    start = max(0, index - 1)
    end = min(len(lines), index + 2)
    return " ".join(line.strip() for line in lines[start:end] if line.strip())[:240]


def extract_certificate_time_fields(text: str) -> dict[str, Any]:
    """Extract certificate issue and expiry dates from OCR/plain text.

    The rule is deliberately conservative: label-near dates win. If labels are
    missing, the first two dates are returned as low-confidence candidates so a
    human can still review the evidence.
    """

    raw_text = str(text or "")
    clean = re.sub(r"[ \t\u3000]+", " ", raw_text)
    lines = [line.strip() for line in re.split(r"[\r\n]+", clean) if line.strip()]
    issue_candidates: list[CertificateDateCandidate] = []
    expiry_candidates: list[CertificateDateCandidate] = []
    all_dates: list[CertificateDateCandidate] = []
    seen_dates: set[str] = set()

    for line_index, line in enumerate(lines):
        for match in DATE_TOKEN_RE.finditer(line):
            normalized = _normalize_date(match.group(0))
            if not normalized or normalized in seen_dates:
                continue
            seen_dates.add(normalized)
            all_dates.append(CertificateDateCandidate(normalized, _line_window(lines, line_index), 20))

        for match in FIELD_DATE_RE.finditer(line):
            label = match.group("label")
            date_matches = list(DATE_TOKEN_RE.finditer(line[match.start():]))
            picked_date = date_matches[-1].group(0) if ("有效" in label or "截止" in label) and date_matches else match.group("date")
            normalized = _normalize_date(picked_date)
            if not normalized:
                continue
            candidate = CertificateDateCandidate(normalized, _line_window(lines, line_index), 95)
            if "有效" in label or "截止" in label:
                expiry_candidates.append(candidate)
            else:
                issue_candidates.append(candidate)

    for index, line in enumerate(lines):
        if "发证" in line or "签发" in line or "颁发" in line:
            for match in DATE_TOKEN_RE.finditer(_line_window(lines, index)):
                normalized = _normalize_date(match.group(0))
                if normalized:
                    issue_candidates.append(CertificateDateCandidate(normalized, _line_window(lines, index), 78))
        if "有效" in line or "截止" in line:
            for match in DATE_TOKEN_RE.finditer(_line_window(lines, index)):
                normalized = _normalize_date(match.group(0))
                if normalized:
                    expiry_candidates.append(CertificateDateCandidate(normalized, _line_window(lines, index), 82))

    if not issue_candidates and all_dates:
        issue_candidates.append(all_dates[0])
    if not expiry_candidates and len(all_dates) >= 2:
        expiry_candidates.append(all_dates[1])
    elif not expiry_candidates and len(all_dates) == 1 and not issue_candidates:
        expiry_candidates.append(all_dates[0])

    issue = max(issue_candidates, key=lambda item: item.score, default=None)
    expiry = max(expiry_candidates, key=lambda item: item.score, default=None)
    confidence = 0
    if issue:
        confidence += 45 if issue.score >= 75 else 20
    if expiry:
        confidence += 45 if expiry.score >= 75 else 20
    if issue and expiry:
        confidence += 10

    return {
        "issueDate": issue.value if issue else "",
        "expiryDate": expiry.value if expiry else "",
        "confidence": min(confidence, 100),
        "evidence": {
            "issueDate": issue.source_text if issue else "",
            "expiryDate": expiry.source_text if expiry else "",
        },
        "dates": [candidate.value for candidate in all_dates[:12]],
        "status": "extracted" if issue or expiry else "not_found",
    }


async def _load_raw_files(*, bid_type: str, folder_path: str = "", file_ids: list[str] | None = None) -> list[RawFile]:
    async with async_session() as session:
        await ensure_material_runtime_tables(session)
        stmt = select(RawFile).options(selectinload(RawFile.folder))
        ids = [int(str(file_id).replace("RAW-", "")) for file_id in (file_ids or []) if str(file_id).strip()]
        if ids:
            stmt = stmt.where(RawFile.id.in_(ids))
        else:
            normalized_path = str(folder_path or "").strip().strip("/")
            if normalized_path:
                stmt = stmt.join(RawFolder).where(
                    or_(RawFolder.path == normalized_path, RawFolder.path.like(f"{normalized_path}/%"))
                )
        result = await session.execute(stmt.order_by(RawFile.id))
        items = [item for item in result.scalars().all() if raw_file_matches_bid_type(item, bid_type)]
    return items


def _certificate_payload_from_item(item: RawFile) -> dict[str, Any]:
    ext = item.ext_fields or {}
    meta = ext.get("certificateMeta") if isinstance(ext.get("certificateMeta"), dict) else {}
    return {
        "fileId": _raw_file_id(item),
        "name": item.name,
        "folderPath": item.folder.path if item.folder else "",
        "issueDate": str(meta.get("issueDate") or ""),
        "expiryDate": str(meta.get("expiryDate") or ""),
        "confidence": int(meta.get("confidence") or 0),
        "status": str(meta.get("status") or "pending"),
        "source": str(meta.get("source") or ""),
        "evidence": meta.get("evidence") if isinstance(meta.get("evidence"), dict) else {},
        "dates": meta.get("dates") if isinstance(meta.get("dates"), list) else [],
        "updatedAt": str(meta.get("updatedAt") or ""),
        "errorMessage": str(meta.get("errorMessage") or ""),
    }


async def list_certificate_time_registry(*, bid_type: str) -> dict[str, Any]:
    items = await _load_raw_files(bid_type=bid_type)
    scope_paths = _configured_scope_paths(bid_type=bid_type)
    rows = [_certificate_payload_from_item(item) for item in items]
    rows = [
        row for row in rows
        if row["issueDate"] or row["expiryDate"] or row["status"] in {"extracted", "not_found", "failed", "unsupported"}
    ]
    rows = dedupe_certificate_rows(rows)
    rows.sort(key=lambda item: (item.get("expiryDate") or "9999-99-99", item.get("folderPath") or "", item.get("name") or ""))
    return {
        "items": rows,
        "total": len(rows),
        "config": _read_scope_config(bid_type=bid_type),
        "summary": {
            "extracted": sum(1 for item in rows if item.get("status") == "extracted"),
            "expiring": sum(1 for item in rows if item.get("expiryDate")),
            "failed": sum(1 for item in rows if item.get("status") == "failed"),
            "scopeCount": len(scope_paths),
        },
    }


async def suggest_certificate_time_scopes(*, bid_type: str) -> dict[str, Any]:
    from app.services.technical_material_index import load_technical_material_index, rebuild_technical_material_index

    index_payload = load_technical_material_index()
    if not index_payload:
        index_payload = await rebuild_technical_material_index()

    configured = set(_configured_scope_paths(bid_type=bid_type))
    grouped: dict[str, dict[str, Any]] = {}
    for tier in index_payload.get("tiers") or []:
        for folder in tier.get("folders") or []:
            folder_path = _normalize_path(folder.get("path"))
            for file_item in folder.get("files") or []:
                name = str(file_item.get("name") or "")
                file_path = _normalize_path(file_item.get("path"))
                if not _supported_file_name(name):
                    continue
                haystack = " ".join([
                    name,
                    file_path,
                    " ".join(str(tag or "") for tag in file_item.get("tags") or []),
                ])
                if not _looks_like_certificate(haystack):
                    continue
                file_parent = _parent_path(file_path)
                scope_path = file_parent if _looks_like_certificate(file_parent) else folder_path
                if not scope_path:
                    continue
                item = grouped.setdefault(scope_path, {
                    "path": scope_path,
                    "name": scope_path.split("/")[-1],
                    "tier": folder.get("tier") or tier.get("tier") or "",
                    "candidateCount": 0,
                    "fileCount": 0,
                    "examples": [],
                    "selected": scope_path in configured,
                    "reason": "目录或文件名命中证书关键词",
                })
                item["candidateCount"] += 1
                item["fileCount"] += 1
                if len(item["examples"]) < 3:
                    item["examples"].append(name)

    suggestions = sorted(
        grouped.values(),
        key=lambda item: (-int(item.get("candidateCount") or 0), str(item.get("path") or "")),
    )
    return {
        "items": suggestions,
        "total": len(suggestions),
        "config": _read_scope_config(bid_type=bid_type),
    }


async def update_certificate_time_scopes(*, bid_type: str, scopes: Any) -> dict[str, Any]:
    config = _write_scope_config(bid_type=bid_type, scopes=list(scopes or []))
    return {"message": "证书识别范围已更新", "config": config}


async def delete_certificate_time_record(*, bid_type: str, file_id: str) -> dict[str, Any]:
    numeric_id = _raw_file_numeric_id(file_id)
    async with async_session() as session:
        await ensure_material_runtime_tables(session)
        result = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")
        folder_path = item.folder.path if item.folder else ""
        duplicate_result = await session.execute(
            select(RawFile)
            .join(RawFolder)
            .where(RawFile.name == item.name, RawFolder.path == folder_path)
            .options(selectinload(RawFile.folder))
        )
        duplicates = [
            duplicate
            for duplicate in duplicate_result.scalars().all()
            if raw_file_matches_bid_type(duplicate, bid_type)
        ]
        for duplicate in duplicates:
            ext = dict(duplicate.ext_fields or {})
            ext.pop("certificateMeta", None)
            duplicate.ext_fields = ext
        await session.commit()
    return {"message": "证书台账记录已删除", "fileId": file_id, "deletedCount": len(duplicates)}


async def delete_certificate_time_records(*, bid_type: str, file_ids: Any) -> dict[str, Any]:
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for value in list(file_ids or []):
        file_id = str(value or "").strip()
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        normalized_ids.append(file_id)
    if not normalized_ids:
        raise PeripheralError(400, "请选择需要删除的证书台账记录。", "CERTIFICATE_DELETE_EMPTY")
    if len(normalized_ids) > 500:
        raise PeripheralError(400, "单次最多批量删除 500 条证书台账记录。", "CERTIFICATE_DELETE_LIMIT")

    deleted_count = 0
    failed: list[dict[str, str]] = []
    for file_id in normalized_ids:
        try:
            result = await delete_certificate_time_record(bid_type=bid_type, file_id=file_id)
            deleted_count += int(result.get("deletedCount") or 0)
        except Exception as exc:  # noqa: BLE001 - keep batch delete best-effort
            failed.append({"fileId": file_id, "message": str(exc)})

    return {
        "message": f"已删除 {len(normalized_ids) - len(failed)} 条证书台账记录",
        "requested": len(normalized_ids),
        "deleted": len(normalized_ids) - len(failed),
        "deletedCount": deleted_count,
        "failed": failed,
    }


async def run_certificate_time_incremental(*, bid_type: str, limit: int = 50, include_failed: bool = True) -> dict[str, Any]:
    scope_paths = _configured_scope_paths(bid_type=bid_type)
    if not scope_paths:
        raise PeripheralError(400, "请先确认需要识别的证书目录。", "CERTIFICATE_SCOPE_REQUIRED")
    items = await _load_raw_files(bid_type=bid_type)
    selected_ids: list[str] = []
    seen_keys: set[str] = set()
    for item in items:
        if not _file_in_scope(item, scope_paths):
            continue
        if not _supported_file_name(item.name):
            continue
        unique_key = _certificate_item_unique_key(item)
        if unique_key in seen_keys:
            continue
        meta = (item.ext_fields or {}).get("certificateMeta")
        status = str(meta.get("status") or "") if isinstance(meta, dict) else ""
        has_result = isinstance(meta, dict) and (
            meta.get("issueDate") or meta.get("expiryDate") or status in {"extracted", "not_found", "manual", "unsupported"}
        )
        if _is_retryable_stale_not_found_meta(meta):
            has_result = False
        if has_result:
            seen_keys.add(unique_key)
            continue
        if status == "failed" and not include_failed:
            continue
        seen_keys.add(unique_key)
        selected_ids.append(_raw_file_id(item))
    if not selected_ids:
        return {
            "items": [],
            "total": 0,
            "processed": 0,
            "skipped": 0,
            "failed": [],
            "message": "没有需要增量识别的证书文件",
        }
    return await run_certificate_time_batch(
        bid_type=bid_type,
        file_ids=selected_ids,
        limit=limit,
    )


def _validate_manual_date(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = _normalize_date(text)
    if normalized and ISO_DATE_RE.match(normalized):
        return normalized
    raise PeripheralError(400, f"{label}格式应为 YYYY-MM-DD。", "CERTIFICATE_DATE_INVALID")


async def update_certificate_time_record(
    *,
    bid_type: str,
    file_id: str,
    issue_date: Any = "",
    expiry_date: Any = "",
) -> dict[str, Any]:
    numeric_id = _raw_file_numeric_id(file_id)
    async with async_session() as session:
        await ensure_material_runtime_tables(session)
        result = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")

        ext = dict(item.ext_fields or {})
        previous = ext.get("certificateMeta") if isinstance(ext.get("certificateMeta"), dict) else {}
        meta = {
            **previous,
            "issueDate": _validate_manual_date(issue_date, "发证日期"),
            "expiryDate": _validate_manual_date(expiry_date, "有效期至"),
            "status": "manual",
            "source": "manual",
            "confidence": 100,
            "updatedAt": now_iso(),
            "errorMessage": "",
        }
        ext["certificateMeta"] = meta
        item.ext_fields = ext
        await session.commit()
        await session.refresh(item)
        return {"message": "证书时间已更新", "item": _certificate_payload_from_item(item)}


def _extract_text_without_ocr(file_name: str, content: bytes) -> tuple[str, dict[str, Any]]:
    suffix = Path(file_name).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="certificate-time-") as temp_root:
        path = Path(temp_root) / (Path(file_name).name or f"material{suffix}")
        path.write_bytes(content)
        if suffix == ".docx":
            return extract_docx_text(path), {"source": "docx_text"}
        if suffix == ".pdf":
            text, info = extract_pdf_text(path)
            return text, {"source": "pdf_text", **info}
    return "", {"source": "unsupported"}


def _should_accept_text_without_ocr(*, suffix: str, text: str) -> bool:
    if not str(text or "").strip():
        return False
    if suffix == ".pdf":
        return extract_certificate_time_fields(text).get("status") == "extracted"
    return True


async def _extract_source_text(item: RawFile) -> tuple[str, dict[str, Any]]:
    suffix = Path(item.name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise PeripheralError(400, "仅支持 PDF、DOCX 和图片证书。", "CERTIFICATE_FILE_TYPE_UNSUPPORTED")

    content = minio_client.get_object(item.minio_bucket, item.minio_key)
    if suffix in {".docx", ".pdf"}:
        try:
            text, info = _extract_text_without_ocr(item.name, content)
            if _should_accept_text_without_ocr(suffix=suffix, text=text):
                return text, info
        except Exception:
            if suffix == ".docx":
                raise
    text, info = await ocr_service.recognize_text_for_parse(
        file_name=item.name,
        content=content,
        mime_type=item.mime_type or "",
    )
    return text, {"source": "ocr", **info}


async def run_certificate_time_batch(
    *,
    bid_type: str,
    folder_path: str = "",
    file_ids: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    items = await _load_raw_files(bid_type=bid_type, folder_path=folder_path, file_ids=file_ids)
    limit = max(1, min(int(limit or 50), 200))
    selected = items[:limit]
    rows: list[dict[str, Any]] = []

    for item in selected:
        raw_id = _raw_file_id(item)
        suffix = Path(item.name).suffix.lower()
        meta: dict[str, Any]
        try:
            if suffix not in SUPPORTED_SUFFIXES:
                raise PeripheralError(400, "仅支持 PDF、DOCX 和图片证书。", "CERTIFICATE_FILE_TYPE_UNSUPPORTED")
            text, source_info = await _extract_source_text(item)
            extracted = extract_certificate_time_fields(text)
            meta = {
                **extracted,
                "source": str(source_info.get("source") or ""),
                "pageCount": source_info.get("pageCount") or 0,
                "updatedAt": now_iso(),
                "errorMessage": "",
            }
        except Exception as exc:
            meta = {
                "issueDate": "",
                "expiryDate": "",
                "confidence": 0,
                "status": "unsupported" if suffix not in SUPPORTED_SUFFIXES else "failed",
                "source": "",
                "evidence": {},
                "dates": [],
                "updatedAt": now_iso(),
                "errorMessage": getattr(exc, "detail", str(exc)),
            }

        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            current = await session.get(RawFile, int(item.id))
            if current is not None:
                ext = dict(current.ext_fields or {})
                ext["certificateMeta"] = meta
                current.ext_fields = ext
                await session.commit()

        rows.append({
            "fileId": raw_id,
            "name": item.name,
            "folderPath": item.folder.path if item.folder else "",
            **meta,
        })

    failed = [row for row in rows if row.get("status") in {"failed", "unsupported"}]
    extracted_count = sum(1 for row in rows if row.get("status") == "extracted")
    return {
        "items": rows,
        "total": len(rows),
        "processed": len(rows),
        "skipped": max(0, len(items) - len(selected)),
        "failed": failed,
        "message": f"证书时间整理完成：识别 {extracted_count} 个，失败/不支持 {len(failed)} 个",
    }
