from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import or_, select

from app.models.materials import RawFile, RawFileVersion, RawFolder
from app.services.material_move_metadata import build_raw_move_folder_file_ext_fields
from app.services.material_raw_object_operations import raw_object_key
from app.services.minio_client import minio_client


logger = logging.getLogger(__name__)


async def rename_project_folder_tree(session: Any, project_folder: RawFolder, target_path: str) -> str:
    old_root_path = str(project_folder.path or "").strip().strip("/")
    next_root_path = str(target_path or "").strip().strip("/")
    if not old_root_path or not next_root_path or old_root_path == next_root_path:
        return old_root_path or next_root_path

    folders = (
        await session.execute(
            select(RawFolder).where(
                or_(RawFolder.path == old_root_path, RawFolder.path.startswith(f"{old_root_path}/"))
            )
        )
    ).scalars().all()
    folder_paths = {
        int(folder.id): f"{next_root_path}{str(folder.path or '')[len(old_root_path):]}"
        for folder in folders
    }
    old_folder_paths = {int(folder.id): str(folder.path or "") for folder in folders}
    files = (
        await session.execute(select(RawFile).where(RawFile.folder_id.in_(folder_paths)))
    ).scalars().all()
    file_by_id = {int(item.id): item for item in files}
    versions = (
        await session.execute(select(RawFileVersion).where(RawFileVersion.file_id.in_(file_by_id)))
    ).scalars().all() if file_by_id else []

    file_next_keys: dict[int, str] = {}
    version_next_keys: dict[int, str] = {}
    copied_objects: list[tuple[str, str, str]] = []
    for item in files:
        next_key = raw_object_key(folder_paths[int(item.folder_id)], item.name)
        file_next_keys[int(item.id)] = next_key
        old_key = str(item.minio_key or "")
        if old_key and old_key != next_key:
            minio_client.copy_object(item.minio_bucket, old_key, next_key)
            copied_objects.append((str(item.minio_bucket), old_key, next_key))

    for version in versions:
        item = file_by_id.get(int(version.file_id))
        old_key = str(version.minio_key or "")
        old_folder_path = old_folder_paths.get(int(item.folder_id), "") if item is not None else ""
        new_folder_path = folder_paths.get(int(item.folder_id)) if item is not None else ""
        old_prefix = f"raw/{old_folder_path.strip('/')}/"
        new_prefix = f"raw/{str(new_folder_path or '').strip('/')}/"
        next_key = f"{new_prefix}{old_key[len(old_prefix):]}" if old_key.startswith(old_prefix) else old_key
        version_next_keys[int(version.id)] = next_key
        if item is not None and old_key and old_key != next_key:
            minio_client.copy_object(item.minio_bucket, old_key, next_key)
            copied_objects.append((str(item.minio_bucket), old_key, next_key))

    project_folder.name = next_root_path.rsplit("/", 1)[-1]
    for folder in folders:
        folder.path = folder_paths[int(folder.id)]
    for item in files:
        next_key = file_next_keys[int(item.id)]
        item.minio_key = next_key
        item.ext_fields = build_raw_move_folder_file_ext_fields(
            item.ext_fields or {},
            source_minio_key=next_key,
            source_file_name=item.name,
            material_tier="project",
            destination_bid_type=str(project_folder.bid_type or ""),
            folder_path=folder_paths[int(item.folder_id)],
            destination_project_id=str(project_folder.project_id or ""),
            destination_customer_name=str(project_folder.customer_name or ""),
        )
    for version in versions:
        version.minio_key = version_next_keys[int(version.id)]

    await session.commit()
    for bucket, old_key, _next_key in copied_objects:
        try:
            minio_client.remove_object(bucket, old_key)
        except Exception as exc:  # pragma: no cover - 新对象与数据库均已提交，旧对象残留只告警
            logger.warning("项目素材目录改名后清理旧对象 %s/%s 失败：%s", bucket, old_key, exc)
    return next_root_path
