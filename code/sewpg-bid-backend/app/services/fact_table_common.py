"""事实表共享基元：技术/商务两线逐字相同的解析抽取辅助 + 技术线各模块共用的标签归一。

- looks_like_project_name / looks_like_tender_no / add_performance_facts_from_parse_text
  由 technical_gap_fact_table 与 business_gap_fact_table 共用（原先两份拷贝）。
- looks_like_party_name 两线语义已分叉、无法取严统一，仍各自保留（见各自文件注释）。
- canonical_fact_label / fact_label_key 与 FACT_* 常量原是 technical_gap_fact_table 的
  标签归一基元，拆出 technical_fact_extract_parse / technical_fact_extract_materials
  后为避免循环依赖下沉到这里；商务线的归一口径不同，仍用 business_gap_fact_table 内的版本。
"""

from __future__ import annotations

import re
from typing import Any


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


FACT_TABLE_HEADER_WORDS = {
    "编号",
    "序号",
    "项目",
    "名称",
    "内容",
    "备注",
    "说明",
    "单位",
    "计量单位",
    "技术参数与规格",
    "主要项目",
    "投标机型1",
    "投标机型2",
    "保证值",
    "授权人签名",
}

COMMON_PROJECT_FACT_LABELS = {
    "项目名称",
    "招标编号",
    "招标人",
    "招标方",
    "客户名称",
    "投标方案",
    "投标机型",
    "机组类型",
    "机组台数",
    "总装机容量",
    "单机容量",
    "叶轮直径",
    "轮毂高度",
    "扫风面积",
    "比功率",
    "安全等级",
    "设计寿命",
    "空气密度",
    "湍流强度",
    "极端风速",
    "年平均风速",
    "风剪切",
    "保证发电量",
    "保证有效小时数",
    "功率曲线保证率",
    "全场可利用率",
    "单台可利用率",
    "主要部件更换率",
}

FACT_MATERIAL_SOURCE_PRIORITIES = {
    "project": 300,
    "customer": 200,
    "standard": 100,
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
        "机型": "投标方案",
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
        "项目单位": "招标人",
        "建设单位": "招标人",
        "业主": "招标人",
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
    # 多机型展开出来的「机型N单机容量」「机型N轮毂高度」等按原文保留：下面的包含式规则
    # 会把它们归一成全场共用的那一行，各机型的值互相覆盖。
    if re.match(r"^机型\d+", text):
        return text
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
