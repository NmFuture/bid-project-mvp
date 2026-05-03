from __future__ import annotations

import json
import copy
import asyncio
import mimetypes
import re
import shutil
import sys
import threading
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from docx import Document

from app.core.config import settings
from app.services.ocr_service import IMAGE_SUFFIXES, ocr_service
from app.services.opencode_client import OpencodeClient
from app.services.peripheral import PeripheralError

PARSE_SKILL_NAME = "bid-tender-structured-parser"
PARSER_CORE_DIR = Path(__file__).resolve().parents[2] / "opencode" / "skill" / PARSE_SKILL_NAME / "scripts"
if str(PARSER_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_CORE_DIR))

from parser_core import parse_documents as parse_structured_documents  # noqa: E402

WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_PREVIEW_LIMIT = 600


@dataclass(frozen=True)
class ParseCategory:
    key: str
    label: str
    keywords: tuple[str, ...]


PARSE_CATEGORIES: tuple[ParseCategory, ...] = (
    ParseCategory("scoring_criteria", "评分细则", ("评分", "得分", "分值", "证明材料", "商务评分", "技术评分")),
    ParseCategory(
        "project_basics",
        "项目基础信息",
        (
            "项目名称",
            "招标编号",
            "项目编号",
            "招标人",
            "管理单位",
            "建设单位",
            "业主",
            "标段规模",
            "招标规模",
            "建设规模",
            "交货周期",
            "交货期",
            "质保期",
            "质量保证期",
            "技术承诺",
            "起始日期",
            "开工日期",
            "截止日期",
            "截止时间",
            "结束日期",
        ),
    ),
    ParseCategory(
        "turbine_parameters",
        "风机核心参数",
        (
            "单机容量",
            "叶轮直径",
            "轮毂高度",
            "叶片最低点",
            "塔筒型式",
            "箱变型式",
            "安全等级",
            "空气密度",
            "风速",
            "湍流强度",
        ),
    ),
    ParseCategory(
        "performance_guarantees",
        "性能保证指标",
        ("功率曲线", "可利用率", "发电量", "涉网性能", "保证率", "性能保证"),
    ),
    ParseCategory(
        "environment_adaptation",
        "环境适应性要求",
        ("低温", "覆冰", "防凝露", "潮湿", "防雷暴", "防雷", "风沙", "高温", "环境适应性"),
    ),
    ParseCategory(
        "topic_plans",
        "专题方案要求",
        ("专题方案", "叶片", "变桨系统", "主轴", "齿轮箱", "总体方案", "技术先进性"),
    ),
    ParseCategory("tables_and_scope", "附表和供货范围", ("附表", "供货范围", "供货清单", "供货界面")),
    ParseCategory(
        "assessment_terms",
        "考核条款",
        ("考核", "发电量考核", "可利用率考核", "功率曲线考核", "部件考核", "认证考核"),
    ),
)

DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?"
)
LABEL_VALUE_PATTERN = re.compile(r"^\s*(?P<label>[^:：]{2,40})\s*[:：]\s*(?P<value>.+?)\s*$")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[（(]?\d+[）)]?)\s*[、.．\s]+")

START_DATE_KEYWORDS = ("起始日期", "开始日期", "开工日期", "计划开工", "服务期自", "合同开始")
END_DATE_KEYWORDS = ("投标截止", "截止日期", "截止时间", "结束日期", "竣工日期", "完成日期", "服务期至")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    aliases: tuple[str, ...]


PROJECT_BASIC_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("projectName", "项目名称", ("项目名称",)),
    FieldSpec("tenderNo", "招标编号", ("招标编号", "项目编号")),
    FieldSpec("tenderer", "招标人", ("招标人", "业主", "建设单位")),
    FieldSpec("managementUnit", "管理单位", ("管理单位",)),
    FieldSpec("bidSectionScale", "标段规模", ("标段规模", "招标规模", "建设规模")),
    FieldSpec("deliveryPeriod", "交货周期", ("交货周期", "交货期")),
    FieldSpec("warrantyPeriod", "质保期", ("质保期", "质量保证期")),
    FieldSpec("technicalCommitment", "技术承诺", ("技术承诺",)),
)

TURBINE_CORE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("singleCapacity", "单机容量", ("单机容量",)),
    FieldSpec("rotorDiameter", "叶轮直径", ("叶轮直径",)),
    FieldSpec("hubHeight", "轮毂高度", ("轮毂高度",)),
    FieldSpec("bladeTipClearance", "叶片最低点距地", ("叶片最低点距地", "叶片最低点")),
    FieldSpec("towerType", "塔筒型式", ("塔筒型式",)),
    FieldSpec("boxTransformerType", "箱变型式", ("箱变型式",)),
    FieldSpec("safetyClass", "安全等级", ("安全等级",)),
    FieldSpec("airDensity", "空气密度", ("空气密度",)),
    FieldSpec("windSpeed", "风速", ("风速",)),
    FieldSpec("turbulenceIntensity", "湍流强度", ("湍流强度",)),
)

