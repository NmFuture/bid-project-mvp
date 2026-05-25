from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import async_session
from app.models.materials import RawFile
from app.services.material_raw_file_filter import raw_file_matches_bid_type
from app.services.peripheral import PeripheralError
from app.services.scoped_material_urls import INTERNAL_RAW_URL_PREFIX


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]


async def raw_download_file_operation(
    *,
    file_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
) -> dict[str, Any]:
    numeric_id = int(file_id.replace("RAW-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder)))
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")
        return {
            "fileId": f"RAW-{item.id:04d}",
            "fileName": item.name,
            "downloadUrl": f"{INTERNAL_RAW_URL_PREFIX}/{file_id}/content",
            "message": "已生成下载地址",
        }


async def raw_download_content_operation(
    *,
    file_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
) -> dict[str, Any]:
    numeric_id = int(file_id.replace("RAW-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder)))
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")
        return {
            "fileId": f"RAW-{item.id:04d}",
            "fileName": item.name,
            "bucket": item.minio_bucket,
            "key": item.minio_key,
            "mimeType": item.mime_type or "application/octet-stream",
        }


async def raw_cleaned_preview_operation(
    *,
    file_id: str,
    bid_type: str,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
    content_path_prefix: str = INTERNAL_RAW_URL_PREFIX,
    ensure_runtime_tables: EnsureRuntimeTables,
) -> dict[str, Any]:
    numeric_id = int(file_id.replace("RAW-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder)))
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")

        ext = item.ext_fields or {}
        cleaned_key = str(ext.get("cleanedMinioKey") or "")
        if str(ext.get("cleanStatus") or "") != "cleaned" or not cleaned_key:
            raise PeripheralError(
                400,
                "素材清洗完成后才可预览清洗稿。",
                "RAW_CLEANED_PREVIEW_UNAVAILABLE",
            )

        raw_id = f"RAW-{item.id:04d}"
        cleaned_file_name = str(ext.get("cleanedFileName") or f"{PurePosixPath(item.name).stem}.docx")
        encoded_name = quote(cleaned_file_name)
        file_path = f"{content_path_prefix.rstrip('/')}/{raw_id}/cleaned/content/{encoded_name}"
        browser_file_url = f"{browser_base_url.rstrip('/')}{file_path}" if browser_base_url else file_path
        onlyoffice_file_url = (
            f"{onlyoffice_base_url.rstrip('/')}{file_path}"
            if onlyoffice_base_url
            else browser_file_url
        )
        digest = hashlib.sha1(
            "|".join(
                [
                    raw_id,
                    cleaned_key,
                    str(item.version or 1),
                    str(ext.get("cleanedSize") or 0),
                    str(ext.get("cleanedAt") or ext.get("cleanUpdatedAt") or ""),
                ]
            ).encode("utf-8")
        ).hexdigest()[:16]

        return {
            "status": "ready",
            "fileId": raw_id,
            "sourceFileName": item.name,
            "fileName": cleaned_file_name,
            "fileType": "docx",
            "documentType": "word",
            "folderPath": item.folder.path if item.folder else "",
            "version": item.version or 1,
            "cleanMessage": ext.get("cleanMessage") or "",
            "cleanedAt": ext.get("cleanedAt") or "",
            "cleanedSize": ext.get("cleanedSize") or 0,
            "fileUrl": browser_file_url,
            "onlyoffice": {
                "documentKey": f"material-{raw_id}-v{item.version or 1}-{digest}",
                "title": cleaned_file_name,
                "fileUrl": onlyoffice_file_url,
                "browserFileUrl": browser_file_url,
                "fileType": "docx",
                "documentType": "word",
                "user": {
                    "id": "user-1",
                    "name": "当前用户",
                },
            },
        }


async def raw_download_cleaned_content_operation(
    *,
    file_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
) -> dict[str, Any]:
    numeric_id = int(file_id.replace("RAW-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder)))
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")
        ext = item.ext_fields or {}
        key = str(ext.get("cleanedMinioKey") or "")
        if not key:
            raise PeripheralError(404, "清洗后的 Word 文件尚未生成。", "RAW_CLEANED_FILE_NOT_FOUND")
        return {
            "fileId": f"RAW-{item.id:04d}",
            "fileName": ext.get("cleanedFileName") or f"{PurePosixPath(item.name).stem}.docx",
            "bucket": str(ext.get("cleanedMinioBucket") or settings.minio_buckets["materials"]),
            "key": key,
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
