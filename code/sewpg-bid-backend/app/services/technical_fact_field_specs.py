from __future__ import annotations

"""技术标项目事实表字段 spec（148 条清单）加载与匹配支持。

spec JSON 由 scripts/import_technical_fact_specs.py 从甲方清单 xlsx 生成，
随仓库版本化。清单更新时重跑脚本即可，不要在运行时改 JSON。

匹配策略（在 technical_gap_fact_table._reconcile_with_specs 中使用）：
1. spec.label / spec.reviewLabel 经 canonical_fact_label + fact_label_key 归一后直接匹配；
2. 匹配不到时查 SPEC_LABEL_ALIASES（spec.label → 现有启发式字段标签列表）。
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SPECS_PATH = Path(__file__).resolve().parent.parent / "data" / "technical_fact_field_specs.json"

# spec.label → 现有启发式抽取产出的字段标签（canonical 前的写法均可，匹配时会统一归一）。
# 只收录语义确定等价的项；语义待甲方确认的（如"承诺函致函对象全称"）刻意不映射，保持未提取。
SPEC_LABEL_ALIASES: dict[str, list[str]] = {
    "单台机组功率曲线保证率（%）": ["功率曲线保证率"],
    "单机功率曲线考核阈值": ["功率曲线保证率"],
    "年等效满负荷小时数（保证值，h）": ["保证有效小时数"],
    "年等效满发小时数（保证值，h）": ["保证有效小时数"],
    "等效上网小时数（保证值，h）": ["保证有效小时数"],
    "参考高度处年平均风速（m/s）": ["年平均风速"],
    "单台机组平均可利用率保证值（%）": ["单台可利用率"],
    "单台机组可利用率目标（%）": ["单台可利用率"],
    "单台机组时间可利用率保证值（%）": ["单台可利用率"],
    "质保期单台机组可利用率下限（%）": ["单台可利用率"],
    "全场机组平均可利用率保证值（%）": ["全场可利用率"],
    "全场机组可利用率目标（%）": ["全场可利用率"],
    "全场机组时间可利用率保证值（%）": ["全场可利用率"],
    "质保期全场平均可利用率下限（%）": ["全场可利用率"],
    "主要部件更换率上限（%）": ["主要部件更换率"],
    "投标总装机容量（MW）": ["总装机容量"],
    "招标总装机容量（MW）": ["总装机容量"],
    "投标总容量（MW）": ["总装机容量"],
    "投标总并网容量（MW）": ["总装机容量"],
    "投标机组台数（台）": ["机组台数"],
    "招标风机数量（台）": ["机组台数"],
    "投标单机容量（MW）": ["单机容量"],
    "招标单机容量（出口端，MW）": ["单机容量"],
    "投标叶轮直径（m）": ["叶轮直径"],
    "招标叶轮直径（m）": ["叶轮直径"],
    "投标方案名称": ["投标方案"],
    "函件签署日期": ["日期"],
    # spec label"发电小时数/电量承诺函版本"含"发电小时"，canonical 会坍缩为"保证有效小时数"，
    # 专项抽取器改产出此别名归位（technical_fact_special_extractors.facts_from_hours_commitment_docx）
    "发电小时数/电量承诺函版本": ["电量承诺函版本"],
}

# 骨架字段分类（sourceKind → 事实表 category）
SPEC_SOURCE_KIND_CATEGORIES = {
    "tender": "清单-招标文件",
    "material": "清单-项目定制材料",
    "cert": "清单-认证证书",
    "platform": "清单-平台输入",
    "derived": "清单-自动生成",
}


@lru_cache(maxsize=1)
def load_specs() -> tuple[dict[str, Any], ...]:
    """加载 148 条字段 spec（含 20 条模板更新条目）。"""
    if not SPECS_PATH.exists():
        return ()
    specs = json.loads(SPECS_PATH.read_text(encoding="utf-8"))
    return tuple(spec for spec in specs if isinstance(spec, dict))


def fillable_specs() -> list[dict[str, Any]]:
    """128 条需取数填写的 spec（20 条模板更新条目不进事实表）。"""
    return [spec for spec in load_specs() if spec.get("valueRequired")]


def spec_category(spec: dict[str, Any]) -> str:
    return SPEC_SOURCE_KIND_CATEGORIES.get(str(spec.get("sourceKind") or ""), "清单字段")
