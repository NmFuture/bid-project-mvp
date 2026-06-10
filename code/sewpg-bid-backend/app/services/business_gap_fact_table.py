from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from typing import Any

from app.services.business_s1_handoff import business_s1_parse_result
from app.services.identity import build_project_identity


PROJECT_FACT_TABLE_SCHEMA_VERSION = "bid-project-fact-table-v1"

BASIC_BUSINESS_FACT_FIELD_SPECS = [
    {
        "label": "招标项目名称",
        "category": "招标解析字段",
        "sourceMode": "parse",
        "sourceHint": "招标文件封面/第一章招标公告p8",
        "usage": "封面/页眉信息/开标价格表p658等",
        "required": True,
    },
    {
        "label": "招标编号",
        "category": "招标解析字段",
        "sourceMode": "parse",
        "sourceHint": "招标文件封面/第一章招标公告p8",
        "usage": "封面/开标价格表p658/部分情况说明表等",
        "required": True,
    },
    {
        "label": "招标人",
        "category": "招标解析字段",
        "sourceMode": "parse",
        "sourceHint": "招标文件封面",
        "usage": "承诺函p20/投标人需要说明内容p659等",
        "required": True,
    },
    {
        "label": "招标项目单位",
        "category": "招标解析字段",
        "sourceMode": "parse",
        "sourceHint": "招标文件封面",
        "usage": "承诺函p20/投标人需要说明内容p659等",
        "required": True,
    },
    {
        "label": "招标代理机构",
        "category": "招标解析字段",
        "sourceMode": "parse",
        "sourceHint": "招标文件封面",
        "usage": "承诺函p20/投标人需要说明内容p659等",
        "required": True,
    },
    {
        "label": "风机型号",
        "category": "人工确认字段",
        "sourceMode": "manual",
        "sourceHint": "招标文件 第一章招标公告p8（用户填写）",
        "usage": "开标价格表p658",
        "required": True,
    },
    {
        "label": "投标项目标段名称",
        "category": "人工确认字段",
        "sourceMode": "manual",
        "sourceHint": "招标文件 第一章招标公告p8（用户填写）",
        "usage": "封面/开标价格表p658",
        "required": True,
    },
    {
        "label": "投标人",
        "category": "投标人固定事实",
        "sourceMode": "fixed",
        "sourceHint": "用户填写",
        "usage": "封面/评分索引表（p6）/各类承诺书、说明附件落款等",
        "required": True,
    },
    {
        "label": "投标人地址",
        "category": "投标人固定事实",
        "sourceMode": "fixed",
        "sourceHint": "用户填写",
        "usage": "投标函p20/投标保证金p53等",
        "required": True,
    },
    {
        "label": "投标人电话",
        "category": "投标人固定事实",
        "sourceMode": "fixed",
        "sourceHint": "用户填写",
        "usage": "投标函p20",
        "required": True,
    },
    {
        "label": "法定代表人姓名/性别/年龄/职务",
        "category": "投标人固定事实",
        "sourceMode": "fixed",
        "sourceHint": "用户填写（部分可身份证识别）",
        "usage": "法定代表人身份证明p23",
        "required": True,
    },
    {
        "label": "委托人姓名/身份证",
        "category": "投标人固定事实",
        "sourceMode": "fixed",
        "sourceHint": "用户填写（也可身份证识别）",
        "usage": "投标函p20/委托书p24",
        "required": True,
    },
    {
        "label": "营业执照信息注册资本/信用代码/类型（可选）",
        "category": "投标人固定事实",
        "sourceMode": "fixed",
        "sourceHint": "用户填写（营业执照图片识别）",
        "usage": "商务摘要表p56/近年财务表p208",
        "required": False,
    },
    {
        "label": "存款账户号码/银行/编号（不确定）",
        "category": "投标人固定事实",
        "sourceMode": "fixed",
        "sourceHint": "用户填写",
        "usage": "基本账户存款信息p116",
        "required": True,
    },
    {
        "label": "日期",
        "category": "系统字段",
        "sourceMode": "system",
        "sourceHint": "系统自动/用户填写",
        "usage": "封面/各类承诺函、说明附表落款",
        "required": True,
    },
]

FIXED_BUSINESS_FACT_VALUES = {
    "投标人": "上海电气风电集团股份有限公司",
}

