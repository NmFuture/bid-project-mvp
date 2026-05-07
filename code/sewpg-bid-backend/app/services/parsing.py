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
from app.services.parse_profiles import (
    BUSINESS_PARSE_PROFILE,
    TECHNICAL_PARSE_PROFILE,
    ParseProfile,
    TECHNICAL_PARSE_SKILL_NAME,
    resolve_parse_profile,
)
from app.services.peripheral import PeripheralError

PARSER_CORE_DIR = (
    Path(__file__).resolve().parents[2] / "opencode" / "skill" / TECHNICAL_PARSE_SKILL_NAME / "scripts"
)
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

BUSINESS_RESPONSE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("bidLetterRequired", "投标函要求", ("投标函",)),
    FieldSpec("authorizationLetterRequired", "授权委托书要求", ("授权委托书", "法定代表人授权委托书")),
    FieldSpec("integrityCommitmentRequired", "廉洁承诺要求", ("廉洁", "廉洁自律承诺", "廉洁承诺")),
    FieldSpec("sealValidityStatementRequired", "投标专用章效力说明要求", ("投标专用章效力说明",)),
    FieldSpec("bidPriceTableRequired", "投标价格表要求", ("投标价格", "投标价格表")),
    FieldSpec("openingPriceTableRequired", "开标价格表要求", ("开标价格表",)),
    FieldSpec("specificationTableRequired", "货物规格表要求", ("货物规格", "规格表")),
    FieldSpec("commercialDeviationTableRequired", "商务偏差表要求", ("商务偏差", "偏差表")),
    FieldSpec("supplyScopeTableRequired", "供货范围表要求", ("供货范围", "供货范围表")),
    FieldSpec("bidSecurityRequired", "投标保证金要求", ("投标保证金", "保证金", "保函")),
    FieldSpec("performanceBondCommitmentRequired", "履约保证承诺要求", ("履约保证函", "履约承诺", "履约保证")),
    FieldSpec("attachment9Required", "附件9要求", ("附件9", "附件九")),
)

QUALIFICATION_SUPPORT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("qualificationDocumentRequired", "资格证明文件要求", ("资格证明", "合格投标人", "资格审查")),
    FieldSpec("performanceDocumentRequired", "业绩证明文件要求", ("业绩证明", "合同扫描件", "中标通知书", "验收报告")),
    FieldSpec("financialDocumentRequired", "财务文件要求", ("审计报告", "财务报表", "财务状况")),
    FieldSpec("creditDocumentRequired", "资信诚信文件要求", ("资信证明", "信用中国", "纳税信用", "失信")),
    FieldSpec("certificationDocumentRequired", "证书文件要求", ("认证证书", "资质证书", "体系认证")),
    FieldSpec("customerSpecificProofRequired", "客户专项证明要求", ("战略协议", "框架协议", "评价信", "优秀供应商证明", "示范应用证明")),
)

COMMITMENT_REQUIREMENT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("generalCommitmentCount", "承诺线索识别数", ("承诺",)),
    FieldSpec("generatedCommitmentCount", "自动生成承诺文件数", ("承诺函", "承诺书", "不得存在下列情形")),
    FieldSpec("pendingCommitmentCount", "待确认承诺线索数", ("承诺",)),
    FieldSpec("disqualificationCommitmentRequired", "不得存在下列情形承诺要求", ("不得存在下列情形", "不得存在下列情形之一")),
    FieldSpec("otherCommitmentSectionRequired", "其他承诺章节要求", ("投标人需要说明的其他内容", "其他内容", "其他承诺")),
    FieldSpec("commitmentGenerationBasis", "承诺文件生成依据", ("承诺函", "承诺书", "不得存在下列情形")),
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


def _copy_meta_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceFile": str(item.get("sourceFile") or ""),
        "sourceDocumentId": str(item.get("sourceDocumentId") or ""),
        "section": str(item.get("section") or ""),
        "evidence": str(item.get("evidence") or ""),
        "evidenceLocation": str(item.get("evidenceLocation") or ""),
    }


def _business_field_from_item(spec: FieldSpec, item: dict[str, Any], *, value_override: str | None = None) -> dict[str, Any]:
    field = {
        "key": spec.key,
        "label": spec.label,
        "value": (value_override if value_override is not None else str(item.get("value") or item.get("keyValue") or "")).strip(),
        "status": "found",
        **_copy_meta_fields(item),
        "confidence": float(item.get("confidence") or 0.86),
    }
    return field


def _empty_business_field(spec: FieldSpec, *, value: str = "") -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": value,
        "status": "missing" if not value else "derived",
        "sourceFile": "",
        "sourceDocumentId": "",
        "section": "",
        "evidence": "",
        "evidenceLocation": "",
        "confidence": 0.0,
    }


def _find_business_item(items: list[dict[str, Any]], spec: FieldSpec) -> dict[str, Any] | None:
    for item in items:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("title", "keyEntity", "value", "evidence", "section")
        )
        if any(alias in haystack for alias in spec.aliases):
            return item
    return None


def _build_business_project_basics(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered_specs = tuple(spec for spec in PROJECT_BASIC_FIELDS if spec.key != "technicalCommitment")
    fields: list[dict[str, Any]] = []
    for spec in filtered_specs:
        matched = next(
            (
                item
                for item in items
                if any(alias in str(item.get("keyEntity") or item.get("title") or item.get("evidence") or "") for alias in spec.aliases)
            ),
            None,
        )
        fields.append(_business_field_from_item(spec, matched) if matched else _empty_business_field(spec))
    return fields


def _build_business_response_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for spec in BUSINESS_RESPONSE_FIELDS:
        matched = _find_business_item(items, spec)
        fields.append(_business_field_from_item(spec, matched) if matched else _empty_business_field(spec))
    return fields


def _build_qualification_support_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for spec in QUALIFICATION_SUPPORT_FIELDS:
        matched = _find_business_item(items, spec)
        fields.append(_business_field_from_item(spec, matched) if matched else _empty_business_field(spec))
    return fields


def _find_commitment_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item.get(key) or "") for key in ("title", "value", "evidence", "section"))
        if "承诺" not in text and "不得存在下列情形" not in text:
            continue
        item_id = str(item.get("id") or "")
        if item_id in seen:
            continue
        seen.add(item_id)
        matched.append(item)
    return matched


