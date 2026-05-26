from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    from docx import Document
except ImportError:  # pragma: no cover
    Document = None  # type: ignore[assignment]


SKILL_NAME = "bid-tech-tender-structured-parser"
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    aliases: tuple[str, ...]


CATEGORIES: tuple[Category, ...] = (
    Category("scoring_criteria", "评分细则", ("评分", "得分", "分值", "证明材料", "商务评分", "技术评分")),
    Category(
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
            "项目单位",
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
    Category(
        "turbine_parameters",
        "风机核心参数",
        ("单机容量", "叶轮直径", "轮毂高度", "叶片最低点", "塔筒型式", "箱变型式", "安全等级", "空气密度", "风速", "湍流强度"),
    ),
    Category("performance_guarantees", "性能保证指标", ("功率曲线", "可利用率", "发电量", "上网电量", "涉网性能", "保证率", "性能保证")),
    Category("environment_adaptation", "环境适应性要求", ("低温", "覆冰", "防凝露", "潮湿", "防雷暴", "防雷", "风沙", "高温", "环境适应性")),
    Category("topic_plans", "专题方案要求", ("专题方案", "叶片专题", "变桨系统专题", "主轴专题", "齿轮箱专题", "总体方案", "技术先进性")),
    Category("tables_and_scope", "附表和供货范围", ("附表", "副表", "供货范围", "供货清单", "供货界面")),
    Category("assessment_terms", "考核条款", ("考核", "发电量考核", "可利用率考核", "功率曲线考核", "部件考核", "认证考核")),
)


PROJECT_BASIC_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("projectName", "项目名称", ("项目名称",)),
    FieldSpec("tenderNo", "招标编号", ("招标编号", "项目编号", "招标文件编号")),
    FieldSpec("tenderer", "招标人", ("招标人", "业主", "建设单位", "项目单位")),
    FieldSpec("managementUnit", "管理单位", ("管理单位",)),
    FieldSpec("bidSectionScale", "标段规模", ("标段规模", "招标规模", "建设规模", "项目规模", "总装机容量")),
    FieldSpec("deliveryPeriod", "交货周期", ("交货周期", "交货期", "交货进度", "供货周期")),
    FieldSpec("warrantyPeriod", "质保期", ("质保期", "质量保证期", "质保")),
    FieldSpec("technicalCommitment", "技术承诺", ("技术承诺", "项目技术承诺", "承诺要求")),
)

TURBINE_CORE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("singleCapacity", "单机容量", ("单机容量", "单台容量", "机组容量")),
    FieldSpec("rotorDiameter", "叶轮直径", ("叶轮直径", "风轮直径")),
    FieldSpec("hubHeight", "轮毂高度", ("轮毂高度", "轮毂中心高度")),
    FieldSpec("bladeTipClearance", "叶片最低点距地", ("叶片最低点距地", "叶片运行距地最低点距离", "叶片最低点", "叶尖最低点距地")),
    FieldSpec("towerType", "塔筒型式", ("塔筒型式", "塔架型式", "塔筒形式")),
    FieldSpec("boxTransformerType", "箱变型式", ("箱变型式", "箱变形式", "箱式变压器型式", "箱变")),
    FieldSpec("safetyClass", "安全等级", ("安全等级", "设计安全等级")),
    FieldSpec("airDensity", "空气密度", ("空气密度",)),
    FieldSpec("windSpeed", "风速", ("风速", "最大风速", "平均风速")),
    FieldSpec("turbulenceIntensity", "湍流强度", ("湍流强度", "湍流等级")),
)

PERFORMANCE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("powerCurve", "功率曲线", ("功率曲线",)),
    FieldSpec("availability", "可利用率", ("可利用率", "设备可利用率")),
    FieldSpec("generation", "发电量", ("发电量", "上网电量", "年发电量")),
    FieldSpec("gridPerformance", "涉网性能", ("涉网性能", "高低电压穿越", "电压穿越", "电网适应性")),
)

ENVIRONMENT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("lowTemperature", "抗低温", ("抗低温", "低温")),
    FieldSpec("icingCondensation", "抗覆冰防凝露", ("抗覆冰", "覆冰", "防凝露")),
    FieldSpec("humidity", "防潮湿", ("防潮湿", "潮湿", "湿热")),
    FieldSpec("lightning", "防雷暴", ("防雷暴", "雷暴", "防雷")),
    FieldSpec("sandstorm", "防风沙", ("防风沙", "风沙", "沙尘")),
    FieldSpec("highTemperature", "抗高温", ("抗高温", "高温")),
)

FIELD_GROUP_SPECS: dict[str, tuple[str, tuple[FieldSpec, ...]]] = {
    "projectBasics": ("project_basics", PROJECT_BASIC_FIELDS),
    "turbineCoreParameters": ("turbine_parameters", TURBINE_CORE_FIELDS),
    "performanceGuarantees": ("performance_guarantees", PERFORMANCE_FIELDS),
    "environmentAdaptation": ("environment_adaptation", ENVIRONMENT_FIELDS),
}

