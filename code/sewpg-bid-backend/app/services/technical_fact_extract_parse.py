"""技术标项目事实表：解析文本事实提取（S1 parse 字段、待填写表格标签）。

从 technical_gap_fact_table 拆出；对外仍经 app.services.technical_gap_fact_table 门面 re-export。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document

from app.services.fact_table_common import (
    COMMON_PROJECT_FACT_LABELS,
    FACT_TABLE_HEADER_WORDS,
    add_performance_facts_from_parse_text,
    canonical_fact_label,
    fact_label_key,
    looks_like_project_name,
    looks_like_tender_no,
)


def technical_fact_labels_from_task(task: dict[str, Any]) -> list[str]:
    title = str(task.get("title") or "")
    task_key = str(task.get("taskKey") or "")
    text = f"{title} {task_key}"
    labels: list[str] = []
    if re.search(r"技术响应|技术偏差|技术参数|技术方案|供货范围|机组|风机|塔筒|叶片|发电量|功率曲线|保证值|承诺|声明", text):
        labels.extend(["项目名称", "招标编号", "招标人", "投标人", "日期"])
    if re.search(r"规格|货物|供货范围|供货清单|设备清单|机组配置", text):
        labels.extend(["投标机型", "单机容量", "总装机容量", "机组台数"])
    if re.search(r"技术偏差|参数偏差|条款偏差", text):
        labels.extend(["招标编号", "项目名称", "技术偏差说明"])
    if re.search(r"发电量|有效小时|利用率|功率曲线|性能保证", text):
        labels.extend(["保证发电量", "保证有效小时数", "功率曲线保证率", "全场可利用率"])
    return list(dict.fromkeys(labels))


def trusted_parse_fact_fields(parse_result: Any) -> list[dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}

    def add(
        label: str,
        value: Any,
        *,
        category: str,
        source_field: dict[str, Any],
        confidence: float,
        required: bool = False,
        unit: str = "",
    ) -> None:
        label_text = canonical_fact_label(label)
        value_text = str(value or "").strip()
        if not label_text or not value_text:
            return
        key = fact_label_key(label_text)
        current = fields.get(key)
        fact = {
            "label": label_text,
            "value": value_text,
            "category": category,
            "confidence": confidence,
            "required": required,
            "unit": unit,
            "sourceRef": {
                "type": "parseField",
                "field": str(source_field.get("id") or source_field.get("fieldKey") or source_field.get("title") or ""),
                "fieldKey": str(source_field.get("fieldKey") or ""),
                "title": str(source_field.get("title") or source_field.get("label") or label_text),
                "sourceFile": str(source_field.get("sourceFile") or ""),
            },
        }
        if current is None or confidence > float(current.get("confidence") or 0):
            fields[key] = fact

    for field in iter_parse_fact_fields(parse_result):
        field_key = str(field.get("fieldKey") or "").strip()
        label = str(field.get("title") or field.get("label") or field.get("key") or field.get("id") or "").strip()
        value = str(field.get("value") or field.get("keyValue") or "").strip()
        evidence = str(field.get("evidence") or "").strip()
        text = "。".join(part for part in (label, value, evidence) if part)

        if field_key == "projectName" or fact_label_key(label) == fact_label_key("项目名称"):
            if looks_like_project_name(value):
                add("项目名称", value, category="项目基础信息", source_field=field, confidence=0.95, required=True)
        elif field_key == "tenderNo" or fact_label_key(label) == fact_label_key("招标编号"):
            if looks_like_tender_no(value):
                add("招标编号", value, category="项目基础信息", source_field=field, confidence=0.94, required=True)
        elif field_key in {"tenderer", "owner", "customerName"} or fact_label_key(label) in {
            fact_label_key("招标人"),
            fact_label_key("招标方"),
            fact_label_key("客户名称"),
        }:
            if looks_like_party_name(value):
                add("招标人", value, category="项目基础信息", source_field=field, confidence=0.84, required=False)
        elif field_key == "managementUnit" or fact_label_key(label) == fact_label_key("管理单位"):
            if looks_like_party_name(value):
                add("管理单位", value, category="项目基础信息", source_field=field, confidence=0.82, required=False)
        elif field_key == "bidSectionScale" or fact_label_key(label) in {
            fact_label_key("标段规模"),
            fact_label_key("招标规模"),
        }:
            add("标段规模", value, category="项目基础信息", source_field=field, confidence=0.78, required=False)
        elif field_key == "deliveryPeriod" or fact_label_key(label) == fact_label_key("交货周期"):
            add("交货周期", value, category="项目基础信息", source_field=field, confidence=0.78, required=False)
        elif field_key == "warrantyPeriod" or fact_label_key(label) == fact_label_key("质保期"):
            add("质保期", value, category="项目基础信息", source_field=field, confidence=0.78, required=False)
        elif field_key == "bidStartDate" or fact_label_key(label) == fact_label_key("投标起始日期"):
            add("投标起始日期", value, category="投标时间信息", source_field=field, confidence=0.78, required=False)
        elif field_key == "bidDeadline" or fact_label_key(label) in {
            fact_label_key("投标截止日期"),
            fact_label_key("投标截止时间"),
        }:
            add("投标截止日期", value, category="投标时间信息", source_field=field, confidence=0.82, required=True)

        add_performance_facts_from_parse_text(text, field, add)

    return list(fields.values())


def iter_parse_fact_fields(value: Any) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if len(fields) >= 200:
            return
        if isinstance(node, dict):
            has_label = any(key in node for key in ("label", "title", "key", "id"))
            has_value = any(key in node for key in ("value", "keyValue", "evidence"))
            if has_label and has_value:
                fields.append(node)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return fields


def looks_like_party_name(value: Any) -> bool:
    # 与 business_gap_fact_table 的版本已分叉，不能取严统一：商务线按真实样本加固了
    # 噪声拒绝（盖章/开标/逾期等语境词与标点），接受面收窄；技术线保留「华能|国电|
    # 大唐|华电|招标|业主」等央企短名的宽松接受，S1 招标人抽取依赖这些简称。
    text = str(value or "").strip()
    if not text or len(text) > 80:
        return False
    if re.search(r"[。；;]|投标人|应|必须|不得|标准|规范|条款|认可|提供|要求|报告|测试|审查", text):
        return False
    return bool(re.search(r"公司|集团|有限|招标|业主|电力|能源|华能|国电|大唐|华电", text))


def fillable_table_labels_from_blank_source(blank: dict[str, Any]) -> list[str]:
    path = blank_source_docx_path(blank)
    if path is None:
        return []
    try:
        document = Document(str(path))
    except Exception:
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for table in document.tables:
        for row in table.rows:
            cells = [clean_table_cell_text(cell.text) for cell in row.cells]
            label = table_field_label_from_row(cells)
            if not label:
                continue
            key = fact_label_key(label)
            if not key or key in seen:
                continue
            seen.add(key)
            labels.append(label)
    return labels


def blank_source_docx_path(blank: dict[str, Any]) -> Path | None:
    for key in ("docxPath", "path", "workspacePath"):
        value = str(blank.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        if path.exists():
            return path
    return None


def clean_table_cell_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def table_field_label_from_row(cells: list[str]) -> str:
    if not cells:
        return ""
    fill_positions = [
        index
        for index, text in enumerate(cells)
        if not text or re.search(r"待(?:人工)?(?:补充|填写|解析)|未填写|待确认", text)
    ]
    if not fill_positions:
        return ""
    candidates = cells[: fill_positions[0]]
    for candidate in reversed(candidates):
        label = canonical_fact_label(candidate)
        if looks_like_table_field_label(label):
            return label
    return ""


def looks_like_table_field_label(label: str) -> bool:
    text = str(label or "").strip()
    if not text or len(text) < 2 or len(text) > 80:
        return False
    if text in FACT_TABLE_HEADER_WORDS:
        return False
    if re.fullmatch(r"[\d一二三四五六七八九十]+[.、]?", text):
        return False
    if re.search(r"待(?:人工)?(?:补充|填写|解析)|未填写|授权人签名|日期", text):
        return False
    if re.search(r"同等质量|知名品牌|件套|厂家|品牌|Fluke|FLUKE|SKYLOTEC|DEHN|ABB|西门子|施耐德", text, flags=re.I):
        return False
    if re.search(r"参数|方法|折减|系数", text):
        return False
    if re.fullmatch(r"[A-Z]{1,8}[-A-Z0-9（）()\"'.—]+", text):
        return False
    if re.match(r"^\d", text) and not re.search(r"风速|年|容量|功率|高度|直径|小时|电量|温度", text):
        return False
    if text in COMMON_PROJECT_FACT_LABELS:
        return True
    return bool(
        re.search(
            r"投标机型|机组类型|机组台数|风机台数|单机容量|总装机容量|叶轮直径|风轮直径|轮毂.*高度|"
            r"扫风面积|比功率|安全等级|设计寿命|功率曲线|可利用率|保证电量|保证发电量|发电小时|"
            r"有效小时|等效利用小时|平均风速|空气密度|湍流|风切变|风剪切|极端风速|极大风速|"
            r"低温|高温|海拔|覆冰|盐雾|沙尘|雷电",
            text,
        )
    )
