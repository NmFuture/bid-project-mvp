from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.models import async_session
from app.models.materials import RawFolder, RawFolderDeletion
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.material_folder_maintenance import (
    backfill_existing_business_customized_subfolders,
    bootstrap_project_material_folder,
    ensure_business_standard_subfolders,
    migrate_legacy_technical_folders,
    prune_empty_legacy_business_default_folders,
)
from app.services.material_folder_scope import (
    canonical_raw_folder_metadata,
    raw_material_root_specs,
    raw_material_tier_folder_specs,
)
from app.services.material_taxonomy import RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]


def _safe_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _can_skip_default_folder(child_path: str, deleted_default_paths: set[str]) -> bool:
    normalized = str(child_path or "").replace("\\", "/").strip("/")
    if normalized.startswith(f"{BUSINESS_BID_TYPE}/"):
        return False
    return normalized in deleted_default_paths


class RawFolderOperations:
    def __init__(self, *, ensure_runtime_tables: EnsureRuntimeTables) -> None:
        self._ensure_runtime_tables = ensure_runtime_tables

    async def raw_bootstrap_folders(
        self,
        *,
        project_id: str,
        bid_type: str,
        session_factory: Any = async_session,
    ) -> dict[str, Any]:
        async with session_factory() as session:
            await self.ensure_raw_material_roots(session)
            result = await bootstrap_project_material_folder(
                session,
                project_id=project_id,
                bid_type=bid_type,
                find_folder=self.find_folder,
                ensure_folder_path=self.ensure_folder_path,
            )
            await session.commit()
            return result

    async def ensure_raw_material_roots(self, session: Any) -> list[RawFolder]:
        await self._ensure_runtime_tables(session)
        roots: list[RawFolder] = []
        deleted_default_paths = await self.deleted_default_folder_paths(session)
        for spec in raw_material_root_specs():
            root = await self.ensure_folder_path(
                session,
                str(spec["name"]),
                None,
                str(spec["tier"]),
                str(spec.get("bid_type") or "") or None,
                None,
                int(spec["sort_order"]),
            )
            roots.append(root)
            bid_type = str(spec["name"])
            for child in raw_material_tier_folder_specs(bid_type):
                child_path = f"{bid_type}/{child['name']}"
                if _can_skip_default_folder(child_path, deleted_default_paths):
                    continue
                await self.ensure_folder_path(
                    session,
                    str(child["name"]),
                    root.id,
                    str(child["tier"]),
                    bid_type,
                    None,
                    int(child["sort_order"]),
                    customer_name=str(child.get("customer_name") or "") or None,
                )
            if bid_type == BUSINESS_BID_TYPE:
                standard_root = await self.find_folder(session, f"{bid_type}/通用素材")
                if standard_root is not None:
                    await ensure_business_standard_subfolders(
                        session,
                        standard_root,
                        ensure_folder_path=self.ensure_folder_path,
                    )
                await backfill_existing_business_customized_subfolders(
                    session,
                    ensure_folder_path=self.ensure_folder_path,
                )
                await prune_empty_legacy_business_default_folders(session)
        await migrate_legacy_technical_folders(
            session,
            find_folder=self.find_folder,
            ensure_canonical_folder=self.ensure_canonical_folder,
        )
        return roots

    async def deleted_default_folder_paths(self, session: Any) -> set[str]:
        result = await session.execute(select(RawFolderDeletion.path))
        return {
            str(path or "").strip("/")
            for path in result.scalars().all()
            if str(path or "").strip("/") in RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS
        }

    async def mark_default_folder_deleted(self, session: Any, folder_path: str) -> None:
        normalized = str(folder_path or "").replace("\\", "/").strip("/")
        if normalized not in RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS:
            return
        existing = await session.get(RawFolderDeletion, normalized)
        if existing is not None:
            return
        session.add(RawFolderDeletion(path=normalized, created_by="当前用户"))
        await session.flush()

    async def clear_default_folder_deletion(self, session: Any, folder_path: str) -> None:
        normalized = str(folder_path or "").replace("\\", "/").strip("/")
        if normalized not in RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS:
            return
        existing = await session.get(RawFolderDeletion, normalized)
        if existing is not None:
            await session.delete(existing)
            await session.flush()

    async def find_folder(self, session: Any, folder_path: str) -> RawFolder | None:
        result = await session.execute(select(RawFolder).where(RawFolder.path == folder_path))
        return result.scalar_one_or_none()

    async def ensure_canonical_folder(self, session: Any, folder_path: str) -> RawFolder:
        normalized = str(folder_path or "").strip().strip("/")
        existing = await self.find_folder(session, normalized)
        if existing is not None:
            return existing
        parent = None
        parent_path = "/".join(normalized.split("/")[:-1])
        if parent_path:
            parent = await self.ensure_canonical_folder(session, parent_path)
        metadata = canonical_raw_folder_metadata(normalized)
        return await self.ensure_folder_path(
            session,
            str(metadata["name"]),
            parent.id if parent else None,
            str(metadata["tier"]),
            str(metadata["bidType"]),
            metadata.get("projectId"),
            int(metadata["sortOrder"]),
            customer_name=metadata.get("customerName"),
        )

    async def ensure_folder_path(
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
        parent_path = ""
        if parent_id:
            parent = await session.get(RawFolder, parent_id)
            parent_path = str(parent.path or "")
        path = f"{parent_path}/{name}".lstrip("/")
        await self.clear_default_folder_deletion(session, path)
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

    async def ensure_nested_folder(
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
            segment = _safe_segment(raw_segment, "")
            if not segment:
                continue
            current = await self.ensure_folder_path(
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
