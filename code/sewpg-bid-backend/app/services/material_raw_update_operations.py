from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile
from app.services.material_raw_file_filter import raw_file_matches_bid_type
from app.services.material_update_metadata import build_raw_update_file_ext_fields
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
RawObjectKeyBuilder = Callable[[str, str], str]


def _safe_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


async def update_raw_file(
    *,
    file_id: str,
    bid_type: str,
    name: str = "",
    business_material_kind: str = "",
    tags: Any = None,
    update_tags: bool = False,
    ensure_runtime_tables: EnsureRuntimeTables,
    raw_object_key: RawObjectKeyBuilder,
) -> dict[str, Any]:
    numeric_id = int(file_id.replace("RAW-", ""))
    raw_name = str(name or "").strip()
    next_name = _safe_segment(raw_name, "") if raw_name else ""
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")
        if item.folder is None:
            raise PeripheralError(400, "文件目录信息缺失。", "RAW_FILE_FOLDER_MISSING")
        if not next_name:
            next_name = item.name
        if not next_name:
            raise PeripheralError(400, "文件名不能为空。", "RAW_FILE_NAME_REQUIRED")

        renamed = next_name != item.name
        if renamed:
            conflict = await session.execute(
                select(RawFile).where(
                    RawFile.folder_id == item.folder_id,
                    RawFile.name == next_name,
                    RawFile.id != item.id,
                )
            )
            if conflict.scalar_one_or_none() is not None:
                raise PeripheralError(409, "目标目录存在同名文件。", "MATERIAL_CONFLICT")

        next_key = raw_object_key(item.folder.path, next_name)
        if next_key != item.minio_key and item.minio_key:
            minio_client.copy_object(item.minio_bucket, item.minio_key, next_key)
            minio_client.remove_object(item.minio_bucket, item.minio_key)

        item.name = next_name
        item.minio_key = next_key
        item.ext_fields = build_raw_update_file_ext_fields(
            item.ext_fields or {},
            source_minio_key=next_key,
            source_file_name=next_name,
            business_material_kind=business_material_kind,
            tags=tags,
            update_tags=update_tags,
        )
        await session.commit()
        refreshed = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        updated = refreshed.scalar_one()
        message = "重命名成功" if renamed else "文件信息已更新"
        return {"message": message, "item": updated.to_dict()}