COMMITMENT_DOC_KEYWORDS = ("承诺函", "承诺书")
COMMITMENT_GENERATION_HINTS = (
    "另附承诺函",
    "另附承诺书",
    "单独提供承诺函",
    "单独提供承诺书",
    "须提供承诺函",
    "须提供承诺书",
    "应提供承诺函",
    "应提供承诺书",
    "应出具承诺函",
    "应出具承诺书",
    "需提供承诺函",
    "需提供承诺书",
    "须出具承诺函",
    "须出具承诺书",
)
COMMITMENT_REQUIREMENT_CONTEXT_HINTS = (
    "提供",
    "提交",
    "出具",
    "附",
    "另附",
    "单独",
    "递交",
    "响应",
    "按要求",
    "须",
    "应",
    "需",
    "必须",
)
COMMITMENT_IGNORE_KEYWORDS = (
    "技术承诺",
    "廉洁承诺",
    "廉洁自律承诺",
    "履约承诺",
    "履约保证承诺",
    "投标函",
    "授权委托书",
    "评分标准",
    "评分办法",
    "证明材料",
    "目录",
)
COMMITMENT_NON_REQUIREMENT_TITLE_HINTS = (
    "格式",
    "模板",
    "目录",
    "附件",
    "附录",
    "详见",
    "示例",
    "参考",
)
TECHNICAL_COMMITMENT_KEYWORDS = (
    "发电量",
    "功率曲线",
    "功率",
    "可利用率",
    "涉网性能",
    "机组",
    "叶轮",
    "轮毂",
    "塔筒",
    "箱变",
    "风机",
    "载荷",
    "噪声",
    "振动",
    "发电性能",
    "性能保证",
    "技术指标",
)
COMMITMENT_TOPIC_TITLE_KEYWORDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("confidentiality", ("保密",), "保密承诺书"),
    ("disqualification", ("不得存在下列情形",), "投标人不存在下列情形之一承诺函"),
    ("delivery", ("交货", "供货周期", "交付"), "交货周期承诺书"),
    ("quality", ("质量", "质保", "售后", "服务"), "质量服务承诺书"),
    ("security", ("投标保证金", "保函", "保证金"), "投标保证金承诺书"),
    ("compliance", ("合规", "守法", "违法", "违规", "信用"), "合规承诺书"),
)
COMMITMENT_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("confidentiality", ("保密",)),
    ("compliance", ("合规", "守法", "违法", "违规", "信用")),
    ("security", ("投标保证金", "保函", "保证金")),
    ("disqualification", ("不得存在下列情形",)),
    ("integrity", ("廉洁",)),
    ("performance_bond", ("履约保证", "履约承诺")),
    ("delivery_commitment", ("交货", "工期", "供货周期")),
    ("quality_commitment", ("质量", "质保", "售后", "服务承诺")),
)
COMMITMENT_SEMANTIC_REVIEW_MAX_ITEMS = 12


def _commitment_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "value", "evidence", "section"))


def _is_technical_commitment_item(item: dict[str, Any]) -> bool:
    normalized = re.sub(r"\s+", "", _commitment_text(item))
    if not normalized:
        return False
    return any(keyword in normalized for keyword in TECHNICAL_COMMITMENT_KEYWORDS)


def _preferred_commitment_title(item: dict[str, Any], trigger_text: str) -> str:
    raw_title = str(item.get("title") or "").strip()
    raw_value = str(item.get("value") or "").strip()
    raw_evidence = str(item.get("evidence") or "").strip()
    source_text = raw_evidence or raw_value or raw_title or trigger_text
    normalized_source = re.sub(r"\s+", "", source_text)

    for _, keywords, preferred_title in COMMITMENT_TOPIC_TITLE_KEYWORDS:
        if any(keyword in normalized_source for keyword in keywords):
            return preferred_title

    title = raw_title or trigger_text or "承诺文件"
    if title in COMMITMENT_DOC_KEYWORDS or title == "承诺":
        for keyword in COMMITMENT_GENERATION_HINTS + COMMITMENT_DOC_KEYWORDS:
            if keyword in source_text:
                prefix = _normalize_commitment_title_prefix(source_text.split(keyword, 1)[0])
                if prefix:
                    return f"{prefix}{keyword}"
                return keyword

    title = _normalize_commitment_title_prefix(title)
    if not any(keyword in title for keyword in COMMITMENT_DOC_KEYWORDS):
        title = f"{title}承诺书"
    return title


def _normalize_commitment_topic(text: str) -> str:
    normalized = re.sub(r"\s+", "", str(text or ""))
    for topic, keywords in COMMITMENT_TOPIC_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return topic
    if "承诺函" in normalized or "承诺书" in normalized:
        return normalized[:80]
    return normalized[:80] or "commitment"


def _normalize_commitment_title_prefix(text: str) -> str:
    normalized = str(text or "").strip(" ：:，,、。.；;（）()")
    for prefix in ("投标人应出具", "投标人应提供", "投标人须提供", "投标人需提供", "投标人须出具", "投标人另附", "应出具", "应提供", "须提供", "需提供", "须出具", "另附"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip(" ：:，,、。.；;（）()")
            break
    return normalized


def _contains_commitment_requirement_context(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or ""))
    return any(hint in normalized for hint in COMMITMENT_REQUIREMENT_CONTEXT_HINTS)


def _looks_like_bare_commitment_title(item: dict[str, Any]) -> bool:
    evidence = str(item.get("evidence") or item.get("value") or item.get("title") or "").strip()
    normalized = re.sub(r"\s+", "", evidence)
    if not normalized:
        return False
    if not any(keyword in normalized for keyword in COMMITMENT_DOC_KEYWORDS):
        return False
    if _contains_commitment_requirement_context(normalized):
        return False
    if any(token in normalized for token in COMMITMENT_NON_REQUIREMENT_TITLE_HINTS):
        return True
    if _looks_like_section_heading(evidence):
        return True
    return len(normalized) <= 18 and normalized.endswith(COMMITMENT_DOC_KEYWORDS)


def _extract_commitment_trigger_phrase(text: str) -> str:
    normalized = str(text or "").strip()
    if "不得存在下列情形" in normalized:
        return "投标人不得存在下列情形之一"
    for hint in COMMITMENT_GENERATION_HINTS:
        if hint in normalized:
            return hint
    for keyword in COMMITMENT_DOC_KEYWORDS:
        if keyword in normalized:
            return keyword
    return "承诺"


