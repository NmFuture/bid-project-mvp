from __future__ import annotations

import base64
import copy
import re
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from app.core.config import settings
from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_folder_maintenance import ensure_material_target_folder
from app.services.material_taxonomy import (
    MATERIAL_LIBRARY_ALLOWED_SUFFIXES,
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


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
EnsureFolderPath = Callable[..., Awaitable[RawFolder]]
ClearDefaultFolderDeletion = Callable[[Any, str], Awaitable[None]]
EnsureNestedFolder = Callable[[Any, RawFolder, str], Awaitable[RawFolder]]
ArchiveRawFileVersion = Callable[[Any, RawFile], Awaitable[None]]
CleanedObjectRemover = Callable[[dict[str, Any]], None]
RawObjectKeyBuilder = Callable[[str, str], str]
MaterialTierResolver = Callable[[RawFolder | None], str]
CleaningJobEnqueuer = Callable[[int], dict[str, Any]]


def _safe_segment(value: str, fallback: str) -> str:
    raw = str(value or "").strip()
    # 保留以 '.' 开头的隐藏文件名（如 .gitkeep）在 sanitize 后不丢失前导点
    leading_dot = raw.startswith(".") and len(raw) > 1
    text = re.sub(r"[\\/:*?\"<>|]+", "-", raw)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if leading_dot and text and not text.startswith("."):
        text = "." + text
    return text or fallback


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

    async with async_session() as session:
        await ensure_runtime_tables(session)
        if target_plan["mode"] == "auto":
            base_folder = await ensure_material_target_folder(
                session,
                material_tier=normalized_tier,
                bid_type=normalized_bid_type,
                customer_name=str(target_plan.get("customerName") or ""),
                project_id=str(target_plan.get("projectId") or ""),
                ensure_folder_path=ensure_folder_path,
                clear_default_folder_deletion=clear_default_folder_deletion,
            )
            target_path = base_folder.path
        elif target_plan["mode"] == "error":
            if target_plan["code"] == "BID_TYPE_REQUIRED":
                raise PeripheralError(400, "素材上传必须指定技术标或商务标。", "RAW_UPLOAD_BID_TYPE_REQUIRED")
            if target_plan["code"] == "CUSTOMER_NAME_REQUIRED":
                raise PeripheralError(400, "客户素材必须填写客户名称。", "CUSTOMER_NAME_REQUIRED")
            if target_plan["code"] == "PROJECT_ID_REQUIRED":
                raise PeripheralError(400, "项目素材必须填写项目 ID。", "PROJECT_ID_REQUIRED")
            raise PeripheralError(400, "上传目标目录无效。", "RAW_UPLOAD_TARGET_INVALID")
        elif target_plan["mode"] == "tier-root":
            result = await session.execute(select(RawFolder).where(RawFolder.path == target_plan["targetPath"]))
            base_folder = result.scalar_one_or_none()
            if base_folder is None:
                base_folder = await ensure_material_target_folder(
                    session,
                    material_tier=str(target_plan["inferredTier"]),
                    bid_type=normalized_bid_type,
                    customer_name=str(target_plan.get("customerName") or ""),
                    project_id=str(target_plan.get("projectId") or ""),
                    ensure_folder_path=ensure_folder_path,
                    clear_default_folder_deletion=clear_default_folder_deletion,
                )
            target_path = base_folder.path
        elif target_plan["mode"] == "scoped-path":
            result = await session.execute(select(RawFolder).where(RawFolder.path == target_plan["targetPath"]))
            base_folder = result.scalar_one_or_none()
            if base_folder is None:
                canonical_folder = await ensure_material_target_folder(
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
                    canonical_folder.path,
                )
                if target_resolution["mode"] == "nested":
                    base_folder = await ensure_nested_folder(
                        session,
                        canonical_folder,
                        target_resolution["relativeDir"],
                    )
                elif target_resolution["mode"] == "canonical":
                    base_folder = canonical_folder
                else:
                    raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
            target_path = base_folder.path
        else:
            target_path = str(target_plan["targetPath"])
            result = await session.execute(select(RawFolder).where(RawFolder.path == target_path))
            base_folder = result.scalar_one_or_none()
            if base_folder is None:
                raise PeripheralError(404, "目标目录不存在。", "RAW_FOLDER_NOT_FOUND")
            normalized_tier = normalized_tier or infer_material_tier_from_folder(base_folder)

        uploaded_items: list[dict[str, Any]] = []
        clean_job_targets: list[int] = []
        for item in file_inputs:
            relative_path = str(item.get("relativePath") or "").replace("\\", "/").strip("/")
            relative_parts = [part for part in relative_path.split("/") if part]
            relative_dir = "/".join(relative_parts[:-1]) if len(relative_parts) > 1 else ""
            source_relative_path = "/".join(relative_parts) if relative_parts else ""
            source_root_folder = relative_parts[0] if len(relative_parts) > 1 else ""

            file_name = _safe_segment(relative_parts[-1] if relative_parts else item.get("name") or "", "")
            if not file_name:
                continue
            # macOS 系统噪音文件（._* 前缀的 AppleDouble、.DS_Store），静默跳过，不入库
            if file_name.startswith("._") or file_name.lower() == ".ds_store":
                continue
            suffix = material_suffix(file_name)
            if suffix not in MATERIAL_LIBRARY_ALLOWED_SUFFIXES:
                continue

            folder = await ensure_nested_folder(session, base_folder, relative_dir)

            result = await session.execute(
                select(RawFile).where(RawFile.folder_id == folder.id, RawFile.name == file_name)
            )
            existing = result.scalar_one_or_none()

            upload = item.get("upload")
            mime_type = str(item.get("mimeType") or item.get("type") or getattr(upload, "content_type", "") or "")
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
                source_minio_bucket=settings.minio_buckets["materials"],
                source_minio_key=minio_key,
                source_relative_path=source_relative_path or file_name,
                source_root_folder=source_root_folder,
                tags=item.get("tags", tags),
            )
            extra_ext_fields = item.get("extFields") if isinstance(item.get("extFields"), dict) else {}
            if extra_ext_fields:
                common_ext.update(copy.deepcopy(extra_ext_fields))

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

            if existing and on_conflict in RAW_UPLOAD_CONFLICT_ACTIONS:
                await archive_raw_file_version(session, existing)
                remove_cleaned_object_from_ext(existing.ext_fields or {})
                upload_to_minio()
                existing.size_bytes = size
                existing.minio_key = minio_key
                existing.mime_type = mime_type
                existing.version += 1
                existing.ext_fields = build_raw_upload_existing_ext_fields(
                    existing.ext_fields or {},
                    common_ext,
                    last_action=on_conflict,
                )
                uploaded_items.append(existing.to_dict())
                if clean_status == "pending":
                    clean_job_targets.append(int(existing.id))
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
            record = RawFile(
                folder_id=folder.id,
                name=file_name,
                size_bytes=size,
                mime_type=mime_type,
                minio_key=minio_key,
                minio_bucket=settings.minio_buckets["materials"],
                ext_fields=build_raw_upload_record_ext_fields(common_ext),
            )
            session.add(record)
            await session.flush()
            uploaded_items.append(record.to_dict())
            if clean_status == "pending":
                clean_job_targets.append(int(record.id))

        await session.commit()
        clean_jobs = [enqueue_cleaning_job(file_id) for file_id in clean_job_targets]
        return {
            "message": f"上传完成，共处理 {len(uploaded_items)} 个文件，已触发 {len(clean_job_targets)} 个清洗任务。",
            "items": uploaded_items,
            "cleaning": {"queued": sum(1 for job in clean_jobs if job.get("queued")), "jobs": clean_jobs},
        }
