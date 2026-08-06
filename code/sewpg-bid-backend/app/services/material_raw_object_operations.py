from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.models.materials import RawFile, RawFileVersion
from app.services.material_folder_scope import require_material_bid_type
from app.services.minio_client import minio_client

logger = logging.getLogger(__name__)


def raw_object_key(folder_path: str, file_name: str) -> str:
    return f"raw/{folder_path.strip('/')}/{file_name}"


def raw_version_object_key(file_id: int, version: int, file_name: str) -> str:
    safe_name = PurePosixPath(str(file_name or "").replace("\\", "/")).name
    return f"raw-versions/RAW-{file_id:04d}/v{version}/{safe_name}"


def remove_cleaned_object_from_ext(ext: dict[str, Any]) -> None:
    bucket = str(ext.get("cleanedMinioBucket") or settings.minio_buckets["materials"])
    key = str(ext.get("cleanedMinioKey") or "")
    if not key:
        return
    try:
        minio_client.remove_object(bucket, key)
    except Exception as exc:  # pragma: no cover - MinIO cleanup must not block DB mutations
        logger.warning("Failed to remove cleaned material object %s/%s: %s", bucket, key, exc)


def enqueue_cleaning_job(
    file_id: int,
    *,
    bid_type: str,
    source_version: int | None = None,
    source_bucket: str = "",
    source_key: str = "",
) -> dict[str, Any]:
    from app.services.job_queue import enqueue_generation_job

    raw_id = f"RAW-{file_id:04d}"
    lock_id = f"{raw_id}:v{source_version}" if source_version is not None else raw_id
    # 清洗任务必须携带并校验标类身份：完成钩子据此隔离技术标/商务标的后续动作。
    data: dict[str, Any] = {"fileId": raw_id, "bidType": require_material_bid_type(bid_type, "清洗任务标类")}
    if source_version is not None:
        data.update(
            {
                "sourceVersion": int(source_version),
                "sourceBucket": str(source_bucket or ""),
                "sourceKey": str(source_key or ""),
            }
        )
    try:
        result = enqueue_generation_job("material_cleaning", lock_id, data)
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
    # 逐 key 容错：单个对象删除失败只告警并继续，避免整批 purge 因一个瞬时故障中断（L3）
    for bucket, key in keys:
        if not key:
            continue
        try:
            minio_client.remove_object(bucket, key)
        except Exception as exc:  # pragma: no cover - 单对象清理失败仅告警
            logger.warning("purge 素材对象 %s/%s 失败：%s", bucket, key, exc)
