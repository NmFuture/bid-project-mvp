from __future__ import annotations

"""清单驱动的素材类别映射（技术标事实表）。

以 148 条清单 spec 的 `referenceFile` 列为唯一权威指路牌：
- `material_class_of(spec)` 把 spec 归一到素材类别（注意清单原文 typo
  "基础弯矩表表" 靠"弯矩"子串归一到 bending_moment）；
- `classify_material(material)` 按素材文件名/folderPath 归一到同一类别；
- `required_material_classes()` 从 fillable_specs() 聚合每类需取数字段；
- `material_home_project(material)` 从 folderPath「技术标/项目定制/{项目名}/...」解析归属项目；
- `build_fact_material_check(project, gap_state)` 齐备性预检（T2）：本项目素材按类别对账，
  缺失类别扫全库「技术标/项目定制」给跨项目候选（仅元数据，不下载）。

类别与匹配关键词风格与 technical_gap_fact_table.material_is_fact_relevant 保持一致。
"""

import logging
import re
from typing import Any

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.technical_fact_field_specs import fillable_specs
from app.services.technical_fact_spec_versions import FACT_SPECS_SOURCE_PROJECT, resolve_project_specs
from app.services.technical_gap_fact_table import (
    project_fact_material_index,
    run_async_material_files,
)

logger = logging.getLogger(__name__)

# 需要素材取数的类别（tender 走招标文件解析产物，platform/derived 无需素材）
MATERIAL_CLASS_WIND_RESOURCE = "wind_resource"
MATERIAL_CLASS_TOWER_QUANTITY = "tower_quantity"
MATERIAL_CLASS_BENDING_MOMENT = "bending_moment"
MATERIAL_CLASS_HOURS_COMMITMENT = "hours_commitment"
MATERIAL_CLASS_PRODUCTION_BASE = "production_base"
MATERIAL_CLASS_CERT = "cert"

MATERIAL_CLASSES = [
    MATERIAL_CLASS_WIND_RESOURCE,
    MATERIAL_CLASS_TOWER_QUANTITY,
    MATERIAL_CLASS_BENDING_MOMENT,
    MATERIAL_CLASS_HOURS_COMMITMENT,
    MATERIAL_CLASS_PRODUCTION_BASE,
    MATERIAL_CLASS_CERT,
]

# 无需素材的类别：tender 只从 tenderSources 取数，platform/derived 由平台/系统生成
MATERIAL_CLASS_TENDER = "tender"
MATERIAL_CLASS_PLATFORM = "platform"
MATERIAL_CLASS_DERIVED = "derived"
MATERIAL_CLASS_NONE = "none"

# referenceFile / 素材文件名共用的类别关键词（按优先级先后匹配，命中即归一）。
# wind_resource 必须在 tender 之前："项目定制-风资源报告\n招标文件"这类多行指路牌归风资源。
_MATERIAL_CLASS_PATTERNS: list[tuple[str, str]] = [
    (MATERIAL_CLASS_WIND_RESOURCE, r"风资源|测风"),
    (MATERIAL_CLASS_TOWER_QUANTITY, r"塔架|工程量"),
    (MATERIAL_CLASS_BENDING_MOMENT, r"弯矩"),
    (MATERIAL_CLASS_HOURS_COMMITMENT, r"承诺函|小时数承诺"),
    (MATERIAL_CLASS_PRODUCTION_BASE, r"生产基地|基地专题|供货制造基地"),
    (MATERIAL_CLASS_CERT, r"认证|证书|型式"),
]

_REFERENCE_ONLY_PATTERNS: list[tuple[str, str]] = [
    (MATERIAL_CLASS_TENDER, r"招标文件"),
    (MATERIAL_CLASS_PLATFORM, r"平台输入"),
    (MATERIAL_CLASS_DERIVED, r"自动生成"),
]

# 跨项目候选每类上限（预检返回用；curator 注入额度另见 technical_fact_curator）
CROSS_PROJECT_CANDIDATE_LIMIT = 5


def material_class_of(spec: dict[str, Any]) -> str:
    """spec → 素材类别。referenceFile 多行时按关键词优先级归一；"/" 等无法归一的给 none。"""
    text = str(spec.get("referenceFile") or "")
    for material_class, pattern in [*_MATERIAL_CLASS_PATTERNS, *_REFERENCE_ONLY_PATTERNS]:
        if re.search(pattern, text):
            return material_class
    return MATERIAL_CLASS_NONE


