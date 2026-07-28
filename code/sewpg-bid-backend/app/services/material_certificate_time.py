from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
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
FIELD_LABELS_PATTERN = (
    r"发证日期|签发日期|颁发日期|发证时间|签发时间|颁发时间|"
    r"有效期至|有效期到|有效期截止|有效期|有效日期至|有效至|截止日期"
)
FIELD_DATE_RE = re.compile(
    rf"(?P<label>{FIELD_LABELS_PATTERN})"
    r"\s*[:：]?\s*(?P<date>(?:19|20)\d{2}\s*(?:年|[-/.])\s*\d{1,2}\s*(?:月|[-/.])\s*\d{1,2}\s*日?)"
)
# 只写到年月的模糊日期（如“有效期至：2027年4月”），只在整行完整日期被掩掉后匹配
FIELD_YEAR_MONTH_RE = re.compile(
    rf"(?P<label>{FIELD_LABELS_PATTERN})"
    r"\s*[:：]?\s*(?P<year>(?:19|20)\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*月?"
)
CN_NUMERALS = {
    "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3,
    "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
    "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9, "十": 10, "拾": 10,
}
VALIDITY_DURATION_RE = re.compile(
    r"有效期\s*[为:：]?\s*(?P<num>\d{1,2}|[一壹二贰两三叁四肆五伍六陆七柒八捌九玖十拾])\s*(?P<unit>个月|年|月)"
)
LONG_TERM_RE = re.compile(r"长期有效|永久有效|有效期\s*[为:：]?\s*(?:长期|永久)")
DATE_ORDER_WARNING = "发证日期晚于有效期至，请人工复核"
CERTIFICATE_AI_TEXT_LIMIT = 6000


def _is_equipment_validity_context(line: str, start: int) -> bool:
    """“校准/计量有效期”是测试设备的标定日期，不属于证书本身的有效期。"""
    prefix = line[max(0, start - 8):start]
    return "校准" in prefix or "计量" in prefix

logger = logging.getLogger(__name__)


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


def migrate_certificate_time_scopes_on_path_change(
    *,
    bid_type: str,
    old_path: str,
    new_path: str,
) -> None:
    """目录改名/迁移后，把证书识别范围配置里的旧路径前缀同步替换为新路径。

    只处理以 old_path 为根的 scope；对于合并到已有目录的场景，old_path 下文件已迁入 new_path，
    因此把 scope 指向 new_path 才能保证增量识别继续命中。
    """
    old_path = _normalize_path(old_path)
    new_path = _normalize_path(new_path)
    if not old_path or not new_path or old_path == new_path:
        return

    config = _read_scope_config(bid_type=bid_type)
    scopes = config.get("scopes") or []
    changed = False
    migrated: list[dict[str, Any]] = []
    for scope in scopes:
        scope_path = _normalize_path(scope.get("path"))
        if scope_path and (scope_path == old_path or scope_path.startswith(f"{old_path}/")):
            scope = {**scope, "path": f"{new_path}{scope_path[len(old_path):]}", "updatedAt": now_iso()}
            changed = True
        migrated.append(scope)

    if changed:
        _write_scope_config(bid_type=bid_type, scopes=migrated)
        logger.info("migrated certificate scopes: %s -> %s", old_path, new_path)


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
    try:
        date(year, month, day)
    except ValueError:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _add_months(base: date, months: int) -> date:
    total = base.year * 12 + (base.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(base.day, monthrange(year, month)[1]))


def _derive_expiry_from_duration(issue_iso: str, num: int, unit: str) -> str:
    try:
        base = date.fromisoformat(issue_iso)
    except ValueError:
        return ""
    months = num * 12 if unit == "年" else num
    if months <= 0:
        return ""
    return (_add_months(base, months) - timedelta(days=1)).isoformat()


def _duration_number(token: str) -> int:
    text = str(token or "").strip()
    if text.isdigit():
        return int(text)
    return CN_NUMERALS.get(text, 0)