def _build_commitment_semantic_review_prompt(candidates: list[dict[str, Any]]) -> str:
    records = []
    for item in candidates[:COMMITMENT_SEMANTIC_REVIEW_MAX_ITEMS]:
        records.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "section": str(item.get("section") or ""),
                "evidence": str(item.get("evidence") or item.get("value") or ""),
                "sourceFile": str(item.get("sourceFile") or ""),
                "evidenceLocation": str(item.get("evidenceLocation") or ""),
                "contextBefore": str(item.get("contextBefore") or ""),
                "contextAfter": str(item.get("contextAfter") or ""),
                "topicKey": str(item.get("topicKey") or ""),
                "triggerText": str(item.get("triggerText") or ""),
            }
        )

    return (
        "你在做商务标承诺文件语义复核。请只根据输入文本判断，该条是否要求投标人单独形成一份承诺函/承诺书。\n"
        "输出 JSON，格式为：\n"
        "{\n"
        '  "decisions": [\n'
        '    {"id":"RAW-0001","action":"generate|clue|ignore","topicKey":"confidentiality","preferredTitle":"保密承诺书","reason":"一句简短原因"}\n'
        "  ]\n"
        "}\n"
        "判断规则：\n"
        "1. 如果只是章节标题、目录项、模板名、格式名、附件名，不要生成，action=ignore 或 clue。\n"
        "2. 如果语义上明确要求投标人单独提供/提交/出具一份承诺函或承诺书，action=generate。\n"
        "3. 如果存在承诺字样，但看不出是否必须单独成文，action=clue。\n"
        "4. 如果 evidence 只是类似“保密承诺书”这类短标题，必须结合 section、contextBefore、contextAfter 判断；上下文没有明确“提供/提交/出具/另附/单独成文”要求时，不要生成。\n"
        "5. 同一主题如果只是重复标题、重复要求或同一事项的不同表述，最多保留一个 generate，其余用 ignore 或 clue。\n"
        "6. topicKey 尽量归一，例如 confidentiality、compliance、security、delivery_commitment、quality_commitment、disqualification。\n"
        "7. preferredTitle 只在 action=generate 时填写，且应是适合最终文件名的主题名称。\n\n"
        f"候选列表：\n{json.dumps(records, ensure_ascii=False, indent=2)}"
    )


