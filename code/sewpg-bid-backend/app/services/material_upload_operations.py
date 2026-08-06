from __future__ import annotations

import asyncio
import base64
import copy
import logging
import re
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from app.core.config import settings
from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_folder_maintenance import ensure_material_target_folder
from app.services.material_fulltext_artifacts import purge_material_fulltext_objects
from app.services.material_taxonomy import (
    MATERIAL_LIBRARY_ALLOWED_SUFFIXES,
    SHORTCUT_MATERIAL_SUFFIXES,
    material_suffix,
    normalize_business_material_kind,
)
from app.services.material_upload_metadata import (
    RAW_UPLOAD_CONFLICT_ACTIONS,
    build_raw_upload_existing_ext_fields,
    build_raw_upload_ext_fields,
    build_raw_upload_record_ext_fields,
)
from app.services.material_upload_target import (
    build_raw_upload_target_plan,
    resolve_raw_upload_canonical_target,
)
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError

logger = logging.getLogger(__name__)


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
EnsureFolderPath = Callable[..., Awaitable[RawFolder]]
ClearDefaultFolderDeletion = Callable[[Any, str], Awaitable[None]]
EnsureNestedFolder = Callable[[Any, RawFolder, str], Awaitable[RawFolder]]
ArchiveRawFileVersion = Callable[[Any, RawFile], Awaitable[None]]
CleanedObjectRemover = Callable[[dict[str, Any]], None]
RawObjectKeyBuilder = Callable[[str, str], str]
RawVersionObjectKeyBuilder = Callable[[int, int, str], str]
MaterialTierResolver = Callable[[RawFolder | None], str]
CleaningJobEnqueuer = Callable[..., dict[str, Any]]


def _safe_segment(value: str, fallback: str, *, preserve_leading_dot: bool = True) -> str:
    raw = str(value or "").strip()
    # 保留以 '.' 开头的隐藏文件名（如 .gitkeep）在 sanitize 后不丢失前导点
    leading_dot = preserve_leading_dot and raw.startswith(".") and len(raw) > 1
    text = re.sub(r"[\\/:*?\"<>|]+", "-", raw)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if leading_dot and text and not text.startswith("."):
        text = "." + text
    return text or fallback


