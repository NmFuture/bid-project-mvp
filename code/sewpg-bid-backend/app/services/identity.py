from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.bid_type import BID_TYPES, BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE, require_bid_type


CUSTOMER_REGISTRY = [
    {
        "customerId": "CUST-HUANENG",
        "customerCanonicalName": "华能集团",
        "customerAliases": ["华能", "华能集团", "中国华能", "华能新能源"],
    },
    {
        "customerId": "CUST-DATANG",
        "customerCanonicalName": "大唐集团",
        "customerAliases": ["大唐", "大唐集团", "中国大唐", "大唐新能源"],
    },
    {
        "customerId": "CUST-CHNENERGY",
        "customerCanonicalName": "国家能源集团",
        "customerAliases": ["国能", "国家能源", "国家能源集团", "国能投"],
    },
    {
        "customerId": "CUST-SEWPG",
        "customerCanonicalName": "上海电气风电集团",
        "customerAliases": ["上海电气", "上海电气风电", "上海电气风电集团", "投标方"],
    },
]


ROOT_TIER_ALIASES = {
    "通用素材": "standard",
    "标准文件": "standard",
    "标准模板": "standard",
    "客户素材": "customer",
    "客户定制": "customer",
    "项目素材": "project",
    "项目定制": "project",
}

TECHNICAL_MATERIAL_ROOT = TECHNICAL_BID_TYPE
BUSINESS_MATERIAL_ROOT = BUSINESS_BID_TYPE


def material_scope_root_name(bid_type: str, tier: str) -> str:
    if bid_type == TECHNICAL_BID_TYPE:
        return {
            "standard": "标准文件",
            "customer": "客户定制",
            "project": "项目定制",
        }.get(tier, "")
    return {
        "standard": "通用素材",
        "customer": "客户素材",
        "project": "项目素材",
    }.get(tier, "")


def normalize_identity_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|]+", "", text)
    return text


def _stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10].upper()


def generate_material_project_id(*values: Any) -> str:
    normalized = normalize_identity_text("".join(str(value or "") for value in values))
    if not normalized:
        normalized = "ordinaryproject"
    return f"MATPRJ-{_stable_hash(normalized)}"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = normalize_identity_text(text)
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def canonical_customer(value: Any) -> dict[str, Any]:
    raw = str(value or "").strip()
    normalized = normalize_identity_text(raw)
    if not normalized:
        return {
            "customerId": "",
            "customerCanonicalName": "",
            "customerAliases": [],
            "customerInput": raw,
            "customerMatchedBy": "",
        }

    for item in CUSTOMER_REGISTRY:
        aliases = [str(alias) for alias in item["customerAliases"]]
        alias_keys = [normalize_identity_text(alias) for alias in aliases]
        for alias, alias_key in zip(aliases, alias_keys, strict=False):
            if normalized == alias_key or normalized in alias_key or alias_key in normalized:
                return {
                    "customerId": item["customerId"],
                    "customerCanonicalName": item["customerCanonicalName"],
                    "customerAliases": aliases,
                    "customerInput": raw,
                    "customerMatchedBy": alias,
                }

    canonical_name = raw
    return {
        "customerId": f"CUST-{_stable_hash(normalized)}",
        "customerCanonicalName": canonical_name,
        "customerAliases": _dedupe([raw]),
        "customerInput": raw,
        "customerMatchedBy": "fallback",
    }


def classify_material_path(folder_path: Any, default_bid_type: str) -> dict[str, Any]:
    path = str(folder_path or "").replace("\\", "/").strip("/")
    parts = [part for part in path.split("/") if part]
    root = parts[0] if parts else ""
    tier = ""
    bid_type = require_bid_type(
        default_bid_type,
        allow_general=True,
        error_message="素材路径分类必须显式传入技术标、商务标或通用。",
    )
    customer_name = ""
    project_id = ""

    if root in {TECHNICAL_MATERIAL_ROOT, BUSINESS_MATERIAL_ROOT}:
        bid_type = root
        tier_root = parts[1] if len(parts) >= 2 else ""
        tier = ROOT_TIER_ALIASES.get(tier_root, "")
        if tier == "standard":
            customer_name = "平台标准"
        elif tier == "customer" and len(parts) >= 3:
            customer_name = parts[2]
        elif tier == "project" and len(parts) >= 3:
            project_id = parts[2]
    else:
        # Compatibility for legacy folders created before bid type became the top-level root.
        tier = ROOT_TIER_ALIASES.get(root, "")
        if tier == "standard":
            if len(parts) >= 2 and parts[1] in BID_TYPES:
                bid_type = parts[1]
            customer_name = "平台标准"
        elif tier == "customer":
            if len(parts) >= 2:
                customer_name = parts[1]
            if len(parts) >= 3 and parts[2] in BID_TYPES:
                bid_type = parts[2]
        elif tier == "project":
            if len(parts) >= 2:
                project_id = parts[1]
            if len(parts) >= 3 and parts[2] in BID_TYPES:
                bid_type = parts[2]

    return {
        "folderPath": path,
        "materialTier": tier,
        "bidType": bid_type,
        "customerName": customer_name,
        "projectId": project_id,
    }


