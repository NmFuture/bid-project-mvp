from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_folder_scope import (
    is_raw_folder_move_descendant_target,
    is_raw_folder_move_protected_path,
    is_raw_folder_rename_protected_path,
)
from app.services.material_move_metadata import (
    RAW_MOVE_FILE_ACTION,
    RAW_MOVE_FILE_VERSION_ACTION,
    RAW_MOVE_FOLDER_ACTION,
    RAW_RENAME_FOLDER_ACTION,
    build_raw_move_file_ext_fields,
    build_raw_move_folder_file_ext_fields,
)
from app.services.material_raw_file_filter import raw_file_matches_bid_type, raw_folder_matches_bid_type
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError

logger = logging.getLogger(__name__)


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
        # 先 copy 到新 key（不删源）；DB commit 成功后再删旧源对象，避免"删源后 commit 失败"丢文件（H3）
        stale_source_key = ""
        if item.minio_key and next_key != item.minio_key:
            minio_client.copy_object(item.minio_bucket, item.minio_key, next_key)
            stale_source_key = item.minio_key

        item.folder_id = destination.id
        source_bucket = item.minio_bucket
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
        # commit 后立即取一份快照作为兜底，避免二次读时被并发删除导致误报失败（L2）
        await session.refresh(item, attribute_names=["folder"])
        committed_payload = item.to_dict()

    # commit 成功后再删旧源对象；删除失败只告警（残留源对象可接受，丢文件不可接受）（H3）
    if stale_source_key:
        try:
            minio_client.remove_object(source_bucket, stale_source_key)
        except Exception as cleanup_exc:  # pragma: no cover - 源对象清理失败仅告警
            logger.warning("移动文件后清理旧源对象 %s/%s 失败：%s", source_bucket, stale_source_key, cleanup_exc)

    async with async_session() as verify_session:
        refreshed = await verify_session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        # miss（并发删除）时返回已提交快照，不把已成功的移动误报为异常（L2）
        moved = refreshed.scalar_one_or_none()
        payload = moved.to_dict() if moved is not None else committed_payload
        return {"message": "移动成功", "item": payload}


# 文件夹名称不允许出现的字符（与创建目录 _safe_segment 的清洗口径一致）
RAW_FOLDER_NAME_ILLEGAL_CHARS = re.compile(r"[\\/:*?\"<>|]")


async def _relocate_folder_subtree(
    session: Any,
    *,
    source: RawFolder,
    target_parent: RawFolder,
    next_root_path: str,
    raw_object_key: RawObjectKeyBuilder,
    infer_material_tier_from_folder: MaterialTierResolver,
    rename: bool = False,
) -> int:
    """把 source 子树整体改写到 next_root_path 下（移动或同父级重命名共用）。

    rename=True 时保持 parent_id 与 tier/bid_type/customer/project 等继承属性不变，
    仅改写 name 与子树 path；其余流程（冲突校验、minio key 迁移、ext_fields 审计）一致。
    """
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

    inherited_tier = infer_material_tier_from_folder(target_parent)
    metadata_anchor = source if rename else target_parent
    if rename:
        source.name = next_root_path.rsplit("/", 1)[-1]
    else:
        source.parent_id = target_parent.id
    for old_path, folder in folders_by_old_path.items():
        new_path = old_to_new_path[old_path]
        folder.path = new_path
        if rename:
            continue
        folder.tier = inherited_tier
        folder.bid_type = target_parent.bid_type or folder.bid_type
        folder.customer_name = target_parent.customer_name or folder.customer_name
        folder.project_id = target_parent.project_id or folder.project_id

    # 先把所有对象 copy 到新 key（不删源）并收集待删旧 key；commit 成功后再统一删源（H3）
    stale_source_keys: list[tuple[str, str]] = []
    for item in files:
        old_key = item.minio_key
        new_folder_path = folder_id_to_new_path.get(int(item.folder_id))
        if not new_folder_path:
            continue
        next_key = raw_object_key(new_folder_path, item.name)
        if old_key and old_key != next_key:
            minio_client.copy_object(item.minio_bucket, old_key, next_key)
            stale_source_keys.append((item.minio_bucket, old_key))
        item.minio_key = next_key
        item.ext_fields = build_raw_move_folder_file_ext_fields(
            item.ext_fields or {},
            source_minio_key=next_key,
            source_file_name=item.name,
            material_tier=(
                infer_material_tier_from_folder(getattr(item, "folder", None) or source) if rename else inherited_tier
            ),
            destination_bid_type=str(metadata_anchor.bid_type or ""),
            folder_path=new_folder_path,
            destination_project_id=str(metadata_anchor.project_id or ""),
            destination_customer_name=str(metadata_anchor.customer_name or ""),
            last_action=RAW_RENAME_FOLDER_ACTION if rename else RAW_MOVE_FOLDER_ACTION,
        )

    await session.commit()

    # commit 成功后再逐个删旧源对象；单个失败只告警，不影响整体成功（H3）
    for bucket, old_key in stale_source_keys:
        try:
            minio_client.remove_object(bucket, old_key)
        except Exception as cleanup_exc:  # pragma: no cover - 源对象清理失败仅告警
            logger.warning("移动文件夹后清理旧源对象 %s/%s 失败：%s", bucket, old_key, cleanup_exc)
    return len(files)


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
        moved_count = await _relocate_folder_subtree(
            session,
            source=source,
            target_parent=target_parent,
            next_root_path=next_root_path,
            raw_object_key=raw_object_key,
            infer_material_tier_from_folder=infer_material_tier_from_folder,
        )

    tree = await raw_tree()
    return {
        "message": "文件夹移动成功",
        "sourcePath": source_path,
        "folderPath": next_root_path,
        "movedFileCount": moved_count,
        "tree": tree["tree"],
    }


