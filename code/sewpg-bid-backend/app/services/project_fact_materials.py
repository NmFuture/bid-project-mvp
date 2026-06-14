from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type
from app.services.business_material_store import business_material_store
from app.services.file_utils import run_awaitable_sync, safe_filename
from app.services.minio_client import minio_client
from app.services.performance_material_resolver import (
    downloadable_performance_material_payload,
    is_performance_material,
)
from app.services.technical_material_store import technical_material_store


def _scoped_material_store(bid_type: str):
    normalized_bid_type = require_bid_type(
        bid_type,
        error_message="项目事实素材必须显式传入技术标或商务标。",
    )
    if normalized_bid_type == BUSINESS_BID_TYPE:
        return business_material_store
    return technical_material_store


async def _downloadable_project_fact_material_payload(
    material_id: str,
    bid_type: str,
    material: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    if is_performance_material(material or {"id": material_id}):
        return await downloadable_performance_material_payload({**(material or {}), "id": material_id})
    scoped_store = _scoped_material_store(bid_type)
    try:
        payload = await scoped_store.raw_download_cleaned_content(material_id)
        return payload, "cleaned"
    except Exception:
        payload = await scoped_store.raw_download_content(material_id)
        return payload, "raw"


def prepare_project_fact_material_files(
    material_index: list[dict[str, Any]],
    work_dir: Path,
    *,
    bid_type: str,
    cache_dir: Path | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    cache_dir = cache_dir or (work_dir / "material_index")
    cache_dir.mkdir(parents=True, exist_ok=True)

    for material in material_index[:limit]:
        item = dict(material)
        material_id = str(item.get("id") or item.get("materialId") or "").strip()
        if not material_id:
            prepared.append(item)
            continue
        awaitable = _downloadable_project_fact_material_payload(material_id, bid_type, item)
        try:
            payload, source_kind = run_awaitable_sync(awaitable)
        except Exception:
            if hasattr(awaitable, "close"):
                awaitable.close()
            prepared.append(item)
            continue
        file_name = safe_filename(
            str(item.get("cleanedFileName") or payload.get("fileName") or item.get("name") or f"{material_id}.docx"),
            f"{material_id}.docx",
        )
        target_path = cache_dir / f"{material_id}-{file_name}"
        if not target_path.exists():
            minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
        item.update(
            {
                "path": str(target_path),
                "sourceKind": source_kind,
                "fileName": target_path.name,
            }
        )
        prepared.append(item)
    return prepared
