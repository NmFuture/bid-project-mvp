from __future__ import annotations

import hashlib
import re
from typing import Any


BID_TYPES = {"技术标", "商务标", "通用"}


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
    "标准模板": "standard",
    "客户素材": "customer",
    "客户定制": "customer",
    "项目素材": "project",
    "项目定制": "project",
}


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


def normalize_bid_type(value: Any, default: str = "技术标") -> str:
    text = str(value or "").strip()
    return text if text in BID_TYPES else default


def classify_material_path(folder_path: Any, default_bid_type: str = "技术标") -> dict[str, Any]:
    path = str(folder_path or "").replace("\\", "/").strip("/")
    parts = [part for part in path.split("/") if part]
    root = parts[0] if parts else ""
    tier = ROOT_TIER_ALIASES.get(root, "")
    bid_type = normalize_bid_type(default_bid_type)
    customer_name = ""
    project_id = ""

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
        "bidType": normalize_bid_type(project.get("bidType"), "技术标"),
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


def material_identity(
    *,
    material_tier: Any,
    bid_type: Any = "技术标",
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
            "bidType": normalize_bid_type(bid_type),
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
            "bidType": normalize_bid_type(bid_type),
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
        "bidType": normalize_bid_type(bid_type),
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
    query = canonical_customer(customer_name)
    ext_customer_id = str(ext.get("customerId") or "").strip()
    if query["customerId"] and ext_customer_id and query["customerId"] == ext_customer_id:
        return True
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
