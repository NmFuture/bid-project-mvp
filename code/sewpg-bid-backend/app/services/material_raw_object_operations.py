from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.models.materials import RawFile, RawFileVersion
from app.services.minio_client import minio_client

logger = logging.getLogger(__name__)


def raw_object_key(folder_path: str, file_name: str) -> str:
    return f"raw/{folder_path.strip('/')}/{file_name}"


def remove_cleaned_object_from_ext(ext: dict[str, Any]) -> None:
    bucket = str(ext.get("cleanedMinioBucket") or settings.minio_buckets["materials"])
    key = str(ext.get("cleanedMinioKey") or "")
    if not key:
        return
    try:
        minio_client.remove_object(bucket, key)
    except Exception as exc:  # pragma: no cover - MinIO cleanup must not block DB mutations
        logger.warning("Failed to remove cleaned material object %s/%s: %s", bucket, key, exc)


def enqueue_cleaning_job(file_id: int) -> dict[str, Any]:
    from app.services.job_queue import enqueue_generation_job

    raw_id = f"RAW-{file_id:04d}"
    try:
        result = enqueue_generation_job("material_cleaning", raw_id, {"fileId": raw_id})
    except Exception as exc:  # pragma: no cover - queue outages should not fail uploads
        logger.warning("Failed to enqueue material cleaning job for %s: %s", raw_id, exc)
        return {"queued": False, "unavailable": True, "message": str(exc)}
    return {
        "queued": result.queued,
        "jobId": result.job_id,
        "locked": result.locked,
        "unavailable": result.unavailable,
    }


async def archive_raw_file_version(
    session: Any,
    item: RawFile,
    *,
    ensure_runtime_tables: Any,
) -> None:
    await ensure_runtime_tables(session)
    session.add(
        RawFileVersion(
            file_id=item.id,
            version=int(item.version or 1),
            minio_key=str(item.minio_key or ""),
            size_bytes=int(item.size_bytes or 0),
            created_by="当前用户",
        )
    )
    await session.flush()


async def purge_raw_file_objects(
    session: Any,
    item: RawFile,
    *,
    ensure_runtime_tables: Any,
) -> None:
    await ensure_runtime_tables(session)
    version_rows = (
        await session.execute(select(RawFileVersion).where(RawFileVersion.file_id == item.id))
    ).scalars().all()
    keys = {(str(item.minio_bucket or settings.minio_buckets["materials"]), str(item.minio_key or ""))}
    ext = item.ext_fields or {}
    cleaned_key = str(ext.get("cleanedMinioKey") or "")
    if cleaned_key:
        keys.add((str(ext.get("cleanedMinioBucket") or settings.minio_buckets["materials"]), cleaned_key))
    keys.update(
        (str(item.minio_bucket or settings.minio_buckets["materials"]), str(version.minio_key or ""))
        for version in version_rows
        if version.minio_key
    )
    for bucket, key in keys:
        if key:
            minio_client.remove_object(bucket, key)