def _pick_candidate(
    candidates: list[CertificateDateCandidate],
    *,
    prefer_latest: bool,
    floor: str = "",
) -> CertificateDateCandidate | None:
    """同分候选按语义择优：发证取最早，有效期取最晚且尽量晚于发证日期。"""
    if not candidates:
        return None
    top = max(candidate.score for candidate in candidates)
    pool = [candidate for candidate in candidates if candidate.score == top]
    if floor:
        later = [candidate for candidate in pool if candidate.value > floor]
        if later:
            pool = later
    picker = max if prefer_latest else min
    return picker(pool, key=lambda candidate: candidate.value)


def _line_window(lines: list[str], index: int) -> str:
    start = max(0, index - 1)
    end = min(len(lines), index + 2)
    return " ".join(line.strip() for line in lines[start:end] if line.strip())[:240]


def extract_certificate_time_fields(text: str) -> dict[str, Any]:
    """Extract certificate issue and expiry dates from OCR/plain text.

    The rule is deliberately conservative: label-near dates win. Fuzzy forms
    (year-month only, "有效期 N 年", "长期有效") are resolved with lower scores,
    and issue/expiry ordering is cross-checked so a human can review conflicts.
    """

    raw_text = str(text or "")
    clean = re.sub(r"[ \t\u3000]+", " ", raw_text)
    lines = [line.strip() for line in re.split(r"[\r\n]+", clean) if line.strip()]
    issue_candidates: list[CertificateDateCandidate] = []
    expiry_candidates: list[CertificateDateCandidate] = []
    all_dates: list[CertificateDateCandidate] = []
    seen_dates: set[str] = set()
    duration_hits: list[tuple[int, str, str]] = []
    long_term_sources: list[str] = []

    for line_index, line in enumerate(lines):
        window = _line_window(lines, line_index)
        for match in DATE_TOKEN_RE.finditer(line):
            normalized = _normalize_date(match.group(0))
            if not normalized or normalized in seen_dates:
                continue
            seen_dates.add(normalized)
            all_dates.append(CertificateDateCandidate(normalized, window, 20))

        for match in FIELD_DATE_RE.finditer(line):
            if _is_equipment_validity_context(line, match.start()):
                continue
            label = match.group("label")
            date_matches = list(DATE_TOKEN_RE.finditer(line[match.start():]))
            picked_date = date_matches[-1].group(0) if ("有效" in label or "截止" in label) and date_matches else match.group("date")
            normalized = _normalize_date(picked_date)
            if not normalized:
                continue
            candidate = CertificateDateCandidate(normalized, window, 95)
            if "有效" in label or "截止" in label:
                expiry_candidates.append(candidate)
            else:
                issue_candidates.append(candidate)

        # 掩掉完整日期后再找“年月”模糊日期，避免把完整日期的前半截当成年月
        masked = DATE_TOKEN_RE.sub(" ", line)
        for match in FIELD_YEAR_MONTH_RE.finditer(masked):
            if _is_equipment_validity_context(masked, match.start()):
                continue
            label = match.group("label")
            year = int(match.group("year"))
            month = int(match.group("month"))
            if not 1 <= month <= 12:
                continue
            if "有效" in label or "截止" in label:
                day = monthrange(year, month)[1]
                expiry_candidates.append(
                    CertificateDateCandidate(f"{year:04d}-{month:02d}-{day:02d}", f"{window}（按月末推定）", 70)
                )
            else:
                issue_candidates.append(
                    CertificateDateCandidate(f"{year:04d}-{month:02d}-01", f"{window}（按月初推定）", 70)
                )

        for match in VALIDITY_DURATION_RE.finditer(line):
            num = _duration_number(match.group("num"))
            if num > 0:
                duration_hits.append((num, "年" if match.group("unit") == "年" else "月", window))

        if LONG_TERM_RE.search(line):
            long_term_sources.append(window)

    # 邻行窗口兜底时，跳过已被明确标签认领的日期，避免发证日期串到有效期（反之亦然）
    labeled_issue_values = {candidate.value for candidate in issue_candidates if candidate.score >= 95}
    labeled_expiry_values = {candidate.value for candidate in expiry_candidates if candidate.score >= 95}
    for index, line in enumerate(lines):
        if "发证" in line or "签发" in line or "颁发" in line:
            for match in DATE_TOKEN_RE.finditer(_line_window(lines, index)):
                normalized = _normalize_date(match.group(0))
                if normalized and normalized not in labeled_expiry_values:
                    issue_candidates.append(CertificateDateCandidate(normalized, _line_window(lines, index), 78))
        if "有效" in line or "截止" in line:
            window = _line_window(lines, index)
            for match in DATE_TOKEN_RE.finditer(window):
                if _is_equipment_validity_context(window, match.start()):
                    continue
                normalized = _normalize_date(match.group(0))
                if normalized and normalized not in labeled_issue_values:
                    expiry_candidates.append(CertificateDateCandidate(normalized, _line_window(lines, index), 82))

    # 无标签兜底只补发证日期（取最早）；有效期必须来自明确表述（标签/年限/长期），不用散落日期猜测
    if not issue_candidates and all_dates:
        issue_candidates.append(min(all_dates, key=lambda item: item.value))
    issue = _pick_candidate(issue_candidates, prefer_latest=False)

    if not expiry_candidates and duration_hits and issue:
        num, unit, source = duration_hits[0]
        derived = _derive_expiry_from_duration(issue.value, num, unit)
        if derived:
            expiry_candidates.append(
                CertificateDateCandidate(derived, f"{source}（按发证日期加{num}{unit}推算）", 72)
            )

    expiry = _pick_candidate(expiry_candidates, prefer_latest=True, floor=issue.value if issue else "")

    long_term = False
    if long_term_sources and (expiry is None or expiry.score < 70):
        expiry = None
        long_term = True

    warnings: list[str] = []
    if issue and expiry and issue.value > expiry.value:
        warnings.append(DATE_ORDER_WARNING)

    confidence = 0
    for candidate in (issue, expiry):
        if candidate:
            confidence += 45 if candidate.score >= 75 else 32 if candidate.score >= 55 else 20
    if long_term:
        confidence += 30
    if issue and (expiry or long_term):
        confidence += 10
    if warnings:
        confidence = min(confidence, 40)

    evidence = {
        "issueDate": issue.source_text if issue else "",
        "expiryDate": expiry.source_text if expiry else "",
    }
    if long_term:
        evidence["expiryDate"] = f"{long_term_sources[0]}（长期有效）"

    return {
        "issueDate": issue.value if issue else "",
        "expiryDate": expiry.value if expiry else "",
        "longTerm": long_term,
        "warnings": warnings,
        "confidence": min(confidence, 100),
        "evidence": evidence,
        "dates": [candidate.value for candidate in all_dates[:12]],
        "status": "extracted" if issue or expiry or long_term else "not_found",
    }


