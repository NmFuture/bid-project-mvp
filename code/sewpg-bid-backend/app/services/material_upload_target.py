from __future__ import annotations

from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.identity import classify_material_path
from app.services.material_taxonomy import normalize_material_tier


RAW_UPLOAD_BID_TYPES = {TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE}


def normalize_raw_upload_bid_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in RAW_UPLOAD_BID_TYPES else ""


def build_raw_upload_target_plan(
    *,
    target_path: str = "",
    project_id: str = "",
    customer_name: str = "",
    bid_type: str,
    material_tier: str = "",
) -> dict[str, Any]:
    normalized_bid_type = normalize_raw_upload_bid_type(bid_type)
    normalized_tier = normalize_material_tier(material_tier)
    normalized_target_path = str(target_path or "").replace("\\", "/").strip().strip("/")
    if not normalized_bid_type:
        return {
            "mode": "error",
            "code": "BID_TYPE_REQUIRED",
            "bidType": "",
            "materialTier": normalized_tier,
            "targetPath": normalized_target_path,
        }

    if not normalized_target_path:
        return {
            "mode": "auto",
            "bidType": normalized_bid_type,
            "materialTier": normalized_tier or ("project" if project_id else "standard"),
            "targetPath": "",
            "customerName": customer_name,
            "projectId": project_id,
        }

    target_parts = [part for part in normalized_target_path.split("/") if part]
    location = classify_material_path(normalized_target_path, normalized_bid_type)
    inferred_tier = normalize_material_tier(str(location.get("materialTier") or ""))
    inferred_customer_name = str(customer_name or "")
    inferred_project_id = str(project_id or "")

    if inferred_tier == "standard":
        inferred_customer_name = inferred_customer_name or "平台标准"
    elif inferred_tier == "customer":
        inferred_customer_name = inferred_customer_name or str(location.get("customerName") or "")
    elif inferred_tier == "project":
        inferred_project_id = inferred_project_id or str(location.get("projectId") or "")

    if inferred_tier and len(target_parts) <= 2:
        return {
            "mode": "tier-root",
            "bidType": normalized_bid_type,
            "materialTier": normalized_tier or inferred_tier,
            "inferredTier": inferred_tier,
            "targetPath": normalized_target_path,
            "customerName": inferred_customer_name,
            "projectId": inferred_project_id,
        }

    if not inferred_tier and len(target_parts) == 2 and target_parts[0] in {"客户素材", "客户定制"}:
        inferred_tier = "customer"
        inferred_customer_name = inferred_customer_name or target_parts[1]
    if not inferred_tier and len(target_parts) == 2 and target_parts[0] in {"项目素材", "项目定制"}:
        inferred_tier = "project"
        inferred_project_id = inferred_project_id or target_parts[1]

    if inferred_tier == "customer" and not inferred_customer_name:
        return {
            "mode": "error",
            "code": "CUSTOMER_NAME_REQUIRED",
            "bidType": normalized_bid_type,
            "materialTier": normalized_tier or inferred_tier,
            "targetPath": normalized_target_path,
        }
    if inferred_tier == "project" and not inferred_project_id:
        return {
            "mode": "error",
            "code": "PROJECT_ID_REQUIRED",
            "bidType": normalized_bid_type,
            "materialTier": normalized_tier or inferred_tier,
            "targetPath": normalized_target_path,
        }

    if inferred_tier:
        return {
            "mode": "scoped-path",
            "bidType": normalized_bid_type,
            "materialTier": normalized_tier or inferred_tier,
            "inferredTier": inferred_tier,
            "targetPath": normalized_target_path,
            "requestedPath": "/".join(target_parts),
            "customerName": inferred_customer_name,
            "projectId": inferred_project_id,
        }

    return {
        "mode": "existing-path",
        "bidType": normalized_bid_type,
        "materialTier": normalized_tier,
        "targetPath": normalized_target_path,
    }


def resolve_raw_upload_canonical_target(requested_path: str, canonical_path: str) -> dict[str, str]:
    normalized_requested = str(requested_path or "").replace("\\", "/").strip().strip("/")
    normalized_canonical = str(canonical_path or "").replace("\\", "/").strip().strip("/")
    requested_parts = [part for part in normalized_requested.split("/") if part]
    if normalized_requested.startswith(f"{normalized_canonical}/"):
        return {
            "mode": "nested",
            "relativeDir": normalized_requested.removeprefix(f"{normalized_canonical}/"),
        }
    if normalized_requested == normalized_canonical or (requested_parts and requested_parts[0] not in RAW_UPLOAD_BID_TYPES):
        return {"mode": "canonical", "relativeDir": ""}
    return {"mode": "not-found", "relativeDir": ""}