def build_project_identity(project: dict[str, Any]) -> dict[str, Any]:
    bid_project_id = str(project.get("id") or "").strip()
    bid_project_code = str(
        project.get("projectCode")
        or project.get("externalProjectNo")
        or project.get("projectNo")
        or bid_project_id
    ).strip()
    owner = str(project.get("owner") or project.get("customerName") or "").strip()
    customer = canonical_customer(owner)
    selected_customer_id = str(project.get("materialCustomerId") or project.get("customerId") or "").strip()
    selected_customer_name = str(
        project.get("materialCustomerName")
        or project.get("customerCanonicalName")
        or customer["customerCanonicalName"]
        or owner
    ).strip()
    selected_customer_aliases = _dedupe(
        [
            selected_customer_name,
            owner,
            *(project.get("customerAliases") or []),
            *customer["customerAliases"],
        ]
    )
    if selected_customer_id:
        customer = {
            "customerId": selected_customer_id,
            "customerCanonicalName": selected_customer_name,
            "customerAliases": selected_customer_aliases,
            "customerInput": owner,
            "customerMatchedBy": "material-library",
        }

    bid_project_name = str(project.get("name") or bid_project_id).strip()
    material_project_mode = str(project.get("materialProjectMode") or "").strip()
    material_project_id = str(project.get("materialProjectId") or "").strip()
    material_project_code = str(project.get("materialProjectCode") or bid_project_code or "").strip()
    material_project_name = str(project.get("materialProjectName") or bid_project_name).strip()
    if not material_project_id:
        if material_project_mode == "ordinary":
            material_project_id = generate_material_project_id(
                customer["customerId"],
                material_project_code,
                material_project_name,
            )
        else:
            material_project_id = bid_project_id
    if not material_project_code:
        material_project_code = material_project_id
    return {
        "workspaceProjectId": bid_project_id,
        "bidProjectId": bid_project_id,
        "bidProjectCode": bid_project_code,
        "bidProjectName": bid_project_name,
        "projectId": material_project_id,
        "projectCode": material_project_code,
        "projectName": material_project_name,
        "materialProjectMode": material_project_mode or ("library" if material_project_id != bid_project_id else ""),
        "bidType": require_bid_type(
            project.get("bidType"),
            error_message="项目身份必须显式传入技术标或商务标。",
        ),
        "owner": owner,
        "customerName": owner,
        "customerId": customer["customerId"],
        "customerCanonicalName": customer["customerCanonicalName"],
        "customerAliases": customer["customerAliases"],
        "customerInput": customer["customerInput"],
        "customerMatchedBy": customer["customerMatchedBy"],
        "matchKeys": _dedupe(
            [
                bid_project_id,
                bid_project_code,
                bid_project_name,
                material_project_id,
                material_project_code,
                material_project_name,
                owner,
                customer["customerCanonicalName"],
                *customer["customerAliases"],
            ]
        ),
    }


def build_project_material_scope(project: dict[str, Any]) -> dict[str, Any]:
    identity = build_project_identity(project)
    bid_type = require_bid_type(
        identity.get("bidType") or project.get("bidType"),
        error_message="项目素材范围必须显式传入技术标或商务标。",
    )
    customer_name = str(identity.get("customerCanonicalName") or identity.get("customerName") or "").strip()
    project_id = str(identity.get("projectId") or identity.get("bidProjectId") or project.get("id") or "").strip()
    project_folder_name = (
        str(project.get("name") or "").strip()
        if bid_type == TECHNICAL_BID_TYPE
        else project_id
    )
    standard_root = material_scope_root_name(bid_type, "standard")
    customer_root = material_scope_root_name(bid_type, "customer")
    project_root = material_scope_root_name(bid_type, "project")
    scopes: list[dict[str, Any]] = [
        {
            "key": "standard",
            "label": standard_root,
            "materialTier": "standard",
            "path": f"{bid_type}/{standard_root}",
            "identityMatchedBy": "bidType",
        }
    ]
    if customer_name:
        scopes.append(
            {
                "key": "customer",
                "label": customer_root,
                "materialTier": "customer",
                "path": f"{bid_type}/{customer_root}/{customer_name}",
                "customerId": str(identity.get("customerId") or ""),
                "customerName": customer_name,
                "identityMatchedBy": "customer",
            }
        )
    if project_id and project_folder_name:
        scopes.append(
            {
                "key": "project",
                "label": project_root,
                "materialTier": "project",
                "path": f"{bid_type}/{project_root}/{project_folder_name}",
                "projectId": project_id,
                "projectCode": str(identity.get("projectCode") or ""),
                "projectName": str(identity.get("projectName") or ""),
                "identityMatchedBy": "project",
            }
        )
    return {
        "bidType": bid_type,
        "identity": identity,
        "readableScopes": scopes,
        "paths": [scope["path"] for scope in scopes],
        "summary": "；".join(scope["path"] for scope in scopes),
    }