DATE_PATTERN = re.compile(r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?")
LABEL_VALUE_PATTERN = re.compile(r"^\s*(?P<label>[^:：]{2,50})\s*[:：]\s*(?P<value>.+?)\s*$")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[（(]?\d+[）)]?)\s*[、.．\s]+")
SCORING_SCORE_PATTERN = re.compile(r"(?P<item>[\u4e00-\u9fa5A-Za-z0-9（）()、/]+?)\s*(?P<score>\d+(?:\.\d+)?\s*分)")
BID_START_DATE_KEYWORDS = (
    "招标文件获取",
    "招标文件领取",
    "招标文件发售",
    "招标文件出售",
    "获取招标文件",
    "购买招标文件",
    "报名时间",
    "投标文件递交时间",
    "投标文件提交时间",
)
BID_END_DATE_KEYWORDS = (
    "投标截止",
    "投标文件递交截止",
    "投标文件提交截止",
    "递交投标文件截止",
    "提交投标文件截止",
    "递交截止",
    "提交截止",
    "开标时间",
    "开标日期",
)
BID_GENERIC_DEADLINE_KEYWORDS = ("截止时间", "截止日期")
BID_GENERIC_DEADLINE_CONTEXT = ("投标", "投标文件", "递交", "提交", "开标")
BID_WINDOW_KEYWORDS = ("投标文件递交", "投标文件提交", "递交投标文件", "提交投标文件")
NON_BID_DATE_KEYWORDS = (
    "交货",
    "供货",
    "交付",
    "服务期",
    "工期",
    "开工",
    "竣工",
    "完工",
    "完成",
    "安装",
    "调试",
    "运维",
    "质保",
    "合同",
    "发电",
    "测风",
    "观测",
    "勘察",
    "并网",
    "投产",
)
SCORING_BUCKETS = ("technical", "business", "price", "lcoe", "compliance")


def normalize_text(raw_text: str) -> str:
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
    return normalize_text("".join(pieces))


def _clean(value: Any) -> str:
    text = str(value or "").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def _strip_leading_number(text: str) -> str:
    return LEADING_NUMBER_PATTERN.sub("", text).strip()


def _split_label_value(line: str, fallback_label: str) -> tuple[str, str]:
    normalized = _strip_leading_number(line)
    match = LABEL_VALUE_PATTERN.match(normalized)
    if match:
        label = _strip_leading_number(match.group("label")).strip()
        value = match.group("value").strip(" ；;。)）")
        return label or fallback_label, value or normalized
    return fallback_label, normalized


def _normalize_date_match(match: re.Match[str]) -> str:
    try:
        parsed = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return ""
    return parsed.isoformat()


def _find_dates(text: str) -> list[str]:
    return [value for value in (_normalize_date_match(match) for match in DATE_PATTERN.finditer(text)) if value]


def _has_bid_start_date_hint(line: str) -> bool:
    return any(keyword in line for keyword in BID_START_DATE_KEYWORDS)


def _has_bid_end_date_hint(line: str) -> bool:
    return any(keyword in line for keyword in BID_END_DATE_KEYWORDS) or (
        any(keyword in line for keyword in BID_GENERIC_DEADLINE_KEYWORDS)
        and any(keyword in line for keyword in BID_GENERIC_DEADLINE_CONTEXT)
    )


def _has_bid_window_hint(line: str) -> bool:
    return any(keyword in line for keyword in BID_WINDOW_KEYWORDS)


def _is_non_bid_date_context(line: str) -> bool:
    return any(keyword in line for keyword in NON_BID_DATE_KEYWORDS)


def _is_bid_date_context(line: str) -> bool:
    return (
        _has_bid_start_date_hint(line)
        or _has_bid_end_date_hint(line)
        or _has_bid_window_hint(line)
    )


def _record_project_date(line: str, dates: list[str], project_dates: dict[str, str]) -> None:
    if not dates:
        return

    has_bid_start = _has_bid_start_date_hint(line)
    has_bid_end = _has_bid_end_date_hint(line)
    has_bid_window = _has_bid_window_hint(line)
    if not (has_bid_start or has_bid_end or has_bid_window):
        return
    if _is_non_bid_date_context(line) and not (has_bid_end or has_bid_window):
        return

    if has_bid_window and len(dates) >= 2:
        project_dates["startDate"] = project_dates["startDate"] or dates[0]
        project_dates["endDate"] = dates[-1]
        return

    if has_bid_start and not project_dates["startDate"]:
        project_dates["startDate"] = dates[0]
    if has_bid_end:
        project_dates["endDate"] = dates[-1]


def _first_category(line: str) -> Category | None:
    if "考核" in line:
        return next(category for category in CATEGORIES if category.key == "assessment_terms")
    for category in CATEGORIES:
        if any(keyword in line for keyword in category.keywords):
            return category
    return None


def _docx_paragraph_text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(f"{WORD_NAMESPACE}t")).strip()


def _docx_table_rows(table: Any) -> list[list[str]]:
    return [[_clean(cell.text) for cell in row.cells] for row in table.rows]


def _iter_docx_blocks(path: Path) -> list[dict[str, Any]]:
    if Document is None or not path.exists() or path.suffix.lower() != ".docx":
        return []
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


def _block_plain_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        if block.get("type") == "paragraph":
            parts.append(str(block.get("text") or ""))
        elif block.get("type") == "table":
            for row in block.get("rows") or []:
                parts.append(" ".join(_clean(cell) for cell in row if _clean(cell)))
    return "\n".join(part for part in parts if part).strip()


