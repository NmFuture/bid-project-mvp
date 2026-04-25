from __future__ import annotations

import base64
import copy
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import async_session
from app.models.materials import (
    AuditLog,
    RawFile,
    RawFileVersion,
    RawFolder,
    StructuredRow,
    StructuredTable,
    TemplateAsset,
    WikiAttachment,
    WikiDoc,
    WikiNode,
)
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError


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
        self._runtime_tables_ready = True

    @staticmethod
    def _raw_object_key(folder_path: str, file_name: str) -> str:
        return f"raw/{folder_path.strip('/')}/{file_name}"

    @staticmethod
    def _wiki_attachment_key(node_id: int, file_name: str) -> str:
        return f"wiki/{node_id}/{uuid4().hex}-{file_name}"

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
                {"pathPrefix": "标准模板", "actions": editable_actions},
                {"pathPrefix": "客户定制/*/通用材料", "actions": editable_actions},
                {"pathPrefix": "项目定制", "actions": editable_actions},
            ],
        }

    async def raw_tree(self) -> dict[str, Any]:
        async with async_session() as session:
            folders_result = await session.execute(select(RawFolder).order_by(RawFolder.sort_order))
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

            def build_node(folder: RawFolder) -> dict[str, Any]:
                child_folders = children_by_parent.get(folder.id, [])
                file_count = len(files_by_folder.get(folder.id, []))
                child_count = sum(len(files_by_folder.get(c.id, [])) for c in child_folders)
                return {
                    "id": folder.path,
                    "name": folder.name,
                    "path": folder.path,
                    "fileCount": file_count + child_count,
                    "children": [build_node(c) for c in child_folders],
                }

            roots = [f for f in all_folders if f.parent_id is None]
            return {"tree": [build_node(r) for r in roots], "updatedAt": now_display()}

    async def raw_files(
        self,
        *,
        folder_path: str = "",
        project_id: str = "",
        customer_name: str = "",
        bid_type: str = "",
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        async with async_session() as session:
            stmt = select(RawFile).options(selectinload(RawFile.folder))
            if folder_path:
                stmt = stmt.join(RawFolder).where(RawFolder.path == folder_path)
            if keyword:
                stmt = stmt.where(RawFile.name.ilike(f"%{keyword}%"))
            stmt = stmt.order_by(desc(RawFile.updated_at))
            result = await session.execute(stmt)
            items = result.scalars().all()

            # client-side filtering for ext_fields
            filtered = []
            for item in items:
                ext = item.ext_fields or {}
                if project_id and ext.get("projectId") != project_id:
                    continue
                if customer_name and customer_name not in str(ext.get("customerName") or ""):
                    continue
                if bid_type and ext.get("bidType") != bid_type:
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
        root_path = f"项目定制/{clean_id}/{bid_type or '技术标'}"

        async with async_session() as session:
            # Check if exists
            result = await session.execute(select(RawFolder).where(RawFolder.path == root_path))
            if result.scalar_one_or_none():
                return {"message": "项目目录骨架已存在。", "payload": {"projectId": clean_id, "path": root_path}}

            # Find or create parent chain
            project_root = f"项目定制/{clean_id}"
            parent = await self._ensure_folder_path(session, "项目定制", None, "project", None, None, 0)
            project_folder = await self._ensure_folder_path(session, clean_id, parent.id, "project", None, clean_id, 0)
            await self._ensure_folder_path(session, bid_type or "技术标", project_folder.id, "project", bid_type, clean_id, 0)
            await session.commit()

        return {"message": "项目目录骨架初始化完成。", "payload": {"projectId": clean_id, "path": root_path}}

    async def _ensure_folder_path(
        self,
        session: Any,
        name: str,
        parent_id: int | None,
        tier: str,
        bid_type: str | None,
        project_id: str | None,
        sort_order: int,
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
        bid_type: str = "技术标",
        on_conflict: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        file_inputs = list(files or [])
        if not file_inputs:
            raise PeripheralError(400, "请至少上传一个文件。", "RAW_UPLOAD_FILES_REQUIRED")
        if not target_path:
            if not project_id:
                raise PeripheralError(400, "请提供目标目录或项目 ID。", "RAW_TARGET_PATH_REQUIRED")
            target_path = f"项目定制/{safe_segment(project_id, 'PRJ-UNSET')}/{bid_type or '技术标'}"

        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            result = await session.execute(select(RawFolder).where(RawFolder.path == target_path))
            base_folder = result.scalar_one_or_none()
            if base_folder is None:
                raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")

            uploaded_items: list[dict[str, Any]] = []
            for item in file_inputs:
                relative_path = str(item.get("relativePath") or "").replace("\\", "/").strip("/")
                relative_parts = [part for part in relative_path.split("/") if part]
                relative_dir = "/".join(relative_parts[:-1]) if len(relative_parts) > 1 else ""

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
                    upload_to_minio()
                    existing.size_bytes = size
                    existing.minio_key = minio_key
                    existing.mime_type = mime_type
                    existing.version += 1
                    ext = existing.ext_fields or {}
                    ext["lastAction"] = on_conflict
                    ext["lastOperator"] = "当前用户"
                    existing.ext_fields = ext
                    uploaded_items.append(existing.to_dict())
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
                        "bidType": bid_type or "技术标",
                        "projectId": project_id,
                        "customerName": "测试业主" if project_id else "通用",
                        "lastAction": "upload",
                        "lastOperator": "当前用户",
                    },
                )
                session.add(record)
                await session.flush()
                uploaded_items.append(record.to_dict())

            await session.commit()
            return {"message": f"上传完成，共处理 {len(uploaded_items)} 个文件。", "items": uploaded_items}

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
            item.ext_fields = {**(item.ext_fields or {}), "lastAction": "rename"}
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

    async def wiki_list(self, node_id: str = "") -> dict[str, Any]:
        async with async_session() as session:
            await self._ensure_runtime_tables(session)
            nodes_result = await session.execute(select(WikiNode).order_by(WikiNode.sort_order, WikiNode.id))
            all_nodes = nodes_result.scalars().all()

            children_by_parent: dict[int, list[WikiNode]] = {}
            for n in all_nodes:
                if n.parent_id is not None:
                    children_by_parent.setdefault(n.parent_id, []).append(n)

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

            roots = [n for n in all_nodes if n.parent_id is None]
            tree = [build_node(r) for r in roots]

            selected = None
            if node_id:
                numeric_id = int(node_id.replace("WIKI-", ""))
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

            return {
                "tree": tree,
                "selectedNode": selected,
                "tagOptions": ["风资源", "技术标", "商务标", "通用材料"],
                "applicableTypeOptions": ["技术标", "商务标", "通用"],
            }

    async def wiki_create(self, parent_id: str, title: str, is_folder: bool) -> dict[str, Any]:
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
                bid_types=parent.bid_types if parent else ["通用"],
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

            return {"message": "Created", **await self.wiki_list(f"WIKI-{node.id:04d}")}

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
            return {"message": "Updated", **await self.wiki_list(node_id)}

    async def wiki_refresh_summary(self, node_id: str) -> dict[str, Any]:
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
            return {"summary": summary, **await self.wiki_list(node_id)}

    async def wiki_move(self, node_id: str, target_id: str, mode: str) -> dict[str, Any]:
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
            return {"message": "Moved", **await self.wiki_list(node_id)}

    async def wiki_upload_attachment(
        self,
        node_id: str,
        file_name: str,
        file_size: Any,
        *,
        upload: Any | None = None,
        data: bytes | None = None,
        mime_type: str = "",
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

        return {"message": "Uploaded", **await self.wiki_list(node_id)}

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
                "markdownContent": f"# {normalized_root_title}\n\n这是系统自动生成的平台级 Wiki 根节点。",
                "tags": ["通用材料"],
                "applicableTypes": ["通用"],
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
                message = "平台级 Wiki 已重新生成并覆盖。"
            elif existing_roots:
                root_node = existing_roots[0]
                for duplicate_root in existing_roots[1:]:
                    await purge_wiki_root(duplicate_root)
                await purge_orphaned_platform_sections()
                if normalized_mode == "update":
                    root_node.title = normalized_root_title
                    root_node.path = normalized_root_title
                    root_node.bid_types = ["通用"]
                    doc_result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == root_node.id))
                    root_doc = doc_result.scalar_one_or_none()
                    if root_doc is None:
                        session.add(
                            WikiDoc(
                                node_id=root_node.id,
                                markdown_content=root_spec["markdownContent"],
                                ai_summary="自动生成的 Wiki 初稿节点。",
                                tags=["通用材料"],
                            )
                        )
                    else:
                        root_doc.markdown_content = root_spec["markdownContent"]
                        root_doc.tags = ["通用材料"]
                    for index, child in enumerate(nodes):
                        if isinstance(child, dict):
                            await upsert_node(child, root_node, sort_order=index)
                    message = "平台级 Wiki 已更新，并已清理重复根节点。"
                else:
                    message = "平台级 Wiki 已存在，已保留现有版本并清理重复根节点。"
            else:
                root_node = await create_node(root_spec, None)
                message = "平台级 Wiki 创建成功。"

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
            await session.commit()

        async with async_session() as verify_session:
            refreshed = await verify_session.execute(
                select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
            )
            moved = refreshed.scalar_one()
            return {"message": "移动成功", "item": moved.to_dict()}


material_store = MaterialStore()
