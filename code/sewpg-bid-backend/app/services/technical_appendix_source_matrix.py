from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.core.config import settings


PROJECT_SOURCE_KEYWORDS = ("project", "项目", "项目定制")
STANDARD_SOURCE_KEYWORDS = ("standard", "标准", "标准文件", "通用")
OTHER_SOURCE_KEYWORDS = ("other", "其他", "说明")
SOURCE_MATRIX_ENV = "TECHNICAL_APPENDIX_SOURCE_MATRIX_PATH"
DEFAULT_SOURCE_MATRIX_FILE_NAME = "technical_appendix_source_matrix.xlsx"
APPENDIX_CODE_RE = re.compile(
    r"附表\s*([A-Za-z]?\s*\.?\s*\d+(?:\.\d+)*)(?:\s*[-—~～至到]\s*([A-Za-z]?\s*\.?\s*\d+(?:\.\d+)*))?",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return re.sub(r"\s+", " ", str(value).replace("\n", " / ")).strip()


def normalize_match_text(value: Any) -> str:
    return re.sub(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|]+", "", clean_text(value).lower())


def normalize_appendix_code(value: Any) -> str:
    text = clean_text(value).upper()
    return re.sub(r"\s+", "", text).lstrip(".")


def appendix_code(value: Any) -> str:
    match = APPENDIX_CODE_RE.search(clean_text(value))
    return normalize_appendix_code(match.group(1)) if match else ""


def _appendix_code_parts(value: Any) -> tuple[str, tuple[int, ...]] | None:
    code = normalize_appendix_code(value)
    match = re.fullmatch(r"([A-Z]+)?\.?([0-9]+(?:\.[0-9]+)*)", code)
    if not match:
        return None
    prefix = match.group(1) or ""
    numbers = tuple(int(part) for part in match.group(2).split("."))
    return prefix, numbers


def appendix_rule_code_score(table_title: Any, rule_title: Any) -> float:
    table_code = appendix_code(table_title)
    if not table_code:
        return 0.0
    rule_match = APPENDIX_CODE_RE.search(clean_text(rule_title))
    if not rule_match:
        return 0.0
    start_code = normalize_appendix_code(rule_match.group(1))
    end_code = normalize_appendix_code(rule_match.group(2) or "")
    if not end_code:
        return 0.96 if table_code == start_code else 0.0

    table_parts = _appendix_code_parts(table_code)
    start_parts = _appendix_code_parts(start_code)
    end_parts = _appendix_code_parts(end_code)
    if not table_parts or not start_parts or not end_parts:
        return 0.0
    table_prefix, table_numbers = table_parts
    start_prefix, start_numbers = start_parts
    end_prefix, end_numbers = end_parts
    if not end_prefix:
        end_prefix = start_prefix
    if table_prefix and start_prefix and table_prefix != start_prefix:
        return 0.0
    if table_prefix and end_prefix and table_prefix != end_prefix:
        return 0.0
    if start_numbers <= table_numbers <= end_numbers:
        return 0.94
    return 0.0


def source_terms(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = re.split(r"[&＆,，、;；/／\n]+", text)
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = clean_text(part).strip(" ：:")
        if not item or item in seen:
            continue
        seen.add(item)
        terms.append(item)
    return terms


def _header_kind(value: Any) -> str:
    text = normalize_match_text(value)
    if not text:
        return ""
    if "客户" in text:
        return "customer"
    if "表格" in text or "附表" in text:
        return "table"
    if any(normalize_match_text(keyword) in text for keyword in PROJECT_SOURCE_KEYWORDS):
        return "project"
    if any(normalize_match_text(keyword) in text for keyword in STANDARD_SOURCE_KEYWORDS):
        return "standard"
    if any(normalize_match_text(keyword) in text for keyword in OTHER_SOURCE_KEYWORDS):
        return "other"
    return ""


def _detect_header(values: list[list[Any]]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(values[:12]):
        mapping: dict[str, int] = {}
        for col, value in enumerate(row):
            kind = _header_kind(value)
            if kind and kind not in mapping:
                mapping[kind] = col
        if "customer" in mapping and "table" in mapping:
            return index, mapping
    return -1, {}


def parse_appendix_source_matrix(path: Path | str) -> dict[str, Any]:
    matrix_path = Path(path).expanduser()
    if not matrix_path.exists() or matrix_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return {"schemaVersion": "technical-appendix-source-matrix-v1", "path": str(matrix_path), "rows": []}

    wb = load_workbook(matrix_path, data_only=True, read_only=True)
    rows: list[dict[str, Any]] = []
    for ws in wb.worksheets:
        values = [list(row) for row in ws.iter_rows(values_only=True)]
        header_index, mapping = _detect_header(values)
        if header_index < 0:
            continue
        for row_number, row in enumerate(values[header_index + 1 :], start=header_index + 2):
            def cell(kind: str) -> str:
                col = mapping.get(kind)
                return clean_text(row[col]) if col is not None and col < len(row) else ""

            customer = cell("customer")
            table_title = cell("table")
            if not customer or not table_title:
                continue
            project_sources = source_terms(cell("project"))
            standard_sources = source_terms(cell("standard"))
            other_sources = source_terms(cell("other"))
            if not project_sources and not standard_sources and not other_sources:
                continue
            rows.append(
                {
                    "id": f"{ws.title}!R{row_number}",
                    "sheet": ws.title,
                    "row": row_number,
                    "customer": customer,
                    "tableTitle": table_title,
                    "projectSources": project_sources,
                    "standardSources": standard_sources,
                    "otherSources": other_sources,
                }
            )

    return {
        "schemaVersion": "technical-appendix-source-matrix-v1",
        "path": str(matrix_path),
        "rows": rows,
    }


def resolve_appendix_source_matrix_path(project: dict[str, Any]) -> str:
    candidates = [
        project.get("technicalAppendixSourceMatrixPath"),
        project.get("appendixSourceMatrixPath"),
        (project.get("technicalAppendixSourceMatrix") or {}).get("path")
        if isinstance(project.get("technicalAppendixSourceMatrix"), dict)
        else "",
        os.getenv(SOURCE_MATRIX_ENV),
        settings.documents_dir / "_config" / DEFAULT_SOURCE_MATRIX_FILE_NAME,
    ]
    for candidate in candidates:
        text = clean_text(candidate)
        if not text:
            continue
        path = Path(text).expanduser()
        if path.exists() and path.is_file():
            return str(path)
    return ""


def load_appendix_source_matrix_for_project(project: dict[str, Any]) -> dict[str, Any]:
    path = resolve_appendix_source_matrix_path(project)
    if not path:
        return {"schemaVersion": "technical-appendix-source-matrix-v1", "path": "", "rows": []}
    return parse_appendix_source_matrix(path)


def table_title_match_score(left: Any, right: Any) -> float:
    code_score = appendix_rule_code_score(left, right)
    if code_score:
        return code_score
    left_norm = normalize_match_text(left)
    right_norm = normalize_match_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.88
    shared = len(set(left_norm) & set(right_norm))
    total = len(set(left_norm) | set(right_norm))
    return shared / total if total else 0.0


def customer_match_score(project_customer: Any, rule_customer: Any) -> float:
    project_norm = normalize_match_text(project_customer)
    rule_norm = normalize_match_text(rule_customer)
    if not project_norm or not rule_norm:
        return 0.0
    if project_norm == rule_norm:
        return 1.0
    if project_norm in rule_norm or rule_norm in project_norm:
        return 0.9
    return 0.0


def find_appendix_source_rule(
    matrix: dict[str, Any],
    *,
    customer_name: Any,
    table_title: Any,
) -> dict[str, Any]:
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        table_score = table_title_match_score(table_title, row.get("tableTitle"))
        if table_score < 0.82:
            continue
        customer_score = customer_match_score(customer_name, row.get("customer"))
        if customer_name and customer_score <= 0:
            continue
        score = table_score * 10 + customer_score * 3
        if best is None or score > best[0]:
            best = (score, row)
    if best is None:
        return {}
    return dict(best[1])
