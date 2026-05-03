from __future__ import annotations

import base64
import copy
import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4
from urllib.parse import quote

from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import async_session
from app.models.materials import (
    AuditLog,
    AuthSession,
    BackupRecord,
    OcrCandidate,
    OcrTask,
    RawFile,
    RawFileVersion,
    RawFolder,
    StructuredRow,
    StructuredTable,
    SystemConfig,
    SystemUser,
    TemplateAsset,
    WikiAttachment,
    WikiDoc,
    WikiNode,
)
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError
from app.services.identity import (
    CUSTOMER_REGISTRY,
    canonical_customer,
    classify_material_path,
    customer_matches,
    material_identity,
    project_matches,
)

logger = logging.getLogger(__name__)


def now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_day() -> str:
    return datetime.now().strftime("%Y%m%d")


def size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.2f} MB"


def ext_of(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower().lstrip(".")
    return suffix or "file"


def safe_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


PLATFORM_WIKI_SECTION_TITLES = {
    "平台级Wiki说明",
    "章节骨架",
    "装配规则",
    "同义词映射",
    "通用卡片",
    "项目级Wiki模板",
}

MATERIAL_TIER_VALUES = {"standard", "customer", "project"}
MATERIAL_TIER_LABELS = {
    "standard": "通用素材",
    "customer": "客户素材",
    "project": "项目素材",
}
CLEANABLE_MATERIAL_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".docx", ".doc"}
RAW_MATERIAL_ROOTS = (
    {"name": "技术标", "tier": "standard", "bid_type": "技术标", "sort_order": 1},
    {"name": "商务标", "tier": "standard", "bid_type": "商务标", "sort_order": 2},
)
RAW_MATERIAL_ROOT_TIERS = {str(item["name"]): str(item["tier"]) for item in RAW_MATERIAL_ROOTS}
TECHNICAL_TIER_FOLDERS = (
    {"name": "通用素材", "tier": "standard", "sort_order": 1, "customer_name": "平台标准"},
    {"name": "客户素材", "tier": "customer", "sort_order": 2},
    {"name": "项目素材", "tier": "project", "sort_order": 3},
)


def canonical_technical_material_path(path: str) -> str:
    parts = [part for part in str(path or "").replace("\\", "/").strip("/").split("/") if part]
    if not parts:
        return ""
    if parts[0] == "技术标":
        return "/".join(parts)
    if len(parts) >= 2 and parts[0] in {"通用素材", "标准模板"} and parts[1] == "技术标":
        return "/".join(["技术标", "通用素材", *parts[2:]])
    if len(parts) >= 3 and parts[0] in {"客户素材", "客户定制"} and parts[2] == "技术标":
        return "/".join(["技术标", "客户素材", parts[1], *parts[3:]])
    if len(parts) >= 3 and parts[0] in {"项目素材", "项目定制"} and parts[2] == "技术标":
        return "/".join(["技术标", "项目素材", parts[1], *parts[3:]])
    return "/".join(parts)


