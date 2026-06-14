from __future__ import annotations

from typing import Any

from app.services.performance_library_service import performance_library_service
from app.services.performance_package_service import performance_package_service


PERFORMANCE_LIBRARY_SOURCE_TYPE = "performance_library"
PERFORMANCE_PACKAGE_SOURCE_TYPE = "performance_package"
PERFORMANCE_SOURCE_TYPES = {PERFORMANCE_LIBRARY_SOURCE_TYPE, PERFORMANCE_PACKAGE_SOURCE_TYPE}
PERFORMANCE_DOWNLOAD_SOURCE_KINDS = {
    PERFORMANCE_LIBRARY_SOURCE_TYPE,
    "performance_package_category",
    "performance_package_item",
}


def performance_material_source_type(material: dict[str, Any] | None) -> str:
    if not isinstance(material, dict):
        return ""
    source_type = str(material.get("sourceType") or "")
    material_id = str(material.get("id") or material.get("materialId") or "")
    if source_type in PERFORMANCE_SOURCE_TYPES:
        return source_type
    if material_id.startswith("PERF-"):
        return PERFORMANCE_LIBRARY_SOURCE_TYPE
    if material_id.startswith(("PERCAT-", "PERITEM-")):
        return PERFORMANCE_PACKAGE_SOURCE_TYPE
    return ""


def is_performance_material(material: dict[str, Any] | None) -> bool:
    return bool(performance_material_source_type(material))


def is_performance_download_source_kind(source_kind: str) -> bool:
    return str(source_kind or "") in PERFORMANCE_DOWNLOAD_SOURCE_KINDS


async def downloadable_performance_material_payload(material: dict[str, Any]) -> tuple[dict[str, Any], str]:
    source_type = performance_material_source_type(material)
    material_id = str(material.get("id") or material.get("materialId") or "")
    if source_type == PERFORMANCE_LIBRARY_SOURCE_TYPE:
        return await performance_library_service.download_word(material_id), PERFORMANCE_LIBRARY_SOURCE_TYPE

    if source_type != PERFORMANCE_PACKAGE_SOURCE_TYPE:
        raise ValueError("not a performance material")

    candidate_type = str(material.get("candidateType") or "")
    category_id = str(material.get("categoryId") or "")
    if candidate_type == "performance_item" or material_id.startswith("PERITEM-"):
        item_id = str(material.get("itemId") or material_id)
        attachment_id = _first_attachment_id(material)
        if not category_id or not item_id or not attachment_id:
            raise ValueError("performance item attachment reference is incomplete")
        return (
            await performance_package_service.download_item_attachment(category_id, item_id, attachment_id),
            "performance_package_item",
        )

    attachment_id = (
        str(material.get("attachmentId") or "")
        or str(material.get("summaryAttachmentId") or "")
        or _first_attachment_id(material)
    )
    category_id = category_id or material_id
    if not category_id or not attachment_id:
        raise ValueError("performance category attachment reference is incomplete")
    return await performance_package_service.download_attachment(category_id, attachment_id), "performance_package_category"


def _first_attachment_id(material: dict[str, Any]) -> str:
    attachments = material.get("attachments") if isinstance(material.get("attachments"), list) else []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_id = str(attachment.get("id") or "").strip()
        if attachment_id:
            return attachment_id
    return ""