async def rename_raw_folder(
    *,
    path: str,
    new_name: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    raw_object_key: RawObjectKeyBuilder,
    infer_material_tier_from_folder: MaterialTierResolver,
    raw_tree: RawTreeLoader,
) -> dict[str, Any]:
    """同父级重命名文件夹：复用移动的子树路径改写与级联更新，不改变父级与继承属性。"""
    folder_path = str(path or "").strip().strip("/")
    name = str(new_name or "").strip()
    if not folder_path:
        raise PeripheralError(400, "path 不能为空。", "RAW_FOLDER_PATH_REQUIRED")
    if not name:
        raise PeripheralError(400, "文件夹名称不能为空。", "RAW_FOLDER_NAME_REQUIRED")
    if RAW_FOLDER_NAME_ILLEGAL_CHARS.search(name):
        raise PeripheralError(400, "文件夹名称不能包含 \\ / : * ? \" < > | 字符。", "RAW_FOLDER_NAME_INVALID")
    if is_raw_folder_rename_protected_path(folder_path):
        raise PeripheralError(400, "该基础目录不允许重命名。", "RAW_FOLDER_RENAME_PROTECTED")

    async with async_session() as session:
        await ensure_runtime_tables(session)
        source_result = await session.execute(select(RawFolder).where(RawFolder.path == folder_path))
        source = source_result.scalar_one_or_none()
        if source is None:
            raise PeripheralError(404, "目录不存在。", "RAW_FOLDER_NOT_FOUND")
        if not raw_folder_matches_bid_type(source, bid_type):
            raise PeripheralError(400, "目录不属于当前素材库。", "RAW_FOLDER_SCOPE")

        if name == str(source.name or ""):
            tree = await raw_tree()
            return {
                "message": "文件夹名称未变化。",
                "sourcePath": folder_path,
                "folderPath": source.path,
                "movedFileCount": 0,
                "tree": tree["tree"],
            }

        parent_path = "/".join(str(source.path or "").split("/")[:-1])
        parent_result = await session.execute(select(RawFolder).where(RawFolder.path == parent_path))
        target_parent = parent_result.scalar_one_or_none()
        if target_parent is None:
            raise PeripheralError(404, "父级目录不存在。", "RAW_FOLDER_NOT_FOUND")

        next_root_path = f"{str(target_parent.path or '').rstrip('/')}/{name}"
        moved_count = await _relocate_folder_subtree(
            session,
            source=source,
            target_parent=target_parent,
            next_root_path=next_root_path,
            raw_object_key=raw_object_key,
            infer_material_tier_from_folder=infer_material_tier_from_folder,
            rename=True,
        )

    tree = await raw_tree()
    return {
        "message": "文件夹重命名成功",
        "sourcePath": folder_path,
        "folderPath": next_root_path,
        "movedFileCount": moved_count,
        "tree": tree["tree"],
    }