# ---------- 证书类别有效期规则 ----------

# 规则来源：《证书报告有效期确认.xlsx》（Sheet2，业务确认版）。
# 报告内明确写的有效期始终优先；只有文本未写明时才按规则推算/标注，不做猜测。
CERT_VALIDITY_RULES: tuple[dict[str, Any], ...] = (
    {"category": "整机设计认证", "authority": "CQC", "grade": "A", "mode": "long_term", "condition": "设计不变"},
    {"category": "整机设计认证", "authority": "CQC", "grade": "B", "mode": "years", "years": 1},
    {"category": "整机设计认证", "authority": "CQC", "grade": "D", "mode": "years", "years": 2},
    {"category": "整机型式认证", "authority": "CQC", "grade": "A", "mode": "years", "years": 5},
    {"category": "整机型式认证", "authority": "CQC", "grade": "B", "mode": "years", "years": 1},
    {"category": "部件型式认证", "authority": "CQC", "grade": "A", "mode": "years", "years": 5},
    {"category": "部件型式认证", "authority": "CQC", "grade": "B", "mode": "years", "years": 1},
    {"category": "部件型式认证", "authority": "鉴衡CGC", "grade": "A", "mode": "years", "years": 4},
    {"category": "部件型式认证", "authority": "鉴衡CGC", "grade": "B", "mode": "years", "years": 1},
    {"category": "低压穿越LVRT报告", "authority": "电科院CEPRI", "grade": "", "mode": "follow_turbine"},
    {"category": "高压穿越HVRT报告", "authority": "电科院CEPRI", "grade": "", "mode": "follow_turbine"},
    {"category": "电能质量报告", "authority": "电科院CEPRI", "grade": "", "mode": "follow_turbine"},
    {"category": "电网适应性报告", "authority": "电科院CEPRI", "grade": "", "mode": "follow_turbine"},
    {"category": "故障电压连续穿越检测报告", "authority": "电科院CEPRI", "grade": "", "mode": "follow_turbine"},
    {"category": "机电暂态模型验证报告", "authority": "电科院CEPRI", "grade": "", "mode": "long_term", "condition": "控制策略不变"},
    {"category": "电磁暂态模型验证报告", "authority": "电科院CEPRI", "grade": "", "mode": "long_term", "condition": "控制策略不变"},
)