FACT_VALUE_COMPAT_LABELS = {
    "招标项目名称": ["项目名称", "采购项目名称", "工程名称"],
    "招标人": ["招标方", "客户名称", "业主"],
    "招标项目单位": ["项目单位", "建设单位", "管理单位"],
    "风机型号": ["投标机型", "机型", "机组型号", "投标方案"],
    "投标项目标段名称": ["标段名称", "标段", "项目标段名称"],
    "法定代表人姓名/性别/年龄/职务": ["法定代表人", "单位负责人", "法定代表人姓名"],
    "委托人姓名/身份证": ["委托人", "授权代表", "委托代理人", "授权委托人"],
    "营业执照信息注册资本/信用代码/类型（可选）": [
        "营业执照信息",
        "注册资本",
        "统一社会信用代码",
        "企业类型",
        "信用代码",
    ],
    "存款账户号码/银行/编号（不确定）": [
        "基本存款账户",
        "开户行",
        "银行账号",
        "账户号码",
        "基本存款账户编号",
        "存款账户",
    ],
}

FACT_MATERIAL_SOURCE_PRIORITIES = {
    "project": 300,
    "customer": 200,
    "standard": 100,
}


def empty_project_fact_table(project_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "empty",
        "builtAt": "",
        "updatedAt": "",
        "confirmedAt": "",
        "confirmedBy": "",
        "fields": [],
        "summary": {
            "totalCount": 0,
            "requiredCount": 0,
            "confirmedCount": 0,
            "candidateCount": 0,
            "missingCount": 0,
            "conflictCount": 0,
        },
    }


def summarize_project_fact_fields(fields: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "totalCount": len(fields),
        "requiredCount": sum(1 for field in fields if field.get("required", True)),
        "confirmedCount": sum(1 for field in fields if str(field.get("status") or "") == "confirmed"),
        "candidateCount": sum(1 for field in fields if str(field.get("status") or "") == "candidate"),
        "missingCount": sum(1 for field in fields if str(field.get("status") or "") == "missing"),
        "conflictCount": sum(1 for field in fields if str(field.get("status") or "") == "conflict"),
    }


