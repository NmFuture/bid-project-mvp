from __future__ import annotations

from typing import Any

from app.services.identity import customer_matches, project_matches
from app.services.material_folder_scope import MATERIAL_BID_TYPES
from app.services.material_tags import normalize_material_tags
from app.services.material_taxonomy import normalize_business_material_kind, normalize_material_tier


def build_raw_files_payload(
    items: list[Any],
    *,
    bid_type: str,
    project_id: str = "",
    customer_name: str = "",
    material_tier: str = "",
    clean_status: str = "",
    business_material_kind: str = "",
    tag: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    filtered = [
        item
        for item in items
        if raw_file_matches_scope(
            item,
            project_id=project_id,
            customer_name=customer_name,
            bid_type=bid_type,
            material_tier=material_tier,
            clean_status=clean_status,
            business_material_kind=business_material_kind,
            tag=tag,
            keyword=keyword,
        )
    ]
    current_page = max(1, int(page or 1))
    current_page_size = max(1, int(page_size or 20))
    start = (current_page - 1) * current_page_size
    end = start + current_page_size
    return {
        "items": [_raw_file_to_dict(item) for item in filtered[start:end]],
        "total": len(filtered),
        "page": current_page,
        "pageSize": current_page_size,
    }


def raw_file_matches_scope(
    item: Any,
    *,
    bid_type: str,
    project_id: str = "",
    customer_name: str = "",
    material_tier: str = "",
    clean_status: str = "",
    business_material_kind: str = "",
    tag: str = "",
    keyword: str = "",
) -> bool:
    ext = getattr(item, "ext_fields", None) or {}
    if project_id and not project_matches(project_id, ext):
        return False
    if customer_name and not customer_matches(customer_name, ext):
        return False

    requested_bid_type = str(bid_type or "").strip()
    item_bid_type = str(ext.get("bidType") or "")
    if requested_bid_type in MATERIAL_BID_TYPES and item_bid_type not in {requested_bid_type, "通用"}:
        return False
    if requested_bid_type and requested_bid_type not in MATERIAL_BID_TYPES and item_bid_type != requested_bid_type:
        return False

    requested_tier = normalize_material_tier(material_tier)
    item_tier = str(ext.get("materialTier") or _folder_tier(item))
    if requested_tier and item_tier != requested_tier:
        return False

    requested_clean_status = str(clean_status or "").strip()
    if requested_clean_status and requested_clean_status != "all":
        if str(ext.get("cleanStatus") or "") != requested_clean_status:
            return False

    requested_business_kind = normalize_business_material_kind(business_material_kind)
    if requested_business_kind and str(ext.get("businessMaterialKind") or "") != requested_business_kind:
        return False

    tags = normalize_material_tags(ext.get("tags"))
    requested_tag = str(tag or "").strip()
    if requested_tag and not any(requested_tag in item for item in tags):
        return False

    requested_keyword = str(keyword or "").strip().casefold()
    if requested_keyword:
        haystack = " ".join(
            str(value or "")
            for value in [
                getattr(item, "name", ""),
                getattr(getattr(item, "folder", None), "path", ""),
                ext.get("sourceFileName"),
                ext.get("cleanedFileName"),
                ext.get("businessMaterialKindLabel"),
                ext.get("materialTierLabel"),
                ext.get("cleanMessage"),
                ext.get("cleanStatus"),
                ext.get("customerName"),
                ext.get("projectName"),
                ext.get("projectCode"),
                *tags,
            ]
        ).casefold()
        if requested_keyword not in haystack:
            return False

    return True


def raw_file_matches_bid_type(item: Any, bid_type: str) -> bool:
    requested_bid_type = str(bid_type or "").strip()
    item_bid_type = raw_file_bid_type(item)
    if requested_bid_type in MATERIAL_BID_TYPES:
        return item_bid_type in {requested_bid_type, "通用"}
    if requested_bid_type:
        return item_bid_type == requested_bid_type
    return False


def raw_folder_matches_bid_type(folder: Any, bid_type: str) -> bool:
    requested_bid_type = str(bid_type or "").strip()
    folder_bid_type = raw_folder_bid_type(folder)
    if requested_bid_type in MATERIAL_BID_TYPES:
        return folder_bid_type in {requested_bid_type, "通用"}
    if requested_bid_type:
        return folder_bid_type == requested_bid_type
    return False


def raw_file_bid_type(item: Any) -> str:
    ext = getattr(item, "ext_fields", None) or {}
    explicit = str(ext.get("bidType") or "").strip()
    return explicit or raw_folder_bid_type(getattr(item, "folder", None))


def raw_folder_bid_type(folder: Any) -> str:
    if folder is None:
        return ""
    explicit = str(getattr(folder, "bid_type", "") or "").strip()
    if explicit:
        return explicit
    folder_path = str(getattr(folder, "path", "") or "").strip().strip("/")
    return folder_path.split("/", 1)[0] if folder_path else ""


def _folder_tier(item: Any) -> str:
    folder = getattr(item, "folder", None)
    return str(getattr(folder, "tier", "") or "")


def _raw_file_to_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    return dict(item)