def normalize_material_tier(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in MATERIAL_TIER_VALUES:
        return text
    aliases = {
        "通用": "standard",
        "通用素材": "standard",
        "标准": "standard",
        "标准模板": "standard",
        "客户": "customer",
        "客户素材": "customer",
        "客户定制": "customer",
        "项目": "project",
        "项目素材": "project",
        "项目定制": "project",
    }
    return aliases.get(text, "")


def clean_status_for_new_file(file_name: str) -> tuple[str, str]:
    suffix = PurePosixPath(str(file_name or "")).suffix.lower()
    if suffix in CLEANABLE_MATERIAL_SUFFIXES:
        return "pending", "等待清洗转换为 Word。"
    return "failed", "当前格式暂不支持自动清洗转换。"


class MaterialStore:
    """Real material store backed by PostgreSQL + MinIO.

    Drop-in replacement for ``PeripheralStore`` raw/structured/wiki methods.
    """

    _runtime_tables_ready = False

    async def _ensure_runtime_tables(self, session: Any) -> None:
        if self._runtime_tables_ready:
            return

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS raw_file_versions (
                    id BIGSERIAL PRIMARY KEY,
                    file_id BIGINT NOT NULL REFERENCES raw_files(id) ON DELETE CASCADE,
                    version INT NOT NULL,
                    minio_key VARCHAR(500) NOT NULL,
                    size_bytes BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS wiki_attachments (
                    id BIGSERIAL PRIMARY KEY,
                    doc_id BIGINT NOT NULL REFERENCES wiki_docs(id) ON DELETE CASCADE,
                    file_name VARCHAR(255) NOT NULL,
                    size_bytes BIGINT DEFAULT 0,
                    mime_type VARCHAR(100),
                    minio_key VARCHAR(500),
                    minio_bucket VARCHAR(100) DEFAULT 'bid-materials',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS template_assets (
                    id BIGSERIAL PRIMARY KEY,
                    asset_type VARCHAR(20) NOT NULL,
                    table_key VARCHAR(80),
                    file_name VARCHAR(255) NOT NULL,
                    version VARCHAR(40) NOT NULL,
                    minio_key VARCHAR(500),
                    minio_bucket VARCHAR(100) DEFAULT 'bid-templates',
                    size_bytes BIGINT DEFAULT 0,
                    mime_type VARCHAR(100),
                    is_active BOOLEAN DEFAULT FALSE,
                    uploaded_by VARCHAR(100),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS system_users (
                    id VARCHAR(80) PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    dept VARCHAR(120),
                    roles VARCHAR(80)[] DEFAULT '{}',
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token VARCHAR(128) PRIMARY KEY,
                    user_id VARCHAR(80) NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    user_agent TEXT,
                    ip_address VARCHAR(80)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS system_configs (
                    key VARCHAR(100) PRIMARY KEY,
                    value JSONB NOT NULL,
                    sensitive BOOLEAN DEFAULT FALSE,
                    updated_by VARCHAR(100),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS backup_records (
                    id VARCHAR(80) PRIMARY KEY,
                    backup_type VARCHAR(20) DEFAULT 'manual',
                    status VARCHAR(20) DEFAULT 'success',
                    size_bytes BIGINT DEFAULT 0,
                    note TEXT,
                    manifest JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100),
                    restored_at TIMESTAMPTZ,
                    restored_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    user_id VARCHAR(100) NOT NULL,
                    user_name VARCHAR(100),
                    action VARCHAR(80) NOT NULL,
                    action_type VARCHAR(40) NOT NULL,
                    module_id VARCHAR(80) NOT NULL,
                    module_label VARCHAR(200),
                    target VARCHAR(500),
                    status VARCHAR(20),
                    diff JSONB,
                    meta JSONB,
                    ip_address VARCHAR(80),
                    user_agent TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS meta JSONB"))
        await session.execute(text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip_address VARCHAR(80)"))
        await session.execute(text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent TEXT"))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ocr_tasks (
                    id VARCHAR(80) PRIMARY KEY,
                    project_id VARCHAR(50) NOT NULL,
                    source_file_name VARCHAR(255) NOT NULL,
                    source_path TEXT,
                    mime_type VARCHAR(100),
                    status VARCHAR(30) DEFAULT 'pending',
                    error_message TEXT,
                    page_count INT DEFAULT 0,
                    raw_response JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ocr_candidates (
                    id VARCHAR(80) PRIMARY KEY,
                    task_id VARCHAR(80) NOT NULL REFERENCES ocr_tasks(id) ON DELETE CASCADE,
                    project_id VARCHAR(50) NOT NULL,
                    page_number INT DEFAULT 1,
                    field_name VARCHAR(200) NOT NULL,
                    field_value TEXT,
                    field_type VARCHAR(40) DEFAULT 'text',
                    confidence INT DEFAULT 80,
                    source_text TEXT,
                    status VARCHAR(30) DEFAULT 'pending',
                    confirmed_value TEXT,
                    confirmed_by VARCHAR(100),
                    confirmed_at TIMESTAMPTZ,
                    ignored_reason TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        self._runtime_tables_ready = True

    @staticmethod
    def _raw_object_key(folder_path: str, file_name: str) -> str:
        return f"raw/{folder_path.strip('/')}/{file_name}"

    @staticmethod
    def _wiki_attachment_key(node_id: int, file_name: str) -> str:
        return f"wiki/{node_id}/{uuid4().hex}-{file_name}"

    @staticmethod
    def _cleaned_object_key(file_id: int, file_name: str) -> str:
        stem = PurePosixPath(safe_segment(PurePosixPath(file_name).stem, f"RAW-{file_id:04d}")).stem
        return f"cleaned/RAW-{file_id:04d}/{uuid4().hex}-{stem}.docx"

    @staticmethod
    def _infer_material_tier_from_folder(folder: RawFolder | None) -> str:
        if folder is None:
            return "project"
        tier = normalize_material_tier(str(folder.tier or ""))
        if tier:
            return tier
        path = str(folder.path or "")
        if path.startswith(("技术标/通用素材", "通用素材", "标准模板")):
            return "standard"
        if path.startswith(("技术标/客户素材", "客户素材", "客户定制")):
            return "customer"
        return "project"

    @staticmethod
    def _remove_cleaned_object_from_ext(ext: dict[str, Any]) -> None:
        bucket = str(ext.get("cleanedMinioBucket") or settings.minio_buckets["materials"])
        key = str(ext.get("cleanedMinioKey") or "")
        if not key:
            return
        try:
            minio_client.remove_object(bucket, key)
        except Exception as exc:  # pragma: no cover - MinIO cleanup must not block DB mutations
            logger.warning("Failed to remove cleaned material object %s/%s: %s", bucket, key, exc)

    @staticmethod
    def _enqueue_cleaning_job(file_id: int) -> dict[str, Any]:
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

    @staticmethod
    def _bid_type_for_wiki_root(root_title: str) -> str:
        title = str(root_title or "")
        if title.startswith("商务标"):
            return "商务标"
        return "技术标"

    async def _archive_raw_file_version(self, session: Any, item: RawFile) -> None:
        await self._ensure_runtime_tables(session)
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

    async def _purge_raw_file_objects(self, session: Any, item: RawFile) -> None:
        await self._ensure_runtime_tables(session)
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

    @staticmethod
    def _wiki_attachment_to_dict(attachment: WikiAttachment) -> dict[str, Any]:
        size = int(attachment.size_bytes or 0)
        return {
            "id": f"WIKI-ATT-{attachment.id:04d}",
            "name": attachment.file_name,
            "size": size_label(size),
            "time": attachment.created_at.strftime("%Y-%m-%d %H:%M:%S") if attachment.created_at else now_display(),
            "downloadUrl": f"/api/materials/wiki/attachments/WIKI-ATT-{attachment.id:04d}/content" if attachment.minio_key else "",
        }

    # ------------------------------------------------------------------ #
    # Raw Materials
    # ------------------------------------------------------------------ #

    async def raw_permissions(self, role: str = "member") -> dict[str, Any]:
        normalized = "admin" if role == "admin" else "member"
        editable_actions = {"upload": True, "rename": True, "move": True, "delete": True}
        return {
            "role": normalized,
            "rules": [
                {"pathPrefix": "技术标", "label": "技术标素材", "actions": editable_actions},
                {"pathPrefix": "商务标", "label": "商务标素材", "actions": editable_actions},
            ],
        }

    async def raw_tree(self) -> dict[str, Any]:
        async with async_session() as session:
            root_folders = await self._ensure_raw_material_roots(session)
            await session.commit()

            folders_result = await session.execute(select(RawFolder).order_by(RawFolder.sort_order, RawFolder.id))
            all_folders = folders_result.scalars().all()

            files_result = await session.execute(select(RawFile))
            all_files = files_result.scalars().all()

            files_by_folder: dict[int, list[RawFile]] = {}
            for f in all_files:
                files_by_folder.setdefault(f.folder_id, []).append(f)

            children_by_parent: dict[int, list[RawFolder]] = {}
            for f in all_folders:
                if f.parent_id is not None:
                    children_by_parent.setdefault(f.parent_id, []).append(f)

            def subtree_file_count(folder: RawFolder) -> int:
                child_folders = children_by_parent.get(folder.id, [])
                return len(files_by_folder.get(folder.id, [])) + sum(subtree_file_count(child) for child in child_folders)

            def build_node(folder: RawFolder) -> dict[str, Any]:
                child_folders = children_by_parent.get(folder.id, [])
                direct_file_count = len(files_by_folder.get(folder.id, []))
                return {
                    "id": folder.path,
                    "name": folder.name,
                    "path": folder.path,
                    "directFileCount": direct_file_count,
                    "fileCount": subtree_file_count(folder),
                    "children": [build_node(c) for c in child_folders],
                }

            folders_by_path = {str(folder.path or ""): folder for folder in all_folders}
            roots = [folders_by_path.get(str(root.path or "")) or root for root in root_folders]
            return {"tree": [build_node(r) for r in roots], "updatedAt": now_display()}

    async def identity_options(self, bid_type: str = "") -> dict[str, Any]:
        normalized_bid_type = bid_type if bid_type in {"技术标", "商务标"} else ""

        def sort_key(item: dict[str, Any]) -> str:
            return str(item.get("name") or item.get("projectName") or item.get("customerCanonicalName") or "")

        customers: dict[str, dict[str, Any]] = {}
        projects: dict[str, dict[str, Any]] = {}

        def add_customer(
            *,
            customer_id: str = "",
            name: str = "",
            aliases: list[str] | None = None,
            source: str = "material",
        ) -> None:
            candidate = canonical_customer(name)
            clean_id = str(customer_id or candidate.get("customerId") or "").strip()
            clean_name = str(name or candidate.get("customerCanonicalName") or clean_id).strip()
            if not clean_id and not clean_name:
                return
            clean_id = clean_id or str(candidate.get("customerId") or "")
            existing = customers.get(clean_id) or {}
            merged_aliases = []
            for alias in [
                *(existing.get("aliases") or []),
                *(aliases or []),
                *(candidate.get("customerAliases") or []),
                clean_name,
            ]:
                text = str(alias or "").strip()
                if text and text not in merged_aliases:
                    merged_aliases.append(text)
            customers[clean_id] = {
                "id": clean_id,
                "customerId": clean_id,
                "name": clean_name or existing.get("name") or clean_id,
                "customerCanonicalName": clean_name or existing.get("customerCanonicalName") or clean_id,
                "aliases": merged_aliases,
                "source": source if not existing.get("source") else existing["source"],
            }

        def add_project(
            *,
            project_id: str = "",
            project_code: str = "",
            project_name: str = "",
            customer_id: str = "",
            customer_name: str = "",
            item_bid_type: str = "",
            source: str = "material",
        ) -> None:
            clean_project_id = str(project_id or "").strip()
            if not clean_project_id:
                return
            clean_project_code = str(project_code or clean_project_id).strip()
            clean_project_name = str(project_name or clean_project_code or clean_project_id).strip()
            if normalized_bid_type and item_bid_type and item_bid_type not in {normalized_bid_type, "通用"}:
                return
            customer = canonical_customer(customer_name)
            clean_customer_id = str(customer_id or customer.get("customerId") or "").strip()
            clean_customer_name = str(customer_name or customer.get("customerCanonicalName") or "").strip()
            if clean_customer_id or clean_customer_name:
                add_customer(
                    customer_id=clean_customer_id,
                    name=clean_customer_name,
                    aliases=list(customer.get("customerAliases") or []),
                    source=source,
                )
            existing = projects.get(clean_project_id) or {}
            projects[clean_project_id] = {
                "id": clean_project_id,
                "projectId": clean_project_id,
                "projectCode": clean_project_code or existing.get("projectCode") or clean_project_id,
                "name": clean_project_name or existing.get("name") or clean_project_id,
                "projectName": clean_project_name or existing.get("projectName") or clean_project_id,
                "customerId": clean_customer_id or existing.get("customerId") or "",
                "customerName": clean_customer_name or existing.get("customerName") or "",
                "customerCanonicalName": clean_customer_name or existing.get("customerCanonicalName") or "",
                "bidType": item_bid_type or existing.get("bidType") or "",
                "source": source if not existing.get("source") else existing["source"],
            }

        for item in CUSTOMER_REGISTRY:
            if item["customerId"] == "CUST-SEWPG":
                continue
            add_customer(
                customer_id=str(item["customerId"]),
                name=str(item["customerCanonicalName"]),
                aliases=list(item["customerAliases"]),
                source="registry",
            )

        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            await self._ensure_raw_material_roots(session)
            await session.commit()
            folders = (await session.execute(select(RawFolder))).scalars().all()
            files = (await session.execute(select(RawFile))).scalars().all()

            for folder in folders:
                location = classify_material_path(folder.path, str(folder.bid_type or normalized_bid_type or "技术标"))
                folder_tier = normalize_material_tier(str(folder.tier or location.get("materialTier") or ""))
                if folder_tier == "customer":
                    add_customer(name=str(folder.customer_name or location.get("customerName") or ""))
                elif folder_tier == "project":
                    add_project(
                        project_id=str(folder.project_id or location.get("projectId") or ""),
                        item_bid_type=str(folder.bid_type or location.get("bidType") or ""),
                    )

            for raw_file in files:
                ext = raw_file.ext_fields or {}
                item_tier = normalize_material_tier(str(ext.get("materialTier") or ""))
                item_bid_type = str(ext.get("bidType") or "")
                if item_tier == "customer":
                    add_customer(
                        customer_id=str(ext.get("customerId") or ""),
                        name=str(ext.get("customerCanonicalName") or ext.get("customerName") or ""),
                        aliases=list(ext.get("customerAliases") or []),
                    )
                elif item_tier == "project":
                    add_project(
                        project_id=str(ext.get("projectId") or ""),
                        project_code=str(ext.get("projectCode") or ""),
                        project_name=str(ext.get("projectName") or ""),
                        customer_id=str(ext.get("customerId") or ""),
                        customer_name=str(ext.get("customerCanonicalName") or ext.get("customerName") or ""),
                        item_bid_type=item_bid_type,
                    )

        return {
            "customers": sorted(customers.values(), key=sort_key),
            "projects": sorted(projects.values(), key=sort_key),
        }

    async def raw_files(
        self,
        *,
        folder_path: str = "",
        project_id: str = "",
        customer_name: str = "",
        bid_type: str = "",
        material_tier: str = "",
        clean_status: str = "",
        keyword: str = "",
        recursive: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        async with async_session() as session:
            stmt = select(RawFile).options(selectinload(RawFile.folder))
            normalized_folder_path = str(folder_path or "").strip().strip("/")
            if normalized_folder_path:
                if recursive:
                    stmt = stmt.join(RawFolder).where(
                        or_(
                            RawFolder.path == normalized_folder_path,
                            RawFolder.path.like(f"{normalized_folder_path}/%"),
                        )
                    )
                else:
                    stmt = stmt.join(RawFolder).where(RawFolder.path == normalized_folder_path)
            if keyword:
                stmt = stmt.where(RawFile.name.ilike(f"%{keyword}%"))
            stmt = stmt.order_by(desc(RawFile.updated_at))
            result = await session.execute(stmt)
            items = result.scalars().all()

            # client-side filtering for ext_fields
            filtered = []
            for item in items:
                ext = item.ext_fields or {}
                if project_id and not project_matches(project_id, ext):
                    continue
                if customer_name and not customer_matches(customer_name, ext):
                    continue
                item_bid_type = str(ext.get("bidType") or "")
                if bid_type in {"技术标", "商务标"} and item_bid_type not in {bid_type, "通用"}:
                    continue
                if bid_type and bid_type not in {"技术标", "商务标"} and item_bid_type != bid_type:
                    continue
                normalized_tier = normalize_material_tier(material_tier)
                item_tier = str(ext.get("materialTier") or (item.folder.tier if item.folder else ""))
                if normalized_tier and item_tier != normalized_tier:
                    continue
                normalized_clean_status = str(clean_status or "").strip()
                if normalized_clean_status and normalized_clean_status != "all":
                    if str(ext.get("cleanStatus") or "") != normalized_clean_status:
                        continue
                filtered.append(item)

            total = len(filtered)
            start = max(0, (page - 1) * page_size)
            end = start + page_size
            return {
                "items": [f.to_dict() for f in filtered[start:end]],
                "total": total,
                "page": page,
                "pageSize": page_size,
            }

    async def raw_bootstrap_folders(self, project_id: str, bid_type: str = "技术标") -> dict[str, Any]:
        clean_id = safe_segment(project_id, "")
        if not clean_id:
            raise PeripheralError(400, "projectId 不能为空。", "PROJECT_ID_REQUIRED")
        normalized_bid_type = "技术标"
        root_path = f"{normalized_bid_type}/项目素材/{clean_id}"

        async with async_session() as session:
            await self._ensure_raw_material_roots(session)
            # Check if exists
            result = await session.execute(select(RawFolder).where(RawFolder.path == root_path))
            if result.scalar_one_or_none():
                return {"message": "项目目录骨架已存在。", "payload": {"projectId": clean_id, "path": root_path}}

            # Find or create parent chain
            parent = await self._find_folder(session, f"{normalized_bid_type}/项目素材")
            if parent is None:
                tech_root = await self._ensure_folder_path(
                    session,
                    normalized_bid_type,
                    None,
                    "standard",
                    normalized_bid_type,
                    None,
                    1,
                )
                parent = await self._ensure_folder_path(
                    session,
                    "项目素材",
                    tech_root.id,
                    "project",
                    normalized_bid_type,
                    None,
                    3,
                )
            await self._ensure_folder_path(session, clean_id, parent.id, "project", normalized_bid_type, clean_id, 0)
            await session.commit()

        return {"message": "项目目录骨架初始化完成。", "payload": {"projectId": clean_id, "path": root_path}}

    async def _ensure_material_target_folder(
        self,
        session: Any,
        *,
        material_tier: str,
        bid_type: str,
        customer_name: str = "",
        project_id: str = "",
    ) -> RawFolder:
        tier = normalize_material_tier(material_tier) or "project"
        normalized_bid_type = "技术标"
        tech_root = await self._ensure_folder_path(session, normalized_bid_type, None, "standard", normalized_bid_type, None, 1)

        if tier == "standard":
            return await self._ensure_folder_path(
                session,
                "通用素材",
                tech_root.id,
                "standard",
                normalized_bid_type,
                None,
                1 if normalized_bid_type == "技术标" else 2,
                customer_name="平台标准",
            )

        if tier == "customer":
            clean_customer = safe_segment(customer_name, "")
            if not clean_customer:
                raise PeripheralError(400, "客户素材必须填写客户名称。", "CUSTOMER_NAME_REQUIRED")
            root = await self._ensure_folder_path(session, "客户素材", tech_root.id, "customer", normalized_bid_type, None, 2)
            customer = await self._ensure_folder_path(
                session,
                clean_customer,
                root.id,
                "customer",
                normalized_bid_type,
                None,
                0,
                customer_name=clean_customer,
            )
            return customer

        clean_project_id = safe_segment(project_id, "")
        if not clean_project_id:
            raise PeripheralError(400, "项目素材必须填写项目 ID。", "PROJECT_ID_REQUIRED")
        root = await self._ensure_folder_path(session, "项目素材", tech_root.id, "project", normalized_bid_type, None, 3)
        return await self._ensure_folder_path(
            session,
            clean_project_id,
            root.id,
            "project",
            normalized_bid_type,
            clean_project_id,
            0,
        )

    async def _ensure_raw_material_roots(self, session: Any) -> list[RawFolder]:
        roots: list[RawFolder] = []
        for spec in RAW_MATERIAL_ROOTS:
            root = await self._ensure_folder_path(
                session,
                str(spec["name"]),
                None,
                str(spec["tier"]),
                str(spec.get("bid_type") or "") or None,
                None,
                int(spec["sort_order"]),
            )
            roots.append(root)
            if str(spec["name"]) != "技术标":
                continue
            for child in TECHNICAL_TIER_FOLDERS:
                await self._ensure_folder_path(
                    session,
                    str(child["name"]),
                    root.id,
                    str(child["tier"]),
                    "技术标",
                    None,
                    int(child["sort_order"]),
                    customer_name=str(child.get("customer_name") or "") or None,
                )
        await self._migrate_legacy_technical_folders(session)
        return roots

    async def _find_folder(self, session: Any, folder_path: str) -> RawFolder | None:
        result = await session.execute(select(RawFolder).where(RawFolder.path == folder_path))
        return result.scalar_one_or_none()

    async def _ensure_canonical_folder(self, session: Any, folder_path: str) -> RawFolder:
        normalized = str(folder_path or "").strip().strip("/")
        existing = await self._find_folder(session, normalized)
        if existing is not None:
            return existing
        parent = None
        parent_path = "/".join(normalized.split("/")[:-1])
        if parent_path:
            parent = await self._ensure_canonical_folder(session, parent_path)
        location = classify_material_path(normalized, "技术标")
        parts = [part for part in normalized.split("/") if part]
        if normalized == "技术标":
            tier = "standard"
            bid_type = "技术标"
            project_id = None
            customer_name = None
            sort_order = 1
        elif normalized == "商务标":
            tier = "standard"
            bid_type = "商务标"
            project_id = None
            customer_name = None
            sort_order = 2
        else:
            tier = normalize_material_tier(str(location.get("materialTier") or "")) or "project"
            bid_type = str(location.get("bidType") or "技术标")
            project_id = str(location.get("projectId") or "") or None
            customer_name = str(location.get("customerName") or "") or None
            sort_order = 0
            if len(parts) == 2 and parts[0] == "技术标":
                sort_order = {"通用素材": 1, "客户素材": 2, "项目素材": 3}.get(parts[1], 0)
        return await self._ensure_folder_path(
            session,
            parts[-1],
            parent.id if parent else None,
            tier,
            bid_type,
            project_id,
            sort_order,
            customer_name=customer_name,
        )

    async def _migrate_legacy_technical_folders(self, session: Any) -> None:
        folders = (await session.execute(select(RawFolder))).scalars().all()
        legacy_folders = [
            folder
            for folder in folders
            if (canonical_technical_material_path(str(folder.path or "")) != str(folder.path or "").strip("/"))
            and canonical_technical_material_path(str(folder.path or "")).startswith("技术标/")
        ]
        legacy_folders.sort(key=lambda folder: len(str(folder.path or "").split("/")))

        for folder in legacy_folders:
            old_path = str(folder.path or "").strip("/")
            new_path = canonical_technical_material_path(old_path)
            if not new_path or new_path == old_path:
                continue
            target = await self._find_folder(session, new_path)
            if target is not None and target.id != folder.id:
                files = (await session.execute(select(RawFile).where(RawFile.folder_id == folder.id))).scalars().all()
                for item in files:
                    item.folder_id = target.id
                continue

            parent_path = "/".join(new_path.split("/")[:-1])
            parent = await self._ensure_canonical_folder(session, parent_path) if parent_path else None
            location = classify_material_path(new_path, "技术标")
            folder.parent_id = parent.id if parent else None
            folder.name = new_path.split("/")[-1]
            folder.path = new_path
            folder.tier = normalize_material_tier(str(location.get("materialTier") or "")) or folder.tier
            folder.bid_type = str(location.get("bidType") or folder.bid_type or "技术标")
            folder.customer_name = str(location.get("customerName") or folder.customer_name or "") or None
            folder.project_id = str(location.get("projectId") or folder.project_id or "") or None

        for folder in sorted(legacy_folders, key=lambda item: len(str(item.path or "").split("/")), reverse=True):
            fresh = await session.get(RawFolder, folder.id)
            if fresh is None:
                continue
            has_files = bool((await session.execute(select(RawFile.id).where(RawFile.folder_id == fresh.id))).first())
            has_children = bool((await session.execute(select(RawFolder.id).where(RawFolder.parent_id == fresh.id))).first())
            if not has_files and not has_children and not str(fresh.path or "").startswith(("技术标", "商务标")):
                await session.delete(fresh)

    async def _ensure_folder_path(
        self,
        session: Any,
        name: str,
        parent_id: int | None,
        tier: str,
        bid_type: str | None,
        project_id: str | None,
        sort_order: int,
        customer_name: str | None = None,
    ) -> RawFolder:
        path = f"{parent_id and (await session.get(RawFolder, parent_id)).path or ''}/{name}".lstrip("/")
        result = await session.execute(select(RawFolder).where(RawFolder.path == path))
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        folder = RawFolder(
            parent_id=parent_id,
            name=name,
            path=path,
            tier=tier,
            bid_type=bid_type,
            customer_name=customer_name,
            project_id=project_id,
            sort_order=sort_order,
        )
        session.add(folder)
        await session.flush()
        return folder

    async def _ensure_nested_folder(
        self,
        session: Any,
        base_folder: RawFolder,
        relative_dir: str,
    ) -> RawFolder:
        current = base_folder
        normalized = str(relative_dir or "").replace("\\", "/").strip("/")
        if not normalized:
            return current

        for raw_segment in normalized.split("/"):
            segment = safe_segment(raw_segment, "")
            if not segment:
                continue
            current = await self._ensure_folder_path(
                session,
                segment,
                current.id,
                current.tier,
                current.bid_type,
                current.project_id,
                current.sort_order or 0,
                customer_name=current.customer_name,
            )
        return current

    async def raw_create_folder(self, parent_path: str, folder_name: str) -> dict[str, Any]:
        name = safe_segment(folder_name, "")
        if not name:
            raise PeripheralError(400, "文件夹名称不能为空。", "RAW_FOLDER_NAME_REQUIRED")

        async with async_session() as session:
            result = await session.execute(select(RawFolder).where(RawFolder.path == parent_path))
            parent = result.scalar_one_or_none()
            parent_id = parent.id if parent else None
            full_path = "/".join([p for p in [parent_path.strip("/"), name] if p])

            result2 = await session.execute(select(RawFolder).where(RawFolder.path == full_path))
            if result2.scalar_one_or_none():
                raise PeripheralError(409, "目录已存在。", "RAW_FOLDER_EXISTS")

            folder = RawFolder(
                parent_id=parent_id,
                name=name,
                path=full_path,
                tier=parent.tier if parent else "project",
                bid_type=parent.bid_type if parent else None,
                customer_name=parent.customer_name if parent else None,
                project_id=parent.project_id if parent else None,
            )
            session.add(folder)
            await session.commit()

            tree = await self.raw_tree()
            return {"message": "文件夹创建成功。", "folderPath": full_path, "tree": tree["tree"]}

    async def raw_delete_folder(self, path: str) -> dict[str, Any]:
        folder_path = str(path or "").strip().strip("/")
        if not folder_path:
            raise PeripheralError(400, "path 不能为空。", "RAW_FOLDER_PATH_REQUIRED")

        async with async_session() as session:
            result = await session.execute(select(RawFolder).where(RawFolder.path == folder_path).options(selectinload(RawFolder.files)))
            folder = result.scalar_one_or_none()
            if folder is None:
                raise PeripheralError(404, "目录不存在。", "RAW_FOLDER_NOT_FOUND")
            if folder.files:
                raise PeripheralError(400, "目录下仍有文件，请先移除或迁移文件后再删除。", "RAW_FOLDER_NOT_EMPTY")

            await session.delete(folder)
            await session.commit()

            tree = await self.raw_tree()
            return {"message": "文件夹删除成功。", "folderPath": folder_path, "tree": tree["tree"]}

    async def raw_upload(
        self,
        *,
        target_path: str = "",
        project_id: str = "",
        project_code: str = "",
        project_name: str = "",
        bid_type: str = "技术标",
        material_tier: str = "",
        customer_id: str = "",
        customer_name: str = "",
        on_conflict: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        file_inputs = list(files or [])
        if not file_inputs:
            raise PeripheralError(400, "请至少上传一个文件。", "RAW_UPLOAD_FILES_REQUIRED")
        normalized_bid_type = bid_type if bid_type in {"技术标", "商务标", "通用"} else "技术标"
        if normalized_bid_type != "技术标":
            raise PeripheralError(400, "商务标素材库当前仅保留空目录，暂不支持上传。", "BUSINESS_MATERIAL_DISABLED")
        normalized_tier = normalize_material_tier(material_tier)
        auto_target = not bool(target_path)

        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            if auto_target:
                normalized_tier = normalized_tier or ("project" if project_id else "standard")
                base_folder = await self._ensure_material_target_folder(
                    session,
                    material_tier=normalized_tier,
                    bid_type=normalized_bid_type,
                    customer_name=customer_name,
                    project_id=project_id,
                )
                target_path = base_folder.path
            else:
                target_path = str(target_path or "").strip().strip("/")
                target_parts = [part for part in target_path.split("/") if part]
                location = classify_material_path(target_path, normalized_bid_type)
                inferred_target_tier = normalize_material_tier(str(location.get("materialTier") or ""))
                inferred_customer_name = customer_name
                inferred_project_id = project_id
                if target_parts and target_parts[0] == "商务标":
                    raise PeripheralError(400, "商务标素材库当前仅保留空目录，暂不支持上传。", "BUSINESS_MATERIAL_DISABLED")
                if inferred_target_tier == "standard":
                    inferred_customer_name = inferred_customer_name or "平台标准"
                if inferred_target_tier == "customer":
                    inferred_customer_name = inferred_customer_name or str(location.get("customerName") or "")
                if inferred_target_tier == "project":
                    inferred_project_id = inferred_project_id or str(location.get("projectId") or "")
                if inferred_target_tier and len(target_parts) <= 2:
                    result = await session.execute(select(RawFolder).where(RawFolder.path == target_path))
                    base_folder = result.scalar_one_or_none()
                    if base_folder is None:
                        base_folder = await self._ensure_material_target_folder(
                            session,
                            material_tier=inferred_target_tier,
                            bid_type=normalized_bid_type,
                            customer_name=inferred_customer_name,
                            project_id=inferred_project_id,
                        )
                    normalized_tier = normalized_tier or inferred_target_tier
                    target_path = base_folder.path
                else:
                    if not inferred_target_tier and len(target_parts) == 2 and target_parts[0] == "客户素材":
                        inferred_target_tier = "customer"
                        inferred_customer_name = inferred_customer_name or target_parts[1]
                    if not inferred_target_tier and len(target_parts) == 2 and target_parts[0] == "项目素材":
                        inferred_target_tier = "project"
                        inferred_project_id = inferred_project_id or target_parts[1]
                    if inferred_target_tier == "customer" and not inferred_customer_name:
                        raise PeripheralError(400, "客户素材必须填写客户名称。", "CUSTOMER_NAME_REQUIRED")
                    if inferred_target_tier == "project" and not inferred_project_id:
                        raise PeripheralError(400, "项目素材必须填写项目 ID。", "PROJECT_ID_REQUIRED")

                    if inferred_target_tier:
                        normalized_tier = normalized_tier or inferred_target_tier
                        result = await session.execute(select(RawFolder).where(RawFolder.path == target_path))
                        base_folder = result.scalar_one_or_none()
                        if base_folder is None:
                            requested_path = "/".join(target_parts)
                            canonical_folder = await self._ensure_material_target_folder(
                                session,
                                material_tier=normalized_tier,
                                bid_type=normalized_bid_type,
                                customer_name=inferred_customer_name,
                                project_id=inferred_project_id,
                            )
                            if requested_path.startswith(f"{canonical_folder.path}/"):
                                relative_dir = requested_path.removeprefix(f"{canonical_folder.path}/")
                                base_folder = await self._ensure_nested_folder(session, canonical_folder, relative_dir)
                            elif requested_path == canonical_folder.path or target_parts[0] != "技术标":
                                base_folder = canonical_folder
                            else:
                                raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
                            target_path = base_folder.path
                    else:
                        result = await session.execute(select(RawFolder).where(RawFolder.path == target_path))
                        base_folder = result.scalar_one_or_none()
                        if base_folder is None:
                            raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
                        normalized_tier = normalized_tier or self._infer_material_tier_from_folder(base_folder)

            uploaded_items: list[dict[str, Any]] = []
            clean_job_targets: list[int] = []
            for item in file_inputs:
                relative_path = str(item.get("relativePath") or "").replace("\\", "/").strip("/")
                relative_parts = [part for part in relative_path.split("/") if part]
                relative_dir = "/".join(relative_parts[:-1]) if len(relative_parts) > 1 else ""
                source_relative_path = "/".join(relative_parts) if relative_parts else ""
                source_root_folder = relative_parts[0] if len(relative_parts) > 1 else ""

                file_name = safe_segment(relative_parts[-1] if relative_parts else item.get("name") or "", "")
                if not file_name:
                    continue

                folder = await self._ensure_nested_folder(session, base_folder, relative_dir)

                # Check conflict
                result = await session.execute(
                    select(RawFile).where(RawFile.folder_id == folder.id, RawFile.name == file_name)
                )
                existing = result.scalar_one_or_none()

                upload = item.get("upload")
                mime_type = str(item.get("mimeType") or item.get("type") or getattr(upload, "content_type", "") or "")
                minio_key = self._raw_object_key(folder.path, file_name)
                location = classify_material_path(folder.path, normalized_bid_type)
                folder_tier = (
                    normalize_material_tier(location.get("materialTier"))
                    or normalize_material_tier(normalized_tier)
                    or self._infer_material_tier_from_folder(folder)
                )
                item_bid_type = str(location.get("bidType") or normalized_bid_type)
                clean_status, clean_message = clean_status_for_new_file(file_name)
                item_customer_name = (
                    customer_name
                    or str(location.get("customerName") or "")
                    or folder.customer_name
                    or ("平台标准" if folder_tier == "standard" else "")
                )
                item_project_id = project_id or str(location.get("projectId") or "") or folder.project_id or ""
                item_project_code = project_code or item_project_id
                item_project_name = project_name
                identity = material_identity(
                    material_tier=folder_tier,
                    bid_type=item_bid_type,
                    customer_name=item_customer_name,
                    project_id=item_project_id,
                    project_code=item_project_code,
                    project_name=item_project_name,
                )
                if customer_id and folder_tier in {"customer", "project"}:
                    identity["customerId"] = customer_id
                common_ext = {
                    "bidType": item_bid_type,
                    "projectId": item_project_id,
                    "projectCode": item_project_code,
                    "projectName": item_project_name,
                    "customerId": customer_id or identity.get("customerId") or "",
                    "customerName": item_customer_name,
                    "materialTier": folder_tier,
                    "materialTierLabel": MATERIAL_TIER_LABELS.get(folder_tier, ""),
                    **identity,
                    "sourceMinioBucket": settings.minio_buckets["materials"],
                    "sourceMinioKey": minio_key,
                    "sourceFileName": file_name,
                    "sourceRelativePath": source_relative_path or file_name,
                    "sourceRootFolder": source_root_folder,
                    "cleanStatus": clean_status,
                    "cleanMessage": clean_message,
                    "cleanUpdatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }

                if upload is not None and hasattr(upload, "file"):
                    file_stream = upload.file
                    file_stream.seek(0, 2)
                    size = file_stream.tell()
                    file_stream.seek(0)
                    def upload_to_minio() -> str:
                        return minio_client.put_object_stream(
                            settings.minio_buckets["materials"],
                            minio_key,
                            file_stream,
                            size,
                            content_type=mime_type or "application/octet-stream",
                        )
                else:
                    raw_data = item.get("data") or b""
                    if isinstance(raw_data, str):
                        if raw_data.startswith("data:"):
                            raw_data = raw_data.split(",", 1)[-1]
                        file_data = base64.b64decode(raw_data)
                    else:
                        file_data = raw_data if isinstance(raw_data, bytes) else b""
                    size = len(file_data)
                    def upload_to_minio() -> str:
                        return minio_client.put_object(
                            settings.minio_buckets["materials"],
                            minio_key,
                            file_data,
                            content_type=mime_type or "application/octet-stream",
                        )

                if size > settings.max_upload_file_size_bytes:
                    limit_mb = settings.max_upload_file_size_bytes // 1024 // 1024
                    raise PeripheralError(
                        413,
                        f"文件 {file_name} 超过 {limit_mb}MB 上限。",
                        "RAW_FILE_TOO_LARGE",
                    )

                if existing and on_conflict in {"overwrite", "version"}:
                    await self._archive_raw_file_version(session, existing)
                    self._remove_cleaned_object_from_ext(existing.ext_fields or {})
                    upload_to_minio()
                    existing.size_bytes = size
                    existing.minio_key = minio_key
                    existing.mime_type = mime_type
                    existing.version += 1
                    ext = existing.ext_fields or {}
                    ext.update(common_ext)
                    ext["lastAction"] = on_conflict
                    ext["lastOperator"] = "当前用户"
                    existing.ext_fields = ext
                    uploaded_items.append(existing.to_dict())
                    if clean_status == "pending":
                        clean_job_targets.append(int(existing.id))
                    continue

                if existing and not on_conflict:
                    raise PeripheralError(
                        409,
                        "目标路径存在同名文件",
                        "MATERIAL_CONFLICT",
                        {"conflict": {"path": folder.path, "existingFileId": f"RAW-{existing.id:04d}", "existingFileName": existing.name, "allowedActions": ["overwrite", "version"]}},
                    )

                upload_to_minio()
                record = RawFile(
                    folder_id=folder.id,
                    name=file_name,
                    size_bytes=size,
                    mime_type=mime_type,
                    minio_key=minio_key,
                    minio_bucket=settings.minio_buckets["materials"],
                    ext_fields={
                        **common_ext,
                        "lastAction": "upload",
                        "lastOperator": "当前用户",
                    },
                )
                session.add(record)
                await session.flush()
                uploaded_items.append(record.to_dict())
                if clean_status == "pending":
                    clean_job_targets.append(int(record.id))

            await session.commit()
            clean_jobs = [self._enqueue_cleaning_job(file_id) for file_id in clean_job_targets]
            return {
                "message": f"上传完成，共处理 {len(uploaded_items)} 个文件，已触发 {len(clean_job_targets)} 个清洗任务。",
                "items": uploaded_items,
                "cleaning": {"queued": sum(1 for job in clean_jobs if job.get("queued")), "jobs": clean_jobs},
            }

    async def raw_update_file(self, file_id: str, name: str) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        next_name = safe_segment(name, "")
        if not next_name:
            raise PeripheralError(400, "文件名不能为空。", "RAW_FILE_NAME_REQUIRED")
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder)))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
            if item.folder is None:
                raise PeripheralError(400, "文件目录信息缺失。", "RAW_FILE_FOLDER_MISSING")

            conflict = await session.execute(
                select(RawFile).where(
                    RawFile.folder_id == item.folder_id,
                    RawFile.name == next_name,
                    RawFile.id != item.id,
                )
            )
            if conflict.scalar_one_or_none() is not None:
                raise PeripheralError(409, "目标目录存在同名文件。", "MATERIAL_CONFLICT")

            next_key = self._raw_object_key(item.folder.path, next_name)
            if next_key != item.minio_key and item.minio_key:
                minio_client.copy_object(item.minio_bucket, item.minio_key, next_key)
                minio_client.remove_object(item.minio_bucket, item.minio_key)

            item.name = next_name
            item.minio_key = next_key
            item.ext_fields = {
                **(item.ext_fields or {}),
                "sourceMinioKey": next_key,
                "sourceFileName": next_name,
                "lastAction": "rename",
            }
            await session.commit()
            refreshed = await session.execute(
                select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
            )
            updated = refreshed.scalar_one()
            return {"message": "重命名成功", "item": updated.to_dict()}

    async def raw_delete_file(self, file_id: str) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder)))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
            payload = item.to_dict()
            await self._purge_raw_file_objects(session, item)
            await session.delete(item)
            await session.commit()
            return {"message": "删除成功", "item": payload}

    async def raw_download_file(self, file_id: str) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            result = await session.execute(select(RawFile).where(RawFile.id == numeric_id))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
            return {
                "fileId": f"RAW-{item.id:04d}",
                "fileName": item.name,
                "downloadUrl": f"/api/materials/raw/{file_id}/content",
                "message": "已生成下载地址",
            }

    async def raw_download_content(self, file_id: str) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            result = await session.execute(select(RawFile).where(RawFile.id == numeric_id))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
            return {
                "fileId": f"RAW-{item.id:04d}",
                "fileName": item.name,
                "bucket": item.minio_bucket,
                "key": item.minio_key,
                "mimeType": item.mime_type or "application/octet-stream",
            }

    async def raw_retry_clean_file(self, file_id: str) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            result = await session.execute(
                select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
            )
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
            clean_status, clean_message = clean_status_for_new_file(item.name)
            if clean_status != "pending":
                raise PeripheralError(400, clean_message, "RAW_FILE_NOT_CLEANABLE")
            ext = dict(item.ext_fields or {})
            self._remove_cleaned_object_from_ext(ext)
            ext.update(
                {
                    "cleanStatus": "pending",
                    "cleanMessage": clean_message,
                    "cleanError": "",
                    "cleanLogTail": "",
                    "cleanResultStatus": "",
                    "cleanedMinioKey": "",
                    "cleanedMinioBucket": "",
                    "cleanedFileName": "",
                    "cleanedSize": 0,
                    "cleanedAt": "",
                    "cleanUpdatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }
            )
            item.ext_fields = ext
            await session.flush()
            await session.refresh(item, attribute_names=["updated_at"])
            item_payload = item.to_dict()
            await session.commit()

        job = self._enqueue_cleaning_job(numeric_id)
        return {"message": "已重新触发素材清洗。", "item": item_payload, "cleaning": job}

    async def raw_download_cleaned_file(self, file_id: str) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            result = await session.execute(select(RawFile).where(RawFile.id == numeric_id))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
            ext = item.ext_fields or {}
            if not ext.get("cleanedMinioKey"):
                raise PeripheralError(404, "清洗后的 Word 文件尚未生成。", "RAW_CLEANED_FILE_NOT_FOUND")
            return {
                "fileId": f"RAW-{item.id:04d}",
                "fileName": ext.get("cleanedFileName") or f"{PurePosixPath(item.name).stem}.docx",
                "downloadUrl": f"/api/materials/raw/{file_id}/cleaned/content",
                "message": "已生成清洗后 Word 下载地址",
            }

    async def raw_cleaned_preview(
        self,
        file_id: str,
        *,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            result = await session.execute(select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder)))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")

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
            file_path = f"/api/materials/raw/{raw_id}/cleaned/content/{encoded_name}"
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

    async def raw_download_cleaned_content(self, file_id: str) -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            result = await session.execute(select(RawFile).where(RawFile.id == numeric_id))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
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

    # ------------------------------------------------------------------ #
    # Structured Materials
    # ------------------------------------------------------------------ #

    async def structured_list(self, table: str = "all") -> dict[str, Any]:
        async with async_session() as session:
            if table and table != "all":
                result = await session.execute(select(StructuredTable).where(StructuredTable.table_key == table))
                tbl = result.scalar_one_or_none()
                if tbl is None:
                    return {"items": [], "total": 0, "tableOptions": [], "importHistory": [], "latestReceipt": None}
                rows_result = await session.execute(select(StructuredRow).where(StructuredRow.table_id == tbl.id))
                rows = rows_result.scalars().all()
                return {
                    "items": [r.to_dict() for r in rows],
                    "total": len(rows),
                    "tableOptions": [{"key": tbl.table_key, "label": tbl.table_label}],
                    "importHistory": [],
                    "latestReceipt": None,
                }
            else:
                tables_result = await session.execute(select(StructuredTable))
                tables = tables_result.scalars().all()
                all_rows: list[dict[str, Any]] = []
                for tbl in tables:
                    rows_result = await session.execute(select(StructuredRow).where(StructuredRow.table_id == tbl.id))
                    all_rows.extend([r.to_dict() for r in rows_result.scalars().all()])
                return {
                    "items": all_rows,
                    "total": len(all_rows),
                    "tableOptions": [{"key": t.table_key, "label": t.table_label} for t in tables],
                    "importHistory": [],
                    "latestReceipt": None,
                }

    async def structured_template(self, table: str = "") -> dict[str, Any]:
        async with async_session() as session:
            result = await session.execute(select(StructuredTable).where(StructuredTable.table_key == table))
            tbl = result.scalar_one_or_none()
            if tbl is None:
                tables_result = await session.execute(select(StructuredTable).limit(1))
                tbl = tables_result.scalar_one_or_none()
            label = tbl.table_label if tbl else "未命名"
            return {
                "table": {"key": tbl.table_key if tbl else "", "label": label},
                "fileName": f"{label}_导入模板.xlsx",
                "templateVersion": "2026.04",
                "requiredFields": ["名称", "值"],
                "optionalFields": ["备注"],
                "templateColumns": ["名称", "值", "备注"],
                "sampleRows": [{"名称": "样例", "值": "示例", "备注": "可选"}],
                "notes": ["请勿修改首行字段名。", "可保留可选字段为空。"],
            }

    async def structured_create(self, data: dict[str, Any]) -> dict[str, Any]:
        async with async_session() as session:
            table_key = str(data.get("tableKey") or "performance_guarantee")
            result = await session.execute(select(StructuredTable).where(StructuredTable.table_key == table_key))
            tbl = result.scalar_one_or_none()
            if tbl is None:
                raise PeripheralError(400, "无效的表类型", "STRUCTURED_TABLE_INVALID")
            row = StructuredRow(
                table_id=tbl.id,
                row_data=data.get("rowData") or data,
            )
            session.add(row)
            await session.commit()
            return row.to_dict()

    async def structured_delete(self, item_id: str) -> dict[str, Any]:
        numeric_id = int(item_id.replace("MAT-", ""))
        async with async_session() as session:
            result = await session.execute(select(StructuredRow).where(StructuredRow.id == numeric_id))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "素材不存在。", "STRUCTURED_MATERIAL_NOT_FOUND")
            await session.delete(item)
            await session.commit()
            return {"message": "Deleted"}

    # ------------------------------------------------------------------ #
    # Wiki Materials
    # ------------------------------------------------------------------ #

    async def wiki_list(self, node_id: str = "", bid_type: str = "") -> dict[str, Any]:
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            nodes_result = await session.execute(select(WikiNode).order_by(WikiNode.sort_order, WikiNode.id))
            all_nodes = nodes_result.scalars().all()
            normalized_bid_type = bid_type if bid_type in {"技术标", "商务标"} else ""
            opposite_bid_type = "商务标" if normalized_bid_type == "技术标" else "技术标"

            children_by_parent: dict[int, list[WikiNode]] = {}
            for n in all_nodes:
                if n.parent_id is not None:
                    children_by_parent.setdefault(n.parent_id, []).append(n)

            def root_matches_bid_type(node: WikiNode) -> bool:
                if not normalized_bid_type:
                    return True
                title = str(node.title or "")
                if title.startswith(f"{normalized_bid_type}Wiki"):
                    return True
                if title.startswith(f"{opposite_bid_type}Wiki") or title == "平台级Wiki（自动生成）":
                    return False
                bid_types = {str(item) for item in (node.bid_types or [])}
                return normalized_bid_type in bid_types and opposite_bid_type not in bid_types

            visible_node_ids: set[int] = set()
            visible_node_order: list[int] = []

            def collect_visible(node: WikiNode) -> None:
                node_id_int = int(node.id)
                visible_node_ids.add(node_id_int)
                visible_node_order.append(node_id_int)
                for child in children_by_parent.get(node.id, []):
                    collect_visible(child)

            def build_node(node: WikiNode) -> dict[str, Any]:
                child_nodes = children_by_parent.get(node.id, [])
                has_children = bool(child_nodes)
                return {
                    "id": f"WIKI-{node.id:04d}",
                    "title": node.title,
                    "icon": "folder" if has_children else "article",
                    "expanded": True if has_children else None,
                    "children": [build_node(c) for c in child_nodes],
                }

            roots = [n for n in all_nodes if n.parent_id is None and root_matches_bid_type(n)]
            for root in roots:
                collect_visible(root)
            tree = [build_node(r) for r in roots]

            selected = None
            selected_node_ids: list[int] = []
            if node_id:
                selected_node_ids.append(int(node_id.replace("WIKI-", "")))
            selected_node_ids.extend(item for item in visible_node_order if item not in selected_node_ids)

            for numeric_id in selected_node_ids:
                if normalized_bid_type and numeric_id not in visible_node_ids:
                    continue
                if not normalized_bid_type or numeric_id in visible_node_ids:
                    doc_result = await session.execute(
                        select(WikiDoc).where(WikiDoc.node_id == numeric_id).options(selectinload(WikiDoc.node))
                    )
                    doc = doc_result.scalar_one_or_none()
                    if doc:
                        selected = doc.to_dict()
                        attachment_rows = (
                            await session.execute(
                                select(WikiAttachment)
                                .where(WikiAttachment.doc_id == doc.id)
                                .order_by(desc(WikiAttachment.created_at), desc(WikiAttachment.id))
                            )
                        ).scalars().all()
                        selected["attachments"] = [self._wiki_attachment_to_dict(item) for item in attachment_rows]
                        break

            return {
                "tree": tree,
                "selectedNode": selected,
                "tagOptions": ["技术标", "商务标", "通用素材", "客户素材", "项目素材", "日志"],
                "applicableTypeOptions": ["技术标", "商务标"],
            }

    async def wiki_create(self, parent_id: str, title: str, is_folder: bool, bid_type: str = "") -> dict[str, Any]:
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            parent = None
            if parent_id:
                numeric_parent = int(parent_id.replace("WIKI-", ""))
                result = await session.execute(select(WikiNode).where(WikiNode.id == numeric_parent))
                parent = result.scalar_one_or_none()

            path = f"{parent.path if parent else ''}/{title}".lstrip("/")
            node = WikiNode(
                parent_id=parent.id if parent else None,
                title=title.strip() or ("新建目录" if is_folder else "新建节点"),
                tier=parent.tier if parent else "standard",
                path=path,
                bid_types=parent.bid_types if parent else ([bid_type] if bid_type in {"技术标", "商务标"} else ["通用"]),
            )
            session.add(node)
            await session.flush()

            doc = WikiDoc(
                node_id=node.id,
                markdown_content=f"# {node.title}\n\n请在此补充节点内容。",
                ai_summary="新建节点，尚未生成摘要。",
            )
            session.add(doc)
            await session.commit()

            return {"message": "Created", **await self.wiki_list(f"WIKI-{node.id:04d}", bid_type)}

    async def wiki_update(self, node_id: str, data: dict[str, Any]) -> dict[str, Any]:
        numeric_id = int(node_id.replace("WIKI-", ""))
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(
                select(WikiDoc).where(WikiDoc.node_id == numeric_id).options(selectinload(WikiDoc.node))
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")

            if data.get("title"):
                doc.node.title = str(data["title"])
                doc.node.path = "/".join(doc.node.path.split("/")[:-1] + [doc.node.title])
            if data.get("markdownContent") is not None:
                doc.markdown_content = str(data["markdownContent"])
            if data.get("tags"):
                doc.tags = list(data["tags"])
            if data.get("applicableTypes"):
                doc.node.bid_types = list(data["applicableTypes"])

            await session.commit()
            return {"message": "Updated", **await self.wiki_list(node_id, str(data.get("bidType") or ""))}

    async def wiki_refresh_summary(self, node_id: str, bid_type: str = "") -> dict[str, Any]:
        numeric_id = int(node_id.replace("WIKI-", ""))
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == numeric_id))
            doc = result.scalar_one_or_none()
            if doc is None:
                raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
            text = doc.markdown_content or ""
            summary = re.sub(r"\s+", " ", text.replace("#", "")).strip()[:80] or "暂无摘要。"
            doc.ai_summary = summary
            await session.commit()
            return {"summary": summary, **await self.wiki_list(node_id, bid_type)}

    async def wiki_move(self, node_id: str, target_id: str, mode: str, bid_type: str = "") -> dict[str, Any]:
        numeric_id = int(node_id.replace("WIKI-", ""))
        target_numeric = int(target_id.replace("WIKI-", ""))
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(select(WikiNode).where(WikiNode.id == numeric_id))
            source = result.scalar_one_or_none()
            if source is None:
                raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
            result2 = await session.execute(
                select(WikiNode).where(WikiNode.id == target_numeric).options(selectinload(WikiNode.parent))
            )
            target = result2.scalar_one_or_none()
            if target is None:
                raise PeripheralError(404, "目标节点不存在。", "WIKI_NODE_NOT_FOUND")
            source.parent_id = target.id if mode == "inside" else target.parent_id
            source.path = f"{target.path if mode == 'inside' else (target.parent.path if target.parent else '')}/{source.title}".lstrip("/")
            await session.commit()
            return {"message": "Moved", **await self.wiki_list(node_id, bid_type)}

    async def wiki_upload_attachment(
        self,
        node_id: str,
        file_name: str,
        file_size: Any,
        *,
        upload: Any | None = None,
        data: bytes | None = None,
        mime_type: str = "",
        bid_type: str = "",
    ) -> dict[str, Any]:
        numeric_id = int(node_id.replace("WIKI-", ""))
        clean_name = safe_segment(file_name, "")
        if not clean_name:
            raise PeripheralError(400, "附件文件名不能为空。", "WIKI_ATTACHMENT_NAME_REQUIRED")

        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == numeric_id))
            doc = result.scalar_one_or_none()
            if doc is None:
                raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")

            bucket = settings.minio_buckets["materials"]
            key = self._wiki_attachment_key(numeric_id, clean_name)
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

        return {"message": "Uploaded", **await self.wiki_list(node_id, bid_type)}

    async def wiki_download_attachment_content(self, attachment_id: str) -> dict[str, Any]:
        numeric_id = int(attachment_id.replace("WIKI-ATT-", ""))
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(select(WikiAttachment).where(WikiAttachment.id == numeric_id))
            attachment = result.scalar_one_or_none()
            if attachment is None or not attachment.minio_key:
                raise PeripheralError(404, "附件不存在。", "WIKI_ATTACHMENT_NOT_FOUND")
            return {
                "fileName": attachment.file_name,
                "bucket": attachment.minio_bucket or settings.minio_buckets["materials"],
                "key": attachment.minio_key,
                "mimeType": attachment.mime_type or "application/octet-stream",
            }

    async def import_generated_wiki_blueprint(
        self,
        *,
        root_title: str,
        root_markdown_content: str = "",
        nodes: list[dict[str, Any]],
        mode: str = "create",
    ) -> dict[str, Any]:
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            normalized_mode = mode if mode in {"create", "update", "replace"} else "create"
            normalized_root_title = safe_segment(root_title, "平台级Wiki（自动生成）")

            async def purge_wiki_root(root: WikiNode) -> None:
                all_nodes = (await session.execute(select(WikiNode))).scalars().all()
                nodes_by_id = {int(node.id): node for node in all_nodes}
                children_by_parent: dict[int, list[WikiNode]] = {}
                for node in all_nodes:
                    if node.parent_id is not None:
                        children_by_parent.setdefault(node.parent_id, []).append(node)

                node_ids: set[int] = set()
                node_depths: dict[int, int] = {}

                def collect(node: WikiNode, depth: int = 0) -> None:
                    node_ids.add(int(node.id))
                    node_depths[int(node.id)] = depth
                    for child in children_by_parent.get(node.id, []):
                        collect(child, depth + 1)

                collect(root)
                if node_ids:
                    attachments = (
                        await session.execute(
                            select(WikiAttachment)
                            .join(WikiDoc, WikiAttachment.doc_id == WikiDoc.id)
                            .where(WikiDoc.node_id.in_(node_ids))
                        )
                    ).scalars().all()
                    for attachment in attachments:
                        if attachment.minio_key:
                            minio_client.remove_object(
                                attachment.minio_bucket or settings.minio_buckets["materials"],
                                attachment.minio_key,
                            )
                for node_id in sorted(node_ids - {int(root.id)}, key=lambda item: node_depths.get(item, 0), reverse=True):
                    node = nodes_by_id.get(node_id)
                    if node is not None:
                        await session.delete(node)
                await session.delete(root)
                await session.flush()

            async def purge_orphaned_platform_sections() -> None:
                orphaned_roots = (
                    await session.execute(
                        select(WikiNode).where(
                            WikiNode.parent_id.is_(None),
                            WikiNode.title.in_(PLATFORM_WIKI_SECTION_TITLES),
                        )
                    )
                ).scalars().all()
                for orphaned_root in orphaned_roots:
                    await purge_wiki_root(orphaned_root)

            async def create_node(
                spec: dict[str, Any],
                parent: WikiNode | None,
                *,
                default_tier: str = "standard",
                sort_order: int = 0,
            ) -> WikiNode:
                title = safe_segment(str(spec.get("title") or "未命名节点"), "未命名节点")
                path = f"{parent.path if parent else ''}/{title}".lstrip("/")
                node = WikiNode(
                    parent_id=parent.id if parent else None,
                    title=title,
                    tier=parent.tier if parent else default_tier,
                    path=path,
                    bid_types=list(spec.get("applicableTypes") or ["通用"]),
                    sort_order=sort_order,
                )
                session.add(node)
                await session.flush()
                doc = WikiDoc(
                    node_id=node.id,
                    markdown_content=str(spec.get("markdownContent") or f"# {title}\n"),
                    ai_summary="自动生成的 Wiki 初稿节点。",
                    tags=list(spec.get("tags") or []),
                )
                session.add(doc)
                await session.flush()
                for index, child in enumerate(spec.get("children") or []):
                    if isinstance(child, dict):
                        await create_node(child, node, default_tier=default_tier, sort_order=index)
                return node

            async def upsert_node(spec: dict[str, Any], parent: WikiNode, *, sort_order: int = 0) -> WikiNode:
                title = safe_segment(str(spec.get("title") or "未命名节点"), "未命名节点")
                result = await session.execute(
                    select(WikiNode).where(WikiNode.parent_id == parent.id, WikiNode.title == title)
                )
                node = result.scalar_one_or_none()
                if node is None:
                    node = await create_node(spec, parent, sort_order=sort_order)
                else:
                    node.path = f"{parent.path}/{title}".lstrip("/")
                    node.bid_types = list(spec.get("applicableTypes") or node.bid_types or ["通用"])
                    node.sort_order = sort_order
                    doc_result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == node.id))
                    doc = doc_result.scalar_one_or_none()
                    if doc is None:
                        session.add(
                            WikiDoc(
                                node_id=node.id,
                                markdown_content=str(spec.get("markdownContent") or f"# {title}\n"),
                                ai_summary="自动生成的 Wiki 初稿节点。",
                                tags=list(spec.get("tags") or []),
                            )
                        )
                    else:
                        doc.markdown_content = str(spec.get("markdownContent") or doc.markdown_content or f"# {title}\n")
                        doc.ai_summary = doc.ai_summary or "自动生成的 Wiki 初稿节点。"
                        doc.tags = list(spec.get("tags") or doc.tags or [])
                    await session.flush()
                    for child_index, child in enumerate(spec.get("children") or []):
                        if isinstance(child, dict):
                            await upsert_node(child, node, sort_order=child_index)
                return node

            root_spec = {
                "title": normalized_root_title,
                "markdownContent": root_markdown_content
                or f"# {normalized_root_title}\n\n这是系统自动生成的分标类 Wiki 根节点。",
                "tags": [self._bid_type_for_wiki_root(normalized_root_title), "素材库"],
                "applicableTypes": [self._bid_type_for_wiki_root(normalized_root_title)],
                "children": nodes,
            }

            existing_roots = (
                await session.execute(
                    select(WikiNode)
                    .where(WikiNode.parent_id.is_(None), WikiNode.title == normalized_root_title)
                    .order_by(desc(WikiNode.created_at), desc(WikiNode.id))
                )
            ).scalars().all()

            if normalized_mode == "replace":
                for root in existing_roots:
                    await purge_wiki_root(root)
                await purge_orphaned_platform_sections()
                root_node = await create_node(root_spec, None)
                message = f"{self._bid_type_for_wiki_root(normalized_root_title)} Wiki 已重新生成并覆盖。"
            elif existing_roots:
                root_node = existing_roots[0]
                for duplicate_root in existing_roots[1:]:
                    await purge_wiki_root(duplicate_root)
                await purge_orphaned_platform_sections()
                if normalized_mode == "update":
                    root_node.title = normalized_root_title
                    root_node.path = normalized_root_title
                    root_node.bid_types = list(root_spec["applicableTypes"])
                    doc_result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == root_node.id))
                    root_doc = doc_result.scalar_one_or_none()
                    if root_doc is None:
                        session.add(
                            WikiDoc(
                                node_id=root_node.id,
                                markdown_content=root_spec["markdownContent"],
                                ai_summary="自动生成的 Wiki 初稿节点。",
                                tags=list(root_spec["tags"]),
                            )
                        )
                    else:
                        root_doc.markdown_content = root_spec["markdownContent"]
                        root_doc.tags = list(root_spec["tags"])
                    for index, child in enumerate(nodes):
                        if isinstance(child, dict):
                            await upsert_node(child, root_node, sort_order=index)
                    message = f"{self._bid_type_for_wiki_root(normalized_root_title)} Wiki 已更新，并已清理重复根节点。"
                else:
                    message = f"{self._bid_type_for_wiki_root(normalized_root_title)} Wiki 已存在，已保留现有版本并清理重复根节点。"
            else:
                root_node = await create_node(root_spec, None)
                message = f"{self._bid_type_for_wiki_root(normalized_root_title)} Wiki 创建成功。"

            await session.commit()

        return {"message": message, "mode": normalized_mode, **await self.wiki_list(f"WIKI-{root_node.id:04d}")}

    # ------------------------------------------------------------------ #
    # Structured stubs (MVP compatible)
    # ------------------------------------------------------------------ #

    async def structured_update(self, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
        numeric_id = int(item_id.replace("MAT-", ""))
        async with async_session() as session:
            result = await session.execute(select(StructuredRow).where(StructuredRow.id == numeric_id))
            item = result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "素材不存在。", "STRUCTURED_MATERIAL_NOT_FOUND")
            if "rowData" in data:
                item.row_data = {**item.row_data, **data["rowData"]}
            await session.commit()
            return {"message": "Updated", "item": item.to_dict()}

    async def structured_import_preview(self, table: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        template = await self.structured_template(table)
        return {
            "table": template["table"],
            "file": {"name": str((payload or {}).get("fileName") or "待导入模板.xlsx")},
            "summary": {"totalRows": 2, "successCount": 2, "failCount": 0},
            "mapping": {"名称": "name", "值": "value", "备注": "remark"},
            "previewRows": [{"name": "样例A", "value": "值A", "remark": ""}, {"name": "样例B", "value": "值B", "remark": "备注"}],
            "errors": [],
            "canImport": True,
        }

    async def structured_confirm_import(self, table: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        preview = await self.structured_import_preview(table, payload)
        receipt = {
            "importId": "IMP-0001",
            "snapshotId": "SNAP-0001",
            "table": preview["table"],
            "fileName": preview["file"]["name"],
            "totalRows": preview["summary"]["totalRows"],
            "successCount": preview["summary"]["successCount"],
            "failCount": preview["summary"]["failCount"],
            "version": "2026.04",
            "operator": "当前用户",
            "importedAt": now_display(),
            "errors": [],
        }
        history = {
            "id": receipt["importId"],
            "status": "success",
            "desc": f"当前用户 导入{receipt['table']['label']} {receipt['successCount']} 行",
            "time": now_display(),
            "tableKey": receipt["table"]["key"],
            "tableLabel": receipt["table"]["label"],
            "successCount": receipt["successCount"],
            "failCount": receipt["failCount"],
            "errors": [],
        }
        return {"message": "Imported", "receipt": receipt, "historyItem": history}

    async def structured_import_excel(self) -> dict[str, Any]:
        return {"imported": 12, "failed": 0}

    async def raw_move_file(self, file_id: str, target_path: str, on_conflict: str = "") -> dict[str, Any]:
        numeric_id = int(file_id.replace("RAW-", ""))
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            item_result = await session.execute(
                select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
            )
            item = item_result.scalar_one_or_none()
            if item is None:
                raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")

            folder_result = await session.execute(select(RawFolder).where(RawFolder.path == target_path))
            destination = folder_result.scalar_one_or_none()
            if destination is None:
                raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")

            existing_result = await session.execute(
                select(RawFile)
                .where(
                    RawFile.folder_id == destination.id,
                    RawFile.name == item.name,
                    RawFile.id != item.id,
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing is not None and not on_conflict:
                raise PeripheralError(
                    409,
                    "目标路径存在同名文件",
                    "MATERIAL_CONFLICT",
                    {
                        "conflict": {
                            "path": destination.path,
                            "existingFileId": f"RAW-{existing.id:04d}",
                            "existingFileName": existing.name,
                            "allowedActions": ["overwrite", "version"],
                        }
                    },
                )

            if existing is not None and on_conflict == "overwrite":
                await self._purge_raw_file_objects(session, existing)
                await session.delete(existing)
            elif existing is not None and on_conflict == "version":
                version = int(existing.version or 1) + 1
                stem = PurePosixPath(item.name).stem
                suffix = PurePosixPath(item.name).suffix
                item.name = f"{stem}_v{version}{suffix}"
                item.version = version
                item.ext_fields = {**(item.ext_fields or {}), "lastAction": "version", "lastOperator": "当前用户"}
            else:
                item.ext_fields = {**(item.ext_fields or {}), "lastAction": "move", "lastOperator": "当前用户"}

            next_key = self._raw_object_key(destination.path, item.name)
            if item.minio_key and next_key != item.minio_key:
                minio_client.copy_object(item.minio_bucket, item.minio_key, next_key)
                minio_client.remove_object(item.minio_bucket, item.minio_key)

            item.folder_id = destination.id
            item.minio_key = next_key
            tier = self._infer_material_tier_from_folder(destination)
            item.ext_fields = {
                **(item.ext_fields or {}),
                "sourceMinioKey": next_key,
                "sourceFileName": item.name,
                "materialTier": tier,
                "materialTierLabel": MATERIAL_TIER_LABELS.get(tier, ""),
                "projectId": destination.project_id or (item.ext_fields or {}).get("projectId") or "",
                "customerName": destination.customer_name or (item.ext_fields or {}).get("customerName") or "",
                "bidType": destination.bid_type or (item.ext_fields or {}).get("bidType") or "",
            }
            await session.commit()

        async with async_session() as verify_session:
            refreshed = await verify_session.execute(
                select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
            )
            moved = refreshed.scalar_one()
            return {"message": "移动成功", "item": moved.to_dict()}


material_store = MaterialStore()
