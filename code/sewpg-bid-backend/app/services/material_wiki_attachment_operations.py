from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Awaitable, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import async_session
from app.models.materials import WikiAttachment, WikiDoc
from app.services.bid_type import GENERAL_BID_TYPE
from app.services.filename_utils import short_filename
from app.services.material_wiki_scope import normalize_wiki_bid_type
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError
from app.services.scoped_material_urls import INTERNAL_WIKI_URL_PREFIX


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
WikiListLoader = Callable[[str, str], Awaitable[dict[str, Any]]]


def _now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.2f} MB"


def _safe_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def wiki_attachment_key(node_id: int, file_name: str) -> str:
    safe_name = short_filename(file_name, "attachment.bin", max_bytes=96)
    return f"wiki/{node_id}/{uuid4().hex}-{safe_name}"


def wiki_attachment_to_dict(attachment: WikiAttachment) -> dict[str, Any]:
    size = int(attachment.size_bytes or 0)
    return {
        "id": f"WIKI-ATT-{attachment.id:04d}",
        "name": attachment.file_name,
        "size": _size_label(size),
        "time": attachment.created_at.strftime("%Y-%m-%d %H:%M:%S") if attachment.created_at else _now_display(),
        "downloadUrl": f"{INTERNAL_WIKI_URL_PREFIX}/attachments/WIKI-ATT-{attachment.id:04d}/content" if attachment.minio_key else "",
    }


def purge_wiki_attachment_object(attachment: WikiAttachment) -> None:
    key = str(attachment.minio_key or "")
    if not key:
        return
    bucket = str(attachment.minio_bucket or settings.minio_buckets["materials"])
    minio_client.remove_object(bucket, key)


def wiki_doc_matches_bid_type(doc: WikiDoc | None, bid_type: str) -> bool:
    normalized_bid_type = normalize_wiki_bid_type(bid_type)
    if not normalized_bid_type or doc is None or doc.node is None:
        return False
    type_set = {str(item) for item in (doc.node.bid_types or []) if str(item or "").strip()}
    return normalized_bid_type in type_set or GENERAL_BID_TYPE in type_set


async def upload_wiki_attachment(
    *,
    node_id: str,
    file_name: str,
    file_size: Any,
    upload: Any | None = None,
    data: bytes | None = None,
    mime_type: str = "",
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    numeric_id = int(node_id.replace("WIKI-", ""))
    clean_name = _safe_segment(file_name, "")
    if not clean_name:
        raise PeripheralError(400, "附件文件名不能为空。", "WIKI_ATTACHMENT_NAME_REQUIRED")

    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(
            select(WikiDoc).where(WikiDoc.node_id == numeric_id).options(selectinload(WikiDoc.node))
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
        if not wiki_doc_matches_bid_type(doc, bid_type):
            raise PeripheralError(400, "该 Wiki 节点不属于当前素材库。", "WIKI_NODE_SCOPE")

        bucket = settings.minio_buckets["materials"]
        key = wiki_attachment_key(numeric_id, clean_name)
        size = int(file_size or 0)
        resolved_type = str(mime_type or getattr(upload, "content_type", "") or "application/octet-stream")

        if upload is not None and hasattr(upload, "file"):
            stream = upload.file
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
            minio_client.put_object_stream(bucket, key, stream, size, content_type=resolved_type)
        elif data is not None:
            size = len(data)
            minio_client.put_object(bucket, key, data, content_type=resolved_type)

        attachment = WikiAttachment(
            doc_id=doc.id,
            file_name=clean_name,
            size_bytes=size,
            mime_type=resolved_type,
            minio_key=key if upload is not None or data is not None else "",
            minio_bucket=bucket,
            created_by="当前用户",
        )
        session.add(attachment)
        await session.commit()

    return {"message": "Uploaded", **await wiki_list(node_id, bid_type)}


async def download_wiki_attachment_content(
    *,
    attachment_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
) -> dict[str, Any]:
    numeric_id = int(attachment_id.replace("WIKI-ATT-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(
            select(WikiAttachment)
            .where(WikiAttachment.id == numeric_id)
            .options(selectinload(WikiAttachment.doc).selectinload(WikiDoc.node))
        )
        attachment = result.scalar_one_or_none()
        if attachment is None or not attachment.minio_key:
            raise PeripheralError(404, "附件不存在。", "WIKI_ATTACHMENT_NOT_FOUND")
        if not wiki_doc_matches_bid_type(attachment.doc, bid_type):
            raise PeripheralError(400, "该附件不属于当前素材库。", "WIKI_ATTACHMENT_SCOPE")
        return {
            "fileName": attachment.file_name,
            "bucket": attachment.minio_bucket or settings.minio_buckets["materials"],
            "key": attachment.minio_key,
            "mimeType": attachment.mime_type or "application/octet-stream",
        }


async def delete_wiki_attachment(
    *,
    attachment_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    numeric_id = int(attachment_id.replace("WIKI-ATT-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(
            select(WikiAttachment)
            .where(WikiAttachment.id == numeric_id)
            .options(selectinload(WikiAttachment.doc).selectinload(WikiDoc.node))
        )
        attachment = result.scalar_one_or_none()
        if attachment is None:
            raise PeripheralError(404, "附件不存在。", "WIKI_ATTACHMENT_NOT_FOUND")
        if not wiki_doc_matches_bid_type(attachment.doc, bid_type):
            raise PeripheralError(400, "该附件不属于当前素材库。", "WIKI_ATTACHMENT_SCOPE")
        node_id = int(attachment.doc.node_id) if attachment.doc else 0
        purge_wiki_attachment_object(attachment)
        await session.delete(attachment)
        await session.commit()

    return {
        "message": "附件删除成功。",
        **await wiki_list(f"WIKI-{node_id:04d}" if node_id else "", bid_type),
    }
