from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_folder_scope import (
    is_raw_folder_move_descendant_target,
    is_raw_folder_move_protected_path,
)
from app.services.material_move_metadata import (
    RAW_MOVE_FILE_ACTION,
    RAW_MOVE_FILE_VERSION_ACTION,
    build_raw_move_file_ext_fields,
    build_raw_move_folder_file_ext_fields,
)
from app.services.material_raw_file_filter import raw_file_matches_bid_type, raw_folder_matches_bid_type
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
RawObjectKeyBuilder = Callable[[str, str], str]
RawFilePurger = Callable[[Any, RawFile], Awaitable[None]]
MaterialTierResolver = Callable[[RawFolder | None], str]
RawTreeLoader = Callable[[], Awaitable[dict[str, Any]]]


async def move_raw_file(
    *,
    file_id: str,
    target_path: str,
    bid_type: str,
    on_conflict: str = "",
    ensure_runtime_tables: EnsureRuntimeTables,
    raw_object_key: RawObjectKeyBuilder,
    purge_raw_file_objects: RawFilePurger,
    infer_material_tier_from_folder: MaterialTierResolver,
) -> dict[str, Any]:
    numeric_id = int(file_id.replace("RAW-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        item_result = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        item = item_result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        if not raw_file_matches_bid_type(item, bid_type):
            raise PeripheralError(400, "该文件不属于当前素材库。", "RAW_FILE_SCOPE")

        folder_result = await session.execute(select(RawFolder).where(RawFolder.path == target_path))
        destination = folder_result.scalar_one_or_none()
        if destination is None:
            raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
        if not raw_folder_matches_bid_type(destination, bid_type):
            raise PeripheralError(400, "目标目录不属于当前素材库。", "RAW_FOLDER_SCOPE")

        existing_result = await session.execute(
            select(RawFile).where(
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
            await purge_raw_file_objects(session, existing)
            await session.delete(existing)
            move_action = ""
        elif existing is not None and on_conflict == "version":
            version = int(existing.version or 1) + 1
            stem = PurePosixPath(item.name).stem
            suffix = PurePosixPath(item.name).suffix
            item.name = f"{stem}_v{version}{suffix}"
            item.version = version
            move_action = RAW_MOVE_FILE_VERSION_ACTION
        else:
            move_action = RAW_MOVE_FILE_ACTION

        next_key = raw_object_key(destination.path, item.name)
        if item.minio_key and next_key != item.minio_key:
            minio_client.copy_object(item.minio_bucket, item.minio_key, next_key)
            minio_client.remove_object(item.minio_bucket, item.minio_key)

        item.folder_id = destination.id
        item.minio_key = next_key
        tier = infer_material_tier_from_folder(destination)
        item.ext_fields = build_raw_move_file_ext_fields(
            item.ext_fields or {},
            source_minio_key=next_key,
            source_file_name=item.name,
            material_tier=tier,
            destination_bid_type=str(destination.bid_type or ""),
            folder_path=str(destination.path or ""),
            destination_project_id=str(destination.project_id or ""),
            destination_customer_name=str(destination.customer_name or ""),
            last_action=move_action,
        )
        await session.commit()

    async with async_session() as verify_session:
        refreshed = await verify_session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        moved = refreshed.scalar_one()
        return {"message": "移动成功", "item": moved.to_dict()}


async def move_raw_folder(
    *,
    source_path: str,
    target_parent_path: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    raw_object_key: RawObjectKeyBuilder,
    infer_material_tier_from_folder: MaterialTierResolver,
    raw_tree: RawTreeLoader,
) -> dict[str, Any]:
    source_path = str(source_path or "").strip().strip("/")
    target_parent_path = str(target_parent_path or "").strip().strip("/")
    if not source_path or not target_parent_path:
        raise PeripheralError(400, "源目录和目标目录不能为空。", "RAW_FOLDER_MOVE_PATH_REQUIRED")

    if is_raw_folder_move_protected_path(source_path):
        raise PeripheralError(400, "该基础目录不允许移动。", "RAW_FOLDER_MOVE_PROTECTED")
    if is_raw_folder_move_descendant_target(source_path, target_parent_path):
        raise PeripheralError(400, "不能将目录移动到自身或其子目录下。", "RAW_FOLDER_MOVE_DESCENDANT")

    async with async_session() as session:
        await ensure_runtime_tables(session)
        source_result = await session.execute(select(RawFolder).where(RawFolder.path == source_path))
        source = source_result.scalar_one_or_none()
        if source is None:
            raise PeripheralError(404, "源目录不存在。", "RAW_FOLDER_NOT_FOUND")
        if not raw_folder_matches_bid_type(source, bid_type):
            raise PeripheralError(400, "源目录不属于当前素材库。", "RAW_FOLDER_SCOPE")

        parent_result = await session.execute(select(RawFolder).where(RawFolder.path == target_parent_path))
        target_parent = parent_result.scalar_one_or_none()
        if target_parent is None:
            raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
        if not raw_folder_matches_bid_type(target_parent, bid_type):
            raise PeripheralError(400, "目标目录不属于当前素材库。", "RAW_FOLDER_SCOPE")

        next_root_path = f"{target_parent.path.rstrip('/')}/{source.name}"
        existing_result = await session.execute(select(RawFolder).where(RawFolder.path == next_root_path))
        if existing_result.scalar_one_or_none() is not None:
            raise PeripheralError(409, "目标目录下已存在同名文件夹。", "RAW_FOLDER_EXISTS")

        folder_result = await session.execute(
            select(RawFolder).where(or_(RawFolder.path == source.path, RawFolder.path.startswith(f"{source.path}/")))
        )
        folders = folder_result.scalars().all()
        folders_by_old_path = {folder.path: folder for folder in folders}
        files_result = await session.execute(
            select(RawFile)
            .join(RawFolder, RawFile.folder_id == RawFolder.id)
            .where(or_(RawFolder.path == source.path, RawFolder.path.startswith(f"{source.path}/")))
            .options(selectinload(RawFile.folder))
        )
        files = files_result.scalars().all()

        old_to_new_path: dict[str, str] = {}
        folder_id_to_new_path: dict[int, str] = {}
        for folder in folders:
            suffix = folder.path.removeprefix(source.path).lstrip("/")
            next_path = "/".join([part for part in [next_root_path, suffix] if part])
            old_to_new_path[folder.path] = next_path
            folder_id_to_new_path[int(folder.id)] = next_path

        source.parent_id = target_parent.id
        inherited_tier = infer_material_tier_from_folder(target_parent)
        for old_path, folder in folders_by_old_path.items():
            new_path = old_to_new_path[old_path]
            folder.path = new_path
            folder.tier = inherited_tier
            folder.bid_type = target_parent.bid_type or folder.bid_type
            folder.customer_name = target_parent.customer_name or folder.customer_name
            folder.project_id = target_parent.project_id or folder.project_id

        for item in files:
            old_key = item.minio_key
            new_folder_path = folder_id_to_new_path.get(int(item.folder_id))
            if not new_folder_path:
                continue
            next_key = raw_object_key(new_folder_path, item.name)
            if old_key and old_key != next_key:
                minio_client.copy_object(item.minio_bucket, old_key, next_key)
                minio_client.remove_object(item.minio_bucket, old_key)
            item.minio_key = next_key
            item.ext_fields = build_raw_move_folder_file_ext_fields(
                item.ext_fields or {},
                source_minio_key=next_key,
                source_file_name=item.name,
                material_tier=inherited_tier,
                destination_bid_type=str(target_parent.bid_type or ""),
                folder_path=new_folder_path,
                destination_project_id=str(target_parent.project_id or ""),
                destination_customer_name=str(target_parent.customer_name or ""),
            )

        await session.commit()
        tree = await raw_tree()
        return {
            "message": "文件夹移动成功",
            "sourcePath": source_path,
            "folderPath": next_root_path,
            "movedFileCount": len(files),
            "tree": tree["tree"],
        }