def canonical_fact_label(label: Any) -> str:
    raw = str(label or "").strip()
    if not raw:
        return ""
    text = re.sub(r"\s+", "", raw)
    text = re.sub(r"[（(]\s*(?:MW|kW|m|m2/kW|m²/kW|%|h|MWh/y|MWh/a|台)\s*[）)]", "", text, flags=re.I)
    text = text.strip("：:；;，,、")
    aliases = {
        "方案": "投标方案",
        "项目方案": "投标方案",
        "机型": "风机型号",
        "项目名称": "招标项目名称",
        "采购项目名称": "招标项目名称",
        "工程名称": "招标项目名称",
        "建设容量": "总装机容量",
        "标段规模": "总装机容量",
        "机组数量": "机组台数",
        "风机数量": "机组台数",
        "台数": "机组台数",
        "总容量": "总装机容量",
        "容量": "总装机容量",
        "单机容量": "单机容量",
        "机组额定功率": "单机容量",
        "项目编号": "招标编号",
        "招标文件编号": "招标编号",
        "项目单位": "招标项目单位",
        "建设单位": "招标项目单位",
        "管理单位": "招标项目单位",
        "业主": "招标人",
        "招标方": "招标人",
        "客户名称": "招标人",
        "标段": "投标项目标段名称",
        "标段名称": "投标项目标段名称",
        "项目标段名称": "投标项目标段名称",
        "投标机型": "风机型号",
        "机组型号": "风机型号",
        "法定代表人": "法定代表人姓名/性别/年龄/职务",
        "单位负责人": "法定代表人姓名/性别/年龄/职务",
        "法定代表人姓名": "法定代表人姓名/性别/年龄/职务",
        "委托人": "委托人姓名/身份证",
        "授权代表": "委托人姓名/身份证",
        "委托代理人": "委托人姓名/身份证",
        "授权委托人": "委托人姓名/身份证",
        "营业执照信息": "营业执照信息注册资本/信用代码/类型（可选）",
        "注册资本": "营业执照信息注册资本/信用代码/类型（可选）",
        "统一社会信用代码": "营业执照信息注册资本/信用代码/类型（可选）",
        "企业类型": "营业执照信息注册资本/信用代码/类型（可选）",
        "信用代码": "营业执照信息注册资本/信用代码/类型（可选）",
        "基本存款账户": "存款账户号码/银行/编号（不确定）",
        "开户行": "存款账户号码/银行/编号（不确定）",
        "银行账号": "存款账户号码/银行/编号（不确定）",
        "账户号码": "存款账户号码/银行/编号（不确定）",
        "基本存款账户编号": "存款账户号码/银行/编号（不确定）",
        "存款账户": "存款账户号码/银行/编号（不确定）",
        "交货期": "交货周期",
        "质量保证期": "质保期",
        "投标截止时间": "投标截止日期",
        "轮毂中心高度": "轮毂高度",
        "轮毂高度": "轮毂高度",
        "风轮直径": "叶轮直径",
        "叶轮直径": "叶轮直径",
        "发电小时数承诺": "保证有效小时数",
        "保证有效小时": "保证有效小时数",
        "风电机组设备年平均可利用率保证值": "全场可利用率",
        "适用等级": "安全等级",
    }
    if text in aliases:
        return aliases[text]
    if "总装机容量" in text or text.startswith("总容量"):
        return "总装机容量"
    if (
        "年平均风速" in text
        or "代表年风速" in text
        or ("平均风速" in text and ("机位" in text or "尾流" in text or "轮毂" in text))
    ):
        return "年平均风速"
    if "轮毂" in text and "高度" in text:
        return "轮毂高度"
    if "叶轮直径" in text or "风轮直径" in text:
        return "叶轮直径"
    if ("机组" in text or "风机" in text) and ("台数" in text or "数量" in text):
        return "机组台数"
    if "单机容量" in text or "额定功率" in text:
        return "单机容量"
    if "安全等级" in text or ("安全" in text and "等级" in text):
        return "安全等级"
    if "设计寿命" in text:
        return "设计寿命"
    if "单位千瓦扫风面积" in text:
        return "单位千瓦扫风面积"
    if "空气密度" in text and not re.search(r"参数|系数", text):
        return "空气密度"
    if "湍流强度" in text:
        return "湍流强度"
    if "极端风速" in text or "极大风速" in text:
        return "极端风速"
    if "风剪切" in text or "风切变" in text or "风剪切指数" in text:
        return "风剪切"
    if "功率曲线" in text and ("保证" in text or "保证率" in text):
        return "功率曲线保证率"
    if "单台" in text and "可利用率" in text:
        return "单台可利用率"
    if ("全场" in text or "风电场" in text or "年平均" in text) and "可利用率" in text:
        return "全场可利用率"
    if "发电量" in text and ("保证" in text or "承诺" in text):
        return "保证发电量"
    if "有效小时" in text or "发电小时" in text or "等效利用小时" in text:
        return "保证有效小时数"
    return text


def fact_label_key(label: Any) -> str:
    return re.sub(r"\s+", "", canonical_fact_label(label)).lower()


def business_fact_spec(label: Any) -> dict[str, Any] | None:
    key = fact_label_key(label)
    for spec in BASIC_BUSINESS_FACT_FIELD_SPECS:
        spec_label = str(spec["label"])
        if key == fact_label_key(spec_label):
            return spec
        if key in {fact_label_key(alias) for alias in FACT_VALUE_COMPAT_LABELS.get(spec_label, [])}:
            return spec
    return None


def _put_fact_value_alias(values: dict[str, str], label: str, value: str) -> None:
    if not label or not value:
        return
    values[label] = value
    values[fact_label_key(label)] = value


def fact_source_ref_priority(ref: dict[str, Any]) -> int:
    source_type = str(ref.get("type") or "").strip()
    if source_type in {"project", "projectIdentity", "projectTurbineModel", "derived"}:
        return 320
    if source_type in {"materialFact", "derivedMaterialFact"}:
        tier = str(ref.get("materialTier") or "").strip() or "standard"
        return FACT_MATERIAL_SOURCE_PRIORITIES.get(tier, 50)
    return 0


def normalize_fact_source_refs(refs: Any) -> list[dict[str, Any]]:
    normalized: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for index, ref in enumerate(refs if isinstance(refs, list) else []):
        if not isinstance(ref, dict):
            continue
        item = copy.deepcopy(ref)
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        normalized.append((fact_source_ref_priority(item), index, item))
    normalized.sort(key=lambda item: (-item[0], item[1]))
    return [item for _, _, item in normalized]