def material_identity(
    *,
    material_tier: Any,
    bid_type: Any,
    customer_name: Any = "",
    project_id: Any = "",
    project_code: Any = "",
    project_name: Any = "",
) -> dict[str, Any]:
    tier = str(material_tier or "").strip()
    if tier == "standard":
        return {
            "identityScope": "general",
            "materialScope": "general",
            "bidType": require_bid_type(bid_type, allow_general=True),
            "customerId": "",
            "customerCanonicalName": "",
            "customerAliases": [],
            "projectId": "",
            "projectCode": "",
            "projectName": "",
            "identityDisplay": "通用素材",
        }

    if tier == "customer":
        customer = canonical_customer(customer_name)
        return {
            "identityScope": "customer",
            "materialScope": "customer",
            "bidType": require_bid_type(bid_type, allow_general=True),
            "customerId": customer["customerId"],
            "customerCanonicalName": customer["customerCanonicalName"],
            "customerAliases": customer["customerAliases"],
            "projectId": "",
            "projectCode": "",
            "projectName": "",
            "identityDisplay": customer["customerCanonicalName"] or str(customer_name or ""),
        }

    clean_project_id = str(project_id or "").strip()
    clean_project_code = str(project_code or project_id or "").strip()
    return {
        "identityScope": "project",
        "materialScope": "project",
        "bidType": require_bid_type(bid_type, allow_general=True),
        "customerId": canonical_customer(customer_name)["customerId"] if customer_name else "",
        "customerCanonicalName": canonical_customer(customer_name)["customerCanonicalName"] if customer_name else "",
        "customerAliases": canonical_customer(customer_name)["customerAliases"] if customer_name else [],
        "projectId": clean_project_id,
        "projectCode": clean_project_code,
        "projectName": str(project_name or "").strip(),
        "identityDisplay": clean_project_code or clean_project_id or "未命名项目",
    }


def _candidate_keys(*values: Any) -> set[str]:
    keys: set[str] = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            keys.update(_candidate_keys(*value))
            continue
        key = normalize_identity_text(value)
        if key:
            keys.add(key)
    return keys


def customer_matches(customer_name: Any, ext: dict[str, Any]) -> bool:
    raw_query = str(customer_name or "").strip()
    raw_query_key = normalize_identity_text(raw_query)
    direct_ext_values = [
        ext.get("customerName"),
        ext.get("customerCanonicalName"),
        *(ext.get("customerAliases") or []),
    ]
    direct_ext_keys = _candidate_keys(*direct_ext_values)
    if raw_query_key and raw_query_key in direct_ext_keys:
        return True

    query = canonical_customer(customer_name)
    ext_customer_id = str(ext.get("customerId") or "").strip()
    exact_known_customer = raw_query_key and raw_query_key in _candidate_keys(
        query["customerCanonicalName"],
        query["customerAliases"],
    )
    if exact_known_customer and query["customerId"] and ext_customer_id and query["customerId"] == ext_customer_id:
        return True
    if raw_query_key and direct_ext_keys:
        return False
    query_keys = _candidate_keys(customer_name, query["customerCanonicalName"], query["customerAliases"])
    ext_keys = _candidate_keys(
        ext.get("customerName"),
        ext.get("customerCanonicalName"),
        ext.get("customerAliases") or [],
    )
    return bool(query_keys and ext_keys and (query_keys & ext_keys))


def project_matches(project_id: Any, ext: dict[str, Any]) -> bool:
    query_keys = _candidate_keys(project_id)
    ext_keys = _candidate_keys(ext.get("projectId"), ext.get("projectCode"), ext.get("projectName"))
    return bool(query_keys and ext_keys and (query_keys & ext_keys))