PERFORMANCE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("powerCurve", "功率曲线", ("功率曲线",)),
    FieldSpec("availability", "可利用率", ("可利用率",)),
    FieldSpec("generation", "发电量", ("发电量", "上网电量")),
    FieldSpec("gridPerformance", "涉网性能", ("涉网性能", "高低电压穿越", "电压穿越")),
)

ENVIRONMENT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("lowTemperature", "抗低温", ("抗低温", "低温")),
    FieldSpec("icingCondensation", "抗覆冰防凝露", ("抗覆冰", "覆冰", "防凝露")),
    FieldSpec("humidity", "防潮湿", ("防潮湿", "潮湿")),
    FieldSpec("lightning", "防雷暴", ("防雷暴", "防雷")),
    FieldSpec("sandstorm", "防风沙", ("防风沙", "风沙")),
    FieldSpec("highTemperature", "抗高温", ("抗高温", "高温")),
)

SCORING_SCORE_PATTERN = re.compile(r"(?P<item>[\u4e00-\u9fa5A-Za-z0-9（）()、/]+?)\s*(?P<score>\d+(?:\.\d+)?\s*分)")
MARKDOWN_TABLE_LINE_PATTERN = re.compile(r"^\s*\|.*\|\s*$")


def parsed_project_dir(project_id: str) -> Path:
    path = settings.parsed_dir / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def parsed_appendix_dir(project_id: str) -> Path:
    path = settings.parsed_dir / project_id / "s1_appendices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parsed_appendix_path(project_id: str) -> Path:
    return settings.parsed_dir / project_id / "s1_appendices"


def _normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        compact.append(line)
        previous_blank = blank
    return "\n".join(compact).strip()


