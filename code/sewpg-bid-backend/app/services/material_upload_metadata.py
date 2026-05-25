from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, GENERAL_BID_TYPE
from app.services.identity import classify_material_path, material_identity
from app.services.material_taxonomy import (
    BUSINESS_MATERIAL_KIND_LABELS,
    MATERIAL_TIER_LABELS,
    clean_status_for_new_file,
    normalize_business_material_kind,
    normalize_material_tier,
)
from app.services.turbine_models import turbine_model_from_material_name


RAW_UPLOAD_FILE_ACTION = "upload"
RAW_UPLOAD_OVERWRITE_ACTION = "overwrite"
RAW_UPLOAD_VERSION_ACTION = "version"
RAW_UPLOAD_OPERATOR_LABEL = "当前用户"
RAW_UPLOAD_CONFLICT_ACTIONS = {RAW_UPLOAD_OVERWRITE_ACTION, RAW_UPLOAD_VERSION_ACTION}


def build_raw_upload_ext_fields(
    *,
    file_name: str,
    folder_path: str,
    folder_tier: str,
    folder_customer_name: str = "",
    folder_project_id: str = "",
    requested_bid_type: str,
    requested_material_tier: str = "",
    business_material_kind: str = "",
    customer_id: str = "",
    customer_name: str = "",
    project_id: str = "",
    project_code: str = "",
    project_name: str = "",
    source_minio_bucket: str = "",
    source_minio_key: str = "",
    source_relative_path: str = "",
    source_root_folder: str = "",
    clean_updated_at: str = "",
) -> tuple[dict[str, Any], str]:
    location = classify_material_path(folder_path, requested_bid_type or GENERAL_BID_TYPE)
    material_tier = (
        normalize_material_tier(location.get("materialTier"))
        or normalize_material_tier(requested_material_tier)
        or normalize_material_tier(folder_tier)
        or "project"
    )
    bid_type = str(location.get("bidType") or requested_bid_type or GENERAL_BID_TYPE)
    clean_status, clean_message = clean_status_for_new_file(file_name)
    turbine_hint = turbine_model_from_material_name(file_name, folder_path=folder_path)
    item_customer_name = (
        customer_name
        or str(location.get("customerName") or "")
        or folder_customer_name
        or ("平台标准" if material_tier == "standard" else "")
    )
    item_project_id = project_id or str(location.get("projectId") or "") or folder_project_id or ""
    item_project_code = project_code or item_project_id
    item_project_name = project_name
    identity = material_identity(
        material_tier=material_tier,
        bid_type=bid_type,
        customer_name=item_customer_name,
        project_id=item_project_id,
        project_code=item_project_code,
        project_name=item_project_name,
    )
    if customer_id and material_tier in {"customer", "project"}:
        identity["customerId"] = customer_id

    ext_fields = {
        "bidType": bid_type,
        "projectId": item_project_id,
        "projectCode": item_project_code,
        "projectName": item_project_name,
        "customerId": customer_id or identity.get("customerId") or "",
        "customerName": item_customer_name,
        "materialTier": material_tier,
        "materialTierLabel": MATERIAL_TIER_LABELS.get(material_tier, ""),
        **identity,
        "sourceMinioBucket": source_minio_bucket,
        "sourceMinioKey": source_minio_key,
        "sourceFileName": file_name,
        "sourceRelativePath": source_relative_path or file_name,
        "sourceRootFolder": source_root_folder,
        "cleanStatus": clean_status,
        "cleanMessage": clean_message,
        "cleanUpdatedAt": clean_updated_at or _now_utc_iso(),
    }
    if bid_type == BUSINESS_BID_TYPE:
        business_kind = normalize_business_material_kind(business_material_kind) or "other"
        ext_fields.update(
            {
                "businessMaterialKind": business_kind,
                "businessMaterialKindLabel": BUSINESS_MATERIAL_KIND_LABELS.get(business_kind, ""),
            }
        )
    if turbine_hint:
        ext_fields.update(
            {
                "turbineModel": turbine_hint.get("model") or "",
                "turbineModelLabel": turbine_hint.get("model") or "",
                "turbinePlatform": turbine_hint.get("platform") or "",
                "turbineAliases": turbine_hint.get("aliases") or [],
            }
        )
    return ext_fields, clean_status


def build_raw_upload_record_ext_fields(
    ext_fields: dict[str, Any],
    *,
    last_action: str = RAW_UPLOAD_FILE_ACTION,
    last_operator: str = RAW_UPLOAD_OPERATOR_LABEL,
) -> dict[str, Any]:
    ext = dict(ext_fields or {})
    ext.update({"lastAction": last_action, "lastOperator": last_operator})
    return ext


def build_raw_upload_existing_ext_fields(
    current_ext_fields: dict[str, Any],
    upload_ext_fields: dict[str, Any],
    *,
    last_action: str,
    last_operator: str = RAW_UPLOAD_OPERATOR_LABEL,
) -> dict[str, Any]:
    ext = dict(current_ext_fields or {})
    ext.update(dict(upload_ext_fields or {}))
    ext.update({"lastAction": last_action, "lastOperator": last_operator})
    return ext


def _now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
