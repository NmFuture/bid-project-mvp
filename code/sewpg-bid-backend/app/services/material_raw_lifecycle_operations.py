from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.material_folder_scope import (
    material_bid_type_sort_order,
    material_tier_folder_name_for_bid_type,
    material_tier_folder_sort_order,
    material_tier_root_path,
)
from app.services.material_folder_maintenance import ensure_business_customized_children_for_created_folder
from app.services.material_raw_file_filter import raw_file_matches_bid_type, raw_folder_matches_bid_type
from app.services.material_raw_folder_lock import lock_raw_folder_path
from app.services.material_taxonomy import is_raw_material_protected_folder_path, normalize_material_tier
from app.services.peripheral import PeripheralError


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
EnsureFolderPath = Callable[..., Awaitable[RawFolder]]
RawFilePurger = Callable[[Any, RawFile], Awaitable[None]]
MarkDefaultFolderDeleted = Callable[[Any, str], Awaitable[None]]
RawTreeLoader = Callable[[], Awaitable[dict[str, Any]]]


def _safe_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


async def create_raw_folder(
    *,
    parent_path: str,
    folder_name: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    ensure_folder_path: EnsureFolderPath,
    raw_tree: RawTreeLoader,
) -> dict[str, Any]:
    name = _safe_segment(folder_name, "")
    if not name:
        raise PeripheralError(400, "文件夹名称不能为空。", "RAW_FOLDER_NAME_REQUIRED")

    async with async_session() as session:
        await ensure_runtime_tables(session)
        parent_path_text = str(parent_path or "")
        result = await session.execute(select(RawFolder).where(RawFolder.path == parent_path_text))
        parent = result.scalar_one_or_none()
        if (
            parent is None
            and bid_type == TECHNICAL_BID_TYPE
            and parent_path_text == material_tier_root_path(TECHNICAL_BID_TYPE, "standard")
        ):
            root = await ensure_folder_path(
                session,
                TECHNICAL_BID_TYPE,
                None,
                "standard",
                TECHNICAL_BID_TYPE,
                None,
                material_bid_type_sort_order(TECHNICAL_BID_TYPE),
            )
            parent = await ensure_folder_path(
                session,
                material_tier_folder_name_for_bid_type(TECHNICAL_BID_TYPE, "standard"),
                root.id,
                "standard",
                TECHNICAL_BID_TYPE,
                None,
                material_tier_folder_sort_order("standard"),
                customer_name="平台标准",
            )
        if parent is None or not raw_folder_matches_bid_type(parent, bid_type):
            raise PeripheralError(400, "父级目录不属于当前素材库。", "RAW_FOLDER_SCOPE")
        parent_id = parent.id if parent else None
        full_path = "/".join([p for p in [parent_path_text.strip("/"), name] if p])

        result2 = await session.execute(select(RawFolder).where(RawFolder.path == full_path))
        existing = result2.scalar_one_or_none()
        if existing is not None:
            if parent_path_text == TECHNICAL_BID_TYPE:
                # 技术标根级只允许建三个档位目录（store 层已校验），预置后重复创建按幂等返回
                tree = await raw_tree()
                return {"message": "文件夹已存在，沿用现有目录。", "folderPath": full_path, "tree": tree["tree"]}
            raise PeripheralError(409, "目录已存在。", "RAW_FOLDER_EXISTS")

        await lock_raw_folder_path(session, full_path)
        result2 = await session.execute(select(RawFolder).where(RawFolder.path == full_path))
        if result2.scalar_one_or_none():
            raise PeripheralError(409, "目录已存在。", "RAW_FOLDER_EXISTS")

        folder = RawFolder(
            parent_id=parent_id,
            name=name,
            path=full_path,
            # 技术标根级只能建三个档位目录，tier 由目录名决定而不是继承根目录
            tier=(
                normalize_material_tier(name)
                if parent_path_text == TECHNICAL_BID_TYPE
                else ""
            )
            or (parent.tier if parent else "project"),
            bid_type=parent.bid_type if parent else None,
            customer_name=parent.customer_name if parent else None,
            project_id=parent.project_id if parent else None,
        )
        session.add(folder)
        await session.flush()
        await ensure_business_customized_children_for_created_folder(
            session,
            folder,
            parent_path=parent.path if parent else "",
            ensure_folder_path=ensure_folder_path,
        )
        await session.commit()

        tree = await raw_tree()
        return {"message": "文件夹创建成功。", "folderPath": full_path, "tree": tree["tree"]}


