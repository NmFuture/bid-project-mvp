from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select

from app.core.config import settings
from app.models import async_session
from app.models.materials import StructuredTable, TemplateAsset
from app.services.material_store import size_label
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError, peripheral_store


def now_display() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_segment(value: str, fallback: str) -> str:
    import re

    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


class TemplateStore:
    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await peripheral_store_material_proxy._ensure_runtime_tables(session)
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
        return {item["key"]: item["label"] for item in peripheral_store._structured_table_options}

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
from app.services.material_store import material_store as peripheral_store_material_proxy

template_store = TemplateStore()
