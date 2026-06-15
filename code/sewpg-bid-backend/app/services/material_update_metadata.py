from __future__ import annotations

from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.material_taxonomy import BUSINESS_MATERIAL_KIND_LABELS, normalize_business_material_kind
from app.services.material_tags import normalize_material_tags


def build_raw_update_file_ext_fields(
    ext_fields: dict[str, Any],
    *,
    source_minio_key: str,
    source_file_name: str,
    business_material_kind: str = "",
    tags: Any = None,
    update_tags: bool = False,
) -> dict[str, Any]:
    ext = dict(ext_fields or {})
    ext.update(
        {
            "sourceMinioKey": source_minio_key,
            "sourceFileName": source_file_name,
            "lastAction": "rename",
        }
    )
    next_kind = normalize_business_material_kind(business_material_kind)
    if next_kind and str(ext.get("bidType") or "") == BUSINESS_BID_TYPE:
        ext.update(
            {
                "businessMaterialKind": next_kind,
                "businessMaterialKindLabel": BUSINESS_MATERIAL_KIND_LABELS.get(next_kind, ""),
                "lastAction": "update",
            }
        )
    if update_tags:
        ext.update({"tags": normalize_material_tags(tags), "lastAction": "update"})
    return ext