def normalize_project_fact_field(
    field: dict[str, Any],
    *,
    index: int,
    confirm: bool,
    operator: str,
    saved_at: str,
) -> dict[str, Any]:
    spec = business_fact_spec(field.get("label")) or {}
    label = str(spec.get("label") or canonical_fact_label(field.get("label")) or field.get("label") or "")
    source_mode = str(field.get("sourceMode") or spec.get("sourceMode") or "")
    value = str(field.get("value") or "").strip()
    status = str(field.get("status") or ("candidate" if value else "missing")).strip()
    if confirm:
        status = "confirmed" if value else "missing"
    source_refs = normalize_fact_source_refs(field.get("sourceRefs"))
    source_priority = int(field.get("sourcePriority") or 0)
    if source_refs:
        source_priority = max(source_priority, fact_source_ref_priority(source_refs[0]))
    normalized = {
        "id": str(field.get("id") or f"FACT-{index:04d}"),
        "key": fact_label_key(label) or str(field.get("key") or f"fact-{index}"),
        "label": label,
        "category": str(field.get("category") or spec.get("category") or "项目事实"),
        "sourceMode": source_mode,
        "sourceHint": str(field.get("sourceHint") or spec.get("sourceHint") or ""),
        "usage": str(field.get("usage") or spec.get("usage") or ""),
        "value": value,
        "unit": str(field.get("unit") or ""),
        "required": bool(field.get("required", spec.get("required", True))),
        "status": status if status in {"candidate", "confirmed", "missing", "conflict"} else "candidate",
        "confidence": float(field.get("confidence") or 0),
        "sourcePriority": source_priority,
        "sourceRefs": source_refs,
        "alternatives": copy.deepcopy(field.get("alternatives") if isinstance(field.get("alternatives"), list) else []),
        "notes": str(field.get("notes") or ""),
        "updatedAt": saved_at,
        "updatedBy": operator,
    }
    if normalized["status"] == "confirmed":
        normalized["confirmedAt"] = saved_at
        normalized["confirmedBy"] = operator
    else:
        normalized["confirmedAt"] = str(field.get("confirmedAt") or "")
        normalized["confirmedBy"] = str(field.get("confirmedBy") or "")
    return normalized