def _normalize_relative_directory(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    segments = (
        _safe_segment(segment, "", preserve_leading_dot=False)
        for segment in normalized.split("/")
    )
    return "/".join(segment for segment in segments if segment)


def _sorted_directory_prefixes(relative_directories: set[str]) -> list[str]:
    prefixes: set[str] = set()
    for relative_directory in relative_directories:
        parts = [part for part in relative_directory.split("/") if part]
        prefixes.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
    return sorted(prefixes, key=lambda path: (path.count("/") + 1, path))


async def upload_raw_files(
    *,
    target_path: str = "",
    project_id: str = "",
    project_code: str = "",
    project_name: str = "",
    bid_type: str,
    material_tier: str = "",
    business_material_kind: str = "",
    customer_id: str = "",
    customer_name: str = "",
    tags: Any = None,
    on_conflict: str = "",
    files: list[dict[str, Any]] | None = None,
    ensure_runtime_tables: EnsureRuntimeTables,
    ensure_folder_path: EnsureFolderPath,
    clear_default_folder_deletion: ClearDefaultFolderDeletion,
    ensure_nested_folder: EnsureNestedFolder,
    archive_raw_file_version: ArchiveRawFileVersion,
    remove_cleaned_object_from_ext: CleanedObjectRemover,
    raw_object_key: RawObjectKeyBuilder,
    infer_material_tier_from_folder: MaterialTierResolver,
    enqueue_cleaning_job: CleaningJobEnqueuer,
    raw_version_object_key: RawVersionObjectKeyBuilder | None = None,
) -> dict[str, Any]:
    file_inputs = list(files or [])
    if not file_inputs:
        raise PeripheralError(400, "请至少上传一个文件。", "RAW_UPLOAD_FILES_REQUIRED")
    target_plan = build_raw_upload_target_plan(
        target_path=target_path,
        project_id=project_id,
        customer_name=customer_name,
        bid_type=bid_type,
        material_tier=material_tier,
    )
    normalized_bid_type = str(target_plan["bidType"])
    normalized_tier = str(target_plan.get("materialTier") or "")
    normalized_business_kind = normalize_business_material_kind(business_material_kind)

    if target_plan["mode"] == "error":
        if target_plan["code"] == "BID_TYPE_REQUIRED":
            raise PeripheralError(400, "素材上传必须指定技术标或商务标。", "RAW_UPLOAD_BID_TYPE_REQUIRED")
        if target_plan["code"] == "CUSTOMER_NAME_REQUIRED":
            raise PeripheralError(400, "客户素材必须填写客户名称。", "CUSTOMER_NAME_REQUIRED")
        if target_plan["code"] == "PROJECT_ID_REQUIRED":
            raise PeripheralError(400, "项目素材必须填写项目 ID。", "PROJECT_ID_REQUIRED")
        raise PeripheralError(400, "上传目标目录无效。", "RAW_UPLOAD_TARGET_INVALID")

    skipped_items: list[dict[str, str]] = []
    prepared_inputs: list[dict[str, Any]] = []
    for item in file_inputs:
        relative_path = str(item.get("relativePath") or "").replace("\\", "/").strip("/")
        relative_parts = [part for part in relative_path.split("/") if part]
        relative_dir = _normalize_relative_directory("/".join(relative_parts[:-1]))
        source_relative_path = "/".join(relative_parts) if relative_parts else ""
        source_root_folder = relative_parts[0] if len(relative_parts) > 1 else ""

        file_name = _safe_segment(relative_parts[-1] if relative_parts else item.get("name") or "", "")
        if not file_name or file_name.startswith("._") or file_name.lower() == ".ds_store":
            continue
        suffix = material_suffix(file_name)
        if suffix in SHORTCUT_MATERIAL_SUFFIXES:
            skipped_items.append({"name": file_name, "reason": "快捷方式文件没有实质内容，未存入素材库。"})
            continue
        if suffix not in MATERIAL_LIBRARY_ALLOWED_SUFFIXES:
            raise PeripheralError(
                400,
                f"文件 {file_name} 类型不支持。",
                "RAW_FILE_TYPE_NOT_ALLOWED",
            )

        upload = item.get("upload")
        mime_type = str(item.get("mimeType") or item.get("type") or getattr(upload, "content_type", "") or "")
        file_stream = None
        file_data = b""
        if upload is not None and hasattr(upload, "file"):
            file_stream = upload.file
            file_stream.seek(0, 2)
            size = file_stream.tell()
            file_stream.seek(0)
        else:
            raw_data = item.get("data") or b""
            if isinstance(raw_data, str):
                if raw_data.startswith("data:"):
                    raw_data = raw_data.split(",", 1)[-1]
                file_data = base64.b64decode(raw_data)
            else:
                file_data = raw_data if isinstance(raw_data, bytes) else b""
            size = len(file_data)

        if size <= 0:
            skipped_items.append({"name": file_name, "reason": "文件内容为空（0 字节），未存入素材库。"})
            continue
        if size > settings.max_upload_file_size_bytes:
            limit_mb = settings.max_upload_file_size_bytes // 1024 // 1024
            raise PeripheralError(
                413,
                f"文件 {file_name} 超过 {limit_mb}MB 上限。",
                "RAW_FILE_TOO_LARGE",
            )

        prepared_inputs.append(
            {
                "item": item,
                "relativeDir": relative_dir,
                "sourceRelativePath": source_relative_path,
                "sourceRootFolder": source_root_folder,
                "fileName": file_name,
                "mimeType": mime_type,
                "fileStream": file_stream,
                "fileData": file_data,
                "size": size,
            }
        )

    async with async_session() as session:
        uploaded_items: list[dict[str, Any]] = []
        clean_job_targets: list[dict[str, Any]] = []
        # 本次已写入 MinIO 的新对象；任一环节失败时补偿删除，避免孤儿对象（H1）
        written_object_keys: list[tuple[str, str]] = []
        # 覆盖上传时旧 cleaned 对象延后到 DB commit 成功后再删，写失败不动旧对象（H2）
        pending_cleaned_removals: list[dict[str, Any]] = []
        pending_fulltext_cleanups: list[tuple[int, int]] = []
        materials_bucket = settings.minio_buckets["materials"]
        try:
            await ensure_runtime_tables(session)
            directory_root: RawFolder
            base_relative_dir = ""
            if target_plan["mode"] == "auto":
                directory_root = await ensure_material_target_folder(
                    session,
                    material_tier=normalized_tier,
                    bid_type=normalized_bid_type,
                    customer_name=str(target_plan.get("customerName") or ""),
                    project_id=str(target_plan.get("projectId") or ""),
                    ensure_folder_path=ensure_folder_path,
                    clear_default_folder_deletion=clear_default_folder_deletion,
                )
            elif target_plan["mode"] == "tier-root":
                result = await session.execute(select(RawFolder).where(RawFolder.path == target_plan["targetPath"]))
                directory_root = result.scalar_one_or_none()
                if directory_root is None:
                    directory_root = await ensure_material_target_folder(
                        session,
                        material_tier=str(target_plan["inferredTier"]),
                        bid_type=normalized_bid_type,
                        customer_name=str(target_plan.get("customerName") or ""),
                        project_id=str(target_plan.get("projectId") or ""),
                        ensure_folder_path=ensure_folder_path,
                        clear_default_folder_deletion=clear_default_folder_deletion,
                    )
            elif target_plan["mode"] == "scoped-path":
                result = await session.execute(select(RawFolder).where(RawFolder.path == target_plan["targetPath"]))
                existing_target = result.scalar_one_or_none()
                if existing_target is not None:
                    directory_root = existing_target
                else:
                    directory_root = await ensure_material_target_folder(
                        session,
                        material_tier=normalized_tier,
                        bid_type=normalized_bid_type,
                        customer_name=str(target_plan.get("customerName") or ""),
                        project_id=str(target_plan.get("projectId") or ""),
                        ensure_folder_path=ensure_folder_path,
                        clear_default_folder_deletion=clear_default_folder_deletion,
                    )
                    target_resolution = resolve_raw_upload_canonical_target(
                        str(target_plan["requestedPath"]),
                        directory_root.path,
                    )
                    if target_resolution["mode"] == "nested":
                        base_relative_dir = _normalize_relative_directory(target_resolution["relativeDir"])
                    elif target_resolution["mode"] != "canonical":
                        raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
            else:
                result = await session.execute(select(RawFolder).where(RawFolder.path == target_plan["targetPath"]))
                directory_root = result.scalar_one_or_none()
                if directory_root is None:
                    raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
                normalized_tier = normalized_tier or infer_material_tier_from_folder(directory_root)

            required_relative_dirs = {base_relative_dir}
            for prepared in prepared_inputs:
                folder_key = "/".join(
                    part for part in (base_relative_dir, str(prepared["relativeDir"])) if part
                )
                prepared["folderKey"] = folder_key
                required_relative_dirs.add(folder_key)

            folders_by_relative_dir = {"": directory_root}
            for relative_dir in _sorted_directory_prefixes(required_relative_dirs):
                parent_relative_dir, _, name = relative_dir.rpartition("/")
                parent = folders_by_relative_dir[parent_relative_dir]
                folders_by_relative_dir[relative_dir] = await ensure_folder_path(
                    session,
                    name,
                    parent.id,
                    parent.tier,
                    parent.bid_type,
                    parent.project_id,
                    parent.sort_order or 0,
                    customer_name=parent.customer_name,
                )

            # 目录锁只存活于这个短事务，MinIO 写入开始前已全部释放。
            await session.commit()

            for prepared in prepared_inputs:
                item = prepared["item"]
                folder = folders_by_relative_dir[str(prepared["folderKey"])]
                file_name = str(prepared["fileName"])
                mime_type = str(prepared["mimeType"])
                size = int(prepared["size"])
                result = await session.execute(
                    select(RawFile)
                    .where(RawFile.folder_id == folder.id, RawFile.name == file_name)
                    .with_for_update()
                )
                existing = result.scalar_one_or_none()

                next_version = int(existing.version or 1) + 1 if existing and on_conflict in RAW_UPLOAD_CONFLICT_ACTIONS else 1
                if existing and on_conflict in RAW_UPLOAD_CONFLICT_ACTIONS and raw_version_object_key is not None:
                    minio_key = raw_version_object_key(int(existing.id), next_version, file_name)
                else:
                    minio_key = raw_object_key(folder.path, file_name)
                common_ext, clean_status = build_raw_upload_ext_fields(
                    file_name=file_name,
                    folder_path=folder.path,
                    folder_tier=infer_material_tier_from_folder(folder),
                    folder_customer_name=str(folder.customer_name or ""),
                    folder_project_id=str(folder.project_id or ""),
                    requested_bid_type=normalized_bid_type,
                    requested_material_tier=normalized_tier,
                    business_material_kind=normalized_business_kind,
                    customer_id=customer_id,
                    customer_name=customer_name,
                    project_id=project_id,
                    project_code=project_code,
                    project_name=project_name,
                    source_minio_bucket=materials_bucket,
                    source_minio_key=minio_key,
                    source_relative_path=str(prepared["sourceRelativePath"]) or file_name,
                    source_root_folder=str(prepared["sourceRootFolder"]),
                    tags=item.get("tags", tags),
                )
                extra_ext_fields = item.get("extFields") if isinstance(item.get("extFields"), dict) else {}
                if extra_ext_fields:
                    common_ext.update(copy.deepcopy(extra_ext_fields))

                file_stream = prepared["fileStream"]
                if file_stream is not None:
                    def upload_to_minio() -> str:
                        file_stream.seek(0)
                        return minio_client.put_object_stream(
                            materials_bucket,
                            minio_key,
                            file_stream,
                            size,
                            content_type=mime_type or "application/octet-stream",
                        )

                else:
                    file_data = prepared["fileData"]

                    def upload_to_minio() -> str:
                        return minio_client.put_object(
                            materials_bucket,
                            minio_key,
                            file_data,
                            content_type=mime_type or "application/octet-stream",
                        )

                if existing and on_conflict in RAW_UPLOAD_CONFLICT_ACTIONS:
                    await archive_raw_file_version(session, existing)
                    # 先写新对象成功再登记旧 cleaned 待删；写失败不清理旧对象（H2）
                    upload_to_minio()
                    written_object_keys.append((materials_bucket, minio_key))
                    stale_cleaned = existing.ext_fields or {}
                    stale_cleaned_key = str(stale_cleaned.get("cleanedMinioKey") or "")
                    if stale_cleaned_key:
                        pending_cleaned_removals.append(
                            {
                                "bucket": str(stale_cleaned.get("cleanedMinioBucket") or materials_bucket),
                                "key": stale_cleaned_key,
                            }
                        )
                    pending_fulltext_cleanups.append((int(existing.id), int(existing.version or 1)))
                    existing.size_bytes = size
                    existing.minio_key = minio_key
                    existing.mime_type = mime_type
                    existing.version = next_version
                    existing.ext_fields = build_raw_upload_existing_ext_fields(
                        existing.ext_fields or {},
                        common_ext,
                        last_action=on_conflict,
                    )
                    uploaded_items.append(existing.to_dict())
                    if clean_status == "pending":
                        clean_job_targets.append(
                            {
                                "file_id": int(existing.id),
                                "bid_type": normalized_bid_type,
                                "source_version": next_version,
                                "source_bucket": materials_bucket,
                                "source_key": minio_key,
                            }
                        )
                    continue

                if existing and not on_conflict:
                    raise PeripheralError(
                        409,
                        "目标路径存在同名文件",
                        "MATERIAL_CONFLICT",
                        {
                            "conflict": {
                                "path": folder.path,
                                "existingFileId": f"RAW-{existing.id:04d}",
                                "existingFileName": existing.name,
                                "allowedActions": ["overwrite", "version"],
                            }
                        },
                    )

                upload_to_minio()
                written_object_keys.append((materials_bucket, minio_key))
                record = RawFile(
                    folder_id=folder.id,
                    name=file_name,
                    size_bytes=size,
                    mime_type=mime_type,
                    minio_key=minio_key,
                    minio_bucket=materials_bucket,
                    ext_fields=build_raw_upload_record_ext_fields(common_ext),
                )
                session.add(record)
                await session.flush()
                uploaded_items.append(record.to_dict())
                if clean_status == "pending":
                    clean_job_targets.append(
                        {
                            "file_id": int(record.id),
                            "bid_type": normalized_bid_type,
                            "source_version": int(record.version or 1),
                            "source_bucket": materials_bucket,
                            "source_key": minio_key,
                        }
                    )

            await session.commit()
        except Exception:
            # 事务回滚后补偿删除本次已写入的新对象，避免孤儿文件（H1）
            await session.rollback()
            for bucket, key in written_object_keys:
                try:
                    minio_client.remove_object(bucket, key)
                except Exception as cleanup_exc:  # pragma: no cover - 补偿删除失败仅告警
                    logger.warning("上传失败回滚清理对象 %s/%s 失败：%s", bucket, key, cleanup_exc)
            raise

        # commit 成功后再清理被覆盖的旧产物；清理失败不影响已成功的上传。
        for raw_file_id, source_version in pending_fulltext_cleanups:
            await asyncio.to_thread(
                purge_material_fulltext_objects,
                raw_file_id,
                source_version,
                max_source_version=source_version,
            )
        for removal in pending_cleaned_removals:
            try:
                minio_client.remove_object(removal["bucket"], removal["key"])
            except Exception as cleanup_exc:  # pragma: no cover - 旧对象清理失败仅告警
                logger.warning("覆盖上传清理旧 cleaned 对象 %s/%s 失败：%s", removal["bucket"], removal["key"], cleanup_exc)
        clean_jobs = [enqueue_cleaning_job(**target) for target in clean_job_targets]
        message = f"上传完成，共处理 {len(uploaded_items)} 个文件，已触发 {len(clean_job_targets)} 个清洗任务。"
        if skipped_items:
            shown = skipped_items[:5]
            detail = "；".join(f"{item['name']}（{item['reason'].rstrip('。')}）" for item in shown)
            if len(skipped_items) > len(shown):
                detail += f"；另有 {len(skipped_items) - len(shown)} 个文件同样被过滤"
            message += f"已过滤 {len(skipped_items)} 个文件：{detail}。"
        return {
            "message": message,
            "items": uploaded_items,
            "skipped": skipped_items,
            "cleaning": {"queued": sum(1 for job in clean_jobs if job.get("queued")), "jobs": clean_jobs},
        }
