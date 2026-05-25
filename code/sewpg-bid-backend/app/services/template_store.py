from __future__ import annotations

import logging
import tempfile
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

from sqlalchemy import desc, select

from app.core.config import settings
from app.models import async_session
from app.models.materials import StructuredTable, TemplateAsset
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.file_utils import format_size_label as size_label
from app.services.file_utils import now_display, safe_segment
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError

logger = logging.getLogger(__name__)

FALLBACK_BID_TEMPLATE_NAME = "投标文件-模板.docx"
WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEFAULT_TEMPLATE_TYPES = {
    "technical": TECHNICAL_BID_TYPE,
    "business": BUSINESS_BID_TYPE,
}
DEFAULT_EXCEL_TEMPLATE_TABLE_OPTIONS = (
    {"key": "performance_guarantee", "label": "性能保证"},
    {"key": "project_reference", "label": "项目业绩"},
)
DOCX_MIN_BYTES = 1024
DOCX_DOCUMENT_XML = "word/document.xml"


def is_plausible_docx_size(size_bytes: int) -> bool:
    return int(size_bytes or 0) >= DOCX_MIN_BYTES


def is_valid_docx_stream(stream: BinaryIO) -> bool:
    try:
        position = stream.tell()
    except Exception:
        position = None
    try:
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            return DOCX_DOCUMENT_XML in set(archive.namelist())
    except Exception:
        return False
    finally:
        if position is not None:
            try:
                stream.seek(position)
            except Exception:
                pass


def is_valid_docx_bytes(data: bytes) -> bool:
    return is_valid_docx_stream(BytesIO(data))


def is_valid_docx_file(path: Path) -> bool:
    try:
        with Path(path).open("rb") as handle:
            return is_valid_docx_stream(handle)
    except Exception:
        return False


def template_type_for_bid_type(bid_type: str) -> str:
    text = str(bid_type or "").strip()
    if "商" in text:
        return "business"
    return "technical"


def _record_to_template_summary(asset: TemplateAsset, *, source: str) -> dict[str, Any]:
    available = bool(asset.minio_bucket and asset.minio_key)
    size_bytes = int(asset.size_bytes or 0)
    return {
        "id": f"TPL-{asset.id:04d}",
        "name": asset.file_name,
        "source": source,
        "available": available,
        "templateType": str(asset.table_key or ""),
        "templateTypeLabel": DEFAULT_TEMPLATE_TYPES.get(str(asset.table_key or ""), str(asset.table_key or "")),
        "version": asset.version,
        "uploadedBy": asset.uploaded_by or "",
        "minioBucket": asset.minio_bucket or settings.minio_buckets["templates"],
        "minioKey": asset.minio_key or "",
        "sizeBytes": size_bytes,
        "sizeLabel": size_label(size_bytes),
        "contentType": asset.mime_type or WORD_MEDIA_TYPE,
    }


async def system_default_bid_template_summary(
    *,
    bid_type: str,
    check_exists: bool = True,
) -> dict[str, Any]:
    template_type = template_type_for_bid_type(bid_type)
    async with async_session() as session:
        asset = (
            await session.execute(
                select(TemplateAsset)
                .where(
                    TemplateAsset.asset_type == "default_template",
                    TemplateAsset.table_key == template_type,
                    TemplateAsset.is_active.is_(True),
                )
                .order_by(desc(TemplateAsset.created_at), desc(TemplateAsset.id))
            )
        ).scalars().first()

    if asset is None:
        return {
            "id": "",
            "name": "",
            "source": "system-default",
            "available": False,
            "templateType": template_type,
            "templateTypeLabel": DEFAULT_TEMPLATE_TYPES.get(template_type, template_type),
            "minioBucket": settings.minio_buckets["templates"],
            "minioKey": "",
            "sizeBytes": 0,
            "sizeLabel": size_label(0),
            "contentType": WORD_MEDIA_TYPE,
        }

    summary = _record_to_template_summary(asset, source="system-default")
    if check_exists and summary["available"]:
        try:
            stat = minio_client.client.stat_object(str(summary["minioBucket"]), str(summary["minioKey"]))
            summary["sizeBytes"] = int(getattr(stat, "size", 0) or summary["sizeBytes"])
            summary["sizeLabel"] = size_label(int(summary["sizeBytes"]))
            summary["contentType"] = str(getattr(stat, "content_type", "") or summary["contentType"])
            if not is_plausible_docx_size(int(summary["sizeBytes"])):
                summary["available"] = False
                summary["invalidReason"] = "系统默认模板文件过小，不是有效 DOCX。"
        except Exception as exc:  # MinIO may be unavailable in unit tests.
            logger.info(
                "System default template is not available at %s/%s: %s",
                summary["minioBucket"],
                summary["minioKey"],
                exc,
            )
            summary["available"] = False
    return summary


