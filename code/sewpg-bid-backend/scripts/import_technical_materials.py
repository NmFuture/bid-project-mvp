from __future__ import annotations

import argparse
import asyncio
import mimetypes
import os
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import async_session
from app.models.materials import RawFile, RawFileVersion, RawFolder, WikiNode
from app.services.identity import canonical_customer
from app.services.material_store import clean_status_for_new_file, material_store
from app.services.minio_client import minio_client


DEFAULT_LIBRARY_ROOT = Path("/Users/wlb/Downloads/技术标素材库 0501/华能模板测试-20260430")
DEFAULT_SOURCE_MAP = (
    ("投标资料库-标准文件", "standard", "", ""),
    ("投标资料库-客户定制文件", "customer", "华能集团", ""),
    ("投标资料库-项目定制文件", "project", "华能赤峰翁牛特旗风电项目", "MAT-HN-CHIFENG-001"),
)
SUPPORTED_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm"}


def _iter_material_files(root: Path) -> list[Path]:
    return sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file()
            and not item.name.startswith(".")
            and not item.name.startswith("~$")
            and item.suffix.lower() in SUPPORTED_SUFFIXES
        ),
        key=lambda item: str(item.relative_to(root)),
    )


async def _purge_material_store() -> None:
    bucket = settings.minio_buckets["materials"]
    for prefix in ("raw/", "cleaned/", "wiki/"):
        for item in minio_client.client.list_objects(bucket, prefix=prefix, recursive=True):
            minio_client.remove_object(bucket, item.object_name)

    async with async_session() as session:
        await material_store._ensure_runtime_tables(session)
        await session.execute(delete(RawFileVersion))
        await session.execute(delete(RawFile))
        await session.execute(delete(RawFolder))
        await session.execute(delete(WikiNode))
        await session.commit()


async def _upload_file(
    *,
    source_file: Path,
    source_root: Path,
    material_tier: str,
    customer_name: str,
    project_id: str,
    project_name: str,
) -> dict[str, Any]:
    relative_path = str(source_file.relative_to(source_root))
    with source_file.open("rb") as handle:
        result = await material_store.raw_upload(
            target_path="",
            project_id=project_id if material_tier == "project" else "",
            project_code=project_id if material_tier == "project" else "",
            project_name=project_name if material_tier == "project" else "",
            bid_type="技术标",
            material_tier=material_tier,
            customer_id=canonical_customer(customer_name).get("customerId", "") if customer_name else "",
            customer_name=customer_name,
            on_conflict="overwrite",
            files=[
                {
                    "name": source_file.name,
                    "relativePath": relative_path,
                    "mimeType": mimetypes.guess_type(source_file.name)[0] or "application/octet-stream",
                    "upload": type(
                        "UploadProxy",
                        (),
                        {
                            "filename": source_file.name,
                            "content_type": mimetypes.guess_type(source_file.name)[0] or "application/octet-stream",
                            "file": handle,
                        },
                    )(),
                }
            ],
        )
    return result["items"][0]


async def _mark_non_docx_cleaned() -> None:
    async with async_session() as session:
        result = await session.execute(select(RawFile).options(selectinload(RawFile.folder)))
        rows = result.scalars().all()
        for item in rows:
            ext = Path(item.name).suffix.lower()
            fields = dict(item.ext_fields or {})
            if ext == ".docx":
                fields.update(
                    {
                        "cleanStatus": "cleaned",
                        "cleanMessage": "原始文件为 Word，可直接作为 Wiki 解析和 OnlyOffice 预览来源。",
                        "cleanedMinioBucket": item.minio_bucket,
                        "cleanedMinioKey": item.minio_key,
                        "cleanedFileName": item.name,
                        "cleanedSize": int(item.size_bytes or 0),
                    }
                )
            else:
                clean_status, clean_message = clean_status_for_new_file(item.name)
                fields.update(
                    {
                        "cleanStatus": clean_status,
                        "cleanMessage": clean_message,
                        "cleanedMinioBucket": "",
                        "cleanedMinioKey": "",
                        "cleanedFileName": "",
                        "cleanedSize": 0,
                    }
                )
            item.ext_fields = fields
        await session.commit()


async def import_materials(library_root: Path, purge: bool = True) -> dict[str, Any]:
    if purge:
        await _purge_material_store()

    material_store._enqueue_cleaning_job = lambda file_id: {"queued": False, "importSkipped": True}

    imported: list[dict[str, Any]] = []
    skipped: list[str] = []
    counts_by_tier: dict[str, int] = {"standard": 0, "customer": 0, "project": 0}

    for folder_name, tier, customer_name, project_id in DEFAULT_SOURCE_MAP:
        source_root = library_root / folder_name
        if not source_root.exists():
            skipped.append(str(source_root))
            continue
        for file_path in _iter_material_files(source_root):
            item = await _upload_file(
                source_file=file_path,
                source_root=source_root,
                material_tier=tier,
                customer_name=customer_name,
                project_id=project_id,
                project_name=project_id,
            )
            imported.append(item)
            counts_by_tier[tier] += 1

    await _mark_non_docx_cleaned()

    tree = await material_store.raw_tree()
    return {
        "sourceRoot": str(library_root),
        "imported": len(imported),
        "countsByTier": counts_by_tier,
        "skippedRoots": skipped,
        "tree": tree["tree"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the latest technical-bid material library into PostgreSQL and MinIO.")
    parser.add_argument("--source-root", default=str(DEFAULT_LIBRARY_ROOT))
    parser.add_argument("--no-purge", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(import_materials(Path(args.source_root), purge=not args.no_purge))
    print(result)


if __name__ == "__main__":
    main()
