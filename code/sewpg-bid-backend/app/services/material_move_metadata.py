from __future__ import annotations

from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.material_taxonomy import (
    BUSINESS_MATERIAL_CATEGORY_LABELS,
    BUSINESS_MATERIAL_CATEGORY_SORT_ORDERS,
    MATERIAL_TIER_LABELS,
    infer_business_material_category,
    infer_business_material_subcategory,
)


RAW_MOVE_FILE_ACTION = "move"
RAW_MOVE_FILE_VERSION_ACTION = "version"
RAW_MOVE_FOLDER_ACTION = "move-folder"
RAW_RENAME_FOLDER_ACTION = "rename-folder"
RAW_MATERIAL_OPERATOR_LABEL = "当前用户"


def build_raw_move_file_ext_fields(
    ext_fields: dict[str, Any],
    *,
    source_minio_key: str,
    source_file_name: str,
    material_tier: str,
    destination_bid_type: str,
    folder_path: str = "",
    destination_project_id: str = "",
    destination_customer_name: str = "",
    last_action: str = "",
    last_operator: str = RAW_MATERIAL_OPERATOR_LABEL,
) -> dict[str, Any]:
    ext = dict(ext_fields or {})
    ext.update(
        {
            "sourceMinioKey": source_minio_key,
            "sourceFileName": source_file_name,
            "materialTier": material_tier,
            "materialTierLabel": MATERIAL_TIER_LABELS.get(material_tier, ""),
            "projectId": destination_project_id or ext.get("projectId") or "",
            "customerName": destination_customer_name or ext.get("customerName") or "",
            "bidType": destination_bid_type or ext.get("bidType") or "",
        }
    )
    if destination_bid_type == BUSINESS_BID_TYPE:
        material_category = infer_business_material_category(folder_path, source_file_name, material_tier)
        material_subcategory = infer_business_material_subcategory(folder_path, source_file_name)
        ext.update(
            {
                "materialCategory": material_category,
                "materialCategoryLabel": BUSINESS_MATERIAL_CATEGORY_LABELS.get(material_category, ""),
                "materialSubcategory": material_subcategory,
                "sortOrder": BUSINESS_MATERIAL_CATEGORY_SORT_ORDERS.get(material_category, 999),
            }
        )
    if last_action:
        ext.update({"lastAction": last_action, "lastOperator": last_operator})
    return ext


def build_raw_move_folder_file_ext_fields(
    ext_fields: dict[str, Any],
    *,
    source_minio_key: str,
    source_file_name: str,
    material_tier: str,
    destination_bid_type: str,
    folder_path: str = "",
    destination_project_id: str = "",
    destination_customer_name: str = "",
    last_action: str = RAW_MOVE_FOLDER_ACTION,
) -> dict[str, Any]:
    ext = build_raw_move_file_ext_fields(
        ext_fields,
        source_minio_key=source_minio_key,
        source_file_name=source_file_name,
        folder_path=folder_path,
        material_tier=material_tier,
        destination_bid_type=destination_bid_type,
        destination_project_id=destination_project_id,
        destination_customer_name=destination_customer_name,
    )
    ext.update({"lastAction": last_action, "lastOperator": RAW_MATERIAL_OPERATOR_LABEL})
    return ext