async def delete_raw_folder(
    *,
    path: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    purge_raw_file_objects: RawFilePurger,
    mark_default_folder_deleted: MarkDefaultFolderDeleted,
    raw_tree: RawTreeLoader,
    allow_protected: bool = False,
    expected_project_id: str = "",
) -> dict[str, Any]:
    folder_path = str(path or "").strip().strip("/")
    if not folder_path:
        raise PeripheralError(400, "path 不能为空。", "RAW_FOLDER_PATH_REQUIRED")
    if is_raw_material_protected_folder_path(folder_path) and not allow_protected:
        raise PeripheralError(400, "基础素材目录不允许删除。", "RAW_FOLDER_DELETE_PROTECTED")
    async with async_session() as session:
        await ensure_runtime_tables(session)
        clean_expected_project_id = str(expected_project_id or "").strip()
        if clean_expected_project_id:
            result = await session.execute(
                select(RawFolder).where(
                    RawFolder.project_id == clean_expected_project_id,
                    RawFolder.bid_type == bid_type,
                    RawFolder.tier == "project",
                )
            )
            folder = next(
                (
                    candidate
                    for candidate in result.scalars().all()
                    if len(str(candidate.path or "").strip("/").split("/")) == 3
                ),
                None,
            )
        else:
            result = await session.execute(select(RawFolder).where(RawFolder.path == folder_path))
            folder = result.scalar_one_or_none()
        if folder is None:
            raise PeripheralError(404, "目录不存在。", "RAW_FOLDER_NOT_FOUND")
        if not raw_folder_matches_bid_type(folder, bid_type):
            raise PeripheralError(400, "目录不属于当前素材库。", "RAW_FOLDER_SCOPE")
        folder_project_id = str(folder.project_id or "").strip()
        if clean_expected_project_id and folder_project_id != clean_expected_project_id:
            raise PeripheralError(
                409,
                "项目素材目录归属与待删除项目不一致。",
                "PROJECT_FOLDER_OWNERSHIP_MISMATCH",
            )
        folder_path = str(folder.path or "").strip().strip("/")

        descendant_result = await session.execute(
            select(RawFolder).where(or_(RawFolder.path == folder.path, RawFolder.path.startswith(f"{folder.path}/")))
        )
        folders = descendant_result.scalars().all()
        folder_ids = [folder.id for folder in folders]
        files_result = await session.execute(
            select(RawFile).where(RawFile.folder_id.in_(folder_ids)).options(selectinload(RawFile.folder))
        )
        files = files_result.scalars().all()
        for item in files:
            await purge_raw_file_objects(session, item)
            await session.delete(item)

        for descendant in sorted(folders, key=lambda entry: len(str(entry.path or "").split("/")), reverse=True):
            await session.delete(descendant)
        await mark_default_folder_deleted(session, folder_path)
        await session.commit()

        tree = await raw_tree()
        return {
            "message": f"文件夹删除成功，共删除 {len(files)} 个素材文件。",
            "folderPath": folder_path,
            "deletedFileCount": len(files),
            "tree": tree["tree"],
        }


async def delete_raw_file(
    *,
    file_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    purge_raw_file_objects: RawFilePurger,
) -> dict[str, Any]:
    numeric_id = int(file_id.replace("RAW-", ""))
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
        payload = item.to_dict()
        await purge_raw_file_objects(session, item)
        await session.delete(item)
        await session.commit()
        return {"message": "删除成功", "item": payload}
