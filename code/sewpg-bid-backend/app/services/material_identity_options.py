from __future__ import annotations

import json
from typing import Any

from app.services.bid_type import GENERAL_BID_TYPE
from app.services.identity import build_project_identity, canonical_customer, classify_material_path
from app.services.material_folder_scope import MATERIAL_BID_TYPES
from app.services.material_taxonomy import normalize_material_tier


def build_material_identity_options(
    *,
    folders: list[Any],
    files: list[Any],
    project_rows: list[Any],
    bid_type: str,
) -> dict[str, Any]:
    normalized_bid_type = str(bid_type or "").strip()
    if normalized_bid_type not in MATERIAL_BID_TYPES:
        normalized_bid_type = ""

    customers: dict[str, dict[str, Any]] = {}
    projects: dict[str, dict[str, Any]] = {}

    def sort_key(item: dict[str, Any]) -> str:
        return str(item.get("name") or item.get("projectName") or item.get("customerCanonicalName") or "")

    def add_customer(
        *,
        customer_id: str = "",
        name: str = "",
        aliases: list[str] | None = None,
        source: str = "material",
    ) -> None:
        candidate = canonical_customer(name)
        clean_id = str(customer_id or candidate.get("customerId") or "").strip()
        clean_name = str(name or candidate.get("customerCanonicalName") or clean_id).strip()
        if not clean_id and not clean_name:
            return
        clean_id = clean_id or str(candidate.get("customerId") or "")
        existing = customers.get(clean_id) or {}
        merged_aliases = []
        for alias in [
            *(existing.get("aliases") or []),
            *(aliases or []),
            *(candidate.get("customerAliases") or []),
            clean_name,
        ]:
            text = str(alias or "").strip()
            if text and text not in merged_aliases:
                merged_aliases.append(text)
        customers[clean_id] = {
            "id": clean_id,
            "customerId": clean_id,
            "name": clean_name or existing.get("name") or clean_id,
            "customerCanonicalName": clean_name or existing.get("customerCanonicalName") or clean_id,
            "aliases": merged_aliases,
            "source": source if not existing.get("source") else existing["source"],
        }

    def add_project(
        *,
        project_id: str = "",
        project_code: str = "",
        project_name: str = "",
        customer_id: str = "",
        customer_name: str = "",
        item_bid_type: str,
        source: str = "material",
    ) -> None:
        clean_project_id = str(project_id or "").strip()
        if not clean_project_id:
            return
        if normalized_bid_type and item_bid_type and item_bid_type not in {normalized_bid_type, "通用"}:
            return
        clean_project_code = str(project_code or clean_project_id).strip()
        clean_project_name = str(project_name or clean_project_code or clean_project_id).strip()
        customer = canonical_customer(customer_name)
        clean_customer_id = str(customer_id or customer.get("customerId") or "").strip()
        clean_customer_name = str(customer_name or customer.get("customerCanonicalName") or "").strip()
        if clean_customer_id or clean_customer_name:
            add_customer(
                customer_id=clean_customer_id,
                name=clean_customer_name,
                aliases=list(customer.get("customerAliases") or []),
                source=source,
            )
        existing = projects.get(clean_project_id) or {}
        projects[clean_project_id] = {
            "id": clean_project_id,
            "projectId": clean_project_id,
            "projectCode": clean_project_code or existing.get("projectCode") or clean_project_id,
            "name": clean_project_name or existing.get("name") or clean_project_id,
            "projectName": clean_project_name or existing.get("projectName") or clean_project_id,
            "customerId": clean_customer_id or existing.get("customerId") or "",
            "customerName": clean_customer_name or existing.get("customerName") or "",
            "customerCanonicalName": clean_customer_name or existing.get("customerCanonicalName") or "",
            "bidType": item_bid_type or existing.get("bidType") or "",
            "source": source if not existing.get("source") else existing["source"],
        }

    for folder in folders:
        folder_path = str(getattr(folder, "path", "") or "")
        folder_bid_type = str(getattr(folder, "bid_type", "") or normalized_bid_type or GENERAL_BID_TYPE)
        location = classify_material_path(folder_path, folder_bid_type)
        folder_tier = normalize_material_tier(str(getattr(folder, "tier", "") or location.get("materialTier") or ""))
        if folder_tier == "customer":
            add_customer(name=str(getattr(folder, "customer_name", "") or location.get("customerName") or ""))
        elif folder_tier == "project":
            add_project(
                project_id=str(getattr(folder, "project_id", "") or location.get("projectId") or ""),
                item_bid_type=str(getattr(folder, "bid_type", "") or location.get("bidType") or ""),
            )

    for raw_file in files:
        ext = getattr(raw_file, "ext_fields", None) or {}
        item_tier = normalize_material_tier(str(ext.get("materialTier") or ""))
        item_bid_type = str(ext.get("bidType") or "")
        if item_tier == "customer":
            add_customer(
                customer_id=str(ext.get("customerId") or ""),
                name=str(ext.get("customerCanonicalName") or ext.get("customerName") or ""),
                aliases=list(ext.get("customerAliases") or []),
            )
        elif item_tier == "project":
            add_project(
                project_id=str(ext.get("projectId") or ""),
                project_code=str(ext.get("projectCode") or ""),
                project_name=str(ext.get("projectName") or ""),
                customer_id=str(ext.get("customerId") or ""),
                customer_name=str(ext.get("customerCanonicalName") or ext.get("customerName") or ""),
                item_bid_type=item_bid_type,
            )

    for row in project_rows:
        payload = _row_get(row, "payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            continue
        identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else build_project_identity(payload)
        project_id = str(
            payload.get("materialProjectId")
            or identity.get("projectId")
            or payload.get("projectId")
            or payload.get("id")
            or _row_get(row, "id", "")
        )
        customer_name = str(
            payload.get("materialCustomerName")
            or identity.get("customerCanonicalName")
            or payload.get("customerCanonicalName")
            or payload.get("customerName")
            or payload.get("owner")
            or ""
        )
        add_project(
            project_id=project_id,
            project_code=str(
                payload.get("materialProjectCode")
                or identity.get("projectCode")
                or payload.get("projectCode")
                or project_id
            ),
            project_name=str(
                payload.get("materialProjectName")
                or identity.get("projectName")
                or payload.get("name")
                or project_id
            ),
            customer_id=str(
                payload.get("materialCustomerId")
                or identity.get("customerId")
                or payload.get("customerId")
                or ""
            ),
            customer_name=customer_name,
            item_bid_type=str(payload.get("bidType") or identity.get("bidType") or ""),
            source="project",
        )

    return {
        "customers": sorted(customers.values(), key=sort_key),
        "projects": sorted(projects.values(), key=sort_key),
    }


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, "get"):
        return row.get(key, default)
    return getattr(row, key, default)