async def resolve_system_default_bid_template_file(project_id: str, bid_type: str) -> dict[str, Any] | None:
    summary = await system_default_bid_template_summary(bid_type=bid_type, check_exists=True)
    if not summary["available"]:
        return None

    name = safe_segment(str(summary["name"] or ""), FALLBACK_BID_TEMPLATE_NAME)
    target_dir = settings.uploads_dir / project_id / "system-default-template"
    target = target_dir / name
    minio_client.download_file(str(summary["minioBucket"]), str(summary["minioKey"]), target)
    if not is_valid_docx_file(target):
        logger.warning(
            "Skipping invalid system default template for project %s: %s/%s",
            project_id,
            summary["minioBucket"],
            summary["minioKey"],
        )
        target.unlink(missing_ok=True)
        return None
    size_bytes = target.stat().st_size if target.exists() else int(summary.get("sizeBytes") or 0)

    return {
        "id": str(summary["id"]),
        "name": name,
        "stored_name": name,
        "size_bytes": size_bytes,
        "size_label": size_label(size_bytes),
        "content_type": str(summary.get("contentType") or WORD_MEDIA_TYPE),
        "path": str(target),
        "source": "system-default",
        "isFallback": True,
        "fallbackSourceId": str(summary["id"]),
        "templateType": str(summary.get("templateType") or ""),
        "templateTypeLabel": str(summary.get("templateTypeLabel") or ""),
        "minioBucket": str(summary["minioBucket"]),
        "minioKey": str(summary["minioKey"]),
    }


async def resolve_fallback_bid_template_file(project_id: str, bid_type: str) -> dict[str, Any] | None:
    return await resolve_system_default_bid_template_file(project_id, bid_type)


def resolve_fallback_bid_template_file_sync(project_id: str, bid_type: str) -> dict[str, Any] | None:
    import asyncio

    result: dict[str, Any] | None = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            with tempfile.TemporaryDirectory(prefix="bid-template-loop-"):
                result = asyncio.run(resolve_fallback_bid_template_file(project_id, bid_type))
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            error = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


async def template_fallback_payload(
    *,
    project_id: str,
    bid_type: str,
    enabled: bool,
    source_id: str,
    has_project_template: bool,
) -> dict[str, Any]:
    effective_template = None
    if enabled and not has_project_template:
        record = await resolve_fallback_bid_template_file(project_id, bid_type)
        if record is not None:
            effective_template = {
                "id": str(record.get("id") or ""),
                "name": str(record.get("name") or ""),
                "source": str(record.get("source") or ""),
                "available": True,
                "templateType": str(record.get("templateType") or ""),
                "templateTypeLabel": str(record.get("templateTypeLabel") or ""),
                "minioBucket": str(record.get("minioBucket") or ""),
                "minioKey": str(record.get("minioKey") or ""),
                "sizeBytes": int(record.get("size_bytes") or 0),
                "sizeLabel": str(record.get("size_label") or ""),
                "contentType": str(record.get("content_type") or ""),
            }

    system_template = await system_default_bid_template_summary(bid_type=bid_type)
    return {
        "projectId": project_id,
        "enabled": enabled,
        "sourceId": source_id,
        "template": effective_template or system_template,
        "systemDefaultTemplate": system_template,
        "usesFallbackWhenProjectTemplateMissing": not has_project_template,
    }