def classify_material(material: dict[str, Any]) -> str | None:
    """素材 → 类别：按文件名 + folderPath 关键词匹配，都不命中返回 None。"""
    text = " ".join(
        str(material.get(key) or "")
        for key in ("name", "cleanedFileName", "folderPath")
    )
    if not text.strip():
        return None
    for material_class, pattern in _MATERIAL_CLASS_PATTERNS:
        if re.search(pattern, text):
            return material_class
    return None


def material_home_project(material: dict[str, Any]) -> str:
    """从 folderPath「技术标/项目定制/{项目名}/...」解析归属项目名（第三段），否则 ""。"""
    folder_path = str(material.get("folderPath") or "")
    parts = [part for part in folder_path.split("/") if part]
    if len(parts) >= 3 and parts[0] == TECHNICAL_BID_TYPE and parts[1] == "项目定制":
        return parts[2]
    return ""


def required_material_classes(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """从 fillable spec 聚合需素材类别 → {fieldKeys, fieldCount}（无需素材类别不计入）。

    specs 为 None 时用系统默认清单 fillable_specs()；项目链路传项目绑定版本快照。
    """
    required: dict[str, dict[str, Any]] = {
        material_class: {"fieldKeys": [], "fieldCount": 0} for material_class in MATERIAL_CLASSES
    }
    active_specs = (
        [spec for spec in specs if spec.get("valueRequired")] if specs is not None else fillable_specs()
    )
    for spec in active_specs:
        material_class = material_class_of(spec)
        info = required.get(material_class)
        if info is None:
            continue
        info["fieldKeys"].append(str(spec.get("key") or ""))
        info["fieldCount"] += 1
    return {key: value for key, value in required.items() if value["fieldCount"]}


def _cross_project_material_pool() -> list[dict[str, Any]]:
    """全库「技术标/项目定制」素材元数据（不下载）；查询失败按无候选继续。"""
    try:
        payload = run_async_material_files(
            folder_path=f"{TECHNICAL_BID_TYPE}/项目定制",
            recursive=True,
            page=1,
            page_size=10000,
        )
    except Exception:
        logger.exception("跨项目素材扫描失败，按无候选继续")
        return []
    return [item for item in (payload.get("items") or []) if isinstance(item, dict)]


def build_fact_material_check(project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
    """素材齐备性预检：按清单类别对账本项目范围内素材，缺失类别给跨项目候选。

    同步重活（素材索引内部经 run_awaitable_sync 桥接异步），调用方须放工作线程。
    """
    # 规则按项目绑定版本取（R06-B04-02）；项目未上传实时表时回落系统默认清单
    project_specs, specs_meta = resolve_project_specs(gap_state)
    required = required_material_classes(
        project_specs if specs_meta.get("source") == FACT_SPECS_SOURCE_PROJECT else None
    )
    materials = project_fact_material_index(project, gap_state)
    project_name = str(project.get("name") or "")
    matched_by_class: dict[str, list[dict[str, Any]]] = {key: [] for key in required}
    for material in materials:
        material_class = classify_material(material)
        if material_class in matched_by_class:
            matched_by_class[material_class].append(material)
    missing_classes = [key for key in required if not matched_by_class[key]]
    # 全库扫描只在有缺失类别时做一次（仅元数据，不下载）
    pool = _cross_project_material_pool() if missing_classes else []
    own_ids = {str(material.get("id") or "") for material in materials}

    classes: list[dict[str, Any]] = []
    for material_class, info in required.items():
        matched = [
            {
                "id": str(material.get("id") or ""),
                "name": str(material.get("name") or material.get("cleanedFileName") or ""),
                "folderPath": str(material.get("folderPath") or ""),
            }
            for material in matched_by_class[material_class]
        ]
        missing = material_class in missing_classes
        candidates: list[dict[str, Any]] = []
        if missing:
            for item in pool:
                if len(candidates) >= CROSS_PROJECT_CANDIDATE_LIMIT:
                    break
                if classify_material(item) != material_class:
                    continue
                home_project = material_home_project(item)
                if not home_project or home_project == project_name:
                    continue
                item_id = str(item.get("id") or "")
                if not item_id or item_id in own_ids:
                    continue
                candidates.append(
                    {
                        "id": item_id,
                        "name": str(item.get("name") or item.get("cleanedFileName") or ""),
                        "folderPath": str(item.get("folderPath") or ""),
                        "homeProject": home_project,
                    }
                )
        classes.append(
            {
                "class": material_class,
                "requiredFieldCount": info["fieldCount"],
                "fieldKeys": info["fieldKeys"],
                "matched": matched,
                "missing": missing,
                "crossProjectCandidates": candidates,
            }
        )
    return {
        "classes": classes,
        "summary": {
            "missingClasses": missing_classes,
            "affectedFieldCount": sum(required[key]["fieldCount"] for key in missing_classes),
        },
    }