# 类别关键词（按特异性从高到低匹配，命中即止）
CERT_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("机电暂态模型验证报告", ("机电暂态",)),
    ("电磁暂态模型验证报告", ("电磁暂态",)),
    ("故障电压连续穿越检测报告", ("故障电压连续穿越", "连续穿越检测", "连续穿越")),
    ("低压穿越LVRT报告", ("低压穿越", "低电压穿越", "lvrt")),
    ("高压穿越HVRT报告", ("高压穿越", "高电压穿越", "hvrt")),
    ("电能质量报告", ("电能质量",)),
    ("电网适应性报告", ("电网适应性",)),
    ("整机设计认证", ("整机设计认证", "设计认证")),
    ("整机型式认证", ("整机型式认证",)),
    ("部件型式认证", ("部件型式认证", "大部件型式")),
)
CERT_AUTHORITY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("鉴衡CGC", ("鉴衡", "cgc")),
    ("电科院CEPRI", ("电科院", "cepri", "中国电力科学研究院")),
    ("CQC", ("cqc", "中国质量认证中心")),
)

# 等级写法："A级"/"等级：B"/"（D级）"/"型式认证A" 等；大小写敏感，避免命中型号里的字母
CERT_GRADE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"([ABD])\s*级"),
    re.compile(r"等级\s*[:：]?\s*([ABD])(?![A-Za-z0-9])"),
    re.compile(r"认证\s*([ABD])(?![A-Za-z0-9])"),
)
# 全角等级字母归一（如“设计认证Ａ”）
_FULLWIDTH_GRADE_TRANS = str.maketrans("ＡＢＤ", "ABD")

_CERT_GRADE_REQUIRED_CATEGORIES = {"整机设计认证", "整机型式认证", "部件型式认证"}


def classify_certificate_validity_rule(text: str, file_name: str = "", folder_path: str = "") -> dict[str, Any]:
    """按规则表识别证书类别/发证机构/等级，并查出对应有效期规则。

    类别有多个发证机构（部件型式认证：CQC/鉴衡CGC）而机构未识别时不猜；
    等级必填的类别（设计/型式认证）未识别到等级时同样不猜。
    文件名/正文只写“型式认证”时，按目录兜底：目录在“部件”下归为部件型式认证，
    否则归为整机型式认证。
    """
    haystack_raw = f"{file_name}\n{str(text or '')[:4000]}".translate(_FULLWIDTH_GRADE_TRANS)
    haystack = haystack_raw.casefold()
    folder_text = str(folder_path or "")

    category = ""
    for name, keywords in CERT_CATEGORY_PATTERNS:
        if any(keyword.casefold() in haystack for keyword in keywords):
            category = name
            break
    if not category and "型式认证" in haystack:
        category = "部件型式认证" if "部件" in folder_text else "整机型式认证"

    authority = ""
    for name, keywords in CERT_AUTHORITY_PATTERNS:
        if any(keyword.casefold() in haystack for keyword in keywords):
            authority = name
            break

    grade = ""
    if category in _CERT_GRADE_REQUIRED_CATEGORIES:
        for pattern in CERT_GRADE_PATTERNS:
            match = pattern.search(haystack_raw)
            if match:
                grade = match.group(1)
                break

    rule = None
    if category:
        candidates = [item for item in CERT_VALIDITY_RULES if item["category"] == category]
        authorities = {item["authority"] for item in candidates}
        effective_authority = authority or (next(iter(authorities)) if len(authorities) == 1 else "")
        if effective_authority:
            rule = next(
                (
                    item
                    for item in candidates
                    if item["authority"] == effective_authority
                    and (not item["grade"] or item["grade"] == grade)
                ),
                None,
            )
        # 类别在规则表中只有单一机构时，OCR 噪声导致的机构误检不拦截规则
        if rule is None and authority and len(authorities) == 1:
            rule = next(
                (item for item in candidates if not item["grade"] or item["grade"] == grade),
                None,
            )
        if rule is not None and rule["grade"] and not grade:
            rule = None

    return {
        "certCategory": category,
        "certAuthority": authority,
        "certGrade": grade,
        "rule": rule,
    }


