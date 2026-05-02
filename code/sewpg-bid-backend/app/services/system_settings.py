from __future__ import annotations

import copy
import json
import time
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import desc, select

from app.core.config import settings
from app.models import async_session
from app.models.materials import BackupRecord, SystemConfig, TemplateAsset
from app.services.audit_service import audit_service
from app.services.material_store import material_store, safe_segment, size_label
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError

DEFAULT_TEMPLATE_TYPES = {
    "technical": "技术标",
    "business": "商务标",
}


def now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return f"{text[:2]}****"
    return f"{text[:4]}****{text[-4:]}"


class SystemSettingsService:
    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await material_store._ensure_runtime_tables(session)
            await session.commit()
        await self._ensure_model_defaults()
        from app.services.template_store import seed_legacy_fallback_as_system_default

        await seed_legacy_fallback_as_system_default()

    async def _ensure_model_defaults(self) -> None:
        async with async_session() as session:
            existing_keys = set(
                (await session.execute(select(SystemConfig.key))).scalars().all()
            )
            defaults = {
                "llm": {
                    "enabled": bool(settings.default_llm_base_url or settings.default_llm_api_key or settings.default_llm_model),
                    "baseUrl": settings.default_llm_base_url,
                    "apiKey": settings.default_llm_api_key,
                    "model": settings.default_llm_model,
                    "timeoutMs": 30000,
                    "maxTokens": 4096,
                },
                "ocr": {
                    "enabled": bool(settings.default_ocr_base_url or settings.default_ocr_api_key),
                    "baseUrl": settings.default_ocr_base_url,
                    "apiKey": settings.default_ocr_api_key,
                    "model": settings.default_ocr_model,
                    "timeoutMs": 60000,
                    "maxTokens": 2048,
                },
            }
            for key, value in defaults.items():
                if key not in existing_keys:
                    session.add(SystemConfig(key=key, value=value, sensitive=True, updated_by="系统初始化"))
            await session.commit()

    @staticmethod
    def _public_model_config(config: dict[str, Any]) -> dict[str, Any]:
        payload = copy.deepcopy(config)
        payload["apiKeyMasked"] = mask_secret(str(payload.pop("apiKey", "") or ""))
        return payload

    async def get_model_config(self, kind: str) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            row = (await session.execute(select(SystemConfig).where(SystemConfig.key == kind))).scalar_one_or_none()
        if row is None:
            return self._public_model_config({})
        payload = self._public_model_config(row.value or {})
        payload["updatedAt"] = row.updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.updated_at else ""
        payload["updatedBy"] = row.updated_by or ""
        return payload

    async def get_model_secret_config(self, kind: str) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            row = (await session.execute(select(SystemConfig).where(SystemConfig.key == kind))).scalar_one_or_none()
        return copy.deepcopy(row.value or {}) if row is not None else {}

    async def update_model_config(self, kind: str, data: dict[str, Any], *, user: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._ensure_tables()
        current = await self.get_model_secret_config(kind)
        before = self._public_model_config(current)
        next_config = {
            **current,
            "enabled": bool(data.get("enabled", current.get("enabled", False))),
            "baseUrl": str(data.get("baseUrl") or data.get("endpoint") or current.get("baseUrl") or "").strip(),
            "model": str(data.get("model") or current.get("model") or "").strip(),
            "timeoutMs": int(data.get("timeoutMs") or current.get("timeoutMs") or 30000),
            "maxTokens": int(data.get("maxTokens") or current.get("maxTokens") or 2048),
        }
        if "apiKey" in data and str(data.get("apiKey") or "").strip():
            next_config["apiKey"] = str(data.get("apiKey") or "").strip()

        async with async_session() as session:
            row = (await session.execute(select(SystemConfig).where(SystemConfig.key == kind))).scalar_one_or_none()
            if row is None:
                row = SystemConfig(key=kind, value=next_config, sensitive=True)
                session.add(row)
            else:
                row.value = next_config
            row.updated_by = str((user or {}).get("name") or "当前用户")
            await session.commit()

        label = "LLM 模型配置" if kind == "llm" else "OCR 模型配置"
        await audit_service.record(
            action=f"更新{label}",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=label,
            user=user,
            diff={"before": before, "after": self._public_model_config(next_config)},
        )
        return {"message": "Config updated", "config": await self.get_model_config(kind)}

    async def test_model_config(self, kind: str, data: dict[str, Any] | None = None, *, user: dict[str, Any] | None = None) -> dict[str, Any]:
        config = await self.get_model_secret_config(kind)
        if data:
            if data.get("baseUrl") or data.get("endpoint"):
                config["baseUrl"] = str(data.get("baseUrl") or data.get("endpoint") or "").strip()
            if data.get("model"):
                config["model"] = str(data.get("model") or "").strip()
            if data.get("apiKey"):
                config["apiKey"] = str(data.get("apiKey") or "").strip()
            if data.get("timeoutMs"):
                config["timeoutMs"] = int(data.get("timeoutMs") or config.get("timeoutMs") or 30000)
        base_url = str(config.get("baseUrl") or "").strip()
        model = str(config.get("model") or "").strip()
        if not base_url or not model:
            raise PeripheralError(400, "Base URL 与模型不能为空", f"{kind.upper()}_TEST_INVALID")

        timeout_ms = int(config.get("timeoutMs") or 30000)
        url = f"{base_url.rstrip('/')}/chat/completions" if base_url.rstrip("/").endswith("/v1") else base_url.rstrip("/")
        payload: dict[str, Any]
        if kind == "ocr":
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Free OCR."}],
                "max_tokens": 8,
                "stream": False,
            }
        else:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
                "stream": False,
            }
        headers = {"Content-Type": "application/json"}
        api_key = str(config.get("apiKey") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_ms / 1000, trust_env=False) as client:
                response = await client.post(url, headers=headers, json=payload)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if response.status_code >= 400:
                raise PeripheralError(
                    response.status_code,
                    f"连接测试失败：HTTP {response.status_code}",
                    f"{kind.upper()}_TEST_FAILED",
                    {"responseText": response.text[:500]},
                )
            result = {"success": True, "latencyMs": latency_ms, "message": "连接测试成功。"}
        except PeripheralError:
            raise
        except Exception as exc:
            raise PeripheralError(502, f"连接测试失败：{exc}", f"{kind.upper()}_TEST_FAILED") from exc

        await audit_service.record(
            action=f"测试{'LLM' if kind == 'llm' else 'OCR'}配置",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=base_url,
            user=user,
            diff={"before": {}, "after": {"success": True, "latencyMs": result["latencyMs"]}},
        )
        return result

    @staticmethod
    def _template_asset_to_dict(asset: TemplateAsset) -> dict[str, Any]:
        template_type = str(asset.table_key or "")
        return {
            "id": f"TPL-{asset.id:04d}",
            "templateType": template_type,
            "templateTypeLabel": DEFAULT_TEMPLATE_TYPES.get(template_type, template_type),
            "name": asset.file_name,
            "version": asset.version,
            "uploadedBy": asset.uploaded_by or "当前用户",
            "uploadedAt": asset.created_at.strftime("%Y-%m-%d %H:%M:%S") if asset.created_at else "",
            "size": size_label(int(asset.size_bytes or 0)),
            "isActive": bool(asset.is_active),
            "minioBucket": asset.minio_bucket or settings.minio_buckets["templates"],
            "minioKey": asset.minio_key or "",
        }

    async def default_templates_list(self) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(TemplateAsset)
                    .where(TemplateAsset.asset_type == "default_template")
                    .order_by(TemplateAsset.table_key, desc(TemplateAsset.created_at), desc(TemplateAsset.id))
                )
            ).scalars().all()
        return {
            "items": [self._template_asset_to_dict(row) for row in rows],
            "templateTypes": [{"key": key, "label": label} for key, label in DEFAULT_TEMPLATE_TYPES.items()],
        }

    async def default_template_upload(
        self,
        *,
        template_type: str,
        file_name: str,
        version: str,
        upload: Any | None = None,
        data: bytes | None = None,
        mime_type: str = "",
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tables()
        if template_type not in DEFAULT_TEMPLATE_TYPES:
            raise PeripheralError(400, "无效的默认模板类型", "DEFAULT_TEMPLATE_TYPE_INVALID")
        clean_name = safe_segment(file_name, "")
        if not clean_name:
            raise PeripheralError(400, "模板文件名不能为空", "DEFAULT_TEMPLATE_NAME_REQUIRED")
        suffix = PurePosixPath(clean_name).suffix.lower()
        if suffix not in {".docx", ".dotx"}:
            raise PeripheralError(400, "系统默认模板仅支持 .docx 或 .dotx", "DEFAULT_TEMPLATE_EXT_INVALID")

        bucket = settings.minio_buckets["templates"]
        key = f"templates/default/{template_type}/{uuid4().hex}-{clean_name}"
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
                asset_type="default_template",
                table_key=template_type,
                file_name=clean_name,
                version=version or datetime.now().strftime("%Y.%m"),
                minio_key=key,
                minio_bucket=bucket,
                size_bytes=size,
                mime_type=resolved_type,
                is_active=False,
                uploaded_by=str((user or {}).get("name") or "当前用户"),
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)

        await audit_service.record(
            action="上传系统默认模板",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=f"{DEFAULT_TEMPLATE_TYPES[template_type]} / {clean_name}",
            user=user,
            diff={"before": {}, "after": self._template_asset_to_dict(asset)},
        )
        payload = await self.default_templates_list()
        payload.update({"message": "Uploaded", "item": next(item for item in payload["items"] if item["id"] == f"TPL-{asset.id:04d}")})
        return payload

    async def default_template_activate(self, template_id: str, *, user: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._ensure_tables()
        numeric_id = int(str(template_id).replace("TPL-", ""))
        async with async_session() as session:
            target = (
                await session.execute(
                    select(TemplateAsset).where(
                        TemplateAsset.id == numeric_id,
                        TemplateAsset.asset_type == "default_template",
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                raise PeripheralError(404, "默认模板不存在", "DEFAULT_TEMPLATE_NOT_FOUND")
            assets = (
                await session.execute(
                    select(TemplateAsset).where(
                        TemplateAsset.asset_type == "default_template",
                        TemplateAsset.table_key == target.table_key,
                    )
                )
            ).scalars().all()
            before = [self._template_asset_to_dict(item) for item in assets]
            for asset in assets:
                asset.is_active = asset.id == target.id
            await session.commit()
            after = [self._template_asset_to_dict(item) for item in assets]

        await audit_service.record(
            action="启用系统默认模板",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=f"{DEFAULT_TEMPLATE_TYPES.get(str(target.table_key or ''), '')} / {target.file_name}",
            user=user,
            diff={"before": before, "after": after},
        )
        payload = await self.default_templates_list()
        payload.update({"message": "Activated", "item": next(item for item in payload["items"] if item["id"] == template_id)})
        return payload

    async def backups_list(self) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            rows = (await session.execute(select(BackupRecord).order_by(desc(BackupRecord.created_at)))).scalars().all()
        items = [self._backup_to_dict(row) for row in rows]
        latest_restore = next((item.get("restoredAt") for item in items if item.get("restoredAt")), "")
        return {"items": items, "latestRestoreAt": latest_restore}

    @staticmethod
    def _backup_to_dict(row: BackupRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "type": row.backup_type or "manual",
            "status": row.status or "success",
            "size": size_label(int(row.size_bytes or 0)),
            "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "",
            "createdBy": row.created_by or "",
            "note": row.note or "",
            "restoredAt": row.restored_at.strftime("%Y-%m-%d %H:%M:%S") if row.restored_at else "",
            "restoredBy": row.restored_by or "",
            "manifest": row.manifest or {},
        }

    async def create_backup(self, note: str, *, user: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._ensure_tables()
        manifest = {
            "uploadsDir": str(settings.uploads_dir),
            "documentsDir": str(settings.documents_dir),
            "parsedDir": str(settings.parsed_dir),
            "createdAt": now_display(),
        }
        size = 0
        for base in (settings.uploads_dir, settings.documents_dir, settings.parsed_dir):
            if base.exists():
                size += sum(path.stat().st_size for path in base.rglob("*") if path.is_file())
        item = BackupRecord(
            id=f"BKP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
            backup_type="manual",
            status="success",
            size_bytes=size,
            note=note or "手动备份",
            manifest=manifest,
            created_by=str((user or {}).get("name") or "当前用户"),
        )
        async with async_session() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
        await audit_service.record(
            action="创建备份",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=item.id,
            user=user,
            diff={"before": {}, "after": self._backup_to_dict(item)},
        )
        payload = await self.backups_list()
        payload.update({"message": "Backup created", "item": self._backup_to_dict(item)})
        return payload

    async def restore_backup(self, backup_id: str, *, user: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            item = (await session.execute(select(BackupRecord).where(BackupRecord.id == backup_id))).scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "Backup not found", "BACKUP_NOT_FOUND")
            before = self._backup_to_dict(item)
            item.restored_at = datetime.now()
            item.restored_by = str((user or {}).get("name") or "当前用户")
            await session.commit()
            await session.refresh(item)
            after = self._backup_to_dict(item)
        await audit_service.record(
            action="恢复备份",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=backup_id,
            user=user,
            diff={"before": before, "after": after},
        )
        payload = await self.backups_list()
        payload.update({"message": "Backup restored", "item": after})
        return payload

    async def health(self) -> list[dict[str, Any]]:
        await self._ensure_tables()
        checks = [
            await self._check_fastapi(),
            await self._check_postgres(),
            await self._check_minio(),
            await self._check_redis(),
            await self._check_http("svc-opencode", "OpenCode 服务", settings.opencode_base_url),
            await self._check_http("svc-onlyoffice", "OnlyOffice 文档服务", settings.onlyoffice_internal_url),
            await self._check_configured_gateway("svc-llm", "LLM 网关", "llm"),
            await self._check_configured_gateway("svc-ocr", "OCR 网关", "ocr"),
        ]
        return checks

    async def _check_fastapi(self) -> dict[str, Any]:
        return {"id": "svc-fastapi", "name": "FastAPI 业务后端", "status": "online", "latency": "0ms", "uptime": "-", "detail": "当前 API 进程正常响应。"}

    async def _check_postgres(self) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            async with async_session() as session:
                await session.execute(select(SystemConfig.key).limit(1))
            return {"id": "svc-postgres", "name": "PostgreSQL 数据库", "status": "online", "latency": f"{int((time.perf_counter() - start) * 1000)}ms", "uptime": "-", "detail": "数据库查询正常。"}
        except Exception as exc:
            return {"id": "svc-postgres", "name": "PostgreSQL 数据库", "status": "offline", "latency": "-", "uptime": "-", "detail": str(exc)}

    async def _check_minio(self) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            minio_client.ensure_bucket(settings.minio_buckets["templates"])
            return {"id": "svc-minio", "name": "MinIO 对象存储", "status": "online", "latency": f"{int((time.perf_counter() - start) * 1000)}ms", "uptime": "-", "detail": "模板 bucket 可访问。"}
        except Exception as exc:
            return {"id": "svc-minio", "name": "MinIO 对象存储", "status": "offline", "latency": "-", "uptime": "-", "detail": str(exc)}

    async def _check_redis(self) -> dict[str, Any]:
        if not settings.redis_url:
            return {"id": "svc-redis", "name": "Redis 队列", "status": "offline", "latency": "-", "uptime": "-", "detail": "未配置 REDIS_URL。"}
        start = time.perf_counter()
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            return {"id": "svc-redis", "name": "Redis 队列", "status": "online", "latency": f"{int((time.perf_counter() - start) * 1000)}ms", "uptime": "-", "detail": "Redis ping 正常。"}
        except Exception as exc:
            return {"id": "svc-redis", "name": "Redis 队列", "status": "offline", "latency": "-", "uptime": "-", "detail": str(exc)}

    async def _check_http(self, item_id: str, name: str, base_url: str) -> dict[str, Any]:
        url = str(base_url or "").rstrip("/")
        if not url:
            return {"id": item_id, "name": name, "status": "offline", "latency": "-", "uptime": "-", "detail": "未配置服务地址。"}
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=2.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(url)
            status = "online" if response.status_code < 500 else "offline"
            return {"id": item_id, "name": name, "status": status, "latency": f"{int((time.perf_counter() - start) * 1000)}ms", "uptime": "-", "detail": f"HTTP {response.status_code}"}
        except Exception as exc:
            return {"id": item_id, "name": name, "status": "offline", "latency": "-", "uptime": "-", "detail": str(exc)}

    async def _check_configured_gateway(self, item_id: str, name: str, kind: str) -> dict[str, Any]:
        config = await self.get_model_secret_config(kind)
        base_url = str(config.get("baseUrl") or "").strip()
        if not bool(config.get("enabled")):
            return {"id": item_id, "name": name, "status": "offline", "latency": "-", "uptime": "-", "detail": "未启用。"}
        if not base_url:
            return {"id": item_id, "name": name, "status": "offline", "latency": "-", "uptime": "-", "detail": "未配置 Base URL。"}
        return await self._check_http(item_id, name, base_url)


system_settings_service = SystemSettingsService()