def _review_commitment_candidates_semantically(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not candidates:
        return {}
    try:
        result = OpencodeClient().review_business_commitments_with_trace(
            _build_commitment_semantic_review_prompt(candidates)
        )
    except RuntimeError:
        return {}
    decisions = result.get("decisions")
    if not isinstance(decisions, list):
        return {}
    reviewed: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        item_id = str(decision.get("id") or "").strip()
        if not item_id:
            continue
        reviewed[item_id] = decision
    return reviewed


def _is_commitment_doc_required(item: dict[str, Any]) -> bool:
    text = _commitment_text(item)
    normalized = re.sub(r"\s+", "", text)
    if "不得存在下列情形" in normalized:
        return True
    if any(hint in normalized for hint in COMMITMENT_GENERATION_HINTS):
        return True
    if any(keyword in normalized for keyword in COMMITMENT_DOC_KEYWORDS):
        if _looks_like_bare_commitment_title(item):
            return False
        if _contains_commitment_requirement_context(normalized):
            return True
        return False
    if any(keyword in normalized for keyword in COMMITMENT_NON_REQUIREMENT_TITLE_HINTS):
        return False
    if _looks_like_section_heading(str(item.get("evidence") or item.get("title") or "")):
        return False
    if ("投标人" in normalized or "投标方" in normalized) and any(token in normalized for token in ("须承诺", "应承诺", "承诺如下")):
        return True
    return False


def _is_commitment_item_ignored(item: dict[str, Any]) -> bool:
    text = _commitment_text(item)
    normalized = re.sub(r"\s+", "", text)
    if "承诺" not in normalized and "不得存在下列情形" not in normalized:
        return True
    if _is_technical_commitment_item(item):
        return True
    if _is_commitment_doc_required(item):
        return False
    if any(keyword in normalized for keyword in COMMITMENT_IGNORE_KEYWORDS):
        if "不得存在下列情形" not in normalized:
            return True
    if any(token in normalized for token in ("评分", "得分", "分值", "证明材料要求")):
        return True
    return False


def _build_business_commitment_analysis(
    items: list[dict[str, Any]],
    *,
    run_semantic_review: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    all_items = _find_commitment_items(items)
    clues: list[dict[str, Any]] = []
    letters: list[dict[str, Any]] = []
    generated_topics: set[str] = set()
    clue_topics: set[tuple[str, str]] = set()
    semantic_candidates: list[dict[str, Any]] = []
    semantic_candidate_ids: set[str] = set()
    semantic_candidate_signatures: set[tuple[str, str, str]] = set()

    for item in all_items:
        if _is_commitment_item_ignored(item):
            continue
        text = _commitment_text(item)
        topic = _normalize_commitment_topic(text)
        trigger_text = _extract_commitment_trigger_phrase(text)
        topic_key = topic or "commitment"
        base = {
            **_copy_meta_fields(item),
            "topic": topic,
            "topicKey": topic_key,
            "triggerText": trigger_text,
            "triggerContext": str(item.get("evidence") or item.get("value") or "").strip(),
        }
        if _is_commitment_doc_required(item):
            normalized = re.sub(r"\s+", "", text)
            if any(keyword in normalized for keyword in COMMITMENT_DOC_KEYWORDS) and not _contains_commitment_requirement_context(normalized):
                item_id = str(item.get("id") or "")
                signature = (
                    str(item.get("sourceFile") or ""),
                    str(item.get("evidenceLocation") or ""),
                    re.sub(r"\s+", "", str(item.get("evidence") or item.get("value") or item.get("title") or "")),
                )
                if item_id and item_id not in semantic_candidate_ids and signature not in semantic_candidate_signatures:
                    semantic_candidate_ids.add(item_id)
                    semantic_candidate_signatures.add(signature)
                    semantic_candidates.append({**item, **base})
                continue

            if topic_key in generated_topics:
                continue
            generated_topics.add(topic_key)
            if topic_key == "disqualification":
                title = "投标人不存在下列情形之一承诺函"
                commitment_type = "disqualification"
            else:
                title = _preferred_commitment_title(item, trigger_text)
                commitment_type = "general_commitment"
            letters.append(
                {
                    "id": f"CL-{len(letters) + 1:04d}",
                    "artifactType": "commitment_letter",
                    "title": title,
                    "commitmentType": commitment_type,
                    "status": "pending_review",
                    **base,
                    "docxPath": "",
                    "workspacePath": "",
                    "placementHint": "投标人需要说明的其他内容",
                    "needsHumanReview": True,
                    "riskFlags": ["template_pending", "legal_wording_review_required"],
                    "previewType": "onlyoffice",
                }
            )
            continue

        normalized = re.sub(r"\s+", "", text)
        if any(keyword in normalized for keyword in COMMITMENT_DOC_KEYWORDS):
            item_id = str(item.get("id") or "")
            signature = (
                str(item.get("sourceFile") or ""),
                str(item.get("evidenceLocation") or ""),
                re.sub(r"\s+", "", str(item.get("evidence") or item.get("value") or item.get("title") or "")),
            )
            if item_id and item_id not in semantic_candidate_ids and signature not in semantic_candidate_signatures:
                semantic_candidate_ids.add(item_id)
                semantic_candidate_signatures.add(signature)
                semantic_candidates.append({**item, **base})
            continue

        clue_key = (topic_key, base["triggerContext"])
        if clue_key in clue_topics:
            continue
        clue_topics.add(clue_key)
        clues.append(
            {
                "id": f"CC-{len(clues) + 1:04d}",
                "artifactType": "commitment_clue",
                "title": str(item.get("title") or trigger_text or "承诺线索").strip() or "承诺线索",
                "clueType": "pending_manual_review",
                "status": "needs_review",
                **base,
                "recommendedAction": "暂不自动生成，请人工判断是否需要单独承诺函/承诺书。",
                "riskFlags": ["ambiguous_requirement"],
            }
        )

    reviewed = _review_commitment_candidates_semantically(semantic_candidates) if run_semantic_review else {}
    for item in semantic_candidates:
        decision = reviewed.get(str(item.get("id") or "")) or {}
        if not run_semantic_review:
            decision = {
                "action": "clue",
                "topicKey": str(item.get("topicKey") or item.get("topic") or "commitment"),
                "reason": "语义复核延后到最终结构化结果阶段执行。",
            }
        action = str(decision.get("action") or "clue").strip().lower()
        topic_key = str(decision.get("topicKey") or item.get("topicKey") or item.get("topic") or "commitment").strip() or "commitment"
        if action == "ignore":
            continue
        if action == "generate":
            if topic_key in generated_topics:
                continue
            generated_topics.add(topic_key)
            title = str(decision.get("preferredTitle") or "").strip() or _preferred_commitment_title(item, str(item.get("triggerText") or "承诺"))
            commitment_type = "disqualification" if topic_key == "disqualification" else "general_commitment"
            letters.append(
                {
                    "id": f"CL-{len(letters) + 1:04d}",
                    "artifactType": "commitment_letter",
                    "title": title,
                    "commitmentType": commitment_type,
                    "status": "pending_review",
                    **_copy_meta_fields(item),
                    "topic": topic_key,
                    "topicKey": topic_key,
                    "triggerText": str(item.get("triggerText") or "承诺"),
                    "triggerContext": str(item.get("triggerContext") or item.get("evidence") or item.get("value") or "").strip(),
                    "docxPath": "",
                    "workspacePath": "",
                    "placementHint": "投标人需要说明的其他内容",
                    "needsHumanReview": True,
                    "riskFlags": ["semantic_review_passed", "legal_wording_review_required"],
                    "previewType": "onlyoffice",
                }
            )
            continue

        clue_key = (
            topic_key,
            str(item.get("triggerContext") or item.get("evidence") or item.get("value") or "").strip(),
        )
        if clue_key in clue_topics:
            continue
        clue_topics.add(clue_key)
        clues.append(
            {
                "id": f"CC-{len(clues) + 1:04d}",
                "artifactType": "commitment_clue",
                "title": str(item.get("title") or item.get("triggerText") or "承诺线索").strip() or "承诺线索",
                "clueType": "pending_manual_review",
                "status": "needs_review",
                **_copy_meta_fields(item),
                "topic": topic_key,
                "topicKey": topic_key,
                "triggerText": str(item.get("triggerText") or "承诺"),
                "triggerContext": str(item.get("triggerContext") or item.get("evidence") or item.get("value") or "").strip(),
                "recommendedAction": str(decision.get("reason") or "暂不自动生成，请人工判断是否需要单独承诺函/承诺书。").strip(),
                "riskFlags": ["semantic_review_required"],
            }
        )

    return {"letters": letters, "clues": clues}


def _looks_like_section_heading(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    return bool(
        re.match(r"^(?:第[一二三四五六七八九十百千0-9]+[章节条]|[（(]?[一二三四五六七八九十0-9]+[）)])", text)
        or text.startswith("附件")
        or text.startswith("附表")
    )


def _scan_business_hint_items(documents: list[dict[str, Any]], texts_by_id: dict[str, str]) -> list[dict[str, Any]]:
    keywords = sorted(
        {
            *[alias for spec in BUSINESS_RESPONSE_FIELDS for alias in spec.aliases],
            *[alias for spec in QUALIFICATION_SUPPORT_FIELDS for alias in spec.aliases],
            *[alias for spec in COMMITMENT_REQUIREMENT_FIELDS for alias in spec.aliases],
            "投标人不得存在下列情形之一",
            "不得存在下列情形",
            "投标人需要说明的其他内容",
        },
        key=len,
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        lines = [line.strip() for line in str(texts_by_id.get(document_id) or "").splitlines()]
        current_section = ""
        for line_number, line in enumerate(lines, start=1):
            if not line:
                continue
            if _looks_like_section_heading(line):
                current_section = line
            matched_keyword = next((keyword for keyword in keywords if keyword and keyword in line), "")
            if not matched_keyword:
                continue
            dedupe_key = (document_id, line)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            label, value = _split_label_value(line, matched_keyword)
            line_index = line_number - 1
            context_before = next(
                (candidate for candidate in reversed(lines[max(0, line_index - 2):line_index]) if candidate),
                "",
            )
            context_after = next(
                (candidate for candidate in lines[line_index + 1:line_index + 3] if candidate),
                "",
            )
            items.append(
                {
                    "id": f"RAW-{len(items) + 1:04d}",
                    "type": "商务提示",
                    "category": "business_hint",
                    "title": label or matched_keyword,
                    "keyEntity": matched_keyword,
                    "keyValue": value,
                    "value": value or line,
                    "sourceFile": source_file,
                    "sourceDocumentId": document_id,
                    "section": current_section,
                    "evidence": line,
                    "evidenceLocation": f"L{line_number}",
                    "contextBefore": context_before,
                    "contextAfter": context_after,
                    "confidence": 0.72,
                }
            )
    return items


def _build_commitment_requirement_fields(
    items: list[dict[str, Any]],
    *,
    analysis: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    analysis = analysis or _build_business_commitment_analysis(items)
    commitment_items = _find_commitment_items(items)
    disqualification_item = next(
        (
            item
            for item in commitment_items
            if "不得存在下列情形" in " ".join(str(item.get(key) or "") for key in ("title", "value", "evidence"))
        ),
        None,
    )
    other_content_item = next(
        (
            item
            for item in items
            if "投标人需要说明的其他内容" in " ".join(str(item.get(key) or "") for key in ("title", "value", "evidence", "section"))
        ),
        None,
    )

    fields: list[dict[str, Any]] = []
    for spec in COMMITMENT_REQUIREMENT_FIELDS:
        if spec.key == "generalCommitmentCount":
            count_text = str(len(analysis["letters"]) + len(analysis["clues"]))
            matched = commitment_items[0] if commitment_items else None
            fields.append(
                _business_field_from_item(spec, matched, value_override=count_text)
                if matched
                else _empty_business_field(spec, value="0")
            )
            continue
        if spec.key == "generatedCommitmentCount":
            matched = analysis["letters"][0] if analysis["letters"] else None
            fields.append(
                _business_field_from_item(spec, matched, value_override=str(len(analysis["letters"])))
                if matched
                else _empty_business_field(spec, value="0")
            )
            continue
        if spec.key == "pendingCommitmentCount":
            matched = analysis["clues"][0] if analysis["clues"] else None
            fields.append(
                _business_field_from_item(spec, matched, value_override=str(len(analysis["clues"])))
                if matched
                else _empty_business_field(spec, value="0")
            )
            continue
        if spec.key == "disqualificationCommitmentRequired":
            fields.append(
                _business_field_from_item(spec, disqualification_item)
                if disqualification_item
                else _empty_business_field(spec)
            )
            continue
        if spec.key == "otherCommitmentSectionRequired":
            fields.append(
                _business_field_from_item(spec, other_content_item)
                if other_content_item
                else _empty_business_field(spec)
            )
            continue
        if spec.key == "commitmentGenerationBasis":
            matched = analysis["letters"][0] if analysis["letters"] else None
            value = "；".join(str(item.get("triggerContext") or "").strip() for item in analysis["letters"][:3] if str(item.get("triggerContext") or "").strip()).strip("；")
            fields.append(
                _business_field_from_item(spec, matched, value_override=value or "未识别到明确的承诺函/承诺书生成依据")
                if matched
                else _empty_business_field(spec, value="未识别到明确的承诺函/承诺书生成依据")
            )
            continue
        fields.append(_empty_business_field(spec))
    return fields


def _business_presence_from_keywords(items: list[dict[str, Any]], *, keywords: tuple[str, ...]) -> dict[str, Any]:
    matched = [
        item
        for item in items
        if any(keyword in " ".join(str(item.get(key) or "") for key in ("title", "value", "evidence", "section")) for keyword in keywords)
    ]
    if not matched:
        return {
            "status": "missing",
            "summary": "招标文件中暂未识别到明确要求。",
            "evidences": [],
        }
    evidences = [
        {
            **_copy_meta_fields(item),
        }
        for item in matched[:8]
    ]
    summary = "；".join(str(item.get("value") or item.get("evidence") or "").strip() for item in matched if str(item.get("value") or item.get("evidence") or "").strip())
    return {
        "status": "present",
        "summary": summary[:800],
        "evidences": evidences,
    }


def _build_business_requirement_presence(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "qualificationDocuments": _business_presence_from_keywords(
            items,
            keywords=("资格证明", "合格投标人", "资格审查"),
        ),
        "performanceDocuments": _business_presence_from_keywords(
            items,
            keywords=("业绩", "合同", "中标通知书", "验收报告", "试运行"),
        ),
        "deviationResponse": _business_presence_from_keywords(
            items,
            keywords=("商务偏差", "偏差表", "偏离表"),
        ),
        "bidSecurity": _business_presence_from_keywords(
            items,
            keywords=("投标保证金", "保证金", "保函"),
        ),
        "otherCommitments": _business_presence_from_keywords(
            items,
            keywords=("承诺", "投标人需要说明的其他内容", "履约保证"),
        ),
        "disqualificationClauses": _business_presence_from_keywords(
            items,
            keywords=("投标人不得存在下列情形之一", "不得存在下列情形"),
        ),
    }


def _filter_business_scoring(scoring: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(scoring, dict):
        return {"business": [], "price": [], "compliance": []}
    return {
        "business": copy.deepcopy(scoring.get("business") or []),
        "price": copy.deepcopy(scoring.get("price") or []),
        "compliance": copy.deepcopy(scoring.get("compliance") or []),
    }


def _build_business_coverage(
    field_groups: dict[str, Any],
    scoring: dict[str, list[dict[str, Any]]],
    presence: dict[str, Any],
) -> list[dict[str, Any]]:
    checks = [
        ("商务评分要求", len(scoring.get("business") or []) > 0),
        ("报价与价格表", any(field.get("status") == "found" for field in field_groups.get("businessResponse") or [] if field.get("key") in {"bidPriceTableRequired", "openingPriceTableRequired"})),
        ("偏差响应", bool((presence.get("deviationResponse") or {}).get("status") == "present")),
        ("资格证明", bool((presence.get("qualificationDocuments") or {}).get("status") == "present")),
        ("业绩证明", bool((presence.get("performanceDocuments") or {}).get("status") == "present")),
        ("保证金", bool((presence.get("bidSecurity") or {}).get("status") == "present")),
        ("其他承诺", bool((presence.get("otherCommitments") or {}).get("status") == "present")),
    ]
    return [
        {
            "label": label,
            "status": "covered" if covered else "missing",
        }
        for label, covered in checks
    ]


def _build_business_commitment_letters(
    project_id: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    _ = project_id
    return _build_business_commitment_analysis(items)["letters"]



def _build_business_commitment_clues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _build_business_commitment_analysis(items)["clues"]


def _transform_to_business_contract(
    project_id: str,
    payload: dict[str, Any],
    *,
    profile: ParseProfile,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
    run_semantic_review: bool = True,
) -> dict[str, Any]:
    result = copy.deepcopy(payload if isinstance(payload, dict) else {})
    items = result.get("items") if isinstance(result.get("items"), list) else []
    hint_items = _scan_business_hint_items(documents, texts_by_id)
    merged_items = [*copy.deepcopy(items), *hint_items]
    result["items"] = merged_items
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    source_documents = copy.deepcopy(structured.get("sourceDocuments") or [])
    project_dates = copy.deepcopy(structured.get("projectDates") or {"startDate": "", "endDate": ""})
    appendices = copy.deepcopy(structured.get("appendices") or [])
    scoring = _filter_business_scoring(structured.get("scoringCriteria") or {})
    commitment_analysis = _build_business_commitment_analysis(
        merged_items,
        run_semantic_review=run_semantic_review,
    )
    field_groups = {
        "projectBasics": _build_business_project_basics(merged_items),
        "businessResponse": _build_business_response_fields(merged_items),
        "qualificationSupport": _build_qualification_support_fields(merged_items),
        "commitmentRequirements": _build_commitment_requirement_fields(
            merged_items,
            analysis=commitment_analysis,
        ),
    }
    presence = _build_business_requirement_presence(merged_items)
    _ = project_id
    commitment_letters = copy.deepcopy(commitment_analysis["letters"])
    commitment_clues = copy.deepcopy(commitment_analysis["clues"])

    result["structured"] = {
        "schemaVersion": profile.schema_version,
        "targetSkill": profile.skill_name,
        "mode": str(structured.get("mode") or "local-structured-parser"),
        "sourceDocuments": source_documents,
        "scoringCriteria": scoring,
        "fieldGroups": field_groups,
        "requirementPresence": presence,
        "coverage": _build_business_coverage(field_groups, scoring, presence),
        "projectDates": {
            "startDate": str(project_dates.get("startDate") or ""),
            "endDate": str(project_dates.get("endDate") or ""),
        },
        "appendices": appendices,
        "commitmentLetters": commitment_letters,
        "commitmentClues": commitment_clues,
        "categoryCounts": {
            "商务评分": len(scoring.get("business") or []),
            "报价评分": len(scoring.get("price") or []),
            "合规审查": len(scoring.get("compliance") or []),
            "商务附表": len(appendices),
            "承诺文件": len(commitment_letters),
            "待确认承诺线索": len(commitment_clues),
        },
        "opencodeOutput": copy.deepcopy(structured.get("opencodeOutput") or {}),
    }
    return result


def _business_project_name_from_structured(structured: dict[str, Any]) -> str:
    field_groups = structured.get("fieldGroups") if isinstance(structured, dict) else {}
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups, dict) else []
    for field in project_basics if isinstance(project_basics, list) else []:
        if not isinstance(field, dict):
            continue
        if str(field.get("key") or "") != "projectName":
            continue
        value = str(field.get("value") or "").strip()
        if value:
            return value
    raw_basics = structured.get("projectBasics") if isinstance(structured, dict) else {}
    if isinstance(raw_basics, dict):
        return str(raw_basics.get("项目名称") or raw_basics.get("projectName") or "").strip()
    return ""


def _business_tenderer_name_from_structured(structured: dict[str, Any]) -> str:
    field_groups = structured.get("fieldGroups") if isinstance(structured, dict) else {}
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups, dict) else []
    for field in project_basics if isinstance(project_basics, list) else []:
        if not isinstance(field, dict):
            continue
        if str(field.get("key") or "") != "tenderer":
            continue
        value = str(field.get("value") or "").strip()
        if value:
            return value
    return ""


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


def _commitment_letter_output_dir(project_id: str) -> Path:
    path = settings.parsed_dir / project_id / "s1_commitment_letters"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workspace_appendix_output_dir(project_id: str, profile: ParseProfile) -> Path:
    return settings.documents_dir / project_id / profile.workspace_dirname / "appendices"


def _workspace_commitment_letter_output_dir(project_id: str, profile: ParseProfile) -> Path:
    return settings.documents_dir / project_id / profile.workspace_dirname / "commitment-letters"


def _appendix_asset_path(project_id: str, appendix_id: str, title: str) -> tuple[Path, str]:
    file_name = f"{appendix_id}-{_sanitize_docx_name(title, '附表')}.docx"
    return _appendix_output_dir(project_id) / file_name, f"s1_appendices/{file_name}"


def _commitment_letter_asset_path(project_id: str, letter_id: str, title: str) -> tuple[Path, str]:
    file_name = f"{letter_id}-{_sanitize_docx_name(title, '承诺函')}.docx"
    return _commitment_letter_output_dir(project_id) / file_name, f"s1_commitment_letters/{file_name}"


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _write_commitment_letter_docx(path: Path, letter: dict[str, Any], *, project_name: str = "", tenderer_name: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    title = str(letter.get("title") or "承诺函").strip() or "承诺函"
    trigger_context = str(letter.get("triggerContext") or letter.get("evidence") or letter.get("triggerText") or "").strip()
    commitment_type = str(letter.get("commitmentType") or "").strip()

    doc = Document()
    doc.add_heading(title, level=1)
    if project_name:
        doc.add_paragraph(f"项目名称：{project_name}")
    if tenderer_name:
        doc.add_paragraph(f"招标人：{tenderer_name}")
    if trigger_context:
        doc.add_paragraph(f"触发依据：{trigger_context}")

    doc.add_paragraph("致：招标人")
    doc.add_paragraph("说明：本文件为商务标解析阶段自动生成的承诺函草稿，请结合招标文件原文、法务要求和项目实际情况复核后使用。")

    if commitment_type == "disqualification":
        doc.add_paragraph("我方在参加本项目投标过程中，郑重承诺如下：")
        doc.add_paragraph("1. 我方不存在招标文件中列示的“投标人不得存在下列情形之一”所述任一情形。")
        doc.add_paragraph("2. 如本承诺与实际情况不符，我方愿意按照招标文件和相关规定承担相应责任。")
    else:
        doc.add_paragraph("根据招标文件中的承诺要求，我方郑重承诺如下：")
        doc.add_paragraph("1. 我方将严格按照招标文件要求对相关事项进行响应并履行承诺。")
        if trigger_context:
            doc.add_paragraph(f"2. 本承诺函重点对应的招标文件原文为：{trigger_context}")
        doc.add_paragraph("3. 如本承诺与实际情况不符，我方愿意按照招标文件和相关规定承担相应责任。")

    doc.add_paragraph("")
    doc.add_paragraph("投标人（盖章）：________________")
    doc.add_paragraph("法定代表人或授权代表（签字或盖章）：________________")
    doc.add_paragraph("日期：________________")
    doc.save(path)


def materialize_appendix_docx(project_id: str, appendix: dict[str, Any], *, profile: ParseProfile = TECHNICAL_PARSE_PROFILE) -> dict[str, Any]:
    """Ensure an appendix entry has a generated Word asset, even when no template table was found."""

    item = copy.deepcopy(appendix)
    appendix_id = str(item.get("id") or "").strip() or "APPX-0000"
    title = str(item.get("title") or item.get("evidence") or "附表").strip() or "附表"
    rows = item.get("rows") if isinstance(item.get("rows"), list) else []
    output_dir = _appendix_output_dir(project_id)
    workspace_output_dir = _workspace_appendix_output_dir(project_id, profile)
    project_workspace_root = settings.documents_dir / project_id

    existing_path = Path(str(item.get("docxPath") or ""))
    if not existing_path.is_absolute():
        existing_path = Path()
    existing_path_allowed = (
        bool(existing_path)
        and (
            _path_is_inside(existing_path, output_dir)
            or _path_is_inside(existing_path, workspace_output_dir)
            or _path_is_inside(existing_path, project_workspace_root)
        )
    )
    if not existing_path_allowed:
        existing_path, workspace_path = _appendix_asset_path(project_id, appendix_id, title)
    else:
        workspace_path = str(item.get("workspacePath") or f"{profile.workspace_dirname}/appendices/{existing_path.name}")

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


def materialize_business_commitment_letter_docx(
    project_id: str,
    letter: dict[str, Any],
    *,
    profile: ParseProfile = BUSINESS_PARSE_PROFILE,
    project_name: str = "",
    tenderer_name: str = "",
) -> dict[str, Any]:
    item = copy.deepcopy(letter)
    letter_id = str(item.get("id") or "").strip() or "CL-0000"
    title = str(item.get("title") or item.get("triggerText") or "承诺函").strip() or "承诺函"
    output_dir = _commitment_letter_output_dir(project_id)
    workspace_output_dir = _workspace_commitment_letter_output_dir(project_id, profile)
    project_workspace_root = settings.documents_dir / project_id

    existing_path = Path(str(item.get("docxPath") or ""))
    if not existing_path.is_absolute():
        existing_path = Path()
    existing_path_allowed = (
        bool(existing_path)
        and (
            _path_is_inside(existing_path, output_dir)
            or _path_is_inside(existing_path, workspace_output_dir)
            or _path_is_inside(existing_path, project_workspace_root)
        )
    )
    if not existing_path_allowed:
        existing_path, workspace_path = _commitment_letter_asset_path(project_id, letter_id, title)
    else:
        if str(item.get("workspacePath") or "").strip():
            workspace_path = str(item.get("workspacePath") or "")
        elif _path_is_inside(existing_path, workspace_output_dir):
            workspace_path = f"{profile.workspace_dirname}/commitment-letters/{existing_path.name}"
        else:
            workspace_path = f"s1_commitment_letters/{existing_path.name}"

    if not existing_path.exists():
        _write_commitment_letter_docx(existing_path, item, project_name=project_name, tenderer_name=tenderer_name)

    item.update(
        {
            "id": letter_id,
            "title": title,
            "status": "generated",
            "docxPath": str(existing_path),
            "workspacePath": workspace_path,
            "previewType": "onlyoffice",
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
    profile: ParseProfile = TECHNICAL_PARSE_PROFILE,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, appendix in enumerate(_dedupe_appendix_page_number_artifacts(appendices), start=1):
        item = copy.deepcopy(appendix)
        if renumber:
            item["id"] = f"APPX-{index:04d}"
            item["docxPath"] = ""
            item.pop("workspacePath", None)
        prepared.append(materialize_appendix_docx(project_id, item, profile=profile))
    return prepared


def _prepare_commitment_letter_outputs(
    project_id: str,
    letters: list[dict[str, Any]],
    *,
    renumber: bool,
    profile: ParseProfile = BUSINESS_PARSE_PROFILE,
    project_name: str = "",
    tenderer_name: str = "",
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, letter in enumerate(letters, start=1):
        item = copy.deepcopy(letter)
        if renumber:
            item["id"] = f"CL-{index:04d}"
            item["docxPath"] = ""
            item.pop("workspacePath", None)
        prepared.append(
            materialize_business_commitment_letter_docx(
                project_id,
                item,
                profile=profile,
                project_name=project_name,
                tenderer_name=tenderer_name,
            )
        )
    return prepared


def materialize_parse_appendix_docx_assets(project_id: str, parse_result: dict[str, Any], *, bid_type: str = "技术标") -> dict[str, Any]:
    payload = copy.deepcopy(parse_result)
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return payload
    appendices = structured.get("appendices")
    if not isinstance(appendices, list):
        return payload
    profile = resolve_parse_profile(bid_type)
    structured["appendices"] = _prepare_appendix_outputs(project_id, appendices, renumber=False, profile=profile)
    return payload


def materialize_parse_business_commitment_letter_docx_assets(
    project_id: str,
    parse_result: dict[str, Any],
    *,
    bid_type: str = "商务标",
) -> dict[str, Any]:
    payload = copy.deepcopy(parse_result)
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return payload
    if resolve_parse_profile(bid_type).key != "business":
        return payload
    letters = structured.get("commitmentLetters")
    if not isinstance(letters, list):
        return payload
    project_name = _business_project_name_from_structured(structured)
    tenderer_name = _business_tenderer_name_from_structured(structured)
    structured["commitmentLetters"] = _prepare_commitment_letter_outputs(
        project_id,
        letters,
        renumber=False,
        profile=BUSINESS_PARSE_PROFILE,
        project_name=project_name,
        tenderer_name=tenderer_name,
    )
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


def _build_tender_parse_prompt(skill_manifest_path: Path, profile: ParseProfile) -> str:
    if profile.key == "business":
        return f"""
Use the {profile.skill_name} skill.

你现在在做 S1 商务招标文件结构化解析。请调用解析 Skill 读取 manifest 中的多份招标文件文本，输出可直接给后端使用的结构化 JSON。

manifest：{skill_manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 600000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整结构化 JSON 写入 manifest.structuredResultPath，并只在 stdout 打印小型摘要 JSON：

s1parse {skill_manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schemaVersion": "{profile.schema_version}",
  "targetSkill": "{profile.skill_name}",
  "outputFile": "manifest 中的 structuredResultPath",
  "summary": {{"itemCount": 0, "categoryCounts": {{}}, "scoringCounts": {{"business": 0, "price": 0, "compliance": 0}}, "projectDates": {{"startDate": "", "endDate": ""}}}}
}}

解析目标必须覆盖：
1. 商务评分、报价评分、符合性/合规性审查。
2. 项目基础信息：项目名称、招标编号、招标人/管理单位、规模、交货周期、质保期。
3. 商务响应要求：投标函、授权书、保证金、偏差表、报价表、供货范围表、履约承诺等。
4. 资格与业绩支撑：资格证明、业绩证明、财务资料、资信资料、证书资料。
5. 承诺事项要求：全文搜索“承诺”，并识别“投标人不得存在下列情形之一”等条款。
6. 商务附表、空表和标准附件。
7. 投标相关日期：招标文件获取/报名起始日期、投标文件递交截止日期或开标日期。不要把交货、供货、服务期、工期、竣工、安装调试等履约日期写入 projectDates。

完整 JSON 必须包含 structured.sourceDocuments、structured.scoringCriteria、structured.fieldGroups、structured.requirementPresence、structured.coverage。每条 item、评分行和字段必须保留 sourceFile、sourceDocumentId、section、evidence、evidenceLocation。
""".strip()
    return f"""
Use the {profile.skill_name} skill.

你现在在做 S1 招标文件结构化解析。请调用解析 Skill 读取 manifest 中的多份招标文件文本，输出可直接给后端使用的结构化 JSON。

manifest：{skill_manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 600000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整结构化 JSON 写入 manifest.structuredResultPath，并只在 stdout 打印小型摘要 JSON：

s1parse {skill_manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schemaVersion": "{profile.schema_version}",
  "targetSkill": "{profile.skill_name}",
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
    profile: ParseProfile,
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
        structured["targetSkill"] = profile.skill_name
        structured["mode"] = "opencode-skill"
        structured["opencodeOutput"] = result.get("opencodeOutput") or {}
        structured["schemaVersion"] = str(structured.get("schemaVersion") or profile.schema_version)
    return resolved


def _run_parse_skill(
    skill_manifest_path: Path,
    *,
    local_result: dict[str, Any],
    profile: ParseProfile,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> tuple[dict[str, Any], str]:
    if not settings.s1_parse_opencode_enabled:
        return local_result, ""
    try:
        result = OpencodeClient().generate_tender_parse_with_trace(
            _build_tender_parse_prompt(skill_manifest_path, profile),
            stream_callback=(
                (lambda details: progress_callback("opencode_delta", details))
                if progress_callback
                else None
            ),
        )
        return _resolve_skill_structured_result(result, local_result=local_result, profile=profile), ""
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
    *,
    bid_type: str = "技术标",
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = resolve_parse_profile(bid_type)
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
    appendices = _prepare_appendix_outputs(project_id, appendices, renumber=True, profile=profile)
    structured_result["structured"]["appendices"] = appendices
    if profile.key == "business":
        structured_result = _transform_to_business_contract(
            project_id,
            structured_result,
            profile=profile,
            documents=documents,
            texts_by_id=texts_by_id,
            run_semantic_review=not settings.s1_parse_opencode_enabled,
        )
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
        "bidType": profile.bid_type,
        "parseProfile": profile.key,
        "targetSkill": profile.skill_name,
        "combinedTextPath": str(combined_text_path),
        "structuredResultPath": str(structured_path),
        "documents": documents,
        "targets": list(profile.targets),
    }
    skill_manifest_path.write_text(json.dumps(skill_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback("skill_manifest_ready", {"manifestPath": str(skill_manifest_path)})
    structured_result, skill_warning = _run_parse_skill(
        skill_manifest_path,
        local_result=structured_result,
        profile=profile,
        progress_callback=progress_callback,
    )
    should_finalize_business_semantics = (
        profile.key == "business"
        and isinstance(structured_result.get("structured"), dict)
        and (
            str(structured_result["structured"].get("mode") or "").strip() == "opencode-skill"
            or (settings.s1_parse_opencode_enabled and bool(skill_warning))
        )
    )
    if should_finalize_business_semantics:
        structured_result = _transform_to_business_contract(
            project_id,
            structured_result,
            profile=profile,
            documents=documents,
            texts_by_id=texts_by_id,
            run_semantic_review=True,
        )
    resolved_structured = structured_result.setdefault("structured", {})
    if not resolved_structured.get("appendices"):
        resolved_structured["appendices"] = appendices
    elif isinstance(resolved_structured.get("appendices"), list):
        resolved_structured["appendices"] = _prepare_appendix_outputs(
            project_id,
            resolved_structured["appendices"],
            renumber=True,
            profile=profile,
        )
    if profile.key == "business" and isinstance(resolved_structured.get("commitmentLetters"), list):
        resolved_structured["commitmentLetters"] = _prepare_commitment_letter_outputs(
            project_id,
            resolved_structured.get("commitmentLetters") or [],
            renumber=True,
            profile=profile,
            project_name=_business_project_name_from_structured(resolved_structured),
            tenderer_name=_business_tenderer_name_from_structured(resolved_structured),
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
        "targetSkill": profile.skill_name,
        "categoryCounts": structured.get("categoryCounts") or {},
        "projectDates": {
            "startDate": project_dates.get("startDate") or "",
            "endDate": project_dates.get("endDate") or "",
        },
        "appendixCount": len(structured.get("appendices") or []),
    }
    if profile.key == "business":
        summary["commitmentLetterCount"] = len(structured.get("commitmentLetters") or [])

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
        "bidType": profile.bid_type,
        "parseProfile": profile.key,
        "documents": documents,
        "items": items,
        "structured": structured,
        "projectUpdates": {
            "startDate": project_dates.get("startDate") or "",
            "endDate": project_dates.get("endDate") or "",
            "deadline": project_dates.get("endDate") or "",
        },
    }