def normalize_business_fact_fields_for_save(
    fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        raw_label = str(field.get("label") or field.get("title") or "").strip()
        if not raw_label:
            continue
        spec = business_fact_spec(raw_label)
        label = str(spec.get("label") if spec else raw_label)
        key = fact_label_key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        item = copy.deepcopy(field)
        item["label"] = label
        item["key"] = key
        if spec:
            item["category"] = str(item.get("category") or spec.get("category") or "项目事实")
            item["sourceMode"] = str(item.get("sourceMode") or spec.get("sourceMode") or "")
            item["sourceHint"] = str(item.get("sourceHint") or spec.get("sourceHint") or "")
            item["usage"] = str(item.get("usage") or spec.get("usage") or "")
            item["required"] = bool(item.get("required", spec.get("required", True)))
        else:
            item["category"] = str(item.get("category") or "人工补充事实")
            item["sourceMode"] = str(item.get("sourceMode") or "manual")
            item["sourceHint"] = str(item.get("sourceHint") or "用户新增")
            item["usage"] = str(item.get("usage") or "")
            item["required"] = bool(item.get("required", True))
            refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
            if not refs:
                item["sourceRefs"] = [{"type": "manualFact", "title": "用户新增", "field": label, "sourceMode": "manual"}]
        normalized.append(item)
    return normalized


def fact_table_value_map(fact_table: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fact_table.get("fields") or []:
        if not isinstance(field, dict):
            continue
        label = canonical_fact_label(str(field.get("label") or field.get("title") or ""))
        value = str(field.get("value") or "").strip()
        if label and value:
            _put_fact_value_alias(values, label, value)
            for alias in FACT_VALUE_COMPAT_LABELS.get(label, []):
                _put_fact_value_alias(values, alias, value)
    return values


def build_project_fact_table(project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
    built_at = _now_iso()
    existing_table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    existing_by_key = {
        fact_label_key(field.get("label")): field
        for field in (existing_table.get("fields") if isinstance(existing_table.get("fields"), list) else [])
        if isinstance(field, dict) and fact_label_key(field.get("label"))
    }
    parse_facts = trusted_parse_fact_fields(business_s1_parse_result(project))
    parse_by_key = {
        fact_label_key(fact.get("label")): fact
        for fact in parse_facts
        if isinstance(fact, dict) and str(fact.get("value") or "").strip()
    }

    def existing_for(label: str) -> dict[str, Any]:
        labels = [label, *FACT_VALUE_COMPAT_LABELS.get(label, [])]
        for candidate in labels:
            existing = existing_by_key.get(fact_label_key(candidate))
            if isinstance(existing, dict):
                return existing
        return {}

    def parse_for(label: str) -> dict[str, Any]:
        labels = [label, *FACT_VALUE_COMPAT_LABELS.get(label, [])]
        for candidate in labels:
            fact = parse_by_key.get(fact_label_key(candidate))
            if isinstance(fact, dict):
                return fact
        return {}

    fields: list[dict[str, Any]] = []
    for index, spec in enumerate(BASIC_BUSINESS_FACT_FIELD_SPECS, start=1):
        label = str(spec["label"])
        source_mode = str(spec.get("sourceMode") or "")
        existing = existing_for(label)
        existing_value = str(existing.get("value") or "").strip()
        existing_status = str(existing.get("status") or "").strip()
        preserve_existing = bool(existing_value and existing_status in {"candidate", "confirmed"})
        if preserve_existing and existing_status == "candidate" and not fact_candidate_value_valid(label, existing_value):
            preserve_existing = False
        parse_fact = parse_for(label) if source_mode in {"parse", "manual"} else {}
        parse_value = str(parse_fact.get("value") or "").strip()
        if parse_value and fact_value_is_placeholder(label, parse_value):
            parse_value = ""
        value = existing_value if preserve_existing else ""
        confidence = float(existing.get("confidence") or 0) if preserve_existing else 0.0
        source_priority = int(existing.get("sourcePriority") or 0) if preserve_existing else 0
        source_refs = normalize_fact_source_refs(existing.get("sourceRefs")) if preserve_existing else []
        notes = str(existing.get("notes") or "")
        updated_at = str(existing.get("updatedAt") or built_at) if preserve_existing else built_at
        updated_by = str(existing.get("updatedBy") or "") if preserve_existing else ""
        confirmed_at = str(existing.get("confirmedAt") or "") if preserve_existing else ""
        confirmed_by = str(existing.get("confirmedBy") or "") if preserve_existing else ""

        if not value and parse_value:
            value = parse_value
            confidence = float(parse_fact.get("confidence") or 0.82)
            source_priority = 260
            source_refs = normalize_fact_source_refs([copy.deepcopy(parse_fact.get("sourceRef") or {})])
        if not value:
            value, fallback_ref, fallback_confidence, fallback_priority = default_business_fact_value(
                project,
                label,
                source_mode=source_mode,
            )
            if value:
                confidence = fallback_confidence
                source_priority = fallback_priority
                source_refs = normalize_fact_source_refs([fallback_ref])

        status = "confirmed" if preserve_existing and existing_status == "confirmed" else ("candidate" if value else "missing")
        if not source_refs:
            source_refs = [
                {
                    "type": f"{source_mode}Fact" if source_mode else "projectFact",
                    "title": str(spec.get("sourceHint") or label),
                    "field": label,
                    "sourceMode": source_mode,
                }
            ]
        for ref in source_refs:
            if isinstance(ref, dict):
                ref.setdefault("sourceMode", source_mode)
        fields.append(
            {
                "id": str(existing.get("id") or f"FACT-{index:04d}"),
                "key": fact_label_key(label),
                "label": label,
                "category": str(spec.get("category") or "项目事实"),
                "sourceMode": source_mode,
                "sourceHint": str(spec.get("sourceHint") or ""),
                "usage": str(spec.get("usage") or ""),
                "value": value,
                "unit": str(existing.get("unit") or ""),
                "required": bool(spec.get("required", True)),
                "status": status,
                "confidence": confidence,
                "sourcePriority": source_priority,
                "sourceRefs": source_refs,
                "alternatives": copy.deepcopy(existing.get("alternatives") if isinstance(existing.get("alternatives"), list) else []),
                "notes": notes,
                "updatedAt": updated_at,
                "updatedBy": updated_by,
                "confirmedAt": confirmed_at if status == "confirmed" else "",
                "confirmedBy": confirmed_by if status == "confirmed" else "",
            }
        )
    return {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": str(project.get("id") or ""),
        "status": "draft",
        "builtAt": built_at,
        "updatedAt": built_at,
        "confirmedAt": "",
        "confirmedBy": "",
        "fields": fields,
        "summary": summarize_project_fact_fields(fields),
    }


def default_business_fact_value(
    project: dict[str, Any],
    label: str,
    *,
    source_mode: str,
) -> tuple[str, dict[str, Any], float, int]:
    identity: dict[str, Any] = {}
    try:
        identity = build_project_identity(project)
    except Exception:
        identity = {}
    field_aliases = {
        "招标项目名称": ("name", "projectName", "materialProjectName"),
        "招标编号": ("projectCode", "externalProjectNo", "projectNo", "materialProjectCode"),
        "招标人": ("owner", "customerName", "customerCanonicalName"),
        "招标项目单位": ("tenderProjectUnit", "projectUnit", "managementUnit"),
        "招标代理机构": ("tenderAgency", "agency", "tenderAgent"),
        "风机型号": ("turbineModel", "model", "selectedTurbineModel"),
        "投标项目标段名称": ("bidSectionName", "sectionName", "tenderSectionName"),
    }

    def first_value(keys: tuple[str, ...]) -> str:
        for key in keys:
            raw_value = project.get(key)
            if isinstance(raw_value, dict):
                raw_value = raw_value.get("model") or raw_value.get("label") or raw_value.get("name") or ""
            if isinstance(raw_value, (list, tuple, set)):
                raw_value = ""
            if not raw_value:
                raw_value = identity.get(key)
            if isinstance(raw_value, dict):
                raw_value = raw_value.get("model") or raw_value.get("label") or raw_value.get("name") or ""
            if isinstance(raw_value, (list, tuple, set)):
                raw_value = ""
            value = str(raw_value or "").strip()
            if value:
                return value
        return ""

    if label in FIXED_BUSINESS_FACT_VALUES:
        return (
            FIXED_BUSINESS_FACT_VALUES[label],
            {"type": "fixedFact", "title": "投标人固定事实", "field": label, "sourceMode": source_mode},
            0.95,
            280,
        )
    if label == "日期":
        return (
            datetime.now(UTC).strftime("%Y年%m月%d日"),
            {"type": "system", "title": "当前日期", "field": "currentDate", "sourceMode": source_mode},
            0.62,
            120,
        )
    fallback = first_value(field_aliases.get(label, ()))
    if fallback:
        return (
            fallback,
            {"type": "project", "title": label, "field": field_aliases.get(label, (label,))[0], "sourceMode": source_mode},
            0.86,
            220,
        )
    return "", {}, 0.0, 0


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

        if field_key in {"projectName", "tenderProjectName"} or fact_label_key(label) == fact_label_key("项目名称"):
            if looks_like_project_name(value):
                add("招标项目名称", value, category="招标解析字段", source_field=field, confidence=0.95, required=True)
        elif field_key == "tenderNo" or fact_label_key(label) == fact_label_key("招标编号"):
            if looks_like_tender_no(value):
                add("招标编号", value, category="招标解析字段", source_field=field, confidence=0.94, required=True)
        elif field_key in {"tenderer", "owner", "customerName"} or fact_label_key(label) in {
            fact_label_key("招标人"),
            fact_label_key("招标方"),
            fact_label_key("客户名称"),
        }:
            if looks_like_party_name(value) and not looks_like_bidder_signature_context(value, text):
                add("招标人", value, category="招标解析字段", source_field=field, confidence=0.84, required=False)
        elif field_key in {"managementUnit", "projectUnit", "tenderProjectUnit", "constructionUnit"} or fact_label_key(label) in {
            fact_label_key("管理单位"),
            fact_label_key("项目单位"),
            fact_label_key("招标项目单位"),
            fact_label_key("建设单位"),
        }:
            if looks_like_party_name(value):
                add("招标项目单位", value, category="招标解析字段", source_field=field, confidence=0.82, required=False)
        elif field_key in {"agency", "tenderAgency", "tenderAgent", "biddingAgency"} or fact_label_key(label) == fact_label_key("招标代理机构"):
            if looks_like_party_name(value):
                add("招标代理机构", value, category="招标解析字段", source_field=field, confidence=0.82, required=False)
        elif field_key in {"turbineModel", "model", "selectedTurbineModel", "windTurbineModel"} or fact_label_key(label) in {
            fact_label_key("风机型号"),
            fact_label_key("投标机型"),
            fact_label_key("机组型号"),
        }:
            add("风机型号", value, category="人工确认字段", source_field=field, confidence=0.74, required=False)
        elif field_key in {"bidSectionName", "sectionName", "tenderSectionName", "lotName"} or fact_label_key(label) in {
            fact_label_key("投标项目标段名称"),
            fact_label_key("标段名称"),
            fact_label_key("项目标段名称"),
        }:
            add("投标项目标段名称", value, category="人工确认字段", source_field=field, confidence=0.74, required=False)
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


def fact_value_is_placeholder(label: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    aliases = [label, *FACT_VALUE_COMPAT_LABELS.get(str(label), [])]
    for alias in aliases:
        if re.fullmatch(rf"[（(【\[]?\s*{re.escape(str(alias))}\s*[)）】\]]?", text):
            return True
    return False


def fact_candidate_value_valid(label: str, value: str) -> bool:
    if fact_value_is_placeholder(label, value):
        return False
    label_text = str(label)
    if label_text == "招标项目名称":
        return looks_like_project_name(value)
    if label_text == "招标编号":
        return looks_like_tender_no(value)
    if label_text in {"招标人", "招标项目单位", "招标代理机构"}:
        return looks_like_party_name(value)
    return True


def looks_like_project_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 160:
        return False
    if re.match(r"^[（(【\[]\s*(项目名称|工程名称|招标项目名称|采购项目名称)\s*[)）】\]]", text):
        return False
    if re.search(r"[。！？；]", text):
        return False
    if re.search(r"投标人|招标人|应当|必须|不得|标准|规范|条款|认可|提供|协议|事宜|订立|承诺|声明", text):
        return False
    return "项目" in text or "工程" in text


def looks_like_tender_no(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and len(text) <= 80 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-./]+", text))


def looks_like_party_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 80:
        return False
    if re.search(
        r"[。；;,.，]|投标人|投标截止|开标|收到|逾期|确认|视为|一律|澄清|应|必须|不得|标准|规范|条款|认可|提供|要求|报告|测试|审查|盖单位章|盖章|答复|暂停|活动",
        text,
    ):
        return False
    if re.search(r"公司|集团|有限|电力|能源", text):
        return True
    return bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,24}(?:招标人|业主)", text))


def looks_like_bidder_signature_context(value: Any, context: Any) -> bool:
    value_text = re.sub(r"\s+", "", str(value or ""))
    text = re.sub(r"\s+", "", str(context or ""))
    if not value_text or not text:
        return False
    window = text[: max(len(value_text) + 40, 80)]
    return bool(re.search(r"盖单位章|盖章|法定代表人|委托代理人|投标人[:：]|签字|签章|年月日|答复前.*暂停", window))


def add_performance_facts_from_parse_text(text: str, source_field: dict[str, Any], add: Any) -> None:
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return

    patterns = [
        (r"功率曲线[^。；;]{0,24}(?:不低于|≥|>=)(?:保证值的)?([0-9]+(?:\.[0-9]+)?%)", "功率曲线保证率"),
        (r"风电场机组年平均可利用率(?:≥|>=|不低于)([0-9]+(?:\.[0-9]+)?%)", "全场可利用率"),
        (r"(?:全部机组|全场).*?平均可利用率(?:≥|>=|不低于)([0-9]+(?:\.[0-9]+)?%)", "全场可利用率"),
        (r"单台机组年平均可利用率(?:≥|>=|不低于)([0-9]+(?:\.[0-9]+)?%)", "单台可利用率"),
        (r"主要部件更换率(?:低于|不高于|≤|<=)([0-9]+(?:\.[0-9]+)?%)", "主要部件更换率"),
    ]
    for pattern, label in patterns:
        match = re.search(pattern, normalized)
        if match:
            add(
                label,
                match.group(1),
                category="性能保证",
                source_field=source_field,
                confidence=0.86,
                required=False,
                unit="%",
            )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