def _classify_document_role(name: str, text: str) -> str:
    combined = f"{name}\n{text}"
    if any(keyword in combined for keyword in ("评标办法", "技术评分标准表", "商务评分标准表", "符合性审查标准表", "投标报价评分标准", "度电成本评分标准")):
        return "evaluation"
    if any(keyword in combined for keyword in ("技术规范书", "技术规范", "招标机型要求", "风资源情况", "性能保证指标", "供货范围")):
        return "technical_spec"
    if any(keyword in combined for keyword in ("投标文件格式", "资格审查", "投标人资格要求")):
        return "commercial_volume"
    return "unknown"


def _new_item(
    items: list[dict[str, Any]],
    *,
    category: str,
    label: str,
    value: str,
    document: dict[str, Any],
    evidence: str,
    location: str,
    section: str = "",
    confidence: float = 0.86,
    field_key: str = "",
    field_group: str = "",
    from_scoring_table: bool = False,
) -> dict[str, Any]:
    category_label = next((item.label for item in CATEGORIES if item.key == category), category)
    item = {
        "id": f"REQ-{len(items) + 1:04d}",
        "type": category_label,
        "category": category,
        "title": label,
        "keyEntity": label,
        "keyValue": value,
        "value": value,
        "sourceFile": str(document.get("name") or document.get("id") or "招标文件"),
        "sourceDocumentId": str(document.get("id") or ""),
        "section": section,
        "evidence": evidence,
        "evidenceLocation": location,
        "confidence": confidence,
    }
    if field_key:
        item["fieldKey"] = field_key
    if field_group:
        item["fieldGroup"] = field_group
    if from_scoring_table:
        item["fromScoringTable"] = True
    dates = _find_dates(f"{label}：{value}")
    if dates:
        item["dates"] = dates
    items.append(item)
    return item


def _field_matches(label: str) -> tuple[str, str, FieldSpec] | None:
    normalized = _clean(label).strip(" ：:;；。")
    if not normalized:
        return None
    matches: list[tuple[int, int, str, str, FieldSpec]] = []
    for group_key, (category, specs) in FIELD_GROUP_SPECS.items():
        for spec in specs:
            for alias in spec.aliases:
                if not alias:
                    continue
                if normalized == alias:
                    return group_key, category, spec
                index = normalized.find(alias)
                if index >= 0:
                    matches.append((index, len(alias), group_key, category, spec))
    if not matches:
        return None
    _, _, group_key, category, spec = max(matches, key=lambda item: (item[0], item[1]))
    return group_key, category, spec


def _value_from_label_cell(cell: str, spec: FieldSpec) -> str:
    text = _clean(cell)
    for alias in sorted(spec.aliases, key=len, reverse=True):
        if alias in text:
            tail = text.split(alias, 1)[1].strip(" ：:;；,，。")
            if not tail and text.strip(" ：:;；,，。") == alias:
                return ""
            if tail.startswith(("（", "(", "【")) and not re.search(r"\d", tail):
                return ""
            if tail and tail not in {"要求", "参数", "指标", "说明", "内容"}:
                return tail
    return ""


def _next_value(cells: list[str], index: int) -> str:
    for value in cells[index + 1 :]:
        cleaned = _clean(value)
        if cleaned and cleaned not in {"：", ":", "要求", "参数", "指标", "说明", "内容", "评分标准", "证明材料要求"}:
            return cleaned
    return ""


