from __future__ import annotations

import argparse
import asyncio
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import async_session
from app.models.materials import RawFile, RawFileVersion, RawFolder
from app.services.identity import canonical_customer, generate_material_project_id
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.material_store import material_store
from app.services.material_taxonomy import (
    MATERIAL_LIBRARY_ALLOWED_SUFFIXES,
    clean_status_for_new_file,
)
from app.services.minio_client import minio_client


DEFAULT_LIBRARY_ROOT = Path("/Users/sean/Downloads/技术标-0615/技术标素材库-20260615")

# 三档与源库二级目录名的对应关系。只导这三档；其它顶层目录（如“招投标文件”）忽略。
STANDARD_DIR_NAME = "标准文件"
CUSTOMER_DIR_NAME = "客户定制"
PROJECT_DIR_NAME = "项目定制"

# 素材库白名单后缀，去掉占位类（.ds_store）。Thumbs.db / .msg 等不在白名单内会被自动跳过。
SUPPORTED_SUFFIXES = {suffix for suffix in MATERIAL_LIBRARY_ALLOWED_SUFFIXES if suffix != ".ds_store"}


@dataclass(frozen=True)
class SourceSpec:
    """一个待导入的源目录及其档位身份。源目录本身即三级目录的内容根。"""

    source_root: Path
    material_tier: str
    customer_name: str
    project_id: str
    project_name: str


def discover_sources(library_root: Path) -> list[SourceSpec]:
    """扫描技术标素材库真实目录，按子目录动态推断档位与客户/项目身份。

    - 标准文件/        → standard，无身份，整目录作为一个源（保留机型号/部件/认证证书等子层级）。
    - 客户定制/{客户}/ → customer，customerName 由子目录名经 canonical_customer 归一。
    - 项目定制/{项目}/ → project，projectId 由子目录名生成稳定 ID，projectName 保留目录全名。

    不再写死单一客户/项目，每个子目录各自绑定自己的身份。
    """

    sources: list[SourceSpec] = []

    standard_root = library_root / STANDARD_DIR_NAME
    if standard_root.is_dir():
        sources.append(SourceSpec(standard_root, "standard", "", "", ""))

    customer_root = library_root / CUSTOMER_DIR_NAME
    if customer_root.is_dir():
        for child in sorted(customer_root.iterdir(), key=lambda item: item.name):
            if not child.is_dir() or child.name.startswith("."):
                continue
            canonical = canonical_customer(child.name)
            customer_name = str(canonical.get("customerCanonicalName") or child.name)
            sources.append(SourceSpec(child, "customer", customer_name, "", ""))

    project_root = library_root / PROJECT_DIR_NAME
    if project_root.is_dir():
        for child in sorted(project_root.iterdir(), key=lambda item: item.name):
            if not child.is_dir() or child.name.startswith("."):
                continue
            project_id = generate_material_project_id(child.name)
            sources.append(SourceSpec(child, "project", "", project_id, child.name))

    return sources


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


async def _purge_technical_material_store() -> None:
    """只清技术标素材，保留商务标等其它档，避免误删共享底座数据。"""
    bucket = settings.minio_buckets["materials"]
    async with async_session() as session:
        await ensure_material_runtime_tables(session)
        tech_folders = (
            await session.execute(select(RawFolder).where(RawFolder.path.like("技术标%")))
        ).scalars().all()
        folder_ids = [folder.id for folder in tech_folders]
        tech_files: list[RawFile] = []
        if folder_ids:
            tech_files = (
                await session.execute(select(RawFile).where(RawFile.folder_id.in_(folder_ids)))
            ).scalars().all()
        for item in tech_files:
            key = str(item.minio_key or "")
            if key:
                try:
                    minio_client.remove_object(item.minio_bucket or bucket, key)
                except Exception:  # noqa: BLE001 - 缺对象不阻断清理
                    pass
            file_id = int(item.id)
            await session.execute(delete(RawFileVersion).where(RawFileVersion.file_id == file_id))
            await session.execute(delete(RawFile).where(RawFile.id == file_id))
        # 删除技术标目录（叶子优先），保留根“技术标”节点由后续 ensure 重新维护。
        for folder in sorted(tech_folders, key=lambda f: len(str(f.path or "").split("/")), reverse=True):
            await session.execute(delete(RawFolder).where(RawFolder.id == folder.id))
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
        await _purge_technical_material_store()

    material_store._enqueue_cleaning_job = lambda file_id: {"queued": False, "importSkipped": True}

    sources = discover_sources(library_root)

    imported: list[dict[str, Any]] = []
    sources_summary: list[dict[str, Any]] = []
    counts_by_tier: dict[str, int] = {"standard": 0, "customer": 0, "project": 0}

    for spec in sources:
        files = _iter_material_files(spec.source_root)
        for file_path in files:
            item = await _upload_file(
                source_file=file_path,
                source_root=spec.source_root,
                material_tier=spec.material_tier,
                customer_name=spec.customer_name,
                project_id=spec.project_id,
                project_name=spec.project_name,
            )
            imported.append(item)
            counts_by_tier[spec.material_tier] += 1
        sources_summary.append(
            {
                "sourceRoot": str(spec.source_root),
                "tier": spec.material_tier,
                "customerName": spec.customer_name,
                "projectId": spec.project_id,
                "projectName": spec.project_name,
                "fileCount": len(files),
            }
        )

    await _mark_non_docx_cleaned()

    # 脚本走底层 material_store，不触发 technical_material_store 的索引钩子，这里显式重建一次。
    index_stats: dict[str, Any] = {}
    try:
        from app.services.technical_material_index import rebuild_technical_material_index

        index_payload = await rebuild_technical_material_index()
        index_stats = dict((index_payload or {}).get("stats") or {})
    except Exception as exc:  # noqa: BLE001 - 索引失败不应让导入结果丢失
        index_stats = {"error": str(exc)}

    tree = await material_store.raw_tree(bid_type="技术标")
    return {
        "sourceRoot": str(library_root),
        "imported": len(imported),
        "countsByTier": counts_by_tier,
        "sources": sources_summary,
        "indexStats": index_stats,
        "treeTopLevel": [str(node.get("path") or node.get("name") or "") for node in (tree.get("tree") or [])],
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
