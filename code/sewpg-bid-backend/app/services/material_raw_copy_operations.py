"""素材目录内容复制：把来源项目目录整棵子树复制到目标项目目录。

与移动的关键区别是对象必须真复制一份，不能让两条 RawFile 记录共用同一个
minio_key——更新文件时会 copy 到新 key 再删旧 key（见 material_raw_update_operations），
共用会让另一条记录变成悬空引用。

逐个文件提交：素材边复制边出现在素材库里，单个文件失败也不影响其余文件。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from sqlalchemy import or_, select

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_move_metadata import build_raw_move_file_ext_fields
from app.services.material_raw_file_filter import raw_folder_matches_bid_type
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError

logger = logging.getLogger(__name__)

RAW_COPY_FILE_ACTION = "copy_from_project"


def _copied_ext_fields(
    source_ext: dict[str, Any],
    *,
    minio_key: str,
    file_name: str,
    material_tier: str,
    folder: RawFolder,
    source_project_id: str,
) -> dict[str, Any]:
    # 清洗产物、全文产物都是按源文件 id/版本存的，副本不继承，按需重新生成；
    # 继承会让副本指向来源文件的对象，删副本就会破坏来源。
    ext = {key: value for key, value in (source_ext or {}).items() if not str(key).startswith("cleaned")}
    ext = build_raw_move_file_ext_fields(
        ext,
        source_minio_key=minio_key,
        source_file_name=file_name,
        material_tier=material_tier,
        destination_bid_type=str(folder.bid_type or ""),
        folder_path=str(folder.path or ""),
        destination_project_id=str(folder.project_id or ""),
        destination_customer_name=str(folder.customer_name or ""),
        last_action=RAW_COPY_FILE_ACTION,
    )
    ext["copiedFromProjectId"] = source_project_id
    return ext


async def copy_raw_folder_contents(
    *,
    source_path: str,
    target_path: str,
    bid_type: str,
    exclude_top_level_names: set[str] | None = None,
    ensure_runtime_tables: Callable[[Any], Awaitable[None]],
    ensure_nested_folder: Callable[..., Awaitable[RawFolder]],
    raw_object_key: Callable[[str, str], str],
    infer_material_tier_from_folder: Callable[[RawFolder | None], str],
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """把 source_path 子树里的文件复制进 target_path，返回复制统计。

    已存在同名文件的目标位置直接跳过，因此整个操作可以安全重跑。
    """

    excluded = {str(name).strip() for name in (exclude_top_level_names or set()) if str(name).strip()}
    normalized_source = str(source_path or "").strip("/")
    normalized_target = str(target_path or "").strip("/")
    if not normalized_source or not normalized_target:
        raise PeripheralError(400, "复制素材需要来源目录与目标目录。", "RAW_COPY_PATH_REQUIRED")
    if normalized_source == normalized_target:
        return {"copied": 0, "skipped": 0, "total": 0, "failed": []}

    async with async_session() as session:
        await ensure_runtime_tables(session)
        source_folder = (
            await session.execute(select(RawFolder).where(RawFolder.path == normalized_source))
        ).scalar_one_or_none()
        if source_folder is None:
            raise PeripheralError(404, "来源项目目录不存在。", "RAW_COPY_SOURCE_NOT_FOUND")
        if not raw_folder_matches_bid_type(source_folder, bid_type):
            raise PeripheralError(400, "来源目录不属于当前素材库。", "RAW_COPY_SOURCE_SCOPE")

        subtree_folders = (
            (
                await session.execute(
                    select(RawFolder).where(
                        or_(
                            RawFolder.path == normalized_source,
                            RawFolder.path.startswith(f"{normalized_source}/"),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        folder_by_id = {int(folder.id): folder for folder in subtree_folders}
        excluded_prefixes = tuple(f"{normalized_source}/{name}" for name in excluded)
        copyable_folder_ids = [
            folder_id
            for folder_id, folder in folder_by_id.items()
            if not any(
                str(folder.path or "") == prefix or str(folder.path or "").startswith(f"{prefix}/")
                for prefix in excluded_prefixes
            )
        ]
        source_files = (
            (
                await session.execute(
                    select(RawFile).where(RawFile.folder_id.in_(copyable_folder_ids))
                )
            )
            .scalars()
            .all()
            if copyable_folder_ids
            else []
        )
        plan = [
            {
                "id": int(item.id),
                "name": str(item.name or ""),
                "sizeBytes": int(item.size_bytes or 0),
                "mimeType": str(item.mime_type or ""),
                "minioKey": str(item.minio_key or ""),
                "minioBucket": str(item.minio_bucket or ""),
                "extFields": dict(item.ext_fields or {}),
                "relativeDir": str(folder_by_id[int(item.folder_id)].path or "")[len(normalized_source):].strip("/"),
            }
            for item in source_files
        ]

    total = len(plan)
    copied = 0
    skipped = 0
    failed: list[dict[str, Any]] = []
    if on_progress:
        on_progress(0, total)

    for index, entry in enumerate(plan, start=1):
        try:
            async with async_session() as session:
                await ensure_runtime_tables(session)
                target_folder = (
                    await session.execute(select(RawFolder).where(RawFolder.path == normalized_target))
                ).scalar_one_or_none()
                if target_folder is None:
                    raise PeripheralError(404, "目标项目目录不存在。", "RAW_COPY_TARGET_NOT_FOUND")
                destination = await ensure_nested_folder(session, target_folder, entry["relativeDir"])
                existing = (
                    await session.execute(
                        select(RawFile).where(
                            RawFile.folder_id == destination.id,
                            RawFile.name == entry["name"],
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    skipped += 1
                    await session.commit()
                    continue

                next_key = raw_object_key(str(destination.path or ""), entry["name"])
                bucket = entry["minioBucket"] or ""
                if entry["minioKey"] and next_key != entry["minioKey"]:
                    await asyncio.to_thread(minio_client.copy_object, bucket, entry["minioKey"], next_key)
                tier = infer_material_tier_from_folder(destination)
                session.add(
                    RawFile(
                        folder_id=destination.id,
                        name=entry["name"],
                        size_bytes=entry["sizeBytes"],
                        mime_type=entry["mimeType"],
                        minio_key=next_key,
                        minio_bucket=bucket,
                        version=1,
                        ext_fields=_copied_ext_fields(
                            entry["extFields"],
                            minio_key=next_key,
                            file_name=entry["name"],
                            material_tier=tier,
                            folder=destination,
                            source_project_id=str(source_folder.project_id or ""),
                        ),
                    )
                )
                await session.commit()
                copied += 1
        except Exception as exc:  # noqa: BLE001 - 单个文件失败不阻断整批，原因回传给前端
            logger.warning("复制素材 %s 失败：%s", entry["name"], exc)
            failed.append({"name": entry["name"], "reason": str(exc)})
        if on_progress:
            on_progress(index, total)

    return {"copied": copied, "skipped": skipped, "total": total, "failed": failed}
