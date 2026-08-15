"""商务字段识别：FieldSpec 族、项目基础信息、资格/承诺/评分提取与商务契约总装。

来源：parsing-01 拆分，自 app/services/parsing.py 逐字搬迁，实现与行为不变；
符号经 parsing.py 门面 re-export，外部仍按 `app.services.parsing.<符号>` 访问。
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.services.agent_engine.factory import AgentEngineFactory
from app.services.parse_common import (
    _detect_business_format_regions,
    _iter_docx_blocks,
    _run_coroutine_blocking,
)
from app.services.parse_profiles import ParseProfile


BID_DEADLINE_DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?"
    r"(?:[\sT]*(?P<hour>\d{1,2})\s*(?:时|:|：)\s*(?P<minute>\d{1,2})\s*分?)?"
)
LABEL_VALUE_PATTERN = re.compile(r"^\s*(?P<label>[^:：]{2,40})\s*[:：]\s*(?P<value>.+?)\s*$")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[（(]?\d+[）)]?)\s*[、.．\s]+")

BID_DEADLINE_CONTEXT = ("递交截止时间", "投标文件递交截止时间", "投标截止时间", "提交截止时间")
OPENING_TIME_CONTEXT = ("开标时间", "开标日期", "开标时间和地点", "开标地点")


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

QUALIFICATION_SECTION_ANCHORS = (
    "投标人资格要求",
    "投标人资格条件",
    "资格能力要求",
    "专用资格条件",
    "通用资格条件",
    "合格投标人资格",
    "供应商资格要求",
    "资质条件、能力和信誉",
)

QUALIFICATION_STOP_ANCHORS = (
    "投标文件的组成",
    "投标报价",
    "投标保证金",
    "投标人须知",
    "资格审查资料",
    "评标办法",
    "符合性审查",
    "商务评分",
    "技术评分",
    "投标文件格式",
    "合同条款",
)

QUALIFICATION_EXCLUDE_KEYWORDS = (
    "资格审查资料",
    "复印件",
    "扫描件",
    "附件",
    "评分",
    "得分",
    "分值",
    "满分",
    "基础分",
    "加分",
    "否决",
    "废标",
    "不予受理",
    "目录",
    "页码",
    "见投标人须知前附表",
    "见评标办法前附表",
    "同招标公告",
)

QUALIFICATION_REQUIRED_CUES = (
    "投标人",
    "投标机型",
    "供应商",
    "联合体",
    "须",
    "应",
    "需",
    "具有",
    "具备",
    "不得",
    "不允许",
    "不接受",
    "没有处于",
    "未被",
)

SCOPE_PATTERN = re.compile(
    r"^(?:"
    r"标段[一二三四五六七八九十\d]+(?:[、至和及,\-]+标段?[一二三四五六七八九十\d]+)*"
    r"|第[一二三四五六七八九十\d]+标段"
    r"|所有标段"
    r"|全部标段"
    r"|本项目"
    r")(?:（[^）]*）)?[:：]?$"
)
CLAUSE_PATTERN = re.compile(r"^(?:\d+(?:\.\d+){1,4}|[（(][一二三四五六七八九十\d]+[）)]|[一二三四五六七八九十\d]+[、.．])\s*")

BUSINESS_CORE_PROJECT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("projectName", "项目名称", ("项目名称", "招标项目名称", "采购项目名称")),
    FieldSpec("tenderNo", "招标编号", ("招标编号", "项目编号", "招标文件编号", "采购编号", "采购项目编号")),
    FieldSpec("tenderer", "招标人", ("招标人", "采购人", "采购单位", "业主", "建设单位", "项目单位")),
    FieldSpec("tenderAgency", "招标代理机构", ("招标代理机构", "采购代理机构", "代理机构")),
    FieldSpec("bidDeadline", "递交截止时间", ("递交截止时间", "投标截止时间", "投标文件递交截止时间", "提交截止时间", "响应文件提交截止时间", "响应截止时间", "提交响应文件截止时间")),
)

COMMERCIAL_REJECTION_KEYWORDS = (
    "否决",
    "废标",
    "无效投标",
    "不予受理",
    "★",
    "实质性响应",
    "投标人不得存在",
    "不得存在下列情形",
)

SCORING_SCORE_PATTERN = re.compile(r"(?P<item>[\u4e00-\u9fa5A-Za-z0-9（）()、/]+?)\s*(?P<score>\d+(?:\.\d+)?\s*分)")
MARKDOWN_TABLE_LINE_PATTERN = re.compile(r"^\s*\|.*\|\s*$")
BIDDER_INSTRUCTION_TABLE_TITLE = "投标人须知前附表"


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


def _copy_meta_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceFile": str(item.get("sourceFile") or ""),
        "sourceDocumentId": str(item.get("sourceDocumentId") or ""),
        "section": str(item.get("section") or ""),
        "evidence": str(item.get("evidence") or ""),
        "evidenceLocation": str(item.get("evidenceLocation") or ""),
    }


def _qualification_source_text(*, source_file: str, section: str, clause_no: str = "") -> str:
    parts = [part.strip(" ：:") for part in (section, clause_no) if str(part or "").strip()]
    readable = " > ".join(dict.fromkeys(parts))
    if readable:
        return f"{source_file}：{readable}"
    return source_file


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


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def _is_reference_only_value(value: str) -> bool:
    normalized = re.sub(r"\s+", "", str(value or ""))
    if not normalized:
        return False
    if normalized in {
        "见招标公告",
        "见采购公告",
        "详见采购公告",
        "见投标人须知前附表",
        "详见招标公告",
        "详见技术规范书",
        "详见招标文件",
        "按招标文件要求",
    }:
        return True
    return bool(re.match(r"^(?:详见|见|参见|按|同)", normalized)) and any(
        token in normalized
        for token in (
            "招标公告",
            "采购公告",
            "投标人须知前附表",
            "供应商须知前附表",
            "招标文件",
            "采购文件",
            "技术规范书",
        )
    )


def _is_bid_deadline_relative_context(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return bool(
        re.search(r"投标截止时间\d{1,3}(?:日|天)前", compact)
        or re.search(r"收到(?:澄清|修改)后\d{1,3}小时内", compact)
        or re.search(r"开标结束后\d{1,3}分钟内", compact)
    )


def _business_project_value_usable(spec: FieldSpec, value: str, evidence: str = "") -> bool:
    cleaned = _clean(value).strip(" ：:；;，,。")
    if not cleaned or _is_reference_only_value(cleaned):
        return False
    if spec.key == "bidDeadline":
        normalized = _normalize_bid_deadline(cleaned)
        combined = f"{evidence} {cleaned}"
        is_opening_time = "开标" in combined and not any(token in combined for token in ("递交截止", "投标截止", "提交截止", "响应截止"))
        return _is_normalized_bid_deadline(normalized) and not is_opening_time and not _is_bid_deadline_relative_context(combined)
    if spec.key in {"tenderer", "tenderAgency"}:
        if len(cleaned) > 100:
            return False
        if any(keyword in cleaned for keyword in ("联系人", "联系方式", "联系电话", "电话", "邮箱", "电子邮件", "地址")):
            return False
        combined = f"{evidence} {cleaned}"
        if any(keyword in combined for keyword in ("招标人代表", "采购人代表", "异议", "投诉", "质疑", "服务费", "代理服务费", "招标人不接受", "采购人不接受")):
            return False
        if re.search(r"(?:现)?委托.+(?:招标|采购|代理)", cleaned):
            return False
        if "，" in cleaned and any(token in cleaned for token in ("进行公开招标", "进行采购", "项目业主为")):
            return False
    if spec.key == "projectName" and len(cleaned) > 160:
        return False
    return True


def _block_number(location: str) -> int:
    match = re.match(r"B(\d+)", str(location or ""))
    return int(match.group(1)) if match else 0


def _business_core_field_score(item: dict[str, Any], spec: FieldSpec) -> int:
    value = str(item.get("value") or item.get("keyValue") or "").strip()
    section = str(item.get("section") or "")
    evidence = str(item.get("evidence") or "")
    location = str(item.get("evidenceLocation") or "")
    block_no = _block_number(location)
    score = 0
    if location.startswith("B"):
        score += 40
        if 0 < block_no <= 30:
            score += 25
    if section == "封面":
        score += 90
    if "投标人须知前附表" in section:
        score += 80
    if "招标公告" in section or "联系方式" in section:
        score += 50
    if _is_reference_only_value(value):
        score -= 220
    if re.search(r"\d{4}-\d{2}-\d{2}|20\d{2}年", value):
        score += 30
    if spec.key == "bidDeadline":
        haystack = " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "value", "evidence", "section"))
        if any(token in haystack for token in BID_DEADLINE_CONTEXT):
            score += 120
        if any(token in haystack for token in OPENING_TIME_CONTEXT):
            score -= 180
        if _is_normalized_bid_deadline(_normalize_bid_deadline(" ".join(part for part in (value, evidence) if part))):
            score += 120
        else:
            score -= 260
    if spec.key == "projectName":
        if "项目" in value and len(value) <= 120:
            score += 45
        if value.endswith("招标") or "采购" in value:
            score += 20
    if spec.key == "tenderNo":
        if re.search(r"[A-Z]{2,}.*\d", value):
            score += 70
        if value in {"招标编号", "项目编号", "招标文件编号"}:
            score -= 100
    if spec.key in {"tenderer", "tenderAgency"}:
        if len(value) <= 100:
            score += 35
        if "：" in value or ":" in value:
            score -= 10
    if len(value) > 180:
        score -= 50
    if not value:
        score -= 300
    if "目录" in evidence:
        score -= 60
    return score


def _normalize_bid_deadline(value: str) -> str:
    text = str(value or "").strip()
    matches = list(BID_DEADLINE_DATE_PATTERN.finditer(text))
    if not matches:
        return text
    first_date = ""
    for match in matches:
        try:
            parsed = date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
        normalized = parsed.isoformat()
        if not first_date:
            first_date = normalized
        hour = match.group("hour")
        minute = match.group("minute")
        if hour is None or minute is None:
            continue
        hour_int = int(hour)
        minute_int = int(minute)
        if hour_int > 23 or minute_int > 59:
            continue
        return f"{normalized} {hour_int:02d}:{minute_int:02d}"
    return first_date or text


def _is_normalized_bid_deadline(value: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}(?: \d{2}:\d{2})?", str(value or "").strip()))


def _strip_core_party_contact_tail(value: str) -> str:
    text = _clean(value).strip(" ：:")
    tail_match = re.search(
        r"\s*(?:地\s*址|联\s*系\s*人|电\s*话|电子\s*邮\s*件|邮\s*箱|传\s*真|网\s*址)\s*[：:]",
        text,
    )
    if tail_match:
        text = text[: tail_match.start()]
    return text.strip(" ：:")


def _normalize_core_field_value(spec: FieldSpec, value: str) -> str:
    cleaned = _clean(value)
    if spec.key == "bidDeadline":
        return _normalize_bid_deadline(cleaned)
    stripped = cleaned
    for alias in sorted(spec.aliases, key=len, reverse=True):
        alias_pattern = r"\s*".join(re.escape(char) for char in alias)
        stripped_candidate = re.sub(rf"^\s*{alias_pattern}\s*[：:]\s*", "", cleaned, count=1)
        if stripped_candidate != cleaned:
            stripped = stripped_candidate.strip()
            break
    if spec.key in {"tenderer", "tenderAgency"}:
        return _strip_core_party_contact_tail(stripped)
    return stripped


def _build_business_project_basics(
    items: list[dict[str, Any]],
    project_dates: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    project_dates = project_dates or {}
    fields: list[dict[str, Any]] = []
    for spec in BUSINESS_CORE_PROJECT_FIELDS:
        project_deadline_value = ""
        if spec.key == "bidDeadline":
            project_deadline_value = _normalize_bid_deadline(str(project_dates.get("endDate") or ""))
        candidates = [
            item
            for item in items
            if any(
                alias in " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "evidence", "section"))
                for alias in spec.aliases
            )
        ]
        candidates = [
            item
            for item in candidates
            if _business_project_value_usable(
                spec,
                str(item.get("value") or item.get("keyValue") or ""),
                str(item.get("evidence") or ""),
            )
        ]
        if spec.key == "bidDeadline":
            candidates = [
                item
                for item in candidates
                if (
                    any(
                        token in " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "evidence", "section", "value"))
                        for token in BID_DEADLINE_CONTEXT
                    )
                    and not any(
                        token in " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "evidence", "section"))
                        for token in OPENING_TIME_CONTEXT
                    )
                    and _is_normalized_bid_deadline(
                        _normalize_bid_deadline(
                            " ".join(
                                str(item.get(key) or "")
                                for key in ("value", "keyValue", "evidence")
                                if str(item.get(key) or "").strip()
                            )
                        )
                    )
                )
            ]
        matched = max(candidates, key=lambda item: _business_core_field_score(item, spec)) if candidates else None
        if matched and _business_core_field_score(matched, spec) > -50:
            if spec.key == "bidDeadline":
                normalized = _normalize_core_field_value(
                    spec,
                    " ".join(
                        str(matched.get(key) or "")
                        for key in ("value", "keyValue", "evidence")
                        if str(matched.get(key) or "").strip()
                    ),
                )
                project_dates["endDate"] = normalized
            else:
                normalized = _normalize_core_field_value(spec, str(matched.get("value") or matched.get("keyValue") or ""))
            fields.append(_business_field_from_item(spec, matched, value_override=normalized))
        elif spec.key == "bidDeadline" and project_deadline_value:
            project_dates["endDate"] = project_deadline_value
            field = _empty_business_field(spec, value=project_deadline_value)
            field["status"] = "found"
            field["confidence"] = 0.78
            fields.append(field)
        else:
            fields.append(_empty_business_field(spec))
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


def _new_docx_candidate_item(
    items: list[dict[str, Any]],
    *,
    document: dict[str, Any],
    label: str,
    value: str,
    section: str,
    evidence: str,
    location: str,
    confidence: float = 0.86,
) -> None:
    cleaned_label = _clean(label)
    cleaned_value = _clean(value)
    if not cleaned_label or not cleaned_value:
        return
    items.append(
        {
            "id": f"DOCX-{len(items) + 1:04d}",
            "type": "商务核心字段候选",
            "category": "business_core_candidate",
            "title": cleaned_label,
            "keyEntity": cleaned_label,
            "keyValue": cleaned_value,
            "value": cleaned_value,
            "sourceFile": str(document.get("name") or document.get("id") or "招标文件"),
            "sourceDocumentId": str(document.get("id") or ""),
            "section": section,
            "evidence": evidence,
            "evidenceLocation": location,
            "confidence": confidence,
        }
    )


def _is_docx_source(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".docx"


def _document_text_lines(document: dict[str, Any], texts_by_id: dict[str, str]) -> list[dict[str, Any]]:
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    text = str(texts_by_id.get(document_id) or "")
    lines: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _clean(raw_line)
        if not line:
            continue
        lines.append(
            {
                "text": line,
                "sourceFile": source_file,
                "sourceDocumentId": document_id,
                "evidenceLocation": f"L{line_number}",
            }
        )
    return lines


def _qualification_heading_level(text: str) -> int:
    stripped = str(text or "").strip()
    match = re.match(r"^(\d+(?:\.\d+){0,4})\s+", stripped)
    if not match:
        return 99
    return match.group(1).count(".") + 1


def _is_qualification_anchor(text: str) -> bool:
    return any(anchor in text for anchor in QUALIFICATION_SECTION_ANCHORS)


def _is_qualification_stop(text: str, active_root_level: int) -> bool:
    if not text:
        return False
    if any(anchor in text for anchor in QUALIFICATION_STOP_ANCHORS):
        return True
    level = _qualification_heading_level(text)
    return level <= active_root_level and not _is_qualification_anchor(text)


def _normalize_qualification_content(text: str) -> str:
    value = _clean(text)
    value = re.sub(r"^\d+(?:\.\d+){1,4}\s*", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十\d]+[）)]\s*", "", value)
    value = re.sub(r"^[一二三四五六七八九十\d]+[、.．]\s*", "", value)
    value = value.strip(" ：:；;。")
    return value


def _looks_like_scope_heading(text: str) -> bool:
    return bool(SCOPE_PATTERN.match(str(text or "").strip()))


def _looks_like_qualification_intro_line(text: str) -> bool:
    value = _normalize_qualification_content(text)
    return bool(
        re.search(r"(?:下列|如下|以下)(?:条件|要求|规定)$", value)
        or re.search(r"(?:应|需)(?:具备|满足|符合).*(?:下列|如下|以下)(?:条件|要求|规定)$", value)
    )


def _normalize_qualification_scope(text: str) -> str:
    value = str(text or "").strip()
    value = re.split(r"[（(]", value, maxsplit=1)[0]
    return value.strip(" ：:")


def _looks_like_qualification_requirement(text: str) -> bool:
    value = _normalize_qualification_content(text)
    if len(value) < 8:
        return False
    if _looks_like_scope_heading(value):
        return False
    if _looks_like_qualification_intro_line(value):
        return False
    compact = re.sub(r"\s+", "", value)
    if re.search(r"\t\d+$|\.{3,}\d+$", value):
        return False
    if any(keyword in value for keyword in QUALIFICATION_EXCLUDE_KEYWORDS):
        return False
    if compact in {"见评标办法前附表", "见投标人须知前附表", "同招标公告"}:
        return False
    return any(cue in value for cue in QUALIFICATION_REQUIRED_CUES)


def _extract_qualification_requirements_from_documents(
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for document in documents:
        source_file = str(document.get("name") or document.get("id") or "招标文件")
        document_id = str(document.get("id") or "")
        active = False
        active_root_level = 99
        section_path: list[tuple[int, str]] = []
        applicable_scope = "全部标段"

        for line in _document_text_lines(document, texts_by_id):
            text = str(line["text"])
            level = _qualification_heading_level(text)

            if _is_qualification_anchor(text):
                was_active = active
                active = True
                if level < 99 and (not was_active or active_root_level == 99):
                    active_root_level = level
                if level < 99:
                    section_path = [(old_level, title) for old_level, title in section_path if old_level < level]
                    section_path.append((level, text))
                elif not section_path:
                    section_path = [(1, text)]
                continue

            if not active:
                continue

            if _is_qualification_stop(text, active_root_level):
                active = False
                section_path = []
                applicable_scope = "全部标段"
                continue

            if level < 99:
                section_path = [(old_level, title) for old_level, title in section_path if old_level < level]
                section_path.append((level, text))
                applicable_scope = "全部标段"

            if _looks_like_scope_heading(text):
                applicable_scope = _normalize_qualification_scope(text)
                continue

            if not _looks_like_qualification_requirement(text):
                continue

            content = _normalize_qualification_content(text)
            section = " > ".join(title for _, title in section_path) or "投标人资格要求"
            clause_no_match = re.match(r"^(\d+(?:\.\d+){1,4}|[（(][一二三四五六七八九十\d]+[）)])", text)
            clause_no = clause_no_match.group(1) if clause_no_match else ""
            dedupe_key = (content, applicable_scope, section)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(
                {
                    "id": f"QUAL-{len(rows) + 1:04d}",
                    "order": len(rows) + 1,
                    "content": content,
                    "applicableScope": applicable_scope or "全部标段",
                    "sourceText": _qualification_source_text(
                        source_file=source_file,
                        section=section,
                        clause_no=clause_no,
                    ),
                    "sourceFile": source_file,
                    "sourceDocumentId": document_id,
                    "section": section,
                    "evidence": text,
                    "evidenceLocation": str(line.get("evidenceLocation") or ""),
                    "confidence": 0.9,
                }
            )

    return rows


def _extract_docx_core_candidate_items(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if not _is_docx_source(source_path):
            continue
        blocks = _iter_docx_blocks(source_path)
        current_section = "封面"
        for block_index, block in enumerate(blocks, start=1):
            if block.get("type") == "paragraph":
                text = _clean(block.get("text"))
                if text:
                    current_section = text
                continue
            if block.get("type") != "table":
                continue
            rows = block.get("rows") or []
            section = current_section or ("封面" if block_index <= 30 else "")
            for row_index, row in enumerate(rows, start=1):
                cells = [_clean(cell) for cell in row if _clean(cell)]
                if len(cells) < 2:
                    continue
                _new_docx_candidate_item(
                    items,
                    document=document,
                    label=cells[0].strip(" ：:"),
                    value=cells[-1].strip(" ：:"),
                    section=section,
                    evidence=" | ".join(cells),
                    location=f"B{block_index}/R{row_index}",
                    confidence=0.9 if block_index <= 30 or "投标人须知前附表" in section else 0.82,
                )
    return items


def _strip_bidder_instruction_title_prefix(text: str) -> str:
    cleaned = _clean(text).strip("# ").strip(" ：:。；;")
    cleaned = re.sub(r"^\s*第?[一二三四五六七八九十百千0-9]+[章节条]?\s*[、.．\s]+", "", cleaned)
    return re.sub(r"\s+", "", cleaned)


def _is_bidder_instruction_title_anchor(text: str) -> bool:
    compact = _strip_bidder_instruction_title_prefix(text)
    if not compact.startswith(BIDDER_INSTRUCTION_TABLE_TITLE):
        return False
    suffix = compact.removeprefix(BIDDER_INSTRUCTION_TABLE_TITLE)
    return bool(re.fullmatch(r"(?:[0-9一二三四五六七八九十百千页（）()、.．:-]*)", suffix))


def _docx_table_after_bidder_instruction_anchor(
    blocks: list[dict[str, Any]],
    anchor_index: int,
    *,
    max_text_gap: int,
) -> tuple[int, list[list[str]]] | None:
    gap = 0
    index = anchor_index + 1
    while index < len(blocks):
        block = blocks[index]
        if block.get("type") == "table":
            rows = [[_clean(cell) for cell in row] for row in block.get("rows") or [] if any(_clean(cell) for cell in row)]
            return (index, rows) if gap <= max_text_gap and len(rows) > 1 else None
        text = _clean(block.get("text")) if block.get("type") == "paragraph" else ""
        if text:
            gap += 1
            if gap > max_text_gap:
                return None
        index += 1
    return None


def _parse_bidder_instruction_rows(
    rows: list[list[str]],
    *,
    document: dict[str, Any],
    section: str,
    block_index: int,
    table_title: str = BIDDER_INSTRUCTION_TABLE_TITLE,
) -> list[dict[str, Any]]:
    cleaned_rows = [[_clean(cell) for cell in row] for row in rows if any(_clean(cell) for cell in row)]
    if len(cleaned_rows) <= 1:
        return []
    header = cleaned_rows[0]
    parsed: list[dict[str, Any]] = []
    for row_index, row in enumerate(cleaned_rows[1:], start=2):
        if len(row) < 2:
            continue
        clause_no = row[0]
        clause_name = row[1]
        content = "；".join(cell for cell in row[2:] if cell).strip()
        if not clause_no and not clause_name and not content:
            continue
        parsed.append(
            {
                "id": f"BIDDER-INST-{len(parsed) + 1:04d}",
                "clauseNo": clause_no,
                "clauseName": clause_name,
                "content": content,
                "headers": header,
                "cells": row,
                "tableTitle": table_title or BIDDER_INSTRUCTION_TABLE_TITLE,
                "tableLocation": f"B{block_index}",
                "sourceFile": str(document.get("name") or ""),
                "sourceDocumentId": str(document.get("id") or ""),
                "section": section,
                "evidence": "；".join(
                    f"{header[index]}：{cell}" if index < len(header) and header[index] else cell
                    for index, cell in enumerate(row)
                    if cell
                ),
                "evidenceLocation": f"B{block_index}/R{row_index}",
                "confidence": 0.9,
            }
        )
    return parsed


def _extract_bidder_instruction_rows(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if not _is_docx_source(source_path):
            continue
        blocks = _iter_docx_blocks(source_path)
        anchors = [
            (index, _clean(block.get("text")))
            for index, block in enumerate(blocks)
            if block.get("type") == "paragraph" and _is_bidder_instruction_title_anchor(str(block.get("text") or ""))
        ]
        for max_text_gap in (0, 3):
            for anchor_index, anchor_title in anchors:
                match = _docx_table_after_bidder_instruction_anchor(blocks, anchor_index, max_text_gap=max_text_gap)
                if not match:
                    continue
                table_index, rows = match
                return _parse_bidder_instruction_rows(
                    rows,
                    document=document,
                    section=anchor_title or BIDDER_INSTRUCTION_TABLE_TITLE,
                    block_index=table_index + 1,
                    table_title=anchor_title or BIDDER_INSTRUCTION_TABLE_TITLE,
                )
    return []


def _build_qualification_requirements(
    items: list[dict[str, Any]],
    *,
    documents: list[dict[str, Any]] | None = None,
    texts_by_id: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if documents is not None and texts_by_id is not None:
        rows = _extract_qualification_requirements_from_documents(documents, texts_by_id)
        if rows:
            return rows

    keywords = ("投标人资格要求", "资格要求", "资格能力要求", "投标人资质条件", "合格投标人")
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "value", "evidence", "section"))
        if not any(keyword in text for keyword in keywords):
            continue
        content = str(item.get("evidence") or item.get("value") or "").strip()
        if not _looks_like_qualification_requirement(content):
            continue
        content = _normalize_qualification_content(content)
        if not content or content in seen:
            continue
        seen.add(content)
        source_file = str(item.get("sourceFile") or "招标文件")
        section = str(item.get("section") or item.get("title") or "投标人资格要求")
        matched.append(
            {
                "id": f"QUAL-{len(matched) + 1:04d}",
                "order": len(matched) + 1,
                "content": content,
                "applicableScope": "全部标段",
                "sourceText": _qualification_source_text(source_file=source_file, section=section),
                **_copy_meta_fields(item),
                "confidence": float(item.get("confidence") or 0.78),
            }
        )
    return matched[:12]


def _extract_commercial_rejection_clauses(
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        current_section = ""
        for line_number, raw_line in enumerate(str(texts_by_id.get(document_id) or "").splitlines(), start=1):
            line = _clean(raw_line)
            if not line:
                continue
            if _looks_like_section_heading(line):
                current_section = line
            if not any(keyword in line for keyword in COMMERCIAL_REJECTION_KEYWORDS):
                continue
            if line in seen:
                continue
            seen.add(line)
            matched_keywords = [keyword for keyword in COMMERCIAL_REJECTION_KEYWORDS if keyword in line]
            clauses.append(
                {
                    "id": f"REJECT-{len(clauses) + 1:04d}",
                    "title": current_section or "商务废标项",
                    "content": line,
                    "matchedKeywords": matched_keywords,
                    "riskLevel": "high"
                    if any(keyword in matched_keywords for keyword in ("否决", "废标", "无效投标", "不予受理"))
                    else "medium",
                    "sourceFile": source_file,
                    "sourceDocumentId": document_id,
                    "section": current_section,
                    "evidence": line,
                    "evidenceLocation": f"L{line_number}",
                    "confidence": 0.82,
                }
            )
    return clauses


def _line_has_explicit_commitment_obligation(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return False
    if "不得存在下列情形" in normalized:
        return True
    if any(hint in normalized for hint in COMMITMENT_GENERATION_HINTS):
        return True
    has_commitment = "承诺" in normalized
    has_obligation = any(token in normalized for token in ("须", "应", "需", "必须", "无条件"))
    has_doc_action = any(token in normalized for token in ("提供", "提交", "出具", "附", "另附", "递交"))
    has_doc_name = any(token in normalized for token in (*COMMITMENT_DOC_KEYWORDS, "书面承诺", "承诺材料"))
    return has_commitment and has_obligation and (has_doc_action or has_doc_name)


def _find_commitment_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item.get(key) or "") for key in ("title", "value", "evidence", "section"))
        category = str(item.get("category") or "")
        key_entity = str(item.get("keyEntity") or "")
        title = str(item.get("title") or "")
        evidence = str(item.get("evidence") or "")
        if "承诺" not in text and "不得存在下列情形" not in text:
            continue
        if category == "project_basics" and key_entity == "项目名称":
            continue
        if title == "项目名称" and evidence.startswith("项目名称"):
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
    "需提供书面承诺",
    "须出具承诺函",
    "须出具承诺书",
    "须无条件承诺",
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
    "等效满负荷小时",
    "满负荷小时",
    "保证年等效",
    "保证小时",
    "发电小时",
    "发电量",
    "上网电量",
    "电量",
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
    ("certificate_obtainment", ("取得本条", "取得材料", "取得证书", "取得认证", "供货前取得"), "材料取得承诺书"),
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
    ("certificate_obtainment", ("取得本条", "取得材料", "取得证书", "取得认证", "供货前取得")),
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


def _normalize_commitment_title_by_topic(topic_key: str, title: str, item: dict[str, Any]) -> str:
    if topic_key == "certificate_obtainment":
        return "材料取得承诺书"
    if topic_key == "disqualification":
        return "投标人不存在下列情形之一承诺函"
    return title.strip() or _preferred_commitment_title(item, str(item.get("triggerText") or "承诺"))


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
    if "须无条件承诺" in normalized:
        return "须无条件承诺"
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
                "id": str(item.get("semanticReviewId") or item.get("id") or ""),
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
        "7. 发电量、功率、满负荷小时数、性能保证、机组技术参数等技术标承诺不要生成商务承诺文件，action=ignore。\n"
        "8. preferredTitle 只在 action=generate 时填写，且应是适合最终文件名的主题名称。\n\n"
        f"候选列表：\n{json.dumps(records, ensure_ascii=False, indent=2)}"
    )


def _review_commitment_candidates_semantically(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not candidates:
        return {}
    try:
        # 默认引擎经 AgentEngineFactory 取（默认恒为 opencode，行为不变）；
        # 保留 OpencodeEngine 门面调用——既有测试经模块符号 patch 该类方法。
        result = _run_coroutine_blocking(AgentEngineFactory.create().review_business_commitments_with_trace(
            _build_commitment_semantic_review_prompt(candidates)
        ))
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


def _commitment_review_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("sourceFile") or ""),
        str(item.get("evidenceLocation") or ""),
        re.sub(r"\s+", "", str(item.get("evidence") or item.get("value") or item.get("title") or "")),
    )


def _commitment_decision_for_item(
    item: dict[str, Any],
    reviewed: dict[str, dict[str, Any]],
    reviewed_by_signature: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    for item_id in (str(item.get("semanticReviewId") or ""), str(item.get("id") or "")):
        if item_id and item_id in reviewed:
            return reviewed[item_id], True
    signature = _commitment_review_signature(item)
    if signature in reviewed_by_signature:
        return reviewed_by_signature[signature], True
    return {}, False


def _commitment_decision_action(decision: dict[str, Any], default: str = "clue") -> str:
    action = str(decision.get("action") or default).strip().lower()
    return action if action in {"generate", "clue", "ignore"} else default


def _append_semantic_commitment_candidate(
    item: dict[str, Any],
    *,
    base: dict[str, Any],
    semantic_candidates: list[dict[str, Any]],
    semantic_candidate_ids: set[str],
    semantic_candidate_signatures: set[tuple[str, str, str]],
    force_generate_on_fallback: bool = False,
) -> None:
    item_id = str(item.get("id") or "")
    signature = _commitment_review_signature(item)
    if item_id and (item_id in semantic_candidate_ids or signature in semantic_candidate_signatures):
        return
    if item_id:
        semantic_candidate_ids.add(item_id)
    semantic_candidate_signatures.add(signature)
    semantic_candidates.append(
        {
            **item,
            **base,
            "forceGenerateOnFallback": force_generate_on_fallback,
        }
    )


def _append_commitment_letter(
    letters: list[dict[str, Any]],
    generated_topics: set[str],
    item: dict[str, Any],
    *,
    topic_key: str,
    title: str,
    commitment_type: str,
    risk_flags: list[str],
) -> bool:
    if topic_key in generated_topics:
        return False
    generated_topics.add(topic_key)
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
            "riskFlags": risk_flags,
            "previewType": "onlyoffice",
        }
    )
    return True


def _append_commitment_clue(
    clues: list[dict[str, Any]],
    clue_topics: set[tuple[str, str]],
    item: dict[str, Any],
    *,
    topic_key: str,
    recommended_action: str,
    risk_flags: list[str],
) -> bool:
    trigger_context = str(item.get("triggerContext") or item.get("evidence") or item.get("value") or "").strip()
    clue_key = (topic_key, trigger_context)
    if clue_key in clue_topics:
        return False
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
            "triggerContext": trigger_context,
            "recommendedAction": recommended_action,
            "riskFlags": risk_flags,
        }
    )
    return True


def _is_commitment_doc_required(item: dict[str, Any]) -> bool:
    text = _commitment_text(item)
    normalized = re.sub(r"\s+", "", text)
    if "不得存在下列情形" in normalized:
        return True
    if any(hint in normalized for hint in COMMITMENT_GENERATION_HINTS):
        return True
    if _line_has_explicit_commitment_obligation(normalized):
        return True
    if any(keyword in normalized for keyword in COMMITMENT_DOC_KEYWORDS):
        if _looks_like_bare_commitment_title(item):
            return False
        if str(item.get("category") or "") == "business_hint" and str(item.get("section") or "").strip() == str(item.get("evidence") or "").strip():
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
        normalized = re.sub(r"\s+", "", text)
        if topic_key == "disqualification" or "不得存在下列情形" in normalized:
            _append_commitment_letter(
                letters,
                generated_topics,
                {**item, **base},
                topic_key="disqualification",
                title="投标人不存在下列情形之一承诺函",
                commitment_type="disqualification",
                risk_flags=["template_pending", "legal_wording_review_required"],
            )
            continue

        if _is_commitment_doc_required(item):
            _append_semantic_commitment_candidate(
                item,
                base=base,
                semantic_candidates=semantic_candidates,
                semantic_candidate_ids=semantic_candidate_ids,
                semantic_candidate_signatures=semantic_candidate_signatures,
                force_generate_on_fallback=True,
            )
            continue

        if any(keyword in normalized for keyword in COMMITMENT_DOC_KEYWORDS):
            _append_semantic_commitment_candidate(
                item,
                base=base,
                semantic_candidates=semantic_candidates,
                semantic_candidate_ids=semantic_candidate_ids,
                semantic_candidate_signatures=semantic_candidate_signatures,
            )
            continue

        _append_commitment_clue(
            clues,
            clue_topics,
            {**item, **base},
            topic_key=topic_key,
            recommended_action="暂不自动生成，请人工确认是否需要单独承诺函/承诺书。",
            risk_flags=["ambiguous_requirement"],
        )

    reviewed = _review_commitment_candidates_semantically(semantic_candidates) if run_semantic_review else {}
    for index, item in enumerate(semantic_candidates[:COMMITMENT_SEMANTIC_REVIEW_MAX_ITEMS], start=1):
        item["semanticReviewId"] = f"RAW-{index:04d}"
    semantic_candidate_by_id: dict[str, dict[str, Any]] = {}
    for item in semantic_candidates:
        for key in (str(item.get("id") or ""), str(item.get("semanticReviewId") or "")):
            if key:
                semantic_candidate_by_id[key] = item
    reviewed_by_signature: dict[tuple[str, str, str], dict[str, Any]] = {}
    for reviewed_id, decision in reviewed.items():
        source_item = semantic_candidate_by_id.get(reviewed_id)
        if source_item:
            reviewed_by_signature[_commitment_review_signature(source_item)] = decision
    for item in semantic_candidates:
        decision, has_ai_decision = _commitment_decision_for_item(item, reviewed, reviewed_by_signature)
        has_ai_decision = bool(run_semantic_review and has_ai_decision)
        if has_ai_decision:
            action = _commitment_decision_action(decision)
        elif bool(item.get("forceGenerateOnFallback")):
            action = "generate"
            decision = {
                "topicKey": str(item.get("topicKey") or item.get("topic") or "commitment"),
                "preferredTitle": _preferred_commitment_title(item, str(item.get("triggerText") or "承诺")),
                "reason": "AI 语义复核未返回结果，按明确承诺要求规则兜底生成。",
            }
        else:
            action = "clue"
            decision = {
                "topicKey": str(item.get("topicKey") or item.get("topic") or "commitment"),
                "reason": "AI 语义复核未返回结果，保留为人工确认线索。",
            }

        topic_key = str(decision.get("topicKey") or item.get("topicKey") or item.get("topic") or "commitment").strip() or "commitment"
        if action == "ignore":
            continue
        if action == "generate":
            title = str(decision.get("preferredTitle") or "").strip() or _preferred_commitment_title(item, str(item.get("triggerText") or "承诺"))
            title = _normalize_commitment_title_by_topic(topic_key, title, item)
            commitment_type = "disqualification" if topic_key == "disqualification" else "general_commitment"
            risk_flags = ["semantic_review_passed", "legal_wording_review_required"] if has_ai_decision else ["rule_fallback_generated", "legal_wording_review_required"]
            _append_commitment_letter(
                letters,
                generated_topics,
                item,
                topic_key=topic_key,
                title=title,
                commitment_type=commitment_type,
                risk_flags=risk_flags,
            )
            continue

        _append_commitment_clue(
            clues,
            clue_topics,
            item,
            topic_key=topic_key,
            recommended_action=str(decision.get("reason") or "暂不自动生成，请人工确认是否需要单独承诺函/承诺书。").strip(),
            risk_flags=["semantic_review_required"] if has_ai_decision else ["semantic_review_unavailable"],
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
            *[alias for spec in PROJECT_BASIC_FIELDS for alias in spec.aliases if spec.key != "technicalCommitment"],
            *[alias for spec in BUSINESS_RESPONSE_FIELDS for alias in spec.aliases],
            *[alias for spec in QUALIFICATION_SUPPORT_FIELDS for alias in spec.aliases],
            *[alias for spec in COMMITMENT_REQUIREMENT_FIELDS for alias in spec.aliases],
            "投标人不得存在下列情形之一",
            "不得存在下列情形",
            "投标人需要说明的其他内容",
            "书面承诺",
            "无条件承诺",
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
            is_commitment_obligation = _line_has_explicit_commitment_obligation(line)
            if not matched_keyword and not is_commitment_obligation:
                continue
            dedupe_key = (document_id, line)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            label, value = _split_label_value(line, matched_keyword or "承诺要求")
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
                    "title": label or matched_keyword or "承诺要求",
                    "keyEntity": matched_keyword or "承诺要求",
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


def _scoring_bucket_from_title(title: str) -> str:
    text = re.sub(r"\s+", " ", str(title or "").replace("\u3000", " ")).strip()
    if not text:
        return ""
    if any(keyword in text for keyword in ("投标报价评分", "报价评分", "价格评分", "开标价格表", "报价表")):
        return "price"
    if any(keyword in text for keyword in ("符合性审查", "合规", "符合性", "审查标准")):
        return "compliance"
    if any(keyword in text for keyword in ("商务评分", "商务评审", "商务打分", "评标办法")):
        return "business"
    return ""


def _collect_markdown_table(lines: list[str], start_index: int) -> tuple[list[tuple[int, str]], int]:
    rows: list[tuple[int, str]] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        if not MARKDOWN_TABLE_LINE_PATTERN.match(line.strip()):
            break
        rows.append((index + 1, line))
        index += 1
    return rows, index


def _parse_markdown_scoring_rows(
    *,
    rows: list[tuple[int, str]],
    document: dict[str, Any],
    section: str,
    start_index: int,
) -> list[dict[str, Any]]:
    parsed_rows: list[dict[str, Any]] = []
    table_rows = [(line_no, _parse_markdown_table_row(line)) for line_no, line in rows]
    filtered_rows = [(line_no, cells) for line_no, cells in table_rows if cells and not _is_markdown_separator_row(cells)]
    if len(filtered_rows) <= 1:
        return parsed_rows
    data_rows = filtered_rows[1:]
    order = start_index
    for line_no, cells in data_rows:
        if len(cells) < 4:
            continue
        scoring_item = cells[1].strip() if len(cells) > 1 else ""
        score = cells[2].strip() if len(cells) > 2 else ""
        score_point = cells[3].strip() if len(cells) > 3 else ""
        proof_requirement = cells[4].strip() if len(cells) > 4 else ""
        if not scoring_item and not score_point:
            continue
        parsed_rows.append(
            {
                "order": str(order),
                "scoringItem": scoring_item,
                "score": score,
                "scorePoint": score_point,
                "proofRequirement": proof_requirement,
                "status": "found",
                "sourceFile": str(document.get("name") or ""),
                "sourceDocumentId": str(document.get("id") or ""),
                "section": section,
                "evidence": " | ".join(cell for cell in cells if cell),
                "evidenceLocation": f"L{line_no}",
            }
        )
        order += 1
    return parsed_rows


def _extract_markdown_scoring(documents: list[dict[str, Any]], texts_by_id: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    scoring = {"business": [], "price": [], "compliance": []}
    for document in documents:
        text = str(texts_by_id.get(str(document.get("id") or "")) or "")
        if "|" not in text:
            continue
        lines = text.splitlines()
        current_section = ""
        pending_scoring_title = ""
        index = 0
        while index < len(lines):
            raw_line = lines[index]
            line = raw_line.strip()
            if not line:
                index += 1
                continue
            if line.startswith("#"):
                current_section = line.strip("# ").strip()
                pending_scoring_title = ""
                index += 1
                continue

            bucket_from_line = _scoring_bucket_from_title(line)
            if _looks_like_section_heading(line):
                current_section = line
                pending_scoring_title = line if bucket_from_line else ""
                index += 1
                continue

            if bucket_from_line:
                pending_scoring_title = line
                if index + 1 < len(lines) and MARKDOWN_TABLE_LINE_PATTERN.match(lines[index + 1].strip()):
                    rows, next_index = _collect_markdown_table(lines, index + 1)
                    scoring[bucket_from_line].extend(
                        _parse_markdown_scoring_rows(
                            rows=rows,
                            document=document,
                            section=line,
                            start_index=len(scoring[bucket_from_line]) + 1,
                        )
                    )
                    pending_scoring_title = ""
                    index = next_index
                    continue

            if MARKDOWN_TABLE_LINE_PATTERN.match(line):
                bucket = _scoring_bucket_from_title(pending_scoring_title or current_section)
                if bucket:
                    rows, next_index = _collect_markdown_table(lines, index)
                    scoring[bucket].extend(
                        _parse_markdown_scoring_rows(
                            rows=rows,
                            document=document,
                            section=pending_scoring_title or current_section,
                            start_index=len(scoring[bucket]) + 1,
                        )
                    )
                    pending_scoring_title = ""
                    index = next_index
                    continue

            index += 1
    return scoring


def _merge_business_scoring(
    base_scoring: dict[str, Any],
    markdown_scoring: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    merged = _filter_business_scoring(base_scoring)
    seen = {
        bucket: {
            (
                str(row.get("sourceDocumentId") or ""),
                str(row.get("evidenceLocation") or ""),
                str(row.get("scoringItem") or ""),
                str(row.get("score") or ""),
            )
            for row in merged.get(bucket) or []
            if isinstance(row, dict)
        }
        for bucket in merged
    }
    for bucket, rows in markdown_scoring.items():
        for row in rows:
            key = (
                str(row.get("sourceDocumentId") or ""),
                str(row.get("evidenceLocation") or ""),
                str(row.get("scoringItem") or ""),
                str(row.get("score") or ""),
            )
            if key in seen[bucket]:
                continue
            seen[bucket].add(key)
            merged[bucket].append(row)
    return merged


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


def _normalized_business_match_text(value: str) -> str:
    return re.sub(
        r"(?:附件|附表)?[A-Za-z0-9一二三四五六七八九十]+|承诺函|承诺书|格式|模板|投标人|投标方|我方|本公司|\s+",
        "",
        str(value or ""),
    )


def _commitment_alignment_topics_for_template(appendix: dict[str, Any]) -> set[str]:
    template_type = str(appendix.get("templateType") or "").strip()
    text = re.sub(
        r"\s+",
        "",
        " ".join(
            str(appendix.get(key) or "")
            for key in ("title", "templateType", "templateTypeLabel", "evidence")
        ),
    )
    topics: set[str] = set()
    if template_type == "integrity_commitment" or "廉洁" in text:
        topics.add("integrity")
    if template_type == "performance_bond" or "履约保证" in text or "履约保函" in text:
        topics.add("performance_bond")
    if template_type == "bid_security" or "投标保证金" in text or "保证金" in text:
        topics.add("security")
    if "保密" in text:
        topics.add("confidentiality")
    if "不得存在下列情形" in text:
        topics.add("disqualification")
    if any(token in text for token in ("取得本条", "取得材料", "材料取得", "取得证书", "证书取得", "取得认证", "供货前取得")):
        topics.add("certificate_obtainment")
    if any(token in text for token in ("合规", "守法", "违法", "违规", "信用")):
        topics.add("compliance")
    if any(token in text for token in ("交货", "工期", "供货周期", "交付")):
        topics.update({"delivery", "delivery_commitment"})
    if any(token in text for token in ("质量", "质保", "售后", "服务承诺")):
        topics.update({"quality", "quality_commitment"})
    if template_type == "commitment" and not topics:
        topics.add("generic_commitment_template")
    return topics


def _commitment_template_can_cover_letter(letter: dict[str, Any], appendix: dict[str, Any]) -> bool:
    topic_key = str(letter.get("topicKey") or letter.get("topic") or "").strip()
    if not topic_key:
        return False
    template_topics = _commitment_alignment_topics_for_template(appendix)
    if topic_key in template_topics:
        return True
    if topic_key == "security" and "bid_security" in template_topics:
        return True
    if topic_key in {"delivery", "delivery_commitment"} and template_topics & {"delivery", "delivery_commitment"}:
        return True
    if topic_key in {"quality", "quality_commitment"} and template_topics & {"quality", "quality_commitment"}:
        return True
    return False


def _commitment_template_match_score(letter: dict[str, Any], appendix: dict[str, Any]) -> float:
    if not _commitment_template_can_cover_letter(letter, appendix):
        return 0.0
    letter_text = " ".join(
        str(letter.get(key) or "")
        for key in ("title", "topicKey", "triggerText", "triggerContext")
    )
    appendix_text = " ".join(
        str(appendix.get(key) or "")
        for key in ("title", "templateType", "templateTypeLabel", "evidence")
    )
    letter_normalized = _normalized_business_match_text(letter_text)
    appendix_normalized = _normalized_business_match_text(appendix_text)
    score = 0.74
    if not letter_normalized or not appendix_normalized:
        return score
    if letter_normalized in appendix_normalized or appendix_normalized in letter_normalized:
        return 0.92
    topic_key = str(letter.get("topicKey") or "")
    for key, keywords in COMMITMENT_TOPIC_KEYWORDS:
        if key == topic_key and any(keyword in appendix_text for keyword in keywords):
            score = max(score, 0.86)
    letter_tokens = {token for token in re.split(r"[、，,；;：:（）()]+", letter_normalized) if len(token) >= 2}
    appendix_tokens = {token for token in re.split(r"[、，,；;：:（）()]+", appendix_normalized) if len(token) >= 2}
    overlap = letter_tokens & appendix_tokens
    if letter_tokens and appendix_tokens and overlap:
        score = max(score, min(0.82, len(overlap) / max(len(letter_tokens), len(appendix_tokens)) + 0.35))
    return score


def _align_commitment_letters_with_existing_templates(
    letters: list[dict[str, Any]],
    appendices: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    templates = [
        item
        for item in appendices
        if isinstance(item, dict)
        and item.get("artifactType") == "business_attachment_template"
        and (
            str(item.get("templateType") or "") in {"commitment", "integrity_commitment", "performance_bond"}
            or any(token in str(item.get("title") or "") for token in COMMITMENT_DOC_KEYWORDS)
        )
    ]
    if not letters or not templates:
        return letters, []

    remaining: list[dict[str, Any]] = []
    alignments: list[dict[str, Any]] = []
    for letter in letters:
        scored = [
            (_commitment_template_match_score(letter, template), template)
            for template in templates
        ]
        score, template = max(scored, key=lambda item: item[0], default=(0.0, {}))
        if score >= 0.62 and isinstance(template, dict):
            alignments.append(
                {
                    "status": "covered_by_existing_template",
                    "requirementTitle": str(letter.get("title") or ""),
                    "requirementTopicKey": str(letter.get("topicKey") or ""),
                    "requirementSource": str(letter.get("triggerContext") or letter.get("evidence") or ""),
                    "matchedTemplateId": str(template.get("id") or ""),
                    "matchedTemplateTitle": str(template.get("title") or ""),
                    "matchedTemplateType": str(template.get("templateType") or ""),
                    "confidence": round(score, 3),
                }
            )
            continue
        remaining.append(letter)
    return remaining, alignments


BUSINESS_PROJECT_FACT_FIELD_SPECS: tuple[dict[str, Any], ...] = (
    {"fieldKey": "projectName", "label": "项目名称", "required": True},
    {"fieldKey": "tenderNo", "label": "招标编号", "required": True},
    {"fieldKey": "tenderer", "label": "招标人", "required": True},
    {"fieldKey": "managementUnit", "label": "管理单位", "required": False},
    {"fieldKey": "bidSectionScale", "label": "标段规模", "required": False},
    {"fieldKey": "deliveryPeriod", "label": "交货周期", "required": False},
    {"fieldKey": "warrantyPeriod", "label": "质保期", "required": False},
)


def _build_business_project_fact_fields(
    field_groups: dict[str, Any],
    project_dates: dict[str, Any],
) -> list[dict[str, Any]]:
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups.get("projectBasics"), list) else []
    fields_by_key = {
        str(field.get("key") or ""): field
        for field in project_basics
        if isinstance(field, dict)
    }
    fact_fields: list[dict[str, Any]] = []
    for spec in BUSINESS_PROJECT_FACT_FIELD_SPECS:
        field_key = str(spec["fieldKey"])
        source = fields_by_key.get(field_key) or {}
        value = str(source.get("value") or "").strip()
        fact_fields.append(
            {
                "fieldKey": field_key,
                "label": str(spec["label"]),
                "value": value,
                "category": "项目基础信息",
                "status": "found" if value else "missing",
                "required": bool(spec.get("required", False)),
                "confidence": float(source.get("confidence") or (0.86 if value else 0.0)),
                "sourceFile": str(source.get("sourceFile") or ""),
                "sourceDocumentId": str(source.get("sourceDocumentId") or ""),
                "section": str(source.get("section") or ""),
                "evidence": str(source.get("evidence") or ""),
                "evidenceLocation": str(source.get("evidenceLocation") or ""),
            }
        )

    date_specs = (
        ("bidStartDate", "投标起始日期", "startDate", False),
        ("bidDeadline", "投标截止日期", "endDate", True),
    )
    for field_key, label, date_key, required in date_specs:
        value = str(project_dates.get(date_key) or "").strip()
        fact_fields.append(
            {
                "fieldKey": field_key,
                "label": label,
                "value": value,
                "category": "投标时间信息",
                "status": "found" if value else "missing",
                "required": required,
                "confidence": 0.78 if value else 0.0,
                "sourceFile": "",
                "sourceDocumentId": "",
                "section": "",
                "evidence": "",
                "evidenceLocation": "",
            }
        )
    return fact_fields


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
    docx_candidate_items = _extract_docx_core_candidate_items(documents)
    merged_items = [*copy.deepcopy(items), *docx_candidate_items, *hint_items]
    result["items"] = merged_items
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    source_documents = copy.deepcopy(structured.get("sourceDocuments") or [])
    project_dates = copy.deepcopy(structured.get("projectDates") or {"startDate": "", "endDate": ""})
    appendices = copy.deepcopy(structured.get("appendices") or [])
    scoring = _merge_business_scoring(
        structured.get("scoringCriteria") or {},
        _extract_markdown_scoring(documents, texts_by_id),
    )
    commitment_analysis = _build_business_commitment_analysis(
        merged_items,
        run_semantic_review=run_semantic_review,
    )
    field_groups = {
        "projectBasics": _build_business_project_basics(merged_items, project_dates),
        "businessResponse": _build_business_response_fields(merged_items),
        "qualificationSupport": _build_qualification_support_fields(merged_items),
        "qualificationRequirements": _build_qualification_requirements(
            merged_items,
            documents=documents,
            texts_by_id=texts_by_id,
        ),
        "bidderInstructions": _extract_bidder_instruction_rows(documents),
        "commercialRejectionClauses": _extract_commercial_rejection_clauses(documents, texts_by_id),
        "commitmentRequirements": _build_commitment_requirement_fields(
            merged_items,
            analysis=commitment_analysis,
        ),
    }
    presence = _build_business_requirement_presence(merged_items)
    _ = project_id
    commitment_letters = copy.deepcopy(commitment_analysis["letters"])
    commitment_clues = copy.deepcopy(commitment_analysis["clues"])
    commitment_letters, commitment_template_alignments = _align_commitment_letters_with_existing_templates(
        commitment_letters,
        appendices,
    )
    project_fact_fields = _build_business_project_fact_fields(field_groups, project_dates)

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
        "commitmentTemplateAlignments": commitment_template_alignments,
        "businessFormatRegions": [
            {
                "sourceFile": str(document.get("name") or ""),
                "regionCount": len(_detect_business_format_regions(_iter_docx_blocks(Path(str(document.get("sourcePath") or "")))))
                if str(document.get("sourcePath") or "").lower().endswith(".docx")
                and Path(str(document.get("sourcePath") or "")).exists()
                else 0,
            }
            for document in documents
        ],
        "projectFactFields": project_fact_fields,
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

# 以下两个 markdown 表格辅助函数原属 parsing.py 附表/docx 区段；本模块评分解析
# （_parse_markdown_scoring_rows）调用它们，随迁以避免对门面的反向依赖，
# 门面 re-export 后附表区段与后续 parse_appendix 模块同样可用。


def _parse_markdown_table_row(line: str) -> list[str]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return cells


def _is_markdown_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)
