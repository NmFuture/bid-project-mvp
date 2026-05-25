from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.models.materials import RawFile, RawFolder
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.material_folder_scope import (
    business_customized_child_tier_for_parent_folder_path,
    business_customized_subfolder_specs,
    business_customized_tier_from_folder_path,
    business_standard_subfolder_specs,
    canonical_raw_folder_metadata,
    material_bid_type_sort_order,
    material_tier_folder_name,
    material_tier_folder_sort_order,
    material_tier_root_path,
    normalize_material_bid_type,
    normalize_material_tier,
)
from app.services.material_taxonomy import canonical_technical_material_path
from app.services.peripheral import PeripheralError


EnsureFolderPath = Callable[..., Awaitable[RawFolder]]
FindFolder = Callable[[Any, str], Awaitable[RawFolder | None]]
EnsureCanonicalFolder = Callable[[Any, str], Awaitable[RawFolder]]
ClearDefaultFolderDeletion = Callable[[Any, str], Awaitable[None]]


def safe_folder_segment(value: Any, fallback: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    text = "/".join(part.strip() for part in text.split("/") if part.strip())
    return text or fallback


async def ensure_material_target_folder(
    session: Any,
    *,
    material_tier: str,
    bid_type: str,
    customer_name: str = "",
    project_id: str = "",
    ensure_folder_path: EnsureFolderPath,
    clear_default_folder_deletion: ClearDefaultFolderDeletion,
) -> RawFolder:
    tier = normalize_material_tier(material_tier) or "project"
    normalized_bid_type = normalize_material_bid_type(bid_type)
    root_folder = await ensure_folder_path(
        session,
        normalized_bid_type,
        None,
        "standard",
        normalized_bid_type,
        None,
        material_bid_type_sort_order(normalized_bid_type),
    )

    if tier == "standard":
        await clear_default_folder_deletion(session, material_tier_root_path(normalized_bid_type, "standard"))
        base_folder = await ensure_folder_path(
            session,
            material_tier_folder_name("standard"),
            root_folder.id,
            "standard",
            normalized_bid_type,
            None,
            material_tier_folder_sort_order("standard"),
            customer_name="平台标准",
        )
        if normalized_bid_type == BUSINESS_BID_TYPE:
            await ensure_business_standard_subfolders(
                session,
                base_folder,
                ensure_folder_path=ensure_folder_path,
            )
        return base_folder

    if tier == "customer":
        clean_customer = safe_folder_segment(customer_name, "")
        if not clean_customer:
            raise PeripheralError(400, "客户素材必须填写客户名称。", "CUSTOMER_NAME_REQUIRED")
        await clear_default_folder_deletion(session, material_tier_root_path(normalized_bid_type, "customer"))
        root = await ensure_folder_path(
            session,
            material_tier_folder_name("customer"),
            root_folder.id,
            "customer",
            normalized_bid_type,
            None,
            material_tier_folder_sort_order("customer"),
        )
        customer = await ensure_folder_path(
            session,
            clean_customer,
            root.id,
            "customer",
            normalized_bid_type,
            None,
            0,
            customer_name=clean_customer,
        )
        if normalized_bid_type == BUSINESS_BID_TYPE:
            await ensure_business_customized_subfolders(
                session,
                customer,
                tier="customer",
                ensure_folder_path=ensure_folder_path,
            )
        return customer

    clean_project_id = safe_folder_segment(project_id, "")
    if not clean_project_id:
        raise PeripheralError(400, "项目素材必须填写项目 ID。", "PROJECT_ID_REQUIRED")
    await clear_default_folder_deletion(session, material_tier_root_path(normalized_bid_type, "project"))
    root = await ensure_folder_path(
        session,
        material_tier_folder_name("project"),
        root_folder.id,
        "project",
        normalized_bid_type,
        None,
        material_tier_folder_sort_order("project"),
    )
    project_folder = await ensure_folder_path(
        session,
        clean_project_id,
        root.id,
        "project",
        normalized_bid_type,
        clean_project_id,
        0,
    )
    if normalized_bid_type == BUSINESS_BID_TYPE:
        await ensure_business_customized_subfolders(
            session,
            project_folder,
            tier="project",
            ensure_folder_path=ensure_folder_path,
        )
    return project_folder


async def bootstrap_project_material_folder(
    session: Any,
    *,
    project_id: str,
    bid_type: str,
    find_folder: FindFolder,
    ensure_folder_path: EnsureFolderPath,
) -> dict[str, Any]:
    clean_id = safe_folder_segment(project_id, "")
    if not clean_id:
        raise PeripheralError(400, "projectId 不能为空。", "PROJECT_ID_REQUIRED")
    normalized_bid_type = normalize_material_bid_type(bid_type)
    root_path = f"{material_tier_root_path(normalized_bid_type, 'project')}/{clean_id}"

    if await find_folder(session, root_path):
        return {"message": "项目目录骨架已存在。", "payload": {"projectId": clean_id, "path": root_path}}

    parent = await find_folder(session, material_tier_root_path(normalized_bid_type, "project"))
    if parent is None:
        root_folder = await ensure_folder_path(
            session,
            normalized_bid_type,
            None,
            "standard",
            normalized_bid_type,
            None,
            material_bid_type_sort_order(normalized_bid_type),
        )
        parent = await ensure_folder_path(
            session,
            material_tier_folder_name("project"),
            root_folder.id,
            "project",
            normalized_bid_type,
            None,
            material_tier_folder_sort_order("project"),
        )
    project_folder = await ensure_folder_path(session, clean_id, parent.id, "project", normalized_bid_type, clean_id, 0)
    if normalized_bid_type == BUSINESS_BID_TYPE:
        await ensure_business_customized_subfolders(
            session,
            project_folder,
            tier="project",
            ensure_folder_path=ensure_folder_path,
        )
    return {"message": "项目目录骨架初始化完成。", "payload": {"projectId": clean_id, "path": root_path}}


async def ensure_business_standard_subfolders(
    session: Any,
    standard_root: RawFolder,
    *,
    ensure_folder_path: EnsureFolderPath,
) -> None:
    for spec in business_standard_subfolder_specs(standard_root.customer_name):
        folder = await ensure_folder_path(
            session,
            str(spec["name"]),
            standard_root.id,
            str(spec["tier"]),
            str(spec["bidType"]),
            spec.get("projectId"),
            int(spec["sortOrder"]),
            customer_name=spec.get("customerName"),
        )
        for child in spec.get("children") or ():
            await ensure_folder_path(
                session,
                str(child["name"]),
                folder.id,
                str(child["tier"]),
                str(child["bidType"]),
                child.get("projectId"),
                int(child["sortOrder"]),
                customer_name=child.get("customerName"),
            )


async def ensure_business_customized_subfolders(
    session: Any,
    base_folder: RawFolder,
    *,
    tier: str,
    ensure_folder_path: EnsureFolderPath,
) -> None:
    for spec in business_customized_subfolder_specs(
        tier=tier,
        project_id=base_folder.project_id,
        customer_name=base_folder.customer_name,
    ):
        await ensure_folder_path(
            session,
            str(spec["name"]),
            base_folder.id,
            str(spec["tier"]),
            str(spec["bidType"]),
            spec.get("projectId"),
            int(spec["sortOrder"]),
            customer_name=spec.get("customerName"),
        )


async def ensure_business_customized_children_for_created_folder(
    session: Any,
    folder: RawFolder,
    *,
    parent_path: str = "",
    ensure_folder_path: EnsureFolderPath,
) -> None:
    customized_tier = business_customized_child_tier_for_parent_folder_path(parent_path)
    if not customized_tier:
        return
    await ensure_business_customized_subfolders(
        session,
        folder,
        tier=customized_tier,
        ensure_folder_path=ensure_folder_path,
    )


async def backfill_existing_business_customized_subfolders(
    session: Any,
    *,
    ensure_folder_path: EnsureFolderPath,
) -> None:
    folders = (
        await session.execute(select(RawFolder).where(RawFolder.path.like(f"{BUSINESS_BID_TYPE}/%")))
    ).scalars().all()
    for folder in folders:
        tier = business_customized_tier_from_folder_path(str(folder.path or ""))
        if not tier:
            continue
        await ensure_business_customized_subfolders(
            session,
            folder,
            tier=tier,
            ensure_folder_path=ensure_folder_path,
        )


async def migrate_legacy_technical_folders(
    session: Any,
    *,
    find_folder: FindFolder,
    ensure_canonical_folder: EnsureCanonicalFolder,
) -> None:
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
        target = await find_folder(session, new_path)
        if target is not None and target.id != folder.id:
            files = (await session.execute(select(RawFile).where(RawFile.folder_id == folder.id))).scalars().all()
            for item in files:
                item.folder_id = target.id
            continue

        parent_path = "/".join(new_path.split("/")[:-1])
        parent = await ensure_canonical_folder(session, parent_path) if parent_path else None
        metadata = canonical_raw_folder_metadata(new_path)
        folder.parent_id = parent.id if parent else None
        folder.name = str(metadata["name"])
        folder.path = new_path
        folder.tier = str(metadata.get("tier") or folder.tier)
        folder.bid_type = str(metadata.get("bidType") or folder.bid_type or "")
        folder.customer_name = str(metadata.get("customerName") or folder.customer_name or "") or None
        folder.project_id = str(metadata.get("projectId") or folder.project_id or "") or None

    for folder in sorted(legacy_folders, key=lambda item: len(str(item.path or "").split("/")), reverse=True):
        fresh = await session.get(RawFolder, folder.id)
        if fresh is None:
            continue
        has_files = bool((await session.execute(select(RawFile.id).where(RawFile.folder_id == fresh.id))).first())
        has_children = bool((await session.execute(select(RawFolder.id).where(RawFolder.parent_id == fresh.id))).first())
        if not has_files and not has_children and not str(fresh.path or "").startswith(("技术标", "商务标")):
            await session.delete(fresh)