class TemplateStore:
    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await session.commit()

    @staticmethod
    def _asset_to_dict(asset: TemplateAsset, *, table_label: str = "") -> dict[str, Any]:
        payload = {
            "id": f"{'DOTX' if asset.asset_type == 'dotx' else 'XLSX'}-{asset.id:04d}",
            "version": asset.version,
            "uploadedBy": asset.uploaded_by or "当前用户",
            "uploadedAt": asset.created_at.strftime("%Y-%m-%d %H:%M:%S") if asset.created_at else now_display(),
            "isActive": bool(asset.is_active),
        }
        if asset.asset_type == "dotx":
            payload.update(
                {
                    "name": asset.file_name,
                    "size": size_label(int(asset.size_bytes or 0)),
                }
            )
        else:
            payload.update(
                {
                    "fileName": asset.file_name,
                    "tableKey": asset.table_key or "",
                    "tableLabel": table_label,
                }
            )
        return payload

    @staticmethod
    def _template_key(asset_type: str, file_name: str, table_key: str = "") -> str:
        clean_name = safe_segment(file_name, "template.bin")
        scope = safe_segment(table_key, "common") if table_key else asset_type
        return f"templates/{asset_type}/{scope}/{uuid4().hex}-{clean_name}"

    async def _table_label_map(self) -> dict[str, str]:
        async with async_session() as session:
            rows = (await session.execute(select(StructuredTable))).scalars().all()
            mapping = {row.table_key: row.table_label for row in rows}
            if mapping:
                return mapping
        return {item["key"]: item["label"] for item in DEFAULT_EXCEL_TEMPLATE_TABLE_OPTIONS}

    async def dotx_list(self) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            assets = (
                await session.execute(
                    select(TemplateAsset)
                    .where(TemplateAsset.asset_type == "dotx")
                    .order_by(desc(TemplateAsset.created_at), desc(TemplateAsset.id))
                )
            ).scalars().all()
            return {"items": [self._asset_to_dict(asset) for asset in assets]}

    async def dotx_upload(
        self,
        *,
        file_name: str,
        file_size: Any,
        version: str,
        upload: Any | None = None,
        data: bytes | None = None,
        mime_type: str = "",
    ) -> dict[str, Any]:
        await self._ensure_tables()
        clean_name = safe_segment(file_name, "")
        if not clean_name:
            raise PeripheralError(400, "模板文件名不能为空", "DOTX_NAME_REQUIRED")

        bucket = settings.minio_buckets["templates"]
        key = self._template_key("dotx", clean_name)
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
        else:
            key = ""

        async with async_session() as session:
            asset = TemplateAsset(
                asset_type="dotx",
                file_name=clean_name,
                version=version or "2026.04",
                minio_key=key,
                minio_bucket=bucket,
                size_bytes=size,
                mime_type=resolved_type,
                is_active=False,
                uploaded_by="当前用户",
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)

        payload = await self.dotx_list()
        payload.update({"message": "Uploaded", "item": next(item for item in payload["items"] if item["id"] == f"DOTX-{asset.id:04d}")})
        return payload

    async def dotx_activate(self, template_id: str) -> dict[str, Any]:
        await self._ensure_tables()
        numeric_id = int(template_id.replace("DOTX-", ""))
        async with async_session() as session:
            target = (
                await session.execute(
                    select(TemplateAsset).where(TemplateAsset.id == numeric_id, TemplateAsset.asset_type == "dotx")
                )
            ).scalar_one_or_none()
            if target is None:
                raise PeripheralError(404, "Template not found", "DOTX_NOT_FOUND")
            assets = (
                await session.execute(select(TemplateAsset).where(TemplateAsset.asset_type == "dotx"))
            ).scalars().all()
            for asset in assets:
                asset.is_active = asset.id == target.id
            await session.commit()

        payload = await self.dotx_list()
        payload.update({"message": "Activated", "item": next(item for item in payload["items"] if item["id"] == template_id)})
        return payload

    async def excel_list(self) -> dict[str, Any]:
        await self._ensure_tables()
        label_map = await self._table_label_map()
        async with async_session() as session:
            assets = (
                await session.execute(
                    select(TemplateAsset)
                    .where(TemplateAsset.asset_type == "excel")
                    .order_by(desc(TemplateAsset.created_at), desc(TemplateAsset.id))
                )
            ).scalars().all()
            return {
                "items": [self._asset_to_dict(asset, table_label=label_map.get(asset.table_key or "", "")) for asset in assets],
                "tableOptions": [{"key": key, "label": label} for key, label in label_map.items()],
            }

    async def excel_upload(
        self,
        *,
        table_key: str,
        file_name: str,
        version: str,
        upload: Any | None = None,
        data: bytes | None = None,
        mime_type: str = "",
    ) -> dict[str, Any]:
        await self._ensure_tables()
        label_map = await self._table_label_map()
        if table_key not in label_map:
            raise PeripheralError(400, "无效的数据表类型", "XLSX_TABLE_INVALID")

        clean_name = safe_segment(file_name, "")
        if not clean_name:
            raise PeripheralError(400, "模板文件名不能为空", "XLSX_NAME_REQUIRED")

        bucket = settings.minio_buckets["templates"]
        key = self._template_key("excel", clean_name, table_key=table_key)
        resolved_type = str(mime_type or getattr(upload, "content_type", "") or "application/octet-stream")
        size = 0
        if upload is not None and hasattr(upload, "file"):
            stream = upload.file
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
            minio_client.put_object_stream(bucket, key, stream, size, content_type=resolved_type)
        elif data is not None:
            size = len(data)
            minio_client.put_object(bucket, key, data, content_type=resolved_type)
        else:
            key = ""

        async with async_session() as session:
            asset = TemplateAsset(
                asset_type="excel",
                table_key=table_key,
                file_name=clean_name,
                version=version or "2026.04",
                minio_key=key,
                minio_bucket=bucket,
                size_bytes=size,
                mime_type=resolved_type,
                is_active=False,
                uploaded_by="当前用户",
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)

        payload = await self.excel_list()
        payload.update({"message": "Uploaded", "item": next(item for item in payload["items"] if item["id"] == f"XLSX-{asset.id:04d}")})
        return payload

    async def excel_activate(self, template_id: str) -> dict[str, Any]:
        await self._ensure_tables()
        numeric_id = int(template_id.replace("XLSX-", ""))
        async with async_session() as session:
            target = (
                await session.execute(
                    select(TemplateAsset).where(TemplateAsset.id == numeric_id, TemplateAsset.asset_type == "excel")
                )
            ).scalar_one_or_none()
            if target is None:
                raise PeripheralError(404, "Template not found", "XLSX_TEMPLATE_NOT_FOUND")

            assets = (
                await session.execute(
                    select(TemplateAsset).where(
                        TemplateAsset.asset_type == "excel",
                        TemplateAsset.table_key == target.table_key,
                    )
                )
            ).scalars().all()
            for asset in assets:
                asset.is_active = asset.id == target.id
            await session.commit()

        payload = await self.excel_list()
        payload.update({"message": "Activated", "item": next(item for item in payload["items"] if item["id"] == template_id)})
        return payload
template_store = TemplateStore()