def apply_certificate_validity_rules(
    extracted: dict[str, Any],
    *,
    text: str,
    file_name: str = "",
    folder_path: str = "",
) -> dict[str, Any]:
    """按《证书报告有效期确认》规则表完善有效期的识别与判断。

    - 报告明确写了有效期至 → 以报告为准（explicit），规则不覆盖；
    - 规则为固定年限且已识别发证日期 → 按 发证+N年-1天 推算（rule_derived）；
    - 规则为长期有效 → 标注 longTerm 并给出条件（设计不变/控制策略不变）；
    - 规则为跟随整机型式证 → 不推算日期，标注 follow_turbine；
    - 报告标注与规则矛盾（如 B 级 1 年却写长期有效）→ 加人工复核 warning。
    """
    meta = dict(extracted)
    info = classify_certificate_validity_rule(text, file_name, folder_path)
    meta["certCategory"] = info["certCategory"]
    meta["certAuthority"] = info["certAuthority"]
    meta["certGrade"] = info["certGrade"]
    meta["validityBasis"] = ""
    meta["validityNote"] = ""
    rule = info.get("rule")
    if not rule:
        return meta

    issue = str(meta.get("issueDate") or "")
    expiry = str(meta.get("expiryDate") or "")
    long_term = bool(meta.get("longTerm"))
    warnings = [str(item) for item in meta.get("warnings") or [] if item]
    evidence = dict(meta.get("evidence") or {})
    rule_label = f"{rule['category']} {rule['authority']}".strip()
    if rule.get("grade"):
        rule_label = f"{rule_label} {rule['grade']}级"

    if rule["mode"] == "follow_turbine":
        if not expiry and not long_term:
            meta["validityBasis"] = "follow_turbine"
            meta["validityNote"] = "跟随对应整机型式认证有效期"
            if str(meta.get("status") or "") in {"", "not_found"}:
                meta["status"] = "extracted"
            meta["confidence"] = max(int(meta.get("confidence") or 0), 40)
        else:
            meta["validityBasis"] = "explicit"
    elif rule["mode"] == "long_term":
        if not expiry:
            meta["longTerm"] = True
            meta["validityBasis"] = "rule_long_term" if not long_term else "text_long_term"
            meta["validityNote"] = f"长期有效（{rule['condition']}）"
            if not long_term:
                evidence["expiryDate"] = f"{rule_label}：长期有效（{rule['condition']}，按规则表标注）"
            if str(meta.get("status") or "") in {"", "not_found"}:
                meta["status"] = "extracted"
            meta["confidence"] = max(int(meta.get("confidence") or 0), 50)
        else:
            meta["validityBasis"] = "explicit"
            warning = f"报告标注了有效期至 {expiry}，规则表中{rule_label}为长期有效（{rule['condition']}），请人工复核"
            if warning not in warnings:
                warnings.append(warning)
    else:  # mode == "years"
        years = int(rule["years"])
        if expiry:
            meta["validityBasis"] = "explicit"
        elif long_term:
            meta["validityBasis"] = "text_long_term"
            warning = f"报告标注长期有效，规则表中{rule_label}标准有效期为{years}年，请人工复核"
            if warning not in warnings:
                warnings.append(warning)
        elif issue:
            derived = _derive_expiry_from_duration(issue, years, "年")
            if derived:
                meta["expiryDate"] = derived
                meta["validityBasis"] = "rule_derived"
                meta["validityNote"] = f"按{rule_label}标准有效期{years}年，自发证日期推算"
                evidence["expiryDate"] = f"{meta['validityNote']}（发证日期 {issue}）"
                if str(meta.get("status") or "") in {"", "not_found"}:
                    meta["status"] = "extracted"
                meta["confidence"] = max(int(meta.get("confidence") or 0), 55)
        else:
            meta["validityBasis"] = "rule_underived"
            meta["validityNote"] = f"识别为{rule_label}，但未识别到发证日期，无法按标准有效期{years}年推算"
            warning = meta["validityNote"]
            if warning not in warnings:
                warnings.append(warning)

    meta["warnings"] = warnings
    meta["evidence"] = evidence
    return meta


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
        "longTerm": bool(meta.get("longTerm")),
        "certCategory": str(meta.get("certCategory") or ""),
        "certAuthority": str(meta.get("certAuthority") or ""),
        "certGrade": str(meta.get("certGrade") or ""),
        "validityBasis": str(meta.get("validityBasis") or ""),
        "validityNote": str(meta.get("validityNote") or ""),
        "warnings": [str(item) for item in meta.get("warnings") or [] if item] if isinstance(meta.get("warnings"), list) else [],
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