def extract_docx_text(path: Path) -> str:
    pieces: list[str] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as xml_file:
            for _, element in ET.iterparse(xml_file, events=("end",)):
                if element.tag == f"{WORD_NAMESPACE}t":
                    pieces.append(element.text or "")
                elif element.tag == f"{WORD_NAMESPACE}tab":
                    pieces.append("\t")
                elif element.tag in {f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"}:
                    pieces.append("\n")
                elif element.tag == f"{WORD_NAMESPACE}p":
                    pieces.append("\n")
                    element.clear()
    return _normalize_text("".join(pieces))


def extract_pdf_text(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("未安装 pypdf，当前无法解析 PDF。") from exc

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    empty_pages = 0
    page_texts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            empty_pages += 1
        page_texts.append(text)

    warnings: list[str] = []
    if page_count and empty_pages == page_count:
        warnings.append("PDF 未提取到文本，疑似扫描件，已进入 OCR 兜底识别。")
    elif empty_pages:
        warnings.append(f"PDF 有 {empty_pages} 页未提取到文本。")

    return _normalize_text("\n\n".join(page_texts)), {
        "pageCount": page_count,
        "warnings": warnings,
        "requiresOcr": bool(page_count and empty_pages == page_count),
    }


def _run_async_ocr(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Any = None
    error: BaseException | None = None

    def run() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error = exc

    thread = threading.Thread(target=run, daemon=True, name="parse-visual-recognition")
    thread.start()
    thread.join()
    if error:
        raise error
    return result


def _ocr_fallback_text(project_id: str, file_record: dict[str, Any], file_path: Path) -> tuple[str, dict[str, Any]]:
    _ = project_id
    try:
        text, raw = _run_async_ocr(
            ocr_service.recognize_text_for_parse(
                file_name=str(file_record.get("name") or file_path.name),
                content=file_path.read_bytes(),
                mime_type=str(file_record.get("content_type") or mimetypes.guess_type(file_path.name)[0] or ""),
            )
        )
        return _normalize_text(text), {
            "status": "completed",
            "pageCount": raw.get("pageCount") or "-",
        }
    except PeripheralError as exc:
        return "", {
            "status": "failed",
            "code": exc.code,
            "message": exc.detail,
        }
    except Exception as exc:
        return "", {
            "status": "failed",
            "code": "OCR_PARSE_FALLBACK_FAILED",
            "message": str(exc),
        }


def _normalize_date_match(match: re.Match[str]) -> str:
    try:
        parsed = date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return ""
    return parsed.isoformat()


def _find_dates(text: str) -> list[str]:
    dates: list[str] = []
    for match in DATE_PATTERN.finditer(text):
        normalized = _normalize_date_match(match)
        if normalized:
            dates.append(normalized)
    return dates


def _strip_leading_number(text: str) -> str:
    return LEADING_NUMBER_PATTERN.sub("", text).strip()


def _split_label_value(line: str, fallback_label: str) -> tuple[str, str]:
    normalized = _strip_leading_number(line)
    match = LABEL_VALUE_PATTERN.match(normalized)
    if match:
        label = _strip_leading_number(match.group("label")).strip()
        value = match.group("value").strip(" ；;。")
        return label or fallback_label, value or normalized
    return fallback_label, normalized


def _first_matching_category(line: str) -> ParseCategory | None:
    if "考核" in line:
        return next(category for category in PARSE_CATEGORIES if category.key == "assessment_terms")
    for category in PARSE_CATEGORIES:
        if any(keyword in line for keyword in category.keywords):
            return category
    return None


def _record_project_date(line: str, dates: list[str], project_dates: dict[str, str]) -> None:
    if not dates:
        return
    has_start_keyword = any(keyword in line for keyword in START_DATE_KEYWORDS)
    has_end_keyword = any(keyword in line for keyword in END_DATE_KEYWORDS)
    has_range_hint = any(token in line for token in ("至", "到", "止", "~", "—", "-"))

    if has_start_keyword and not project_dates["startDate"]:
        project_dates["startDate"] = dates[0]
    if has_end_keyword and not project_dates["endDate"]:
        project_dates["endDate"] = dates[-1]
    if has_range_hint and len(dates) >= 2:
        if not project_dates["startDate"]:
            project_dates["startDate"] = dates[0]
        if not project_dates["endDate"]:
            project_dates["endDate"] = dates[-1]


def _empty_field(spec: FieldSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": "",
        "status": "missing",
        "sourceFile": "",
        "evidence": "",
        "evidenceLocation": "",
    }


def _field_from_item(spec: FieldSpec, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": str(item.get("value") or item.get("keyValue") or "").strip(),
        "status": "found",
        "sourceFile": str(item.get("sourceFile") or ""),
        "evidence": str(item.get("evidence") or ""),
        "evidenceLocation": str(item.get("evidenceLocation") or ""),
    }


def _build_fixed_field_group(items: list[dict[str, Any]], specs: tuple[FieldSpec, ...]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for spec in specs:
        matched = next(
            (
                item
                for item in items
                if any(alias in str(item.get("keyEntity") or item.get("title") or item.get("evidence") or "") for alias in spec.aliases)
            ),
            None,
        )
        fields.append(_field_from_item(spec, matched) if matched else _empty_field(spec))
    return fields


def _build_scoring_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scoring_items = [item for item in items if item.get("category") == "scoring_criteria"]
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(scoring_items, start=1):
        evidence = str(item.get("evidence") or item.get("value") or "")
        matches = list(SCORING_SCORE_PATTERN.finditer(evidence))
        if matches:
            for match_index, match in enumerate(matches, start=1):
                next_match = matches[match_index] if match_index < len(matches) else None
                segment = evidence[match.start() : next_match.start() if next_match else len(evidence)]
                segment = segment.strip(" ；;。")
                proof_requirement = segment if any(keyword in segment for keyword in ("证明", "材料", "提供")) else ""
                rows.append(
                    {
                        "id": f"{item.get('id') or f'SCORE-{index}'}-{match_index}",
                        "scoringItem": match.group("item").strip(" ，,：:；;"),
                        "score": match.group("score").replace(" ", ""),
                        "scorePoint": segment or str(item.get("value") or evidence),
                        "proofRequirement": proof_requirement,
                        "sourceFile": item.get("sourceFile") or "",
                        "evidence": evidence,
                        "evidenceLocation": item.get("evidenceLocation") or "",
                    }
                )
            continue

        scoring_item = str(item.get("keyEntity") or item.get("title") or f"评分项{index}")
        proof_requirement = evidence if "证明" in evidence or "材料" in evidence else ""
        rows.append(
            {
                "id": item.get("id") or f"SCORE-{index}",
                "scoringItem": scoring_item,
                "score": "",
                "scorePoint": str(item.get("value") or evidence),
                "proofRequirement": proof_requirement,
                "sourceFile": item.get("sourceFile") or "",
                "evidence": evidence,
                "evidenceLocation": item.get("evidenceLocation") or "",
            }
        )
    return rows


def _presence_from_items(
    items: list[dict[str, Any]],
    category: str,
    *,
    keywords: tuple[str, ...] = (),
) -> dict[str, Any]:
    matched = [item for item in items if item.get("category") == category]
    if keywords:
        matched = [
            item
            for item in matched
            if any(
                keyword in str(item.get("title") or item.get("value") or item.get("evidence") or "")
                for keyword in keywords
            )
        ]
    if not matched:
        return {
            "status": "missing",
            "summary": "招标文件中暂未识别到明确要求。",
            "evidences": [],
        }
    evidences = [
        {
            "sourceFile": item.get("sourceFile") or "",
            "evidence": item.get("evidence") or item.get("value") or "",
            "evidenceLocation": item.get("evidenceLocation") or "",
        }
        for item in matched[:5]
    ]
    summary_parts = [str(item.get("value") or item.get("evidence") or "").strip() for item in matched]
    return {
        "status": "present",
        "summary": "；".join(part for part in summary_parts if part)[:500],
        "evidences": evidences,
    }


def _build_requirement_presence(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "topicPlans": _presence_from_items(items, "topic_plans"),
        "supplyScope": _presence_from_items(
            items,
            "tables_and_scope",
            keywords=("供货范围", "供货清单", "供货界面", "供货"),
        ),
        "assessmentTerms": _presence_from_items(items, "assessment_terms"),
    }


def _build_field_groups(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "scoringCriteria": _build_scoring_fields(items),
        "projectBasics": _build_fixed_field_group(items, PROJECT_BASIC_FIELDS),
        "turbineCoreParameters": _build_fixed_field_group(items, TURBINE_CORE_FIELDS),
        "performanceGuarantees": _build_fixed_field_group(items, PERFORMANCE_FIELDS),
        "environmentAdaptation": _build_fixed_field_group(items, ENVIRONMENT_FIELDS),
    }


def _sanitize_docx_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    while len(cleaned.encode("utf-8")) > 120:
        cleaned = cleaned[:-1].strip(" .")
    return cleaned or fallback


def _parse_markdown_table_row(line: str) -> list[str]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return cells


def _is_markdown_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _write_appendix_docx(path: Path, title: str, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading(title, level=1)
    if rows:
        column_count = max(len(row) for row in rows)
        table = doc.add_table(rows=len(rows), cols=column_count)
        table.style = "Table Grid"
        for row_index, row in enumerate(rows):
            for col_index in range(column_count):
                table.cell(row_index, col_index).text = row[col_index] if col_index < len(row) else ""
    doc.save(path)


def _appendix_output_dir(project_id: str) -> Path:
    return parsed_appendix_path(project_id)


def _workspace_appendix_output_dir(project_id: str) -> Path:
    return settings.documents_dir / project_id / "technical-workspace" / "appendices"


def _appendix_asset_path(project_id: str, appendix_id: str, title: str) -> tuple[Path, str]:
    file_name = f"{appendix_id}-{_sanitize_docx_name(title, '附表')}.docx"
    return _appendix_output_dir(project_id) / file_name, f"s1_appendices/{file_name}"


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def materialize_appendix_docx(project_id: str, appendix: dict[str, Any]) -> dict[str, Any]:
    """Ensure an appendix entry has a generated Word asset, even when no template table was found."""

    item = copy.deepcopy(appendix)
    appendix_id = str(item.get("id") or "").strip() or "APPX-0000"
    title = str(item.get("title") or item.get("evidence") or "附表").strip() or "附表"
    rows = item.get("rows") if isinstance(item.get("rows"), list) else []
    output_dir = _appendix_output_dir(project_id)
    workspace_output_dir = _workspace_appendix_output_dir(project_id)

    existing_path = Path(str(item.get("docxPath") or ""))
    if not existing_path.is_absolute():
        existing_path = Path()
    existing_path_allowed = (
        bool(existing_path)
        and (
            _path_is_inside(existing_path, output_dir)
            or _path_is_inside(existing_path, workspace_output_dir)
        )
    )
    if not existing_path_allowed:
        existing_path, workspace_path = _appendix_asset_path(project_id, appendix_id, title)
    else:
        workspace_path = str(item.get("workspacePath") or f"technical-workspace/appendices/{existing_path.name}")

    if not existing_path.exists():
        _write_appendix_docx(existing_path, title, rows)

    item.update(
        {
            "id": appendix_id,
            "title": title,
            "status": "generated",
            "rows": rows,
            "rowCount": len(rows),
            "docxPath": str(existing_path),
            "workspacePath": workspace_path,
        }
    )
    return item


def _appendix_title_for_match(value: str) -> str:
    title = str(value or "").strip().lstrip("#").strip()
    return re.sub(r"\s+", " ", title)


def _appendix_row_count(item: dict[str, Any]) -> int:
    row_count = item.get("rowCount")
    if isinstance(row_count, int):
        return row_count
    rows = item.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def _is_toc_page_number_appendix(item: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    if _appendix_row_count(item) > 0:
        return False

    title = _appendix_title_for_match(str(item.get("title") or item.get("evidence") or ""))
    if not re.search(r"\d{1,4}$", title):
        return False

    for candidate in candidates:
        if candidate is item:
            continue
        candidate_title = _appendix_title_for_match(str(candidate.get("title") or candidate.get("evidence") or ""))
        if not candidate_title or candidate_title == title or not title.startswith(candidate_title):
            continue

        suffix = title[len(candidate_title):]
        if not re.fullmatch(r"\d{1,4}", suffix):
            continue
        if len(suffix) == 1 and re.search(r"[\w.]$", candidate_title):
            continue
        return True

    return False


def _dedupe_appendix_page_number_artifacts(appendices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in appendices
        if isinstance(item, dict) and _is_appendix_heading(str(item.get("title") or item.get("evidence") or ""))
    ]
    return [item for item in candidates if not _is_toc_page_number_appendix(item, candidates)]


def _prepare_appendix_outputs(
    project_id: str,
    appendices: list[dict[str, Any]],
    *,
    renumber: bool,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, appendix in enumerate(_dedupe_appendix_page_number_artifacts(appendices), start=1):
        item = copy.deepcopy(appendix)
        if renumber:
            item["id"] = f"APPX-{index:04d}"
            item["docxPath"] = ""
            item.pop("workspacePath", None)
        prepared.append(materialize_appendix_docx(project_id, item))
    return prepared


def materialize_parse_appendix_docx_assets(project_id: str, parse_result: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(parse_result)
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return payload
    appendices = structured.get("appendices")
    if not isinstance(appendices, list):
        return payload
    structured["appendices"] = _prepare_appendix_outputs(project_id, appendices, renumber=False)
    return payload


def _is_appendix_heading(text: str) -> bool:
    normalized = str(text or "").strip().lstrip("#").strip()
    return bool(re.match(r"^(?:技术)?[附副]表(?:\s*[A-Za-z0-9一二三四五六七八九十]+)?(?:[：:、.．\s]|$)", normalized))


def _is_scoring_appendix_heading(text: str) -> bool:
    return any(keyword in text for keyword in ("评分标准", "评分细则", "评标办法", "符合性审查", "投标报价评分", "度电成本评分"))


def _appendix_title_has_trailing_page_number(text: str) -> bool:
    title = _appendix_title_for_match(text)
    return bool(re.search(r"\D\d{2,4}$", title))


def _is_docx_appendix_toc_artifact(blocks: list[dict[str, Any]], index: int) -> bool:
    line = str(blocks[index].get("text") or "").strip()
    if not _appendix_title_has_trailing_page_number(line):
        return False

    for lookahead in range(index + 1, min(len(blocks), index + 8)):
        next_block = blocks[lookahead]
        if next_block.get("type") == "table":
            return False
        if next_block.get("type") == "paragraph" and _is_appendix_heading(str(next_block.get("text") or "")):
            break

    nearby_headings = 0
    for nearby in range(max(0, index - 3), min(len(blocks), index + 4)):
        if nearby == index:
            continue
        block = blocks[nearby]
        if block.get("type") == "paragraph" and _is_appendix_heading(str(block.get("text") or "")):
            nearby_headings += 1

    return nearby_headings >= 1


def _extract_markdown_appendices(
    project_id: str,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    *,
    start_index: int = 0,
) -> list[dict[str, Any]]:
    appendices: list[dict[str, Any]] = []
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".md":
            continue
        lines = texts_by_id.get(document_id, "").splitlines()
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if not _is_appendix_heading(line):
                index += 1
                continue
            if _is_scoring_appendix_heading(line):
                index += 1
                continue

            title = line.strip(" #")
            table_start = index + 1
            while table_start < len(lines) and not MARKDOWN_TABLE_LINE_PATTERN.match(lines[table_start]):
                if lines[table_start].strip() and not _is_appendix_heading(lines[table_start]):
                    break
                table_start += 1
            if table_start >= len(lines) or not MARKDOWN_TABLE_LINE_PATTERN.match(lines[table_start]):
                appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
                appendices.append(materialize_appendix_docx(
                    project_id,
                    {
                        "id": appendix_id,
                        "title": title,
                        "status": "generated",
                        "sourceFile": source_file,
                        "evidence": line,
                        "evidenceLocation": f"L{index + 1}",
                        "rows": [],
                        "rowCount": 0,
                        "docxPath": "",
                    }
                ))
                index += 1
                continue

            rows: list[list[str]] = []
            table_end = table_start
            while table_end < len(lines) and MARKDOWN_TABLE_LINE_PATTERN.match(lines[table_end]):
                cells = _parse_markdown_table_row(lines[table_end])
                if not _is_markdown_separator_row(cells):
                    rows.append(cells)
                table_end += 1

            appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
            appendices.append(materialize_appendix_docx(
                project_id,
                {
                    "id": appendix_id,
                    "title": title,
                    "status": "generated",
                    "sourceFile": source_file,
                    "evidence": line,
                    "evidenceLocation": f"L{index + 1}",
                    "rows": rows,
                    "rowCount": len(rows),
                    "docxPath": "",
                }
            ))
            index = table_end
    return appendices


def _docx_paragraph_text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(f"{WORD_NAMESPACE}t")).strip()


def _docx_table_rows(table: Any) -> list[list[str]]:
    return [[cell.text.strip() for cell in row.cells] for row in table.rows]


def _iter_docx_blocks(path: Path) -> list[dict[str, Any]]:
    doc = Document(str(path))
    tables = iter(doc.tables)
    blocks: list[dict[str, Any]] = []
    for child in doc.element.body.iterchildren():
        if child.tag == f"{WORD_NAMESPACE}p":
            blocks.append({"type": "paragraph", "text": _docx_paragraph_text(child)})
        elif child.tag == f"{WORD_NAMESPACE}tbl":
            table = next(tables, None)
            if table is not None:
                blocks.append({"type": "table", "rows": _docx_table_rows(table)})
    return blocks


def _extract_docx_appendices(
    project_id: str,
    documents: list[dict[str, Any]],
    *,
    start_index: int = 0,
) -> list[dict[str, Any]]:
    appendices: list[dict[str, Any]] = []
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".docx" or not source_path.exists():
            continue

        source_file = str(document.get("name") or source_path.name or "招标文件")
        blocks = _iter_docx_blocks(source_path)
        used_tables: set[int] = set()
        for index, block in enumerate(blocks):
            if block.get("type") != "paragraph":
                continue
            line = str(block.get("text") or "").strip()
            if not _is_appendix_heading(line):
                continue
            if _is_scoring_appendix_heading(line):
                continue
            if _is_docx_appendix_toc_artifact(blocks, index):
                continue

            title = line.strip(" #") or "附表"
            table_index = -1
            rows: list[list[str]] = []
            for lookahead in range(index + 1, min(len(blocks), index + 8)):
                next_block = blocks[lookahead]
                if next_block.get("type") == "paragraph" and _is_appendix_heading(str(next_block.get("text") or "")):
                    break
                if next_block.get("type") == "table" and lookahead not in used_tables:
                    table_index = lookahead
                    rows = next_block.get("rows") or []
                    break

            appendix_id = f"APPX-{start_index + len(appendices) + 1:04d}"
            if table_index == -1 or not rows:
                appendices.append(materialize_appendix_docx(
                    project_id,
                    {
                        "id": appendix_id,
                        "title": title,
                        "status": "generated",
                        "sourceFile": source_file,
                        "evidence": line,
                        "evidenceLocation": f"B{index + 1}",
                        "rows": [],
                        "rowCount": 0,
                        "docxPath": "",
                    }
                ))
                continue

            used_tables.add(table_index)
            appendices.append(materialize_appendix_docx(
                project_id,
                {
                    "id": appendix_id,
                    "title": title,
                    "status": "generated",
                    "sourceFile": source_file,
                    "evidence": line,
                    "evidenceLocation": f"B{index + 1}",
                    "rows": rows,
                    "rowCount": len(rows),
                    "docxPath": "",
                }
            ))
    return appendices


def _extract_structured_requirements(documents: list[dict[str, Any]], texts_by_id: dict[str, str]) -> dict[str, Any]:
    return parse_structured_documents(
        documents,
        texts_by_id,
        mode="local-structured-parser",
    )


def _build_tender_parse_prompt(skill_manifest_path: Path) -> str:
    return f"""
Use the {PARSE_SKILL_NAME} skill.

你现在在做 S1 招标文件结构化解析。请调用解析 Skill 读取 manifest 中的多份招标文件文本，输出可直接给后端使用的结构化 JSON。

manifest：{skill_manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 600000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整结构化 JSON 写入 manifest.structuredResultPath，并只在 stdout 打印小型摘要 JSON：

s1parse {skill_manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schemaVersion": "bid-tender-structured-v1",
  "targetSkill": "{PARSE_SKILL_NAME}",
  "outputFile": "manifest 中的 structuredResultPath",
  "summary": {{"itemCount": 0, "categoryCounts": {{}}, "scoringCounts": {{"technical": 0, "business": 0, "price": 0, "lcoe": 0, "compliance": 0}}, "projectDates": {{"startDate": "", "endDate": ""}}}}
}}

解析目标必须覆盖：
1. 评分细则：评分项、得分点、证明材料要求。
2. 项目基础信息：项目名称、招标编号、招标人/管理单位、规模、交货周期、质保期、技术承诺。
3. 风机核心参数：单机容量、叶轮直径、轮毂高度、叶片最低点距地、塔筒型式、箱变型式、安全等级、空气密度、风速、湍流强度。
4. 性能保证指标：功率曲线、可利用率、发电量、涉网性能。
5. 环境适应性要求：低温、覆冰防凝露、潮湿、防雷暴、防风沙、高温。
6. 专题方案要求：叶片、变桨系统、主轴、齿轮箱等专题。
7. 附表、供货范围和考核条款。
8. 投标相关日期：招标文件获取/报名起始日期、投标文件递交截止日期或开标日期。不要把交货、供货、服务期、工期、竣工、安装调试等履约日期写入 projectDates。

完整 JSON 必须包含 structured.sourceDocuments、structured.scoringCriteria、structured.fieldGroups、structured.requirementPresence、structured.coverage。每条 item、评分行和字段必须保留 sourceFile、sourceDocumentId、section、evidence、evidenceLocation。
""".strip()


def _resolve_skill_structured_result(
    result: dict[str, Any],
    *,
    local_result: dict[str, Any],
) -> dict[str, Any]:
    output_file = Path(str(result.get("outputFile") or ""))
    if output_file.exists():
        loaded = json.loads(output_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
            resolved = loaded
        else:
            resolved = local_result
    elif isinstance(result.get("items"), list):
        resolved = {
            "items": result.get("items") or [],
            "structured": result.get("structured") if isinstance(result.get("structured"), dict) else {},
        }
    else:
        resolved = local_result

    structured = resolved.setdefault("structured", {})
    if isinstance(structured, dict):
        local_structured = local_result.get("structured") if isinstance(local_result, dict) else {}
        if isinstance(local_structured, dict):
            for key in ["sourceDocuments", "fieldGroups", "scoringCriteria", "requirementPresence", "coverage", "appendices"]:
                if not structured.get(key) and local_structured.get(key):
                    structured[key] = local_structured[key]
        structured["targetSkill"] = PARSE_SKILL_NAME
        structured["mode"] = "opencode-skill"
        structured["opencodeOutput"] = result.get("opencodeOutput") or {}
    return resolved


def _run_parse_skill(
    skill_manifest_path: Path,
    *,
    local_result: dict[str, Any],
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> tuple[dict[str, Any], str]:
    if not settings.s1_parse_opencode_enabled:
        return local_result, ""
    try:
        result = OpencodeClient().generate_tender_parse_with_trace(
            _build_tender_parse_prompt(skill_manifest_path),
            stream_callback=(
                (lambda details: progress_callback("opencode_delta", details))
                if progress_callback
                else None
            ),
        )
        return _resolve_skill_structured_result(result, local_result=local_result), ""
    except RuntimeError as exc:
        fallback = json.loads(json.dumps(local_result, ensure_ascii=False))
        structured = fallback.setdefault("structured", {})
        if isinstance(structured, dict):
            structured["mode"] = "local-structured-parser"
            structured["opencodeError"] = str(exc)
        return fallback, f"S1 解析 Skill 调用失败，已使用本地结构化解析兜底：{exc}"


def parse_tender_documents(
    project_id: str,
    tender_files: list[dict[str, Any]],
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_dir = parsed_project_dir(project_id)
    appendix_temp_dir = project_dir / "s1_appendices"
    if appendix_temp_dir.exists():
        shutil.rmtree(appendix_temp_dir)
    documents: list[dict[str, Any]] = []
    combined_parts: list[str] = []
    texts_by_id: dict[str, str] = {}
    warnings: list[str] = []
    if progress_callback:
        progress_callback("extract_started", {"fileCount": len(tender_files)})

    for file_record in tender_files:
        file_path = Path(str(file_record["path"]))
        extension = file_path.suffix.lower()
        page_count: int | str = "-"
        file_warnings: list[str] = []
        ocr_meta: dict[str, Any] | None = None
        if progress_callback:
            progress_callback("extracting_file", {"fileName": file_record.get("name") or file_path.name})

        if extension == ".docx":
            text = extract_docx_text(file_path)
        elif extension == ".md":
            text = file_path.read_text(encoding="utf-8", errors="replace")
        elif extension == ".pdf":
            text, pdf_meta = extract_pdf_text(file_path)
            page_count = pdf_meta["pageCount"]
            file_warnings.extend(pdf_meta["warnings"])
            if pdf_meta.get("requiresOcr"):
                ocr_text, ocr_meta = _ocr_fallback_text(project_id, file_record, file_path)
                if ocr_text:
                    text = ocr_text
                    page_count = ocr_meta.get("pageCount") or page_count
                    file_warnings.append("扫描型 PDF 已通过 OCR/视觉模型转为可解析文本。")
                else:
                    file_warnings.append(
                        f"OCR 兜底识别未完成：{ocr_meta.get('message') if ocr_meta else '未知错误'}"
                    )
        elif extension in IMAGE_SUFFIXES:
            ocr_text, ocr_meta = _ocr_fallback_text(project_id, file_record, file_path)
            if ocr_text:
                text = ocr_text
                page_count = ocr_meta.get("pageCount") or 1
                file_warnings.append("图片文件已通过 OCR/视觉模型转为可解析文本。")
            else:
                text = ""
                page_count = 1
                file_warnings.append(
                    f"图片文件需要 OCR 识别，但兜底识别未完成：{ocr_meta.get('message') if ocr_meta else '未知错误'}"
                )
        else:
            text = ""
            file_warnings.append(f"当前 MVP 暂不解析 {extension or '未知'} 类型文件。")

        text = _normalize_text(text)
        text_length = len(text)
        text_path = project_dir / f"{file_record['id']}.txt"
        text_path.write_text(text, encoding="utf-8")

        metadata: dict[str, Any] = {
            "id": file_record["id"],
            "name": file_record["name"],
            "sourcePath": str(file_path),
            "textPath": str(text_path),
            "textLength": text_length,
            "pageCount": page_count,
            "warnings": file_warnings,
        }
        if ocr_meta:
            metadata["ocr"] = ocr_meta
        documents.append(metadata)
        texts_by_id[str(file_record["id"])] = text
        warnings.extend(file_warnings)

        if text:
            combined_parts.append(f"# 文件：{file_record['name']}\n\n{text}")
        if progress_callback:
            progress_callback(
                "file_extracted",
                {
                    "fileName": file_record.get("name") or file_path.name,
                    "textLength": text_length,
                    "warnings": file_warnings,
                },
            )

    combined_text = _normalize_text("\n\n".join(combined_parts))
    combined_text_path = project_dir / "combined.txt"
    combined_text_path.write_text(combined_text, encoding="utf-8")

    structured_result = _extract_structured_requirements(documents, texts_by_id)
    appendices = _extract_markdown_appendices(project_id, documents, texts_by_id)
    appendices.extend(_extract_docx_appendices(project_id, documents, start_index=len(appendices)))
    appendices = _prepare_appendix_outputs(project_id, appendices, renumber=True)
    structured_result["structured"]["appendices"] = appendices
    if progress_callback:
        progress_callback(
            "appendices_extracted",
            {
                "appendixCount": len(appendices),
                "generatedCount": sum(1 for item in appendices if item.get("status") == "generated"),
            },
        )
    structured_path = project_dir / "s1_structured_result.json"
    structured_path.write_text(json.dumps(structured_result, ensure_ascii=False, indent=2), encoding="utf-8")
    skill_manifest_path = project_dir / "s1_parse_manifest.json"
    skill_manifest = {
        "projectId": project_id,
        "targetSkill": PARSE_SKILL_NAME,
        "combinedTextPath": str(combined_text_path),
        "structuredResultPath": str(structured_path),
        "documents": documents,
        "targets": [
            "评分细则",
            "项目基础信息",
            "风机核心参数",
            "性能保证指标",
            "环境适应性要求",
            "专题方案要求",
            "附表和供货范围",
            "考核条款",
            "投标相关日期",
        ],
    }
    skill_manifest_path.write_text(json.dumps(skill_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback("skill_manifest_ready", {"manifestPath": str(skill_manifest_path)})
    structured_result, skill_warning = _run_parse_skill(
        skill_manifest_path,
        local_result=structured_result,
        progress_callback=progress_callback,
    )
    resolved_structured = structured_result.setdefault("structured", {})
    if not resolved_structured.get("appendices"):
        resolved_structured["appendices"] = appendices
    elif isinstance(resolved_structured.get("appendices"), list):
        resolved_structured["appendices"] = _prepare_appendix_outputs(
            project_id,
            resolved_structured["appendices"],
            renumber=True,
        )
    if skill_warning:
        warnings.append(skill_warning)
    structured_path.write_text(json.dumps(structured_result, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = project_dir / "manifest.json"
    manifest = {
        "projectId": project_id,
        "combinedTextPath": str(combined_text_path),
        "documents": documents,
        "structuredResultPath": str(structured_path),
        "skillManifestPath": str(skill_manifest_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    items = structured_result["items"]
    structured = structured_result["structured"]
    project_dates = structured["projectDates"]

    summary = {
        "fileCount": len(tender_files),
        "extractedCount": len(items),
        "textLength": len(combined_text),
        "textPreview": combined_text[:TEXT_PREVIEW_LIMIT],
        "warnings": warnings,
        "targetSkill": PARSE_SKILL_NAME,
        "categoryCounts": structured["categoryCounts"],
        "projectDates": {
            "startDate": project_dates.get("startDate") or "",
            "endDate": project_dates.get("endDate") or "",
        },
        "appendixCount": len(structured.get("appendices") or []),
    }

    if progress_callback:
        progress_callback(
            "complete",
            {
                "extractedCount": len(items),
                "appendixCount": len(structured.get("appendices") or []),
            },
        )

    return summary, {
        "projectDir": str(project_dir),
        "combinedTextPath": str(combined_text_path),
        "manifestPath": str(manifest_path),
        "structuredResultPath": str(structured_path),
        "skillManifestPath": str(skill_manifest_path),
        "documents": documents,
        "items": items,
        "structured": structured,
        "projectUpdates": {
            "startDate": project_dates.get("startDate") or "",
            "endDate": project_dates.get("endDate") or "",
            "deadline": project_dates.get("endDate") or "",
        },
    }
