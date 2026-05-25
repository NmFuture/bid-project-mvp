from __future__ import annotations

from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, GENERAL_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.identity import classify_material_path
from app.services.material_taxonomy import (
    BUSINESS_CUSTOMIZED_SUBFOLDERS,
    BUSINESS_STANDARD_SUBFOLDERS,
    BUSINESS_TIER_FOLDERS,
    RAW_MATERIAL_ROOTS,
    TECHNICAL_TIER_FOLDERS,
    business_customized_child_tier_for_parent_path as _business_customized_child_tier_for_parent_path,
    business_customized_tier_from_path as _business_customized_tier_from_path,
    normalize_material_tier,
)


MATERIAL_BID_TYPES = {TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE}
BUSINESS_MATERIAL_BID_TYPE = BUSINESS_BID_TYPE
RAW_FOLDER_MOVE_PROTECTED_PATHS = MATERIAL_BID_TYPES
RAW_PERMISSION_ACTIONS = {"upload": True, "rename": True, "move": True, "delete": True}
TIER_FOLDER_NAMES = {
    "standard": "通用素材",
    "customer": "客户素材",
    "project": "项目素材",
}
TIER_FOLDER_SORT_ORDER = {
    "standard": 1,
    "customer": 2,
    "project": 3,
}


def normalize_material_bid_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in MATERIAL_BID_TYPES else ""


def require_material_bid_type(value: Any, label: str = "标类") -> str:
    normalized = normalize_material_bid_type(value)
    if not normalized:
        raise ValueError(f"{label}必须是技术标或商务标。")
    return normalized


def material_bid_type_sort_order(bid_type: str) -> int:
    return 1 if require_material_bid_type(bid_type) == TECHNICAL_BID_TYPE else 2


def raw_material_root_specs() -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in RAW_MATERIAL_ROOTS)


def build_raw_material_permissions(role: str = "member") -> dict[str, Any]:
    normalized_role = "admin" if str(role or "") == "admin" else "member"
    return {
        "role": normalized_role,
        "rules": [
            {
                "pathPrefix": str(spec["name"]),
                "label": f"{spec['name']}素材",
                "actions": dict(RAW_PERMISSION_ACTIONS),
            }
            for spec in raw_material_root_specs()
        ],
    }


def raw_material_tier_folder_specs(bid_type: str) -> tuple[dict[str, Any], ...]:
    normalized_bid_type = require_material_bid_type(bid_type)
    source = TECHNICAL_TIER_FOLDERS if normalized_bid_type == TECHNICAL_BID_TYPE else BUSINESS_TIER_FOLDERS
    return tuple(dict(item) for item in source)


def is_raw_folder_move_protected_path(folder_path: str) -> bool:
    normalized = str(folder_path or "").replace("\\", "/").strip("/")
    return normalized in RAW_FOLDER_MOVE_PROTECTED_PATHS


def is_raw_folder_move_descendant_target(source_path: str, target_parent_path: str) -> bool:
    source = str(source_path or "").replace("\\", "/").strip("/")
    target = str(target_parent_path or "").replace("\\", "/").strip("/")
    return bool(source and target and (target == source or target.startswith(f"{source}/")))


def business_standard_subfolder_specs(customer_name: str | None = None) -> tuple[dict[str, Any], ...]:
    specs: list[dict[str, Any]] = []
    for spec in BUSINESS_STANDARD_SUBFOLDERS:
        specs.append(
            {
                "name": str(spec["name"]),
                "tier": str(spec["tier"]),
                "bidType": BUSINESS_MATERIAL_BID_TYPE,
                "projectId": None,
                "customerName": customer_name,
                "sortOrder": int(spec["sort_order"]),
                "children": tuple(
                    {
                        "name": str(child["name"]),
                        "tier": str(child["tier"]),
                        "bidType": BUSINESS_MATERIAL_BID_TYPE,
                        "projectId": None,
                        "customerName": customer_name,
                        "sortOrder": int(child["sort_order"]),
                    }
                    for child in spec.get("children") or ()
                ),
            }
        )
    return tuple(specs)