async def run_certificate_time_incremental(
    *,
    bid_type: str,
    limit: int = 0,
    include_failed: bool = True,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
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
        on_progress=on_progress,
    )


def _validate_manual_date(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = _normalize_date(text)
    if normalized and ISO_DATE_RE.match(normalized):
        return normalized
    raise PeripheralError(400, f"{label}格式应为 YYYY-MM-DD。", "CERTIFICATE_DATE_INVALID")


def _ensure_manual_date_order(issue_date: str, expiry_date: str) -> None:
    if issue_date and expiry_date and issue_date > expiry_date:
        raise PeripheralError(400, "发证日期不能晚于有效期至。", "CERTIFICATE_DATE_ORDER")


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

        normalized_issue = _validate_manual_date(issue_date, "发证日期")
        normalized_expiry = _validate_manual_date(expiry_date, "有效期至")
        _ensure_manual_date_order(normalized_issue, normalized_expiry)

        ext = dict(item.ext_fields or {})
        previous = ext.get("certificateMeta") if isinstance(ext.get("certificateMeta"), dict) else {}
        meta = {
            **previous,
            "issueDate": normalized_issue,
            "expiryDate": normalized_expiry,
            "longTerm": bool(previous.get("longTerm")) if not normalized_expiry else False,
            "warnings": [],
            "status": "manual",
            "source": "manual",
            "confidence": 100,
            "validityBasis": "manual",
            "validityNote": "",
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


def _needs_ai_assist(meta: dict[str, Any]) -> bool:
    if meta.get("warnings"):
        return True
    if str(meta.get("status") or "") != "extracted":
        return True
    if not meta.get("issueDate"):
        return True
    if not meta.get("expiryDate") and not meta.get("longTerm"):
        return True
    return int(meta.get("confidence") or 0) < 60


def _parse_ai_certificate_reply(reply: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", str(reply or ""), re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    issue = _normalize_date(str(payload.get("issueDate") or ""))
    expiry = _normalize_date(str(payload.get("expiryDate") or ""))
    long_term = bool(payload.get("longTerm"))
    if issue and expiry and issue > expiry:
        return {}
    if not issue and not expiry and not long_term:
        return {}
    return {
        "issueDate": issue,
        "expiryDate": expiry,
        "longTerm": long_term,
        "reason": str(payload.get("reason") or "").strip()[:200],
    }


def _ai_extract_certificate_time(text: str) -> dict[str, Any]:
    from app.services.opencode_client import OpencodeClient

    snippet = str(text or "").strip()[:CERTIFICATE_AI_TEXT_LIMIT]
    if not snippet:
        return {}
    prompt = (
        "你是证书台账助手。请从下面的证书文本中提取发证日期和有效期截止日期。\n"
        "要求：\n"
        "1. 只输出一个 JSON 对象，不要输出其他内容；\n"
        '2. 格式：{"issueDate": "YYYY-MM-DD", "expiryDate": "YYYY-MM-DD", "longTerm": false, "reason": "一句话依据"}；\n'
        "3. 无法确定的字段用空字符串；证书长期/永久有效时 longTerm 为 true 且 expiryDate 留空；\n"
        "4. expiryDate 只能来自文本中明确的有效期表述（有效期至/截止日期/有效期 N 年/长期有效等）；"
        "文本没有明确写有效期时 expiryDate 必须留空，严禁用文中其他日期猜测；\n"
        "5. 只写“有效期 N 年”时，用发证日期加 N 年减 1 天推算 expiryDate；\n"
        "6. 发证日期必须早于有效期截止日期，不确定时宁可留空。\n"
        f"证书文本：\n{snippet}"
    )
    result = OpencodeClient().send_text_prompt("证书时间识别", prompt)
    return _parse_ai_certificate_reply(str(result.get("reply") or ""))


def _merge_ai_certificate_result(rule_meta: dict[str, Any], ai_meta: dict[str, Any]) -> dict[str, Any]:
    """规则结果优先；AI 只补空缺，或在顺序冲突时用一致的完整结果替换。"""
    merged = dict(rule_meta)
    ai_issue = str(ai_meta.get("issueDate") or "")
    ai_expiry = str(ai_meta.get("expiryDate") or "")
    ai_long_term = bool(ai_meta.get("longTerm"))
    changed = False

    if merged.get("warnings") and ai_issue and (ai_expiry or ai_long_term):
        merged["issueDate"] = ai_issue
        merged["expiryDate"] = ai_expiry
        merged["longTerm"] = ai_long_term
        merged["warnings"] = []
        changed = True
    else:
        if not merged.get("issueDate") and ai_issue:
            merged["issueDate"] = ai_issue
            changed = True
        if not merged.get("expiryDate") and not merged.get("longTerm"):
            if ai_expiry:
                merged["expiryDate"] = ai_expiry
                changed = True
            elif ai_long_term:
                merged["longTerm"] = True
                changed = True

    if not changed:
        return rule_meta
    if merged.get("issueDate") and merged.get("expiryDate") and merged["issueDate"] > merged["expiryDate"]:
        return rule_meta

    merged["status"] = "extracted"
    merged["confidence"] = max(int(merged.get("confidence") or 0), 70)
    evidence = dict(merged.get("evidence") or {})
    if ai_meta.get("reason"):
        evidence["aiReason"] = str(ai_meta["reason"])
    merged["evidence"] = evidence
    merged["aiAssisted"] = True
    return merged


async def run_certificate_time_batch(
    *,
    bid_type: str,
    folder_path: str = "",
    file_ids: list[str] | None = None,
    limit: int = 0,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    items = await _load_raw_files(bid_type=bid_type, folder_path=folder_path, file_ids=file_ids)
    # limit <= 0 表示处理全部待识别文件；limit > 0 时按顺序截取（如单文件重识别传 1）
    limit = int(limit or 0)
    selected = items if limit <= 0 else items[:limit]
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
            # 先按《证书报告有效期确认》规则表完善有效期识别与判断
            extracted = apply_certificate_validity_rules(
                extracted,
                text=text,
                file_name=item.name,
                folder_path=item.folder.path if item.folder else "",
            )
            source = str(source_info.get("source") or "")
            # 跟随整机型式证的报告不单独识别有效期，跳过 AI 兜底以免猜出日期
            if (
                _needs_ai_assist(extracted)
                and text.strip()
                and str(extracted.get("validityBasis") or "") != "follow_turbine"
            ):
                try:
                    ai_result = await asyncio.to_thread(_ai_extract_certificate_time, text)
                except Exception as ai_exc:  # noqa: BLE001 - AI 兜底失败时保留规则结果
                    logger.warning("certificate ai assist failed for %s: %s", raw_id, ai_exc)
                    ai_result = {}
                if ai_result:
                    merged = _merge_ai_certificate_result(extracted, ai_result)
                    if merged is not extracted:
                        extracted = merged
                        source = f"{source}+ai" if source else "ai"
            meta = {
                **extracted,
                "source": source,
                "pageCount": source_info.get("pageCount") or 0,
                "updatedAt": now_iso(),
                "errorMessage": "",
            }
        except Exception as exc:
            meta = {
                "issueDate": "",
                "expiryDate": "",
                "longTerm": False,
                "warnings": [],
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
        if on_progress is not None:
            on_progress({
                "processed": len(rows),
                "total": len(selected),
                "failed": sum(1 for row in rows if row.get("status") in {"failed", "unsupported"}),
                "currentFile": item.name,
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