def _value_from_free_text(line: str, spec: FieldSpec) -> str:
    text = _clean(line)
    if spec.key in {"singleCapacity", "bidSectionScale"}:
        match = re.search(r"\d+(?:\.\d+)?\s*(?:MW|兆瓦|万千瓦)", text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    if spec.key == "rotorDiameter":
        match = re.search(r"(?:不小于|不低于|不少于)?\s*\d+(?:\.\d+)?\s*(?:米|m)(?:及以上)?", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    if spec.key == "hubHeight":
        match = re.search(r"(?:不超过|不高于|不大于|不小于)?\s*\d+(?:\.\d+)?\s*m", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    if spec.key == "bladeTipClearance":
        match = re.search(r"(?:不小于|不低于|不少于)\s*\d+(?:\.\d+)?\s*m", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    if spec.key == "safetyClass":
        match = re.search(r"IEC\s*[A-ZⅠⅡⅢIVX0-9 ]+类?(?:及以上)?", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    if spec.key == "airDensity":
        match = re.search(r"\d+(?:\.\d+)?\s*kg/m[³3]?", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    if spec.key == "windSpeed":
        match = re.search(r"(?:不低于|不小于|不少于)?\s*\d+(?:\.\d+)?\s*m/s", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    if spec.key == "turbulenceIntensity":
        match = re.search(r"(?:不低于|不小于|不少于)?\s*IEC\s*[A-ZⅠⅡⅢIVX0-9]+", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    if spec.key == "warrantyPeriod":
        match = re.search(r"\d+(?:\.\d+)?\s*年", text)
        if match:
            return match.group(0)
    return ""


def _extract_table_field_items(
    items: list[dict[str, Any]],
    *,
    document: dict[str, Any],
    rows: list[list[str]],
    section: str,
    block_index: int,
    project_dates: dict[str, str],
    seen: set[tuple[str, str, str, str]],
) -> None:
    for row_index, raw_row in enumerate(rows, start=1):
        cells = [_clean(cell) for cell in raw_row]
        if not any(cells):
            continue
        for col_index, cell in enumerate(cells):
            match = _field_matches(cell)
            if match is None:
                continue
            group_key, category, spec = match
            value = _value_from_label_cell(cell, spec) or _next_value(cells, col_index)
            if not value:
                continue
            evidence = " | ".join(value for value in cells if value)
            dedupe_key = (str(document.get("id") or ""), spec.key, value, evidence)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            item = _new_item(
                items,
                category=category,
                label=spec.label,
                value=value,
                document=document,
                evidence=evidence,
                location=f"B{block_index}/R{row_index}",
                section=section,
                field_key=spec.key,
                field_group=group_key,
            )
            if item.get("dates"):
                _record_project_date(f"{spec.label}：{value}", item["dates"], project_dates)


def _classify_scoring_table(title: str, rows: list[list[str]]) -> str:
    title_text = _clean(title)
    header_text = "\n".join(" ".join(row) for row in rows[:2])
    if "符合性审查" in title_text:
        return "compliance"
    if "度电成本" in title_text and "评分" in title_text:
        return "lcoe"
    if "报价" in title_text and "评分" in title_text:
        return "price"
    if "商务评分" in title_text or "商务部分评审评分" in title_text:
        return "business"
    if "技术评分" in title_text or "技术部分评审评分" in title_text:
        return "technical"
    if "评分" in title_text and all(keyword in header_text for keyword in ("分值", "评审")):
        return "technical"
    return ""


def _header_index(rows: list[list[str]], bucket: str) -> int:
    for index, row in enumerate(rows[:5]):
        joined = "".join(row)
        if bucket == "compliance" and any(keyword in joined for keyword in ("审查项目", "审查标准", "符合性")):
            return index
        if any(keyword in joined for keyword in ("评分项", "评审因素", "分值", "满分", "评分标准", "证明材料")):
            return index
    return 0


def _find_col(headers: list[str], aliases: tuple[str, ...]) -> int:
    for alias in aliases:
        for index, header in enumerate(headers):
            if alias in header:
                return index
    return -1


def _cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return _clean(row[index])


def _first_nonempty_after(row: list[str], start: int = 0) -> str:
    for cell in row[start:]:
        cleaned = _clean(cell)
        if cleaned:
            return cleaned
    return ""


def _make_evidence(headers: list[str], row: list[str]) -> str:
    parts: list[str] = []
    for index, value in enumerate(row):
        cleaned = _clean(value)
        if not cleaned:
            continue
        header = _clean(headers[index]) if index < len(headers) else ""
        parts.append(f"{header}：{cleaned}" if header else cleaned)
    return "；".join(parts)


def _parse_scoring_rows(
    *,
    rows: list[list[str]],
    bucket: str,
    document: dict[str, Any],
    section: str,
    block_index: int,
    start_index: int,
) -> list[dict[str, Any]]:
    cleaned_rows = [[_clean(cell) for cell in row] for row in rows if any(_clean(cell) for cell in row)]
    if not cleaned_rows:
        return []
    header_row_index = _header_index(cleaned_rows, bucket)
    headers = cleaned_rows[header_row_index]
    data_rows = cleaned_rows[header_row_index + 1 :]
    order_col = _find_col(headers, ("序号", "条款号", "编号"))
    item_col = _find_col(headers, ("评分项", "评审因素", "评审项目", "审查项目", "项目", "因素"))
    score_col = _find_col(headers, ("分值", "满分", "权重", "标准分"))
    point_col = _find_col(headers, ("得分点", "评分标准", "评分办法", "评审标准", "审查标准", "标准", "内容"))
    proof_col = _find_col(headers, ("证明材料要求", "证明材料", "证明文件", "材料要求", "资料要求"))

    if order_col == -1 and headers and "序号" in headers[0]:
        order_col = 0
    if item_col == -1:
        item_col = 1 if order_col == 0 and len(headers) > 1 else 0
    if point_col == item_col:
        point_col = _find_col(headers, ("评分标准", "评分办法", "评审标准", "审查标准"))

    parsed: list[dict[str, Any]] = []
    last_item = ""
    prefix = {"technical": "TECH", "business": "BUS", "price": "PRICE", "lcoe": "LCOE", "compliance": "COMP"}.get(bucket, "SCORE")
    for offset, row in enumerate(data_rows, start=header_row_index + 2):
        order = _cell(row, order_col) or str(len(parsed) + 1)
        scoring_item = _cell(row, item_col) or last_item or _first_nonempty_after(row, 1 if order_col == 0 else 0)
        if scoring_item in {"合计", "总计"} or order in {"合计", "总计"}:
            continue
        if scoring_item:
            last_item = scoring_item
        score = _cell(row, score_col)
        score_point = _cell(row, point_col)
        if not score_point:
            score_point = "；".join(_clean(cell) for cell in row if _clean(cell) and _clean(cell) not in {order, scoring_item, score})
        proof = _cell(row, proof_col)
        if not proof and any(keyword in score_point for keyword in ("证明", "材料", "提供")):
            proof = score_point
        evidence = _make_evidence(headers, row)
        if not scoring_item and not score_point:
            continue
        parsed.append(
            {
                "id": f"{prefix}-SCORE-{start_index + len(parsed):04d}",
                "order": order,
                "scoringItem": scoring_item,
                "score": score,
                "scorePoint": score_point,
                "proofRequirement": proof,
                "status": "found",
                "sourceFile": str(document.get("name") or document.get("id") or "招标文件"),
                "sourceDocumentId": str(document.get("id") or ""),
                "section": section,
                "evidence": evidence,
                "evidenceLocation": f"B{block_index}/R{offset}",
            }
        )
    return parsed


def _classify_line_scoring_bucket(item: dict[str, Any]) -> str:
    text = " ".join(str(item.get(key) or "") for key in ("title", "value", "evidence", "section"))
    if "符合性" in text:
        return "compliance"
    if "度电成本" in text:
        return "lcoe"
    if "报价" in text:
        return "price"
    if "商务" in text:
        return "business"
    return "technical"


def _rows_from_line_scoring_items(items: list[dict[str, Any]], scoring: dict[str, list[dict[str, Any]]]) -> None:
    for item in items:
        if item.get("category") != "scoring_criteria" or item.get("fromScoringTable"):
            continue
        evidence = str(item.get("evidence") or item.get("value") or "")
        bucket = _classify_line_scoring_bucket(item)
        if scoring[bucket]:
            continue
        matches = list(SCORING_SCORE_PATTERN.finditer(evidence))
        if not matches and any(keyword in evidence for keyword in ("评分标准表", "评分项", "分值", "得分点", "证明材料要求", "满分")):
            continue
        if matches:
            for match_index, match in enumerate(matches, start=1):
                next_match = matches[match_index] if match_index < len(matches) else None
                segment = evidence[match.start() : next_match.start() if next_match else len(evidence)].strip(" ；;。")
                proof = segment if any(keyword in segment for keyword in ("证明", "材料", "提供")) else ""
                scoring[bucket].append(
                    {
                        "id": f"{item.get('id') or 'SCORE'}-{match_index}",
                        "order": str(len(scoring[bucket]) + 1),
                        "scoringItem": match.group("item").strip(" ，,：:；;"),
                        "score": match.group("score").replace(" ", ""),
                        "scorePoint": segment or str(item.get("value") or evidence),
                        "proofRequirement": proof,
                        "status": "found",
                        "sourceFile": item.get("sourceFile") or "",
                        "sourceDocumentId": item.get("sourceDocumentId") or "",
                        "section": item.get("section") or "",
                        "evidence": evidence,
                        "evidenceLocation": item.get("evidenceLocation") or "",
                    }
                )
            continue
        scoring[bucket].append(
            {
                "id": item.get("id") or f"SCORE-{len(scoring[bucket]) + 1}",
                "order": str(len(scoring[bucket]) + 1),
                "scoringItem": str(item.get("keyEntity") or item.get("title") or f"评分项{len(scoring[bucket]) + 1}"),
                "score": "",
                "scorePoint": str(item.get("value") or evidence),
                "proofRequirement": evidence if any(keyword in evidence for keyword in ("证明", "材料", "提供")) else "",
                "status": "found",
                "sourceFile": item.get("sourceFile") or "",
                "sourceDocumentId": item.get("sourceDocumentId") or "",
                "section": item.get("section") or "",
                "evidence": evidence,
                "evidenceLocation": item.get("evidenceLocation") or "",
            }
        )


def _empty_field(spec: FieldSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "value": "",
        "status": "missing",
        "sourceFile": "",
        "sourceDocumentId": "",
        "section": "",
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
        "sourceDocumentId": str(item.get("sourceDocumentId") or ""),
        "section": str(item.get("section") or ""),
        "evidence": str(item.get("evidence") or ""),
        "evidenceLocation": str(item.get("evidenceLocation") or ""),
    }


def _block_number(location: str) -> int:
    match = re.match(r"B(\d+)", str(location or ""))
    return int(match.group(1)) if match else 0


def _field_candidate_score(item: dict[str, Any], spec: FieldSpec | None = None) -> int:
    value = str(item.get("value") or item.get("keyValue") or "").strip()
    location = str(item.get("evidenceLocation") or "")
    section = str(item.get("section") or "")
    evidence = str(item.get("evidence") or "")
    score = 0
    block_no = _block_number(location)
    if location.startswith("B"):
        score += 40
        if 0 < block_no <= 30:
            score += 35
    if section and not _looks_like_toc_entry(section):
        score += 10
    if value and len(value) <= 120:
        score += 8
    if re.search(r"\d|MW|兆瓦|kg/m|m/s|IEC|年", value, flags=re.IGNORECASE):
        score += 8
    if re.search(r"20\d{2}", value):
        score += 20
    date_count = len(_find_dates(value))
    if date_count >= 2:
        score += 35
    if _looks_like_toc_entry(str(item.get("evidence") or "")):
        score -= 50
    if not value or value in {"：", ":", "要求", "参数", "指标", "内容"}:
        score -= 100
    if len(value) > 180:
        score -= 20

    if spec is not None:
        context = f"{section}\n{evidence}"
        if spec.key == "projectName" and section == "封面":
            score += 80
        if spec.key == "tenderNo":
            if re.search(r"[A-Z]{2,}.*\d", value):
                score += 80
            if value in {"项目编号", "招标编号", "招标文件编号"}:
                score -= 100
        if spec.key in {"tenderer", "managementUnit"}:
            if 0 < block_no <= 30:
                score += 70
            if "意见" in value or "代表" in value:
                score -= 60
        if spec.key == "bidSectionScale" and any(keyword in context for keyword in ("招标机型要求", "总装机容量")):
            score += 70
        if spec.key == "deliveryPeriod":
            if any(keyword in context for keyword in ("交货进度", "供货进度")):
                score += 60
            if re.search(r"20\d{2}", value):
                score += 60
            if "详见" in value:
                score -= 60
        if spec.key == "warrantyPeriod":
            if re.search(r"\d+(?:\.\d+)?\s*年", value):
                score += 90
            if "质保期" in context:
                score += 30
        if spec.key in {"singleCapacity", "rotorDiameter", "hubHeight", "bladeTipClearance", "towerType", "boxTransformerType"}:
            if any(keyword in context for keyword in ("招标机型要求", "表 14")):
                score += 90
        if spec.key in {"safetyClass", "airDensity", "windSpeed", "turbulenceIntensity"}:
            if "风资源情况" in context:
                score += 100
            if "附表" in section:
                score -= 25
        if spec.key in {"powerCurve", "availability", "generation", "gridPerformance"}:
            if any(keyword in context for keyword in ("性能保证", "项目技术承诺要求", "发电量保证")):
                score += 70
            if "附表" in section and not any(keyword in section for keyword in ("性能指标", "保证")):
                score -= 20
        if spec.key in {"lowTemperature", "icingCondensation", "humidity", "lightning", "sandstorm", "highTemperature"}:
            if any(keyword in context for keyword in ("特殊防护要求", "环境适应性", "抗低温", "防潮湿", "防雷暴", "防风沙", "抗高温", "防凝露")):
                score += 90
            if value == "√":
                score += 20
    return score


def _build_fixed_field_group(items: list[dict[str, Any]], specs: tuple[FieldSpec, ...]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for spec in specs:
        candidates = [item for item in items if item.get("fieldKey") == spec.key]
        matched = max(candidates, key=lambda item: _field_candidate_score(item, spec)) if candidates else None
        if matched is None:
            fallback_candidates = [
                item
                for item in items
                if any(alias in str(item.get("keyEntity") or item.get("title") or item.get("evidence") or "") for alias in spec.aliases)
            ]
            matched = max(fallback_candidates, key=lambda item: _field_candidate_score(item, spec)) if fallback_candidates else None
        fields.append(_field_from_item(spec, matched) if matched else _empty_field(spec))
    return fields


def _presence_from_items(items: list[dict[str, Any]], category: str, *, keywords: tuple[str, ...] = ()) -> dict[str, Any]:
    matched = [item for item in items if item.get("category") == category]
    if keywords:
        matched = [
            item
            for item in matched
            if any(keyword in str(item.get("title") or item.get("value") or item.get("evidence") or "") for keyword in keywords)
        ]
    if not matched:
        return {"status": "missing", "summary": "招标文件中暂未识别到明确要求。", "evidences": [], "sources": []}
    evidences = [
        {
            "sourceFile": item.get("sourceFile") or "",
            "sourceDocumentId": item.get("sourceDocumentId") or "",
            "section": item.get("section") or "",
            "evidence": item.get("evidence") or item.get("value") or "",
            "evidenceLocation": item.get("evidenceLocation") or "",
        }
        for item in matched[:8]
    ]
    sources = _unique_sources(evidences)
    summary_parts = [str(item.get("value") or item.get("evidence") or "").strip() for item in matched]
    return {"status": "present", "summary": "；".join(part for part in summary_parts if part)[:800], "evidences": evidences, "sources": sources}


def _build_requirement_presence(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "topicPlans": _presence_from_items(items, "topic_plans"),
        "supplyScope": _presence_from_items(items, "tables_and_scope", keywords=("供货范围", "供货清单", "供货界面", "供货")),
        "assessmentTerms": _presence_from_items(items, "assessment_terms"),
    }


def _unique_sources(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    sources: list[dict[str, str]] = []
    for record in records:
        source_file = str(record.get("sourceFile") or "")
        source_document_id = str(record.get("sourceDocumentId") or "")
        if not source_file and not source_document_id:
            continue
        key = (source_document_id, source_file)
        if key in seen:
            continue
        seen.add(key)
        sources.append({"sourceDocumentId": source_document_id, "sourceFile": source_file})
    return sources


def _build_coverage(field_groups: dict[str, list[dict[str, Any]]], scoring: dict[str, list[dict[str, Any]]], presence: dict[str, Any]) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    scoring_rows = [row for bucket in scoring.values() for row in bucket]
    coverage.append(
        {
            "target": "评分细则",
            "status": "present" if scoring_rows else "missing",
            "summary": f"识别到 {len(scoring_rows)} 条评分/审查条目。" if scoring_rows else "未识别到评分细则。",
            "sources": _unique_sources(scoring_rows),
        }
    )
    for key, label in (
        ("projectBasics", "项目基础信息"),
        ("turbineCoreParameters", "风机核心参数"),
        ("performanceGuarantees", "性能保证指标"),
        ("environmentAdaptation", "环境适应性"),
    ):
        fields = field_groups.get(key) or []
        found = [field for field in fields if field.get("status") == "found"]
        status = "complete" if len(found) == len(fields) and fields else "partial" if found else "missing"
        coverage.append(
            {
                "target": label,
                "status": status,
                "summary": f"识别到 {len(found)}/{len(fields)} 个字段。",
                "sources": _unique_sources(found),
            }
        )
    for key, label in (("topicPlans", "专题方案"), ("supplyScope", "供货范围"), ("assessmentTerms", "考核条款")):
        item = presence.get(key) or {}
        coverage.append(
            {
                "target": label,
                "status": item.get("status") or "missing",
                "summary": item.get("summary") or "",
                "sources": item.get("sources") or [],
            }
        )
    return coverage


def _looks_like_toc_entry(line: str) -> bool:
    text = _clean(line)
    if "：" in text or ":" in text:
        return False
    if "\t" in line and re.search(r"\d{1,4}$", text):
        return True
    if re.match(r"^\d+(?:\.\d+)*\s+.+\d{1,4}$", text) and len(text) < 90:
        return True
    return False


def _extract_line_items(
    items: list[dict[str, Any]],
    *,
    document: dict[str, Any],
    text: str,
    project_dates: dict[str, str],
    seen: set[tuple[str, str, str]],
) -> None:
    current_section = ""
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_section = line.strip(" #")
            continue
        if _looks_like_toc_entry(line):
            continue
        if len(line) <= 80 and re.match(r"^(第?[一二三四五六七八九十0-9]+[章节条]?|[0-9]+(?:\.[0-9]+)*)", line):
            current_section = line
        dates = _find_dates(line)
        _record_project_date(line, dates, project_dates)
        if dates and any(keyword in current_section for keyword in ("交货进度", "供货进度")):
            spec = next(item for item in PROJECT_BASIC_FIELDS if item.key == "deliveryPeriod")
            item = _new_item(
                items,
                category="project_basics",
                label=spec.label,
                value=line,
                document=document,
                evidence=line,
                location=f"L{line_no}",
                section=current_section,
                field_key=spec.key,
                field_group="projectBasics",
            )
            item["dates"] = dates
            continue
        category = _first_category(line)
        raw_field_match = _field_matches(line)
        field_match: tuple[str, str, FieldSpec] | None = None
        if category is None and raw_field_match is not None:
            _, category_key, spec = raw_field_match
            category = next(item for item in CATEGORIES if item.key == category_key)
            label, value = _split_label_value(line, spec.label)
        elif category is not None:
            label, value = _split_label_value(line, category.label)
            if raw_field_match is not None and raw_field_match[1] == category.key:
                field_match = raw_field_match
        else:
            continue
        if category is not None and raw_field_match is not None and field_match is None and raw_field_match[1] == category.key:
            field_match = raw_field_match
        dedupe_key = (category.key, str(document.get("name") or ""), line)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        group_key = ""
        field_key = ""
        if field_match is not None:
            group_key, _, spec = field_match
            label = spec.label if label in {category.label, line} or spec.label in line else label
            if value == line:
                extracted = _value_from_free_text(line, spec) or _value_from_label_cell(line, spec)
                if extracted:
                    value = extracted
                else:
                    continue
            field_key = spec.key
        item = _new_item(
            items,
            category=category.key,
            label=label,
            value=value,
            document=document,
            evidence=line,
            location=f"L{line_no}",
            section=current_section,
            field_key=field_key,
            field_group=group_key,
        )
        if dates:
            item["dates"] = dates


def _extract_docx_table_items(
    items: list[dict[str, Any]],
    scoring: dict[str, list[dict[str, Any]]],
    *,
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    project_dates: dict[str, str],
    seen_fields: set[tuple[str, str, str, str]],
) -> None:
    current_section = ""
    for block_index, block in enumerate(blocks, start=1):
        if block.get("type") == "paragraph":
            text = _clean(block.get("text"))
            if text:
                current_section = text
            continue
        if block.get("type") != "table":
            continue
        rows = block.get("rows") or []
        bucket = _classify_scoring_table(current_section, rows)
        if bucket:
            parsed_rows = _parse_scoring_rows(
                rows=rows,
                bucket=bucket,
                document=document,
                section=current_section,
                block_index=block_index,
                start_index=len(scoring[bucket]) + 1,
            )
            scoring[bucket].extend(parsed_rows)
            for row in parsed_rows:
                _new_item(
                    items,
                    category="scoring_criteria",
                    label=row["scoringItem"],
                    value=row["scorePoint"],
                    document=document,
                    evidence=row["evidence"],
                    location=row["evidenceLocation"],
                    section=current_section,
                    from_scoring_table=True,
                )
            continue
        _extract_table_field_items(
            items,
            document=document,
            rows=rows,
            section=current_section,
            block_index=block_index,
            project_dates=project_dates,
            seen=seen_fields,
        )


def _extract_cover_project_name(
    items: list[dict[str, Any]],
    *,
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    seen_fields: set[tuple[str, str, str, str]],
) -> None:
    for block_index, block in enumerate(blocks[:18], start=1):
        if block.get("type") != "paragraph":
            continue
        text = _clean(block.get("text"))
        if not text:
            continue
        if "目录" in text or "招 标 文 件" in text or "招标文件" in text:
            break
        if "项目" not in text or len(text) < 6:
            continue
        if re.match(r"^\d+(?:\.\d+)*\s+", text):
            continue
        if any(keyword in text for keyword in ("风力发电机组", "招标编号", "第二卷", "技术规范")):
            continue
        spec = PROJECT_BASIC_FIELDS[0]
        dedupe_key = (str(document.get("id") or ""), spec.key, text, text)
        if dedupe_key in seen_fields:
            return
        seen_fields.add(dedupe_key)
        _new_item(
            items,
            category="project_basics",
            label=spec.label,
            value=text,
            document=document,
            evidence=text,
            location=f"B{block_index}",
            section="封面",
            confidence=0.9,
            field_key=spec.key,
            field_group="projectBasics",
        )
        return


def parse_documents(documents: list[dict[str, Any]], texts_by_id: dict[str, str] | None = None, *, mode: str = "local-structured-parser") -> dict[str, Any]:
    texts_by_id = texts_by_id or {}
    items: list[dict[str, Any]] = []
    scoring: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in SCORING_BUCKETS}
    project_dates = {"startDate": "", "endDate": ""}
    line_seen: set[tuple[str, str, str]] = set()
    field_seen: set[tuple[str, str, str, str]] = set()
    source_documents: list[dict[str, Any]] = []

    for document in documents:
        document_id = str(document.get("id") or "")
        source_path = Path(str(document.get("sourcePath") or ""))
        text = texts_by_id.get(document_id, "")
        if not text:
            text_path_value = str(document.get("textPath") or "")
            text_path = Path(text_path_value) if text_path_value else None
            if text_path is not None and text_path.exists() and text_path.is_file():
                text = text_path.read_text(encoding="utf-8", errors="replace")
            elif source_path.suffix.lower() == ".docx" and source_path.exists():
                text = extract_docx_text(source_path)
        text = normalize_text(text)
        blocks = _iter_docx_blocks(source_path)
        block_text = _block_plain_text(blocks)
        role = _classify_document_role(str(document.get("name") or source_path.name or document_id), f"{text}\n{block_text}")
        source_documents.append(
            {
                "id": document_id,
                "name": str(document.get("name") or source_path.name or document_id or "招标文件"),
                "role": role,
                "textLength": len(text),
            }
        )
        if blocks:
            _extract_cover_project_name(
                items,
                document=document,
                blocks=blocks,
                seen_fields=field_seen,
            )
        _extract_line_items(items, document=document, text=text, project_dates=project_dates, seen=line_seen)
        if blocks:
            _extract_docx_table_items(
                items,
                scoring,
                document=document,
                blocks=blocks,
                project_dates=project_dates,
                seen_fields=field_seen,
            )

    _rows_from_line_scoring_items(items, scoring)
    category_map: dict[str, list[dict[str, Any]]] = {category.key: [] for category in CATEGORIES}
    for item in items:
        if item.get("category") in category_map:
            category_map[str(item.get("category"))].append(item)
    categories = [
        {"key": category.key, "label": category.label, "count": len(category_map[category.key]), "items": category_map[category.key]}
        for category in CATEGORIES
        if category_map[category.key]
    ]
    field_groups = {
        key: _build_fixed_field_group(items, specs)
        for key, (_, specs) in FIELD_GROUP_SPECS.items()
    }
    flat_scoring = [row for bucket in SCORING_BUCKETS for row in scoring[bucket]]
    field_groups["scoringCriteria"] = flat_scoring
    requirement_presence = _build_requirement_presence(items)
    project_basics = {
        field["label"]: field["value"]
        for field in field_groups["projectBasics"]
        if field.get("status") == "found" and field.get("value")
    }
    structured = {
        "schemaVersion": "bid-tender-structured-v1",
        "targetSkill": SKILL_NAME,
        "mode": mode,
        "sourceDocuments": source_documents,
        "projectDates": {
            **project_dates,
            "itemIds": [
                item["id"]
                for item in items
                if item.get("dates") and _is_bid_date_context(f"{item.get('title') or ''}：{item.get('value') or ''}")
            ],
        },
        "projectBasics": project_basics,
        "categories": categories,
        "categoryCounts": {category["label"]: category["count"] for category in categories},
        "fieldGroups": field_groups,
        "scoringCriteria": scoring,
        "requirementPresence": requirement_presence,
        "coverage": _build_coverage(field_groups, scoring, requirement_presence),
        "appendices": [],
    }
    return {"items": items, "structured": structured}


def parse_manifest(manifest: dict[str, Any], *, mode: str = "opencode-skill") -> dict[str, Any]:
    documents = [item for item in manifest.get("documents") or [] if isinstance(item, dict)]
    return parse_documents(documents, mode=mode)