def business_customized_subfolder_specs(
    *,
    tier: str,
    project_id: str | None = None,
    customer_name: str | None = None,
) -> tuple[dict[str, Any], ...]:
    material_tier = normalize_material_tier(tier) or "customer"
    return tuple(
        {
            "name": str(spec["name"]),
            "tier": material_tier,
            "bidType": BUSINESS_MATERIAL_BID_TYPE,
            "projectId": project_id,
            "customerName": customer_name,
            "sortOrder": int(spec["sort_order"]),
        }
        for spec in BUSINESS_CUSTOMIZED_SUBFOLDERS
    )


def business_customized_tier_from_folder_path(folder_path: str) -> str:
    return _business_customized_tier_from_path(folder_path)


def business_customized_child_tier_for_parent_folder_path(parent_path: str) -> str:
    return _business_customized_child_tier_for_parent_path(parent_path)


def material_tier_folder_name(material_tier: str) -> str:
    tier = normalize_material_tier(material_tier) or "project"
    return TIER_FOLDER_NAMES[tier]


def material_tier_folder_sort_order(material_tier: str) -> int:
    tier = normalize_material_tier(material_tier) or "project"
    return TIER_FOLDER_SORT_ORDER[tier]


def material_tier_root_path(bid_type: str, material_tier: str) -> str:
    normalized_bid_type = require_material_bid_type(bid_type)
    return f"{normalized_bid_type}/{material_tier_folder_name(material_tier)}"


def project_material_root_path(bid_type: str, project_id: str) -> str:
    return f"{material_tier_root_path(bid_type, 'project')}/{str(project_id or '').strip()}"


def infer_material_tier_from_folder(*, tier: str = "", path: str = "") -> str:
    normalized_tier = normalize_material_tier(str(tier or ""))
    if normalized_tier:
        return normalized_tier
    normalized_path = str(path or "").replace("\\", "/").strip("/")
    if normalized_path.startswith(
        (f"{TECHNICAL_BID_TYPE}/通用素材", f"{BUSINESS_BID_TYPE}/通用素材", "通用素材", "标准模板")
    ):
        return "standard"
    if normalized_path.startswith(
        (f"{TECHNICAL_BID_TYPE}/客户素材", f"{BUSINESS_BID_TYPE}/客户素材", "客户素材", "客户定制")
    ):
        return "customer"
    return "project"


def infer_material_tier_from_raw_folder(folder: Any | None) -> str:
    if folder is None:
        return "project"
    return infer_material_tier_from_folder(
        tier=str(getattr(folder, "tier", "") or ""),
        path=str(getattr(folder, "path", "") or ""),
    )


def canonical_raw_folder_metadata(folder_path: str) -> dict[str, Any]:
    normalized = str(folder_path or "").replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    location = classify_material_path(normalized, GENERAL_BID_TYPE)

    if normalized == TECHNICAL_BID_TYPE:
        return _metadata(parts[-1] if parts else TECHNICAL_BID_TYPE, "standard", TECHNICAL_BID_TYPE, sort_order=1)
    if normalized == BUSINESS_BID_TYPE:
        return _metadata(parts[-1] if parts else BUSINESS_BID_TYPE, "standard", BUSINESS_BID_TYPE, sort_order=2)

    tier = normalize_material_tier(str(location.get("materialTier") or "")) or "project"
    location_bid_type = str(location.get("bidType") or "")
    bid_type = (
        location_bid_type
        if location_bid_type in MATERIAL_BID_TYPES or location_bid_type == GENERAL_BID_TYPE
        else GENERAL_BID_TYPE
    )
    sort_order = 0
    if len(parts) == 2 and parts[0] in MATERIAL_BID_TYPES:
        sort_order = TIER_FOLDER_SORT_ORDER.get(tier, 0)
    return _metadata(
        parts[-1] if parts else "",
        tier,
        bid_type,
        project_id=str(location.get("projectId") or "") or None,
        customer_name=str(location.get("customerName") or "") or None,
        sort_order=sort_order,
    )


def _metadata(
    name: str,
    tier: str,
    bid_type: str,
    *,
    project_id: str | None = None,
    customer_name: str | None = None,
    sort_order: int = 0,
) -> dict[str, Any]:
    return {
        "name": name,
        "tier": tier,
        "bidType": bid_type,
        "projectId": project_id,
        "customerName": customer_name,
        "sortOrder": sort_order,
    }
