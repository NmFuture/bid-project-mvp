from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm import selectinload

from app.core.config import BASE_DIR, settings
from app.models import async_session
from app.models.materials import RawFile
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.filename_utils import short_filename
from app.services.material_doc_conversion import convert_doc_to_docx
from app.services.material_folder_scope import normalize_material_bid_type
from app.services.material_raw_file_filter import raw_file_bid_type
from app.services.material_raw_object_operations import enqueue_cleaning_job
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError

logger = logging.getLogger(__name__)

WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# 线上清洗链路只处理 Word；DOC 先经 OnlyOffice 转为 DOCX，其他格式保留原件。
CLEANABLE_SUFFIXES = {".doc", ".docx"}
# 可由后台任务转换为 Word 的非 Word 素材（driver 的 pdf/excel 分支，技术标深度解析链使用）
DEEP_CONVERTIBLE_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm"}
_sync_cleaning_loop: asyncio.AbstractEventLoop | None = None


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _numeric_raw_file_id(file_id: str) -> int:
    value = str(file_id or "").strip()
    if value.upper().startswith("RAW-"):
        value = value[4:]
    try:
        return int(value)
    except ValueError as exc:
        raise PeripheralError(400, "素材文件 ID 无效。", "RAW_FILE_ID_INVALID") from exc


def _safe_file_name(name: str, fallback: str = "material.bin") -> str:
    safe = PurePosixPath(str(name or "").replace("\\", "/")).name.strip()
    return safe or fallback


def _short_file_name_for_path(name: str, fallback: str = "material.docx") -> str:
    return short_filename(name, fallback, max_bytes=96)


def is_cleanable_material(name: str) -> bool:
    return PurePosixPath(str(name or "")).suffix.lower() in CLEANABLE_SUFFIXES


def is_deep_convertible_material(name: str) -> bool:
    """是否可后台转换为 Word 的非 Word 素材（PDF/XLSX 走 driver 的转换分支）。"""

    return PurePosixPath(str(name or "")).suffix.lower() in DEEP_CONVERTIBLE_SUFFIXES


def cleaned_object_key(raw_file_id: int, file_name: str, *, source_version: int | None = None) -> str:
    short_name = _short_file_name_for_path(file_name, f"RAW-{raw_file_id:04d}.docx")
    stem = short_filename(PurePosixPath(short_name).stem, f"RAW-{raw_file_id:04d}", max_bytes=82)
    if source_version is not None:
        return f"cleaned/RAW-{raw_file_id:04d}/v{int(source_version)}/{stem}.docx"
    return f"cleaned/RAW-{raw_file_id:04d}/{uuid4().hex}-{stem}.docx"


def _stale_cleaning_result(source_version: int, current_version: int) -> dict[str, Any]:
    return {
        "cleanStatus": "stale",
        "cleanMessage": "清洗任务对应的素材版本已过期。",
        "sourceVersion": source_version,
        "currentVersion": current_version,
    }


def _get_sync_cleaning_loop() -> asyncio.AbstractEventLoop:
    global _sync_cleaning_loop
    if _sync_cleaning_loop is None or _sync_cleaning_loop.is_closed():
        _sync_cleaning_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_sync_cleaning_loop)
    return _sync_cleaning_loop


def _skill_driver_path() -> Path:
    return BASE_DIR / "opencode" / "skills" / "bid-material-format-cleaner" / "scripts" / "driver.py"


async def _prepare_cleaning_source(
    *,
    source_name: str,
    source_bucket: str,
    source_key: str,
    source_version: int,
    source_dir: Path,
) -> Path:
    source_dir.mkdir(parents=True, exist_ok=True)
    if PurePosixPath(source_name).suffix.lower() == ".doc":
        converted_name = _short_file_name_for_path(
            f"{PurePosixPath(source_name).stem}.docx",
            "material.docx",
        )
        return await convert_doc_to_docx(
            source_url=minio_client.get_presigned_url(source_bucket, source_key, expires=1800),
            source_name=source_name,
            source_version=source_version,
            target_path=source_dir / converted_name,
        )

    source_path = source_dir / source_name
    minio_client.download_file(source_bucket, source_key, source_path)
    return source_path


def _extract_driver_line(output: str, file_name: str) -> tuple[str, str]:
    status = ""
    detail = ""
    for line in output.splitlines():
        if f"] {file_name}" not in line and f"[{file_name}]" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            status = stripped.split("]", 1)[0].lstrip("[")
            if "(" in stripped and stripped.endswith(")"):
                detail = stripped.rsplit("(", 1)[-1].rstrip(")")
    return status, detail


def _tail_output(stdout: str, stderr: str, limit: int = 8000) -> str:
    text = "\n".join(part for part in [stdout.strip(), stderr.strip()] if part)
    return text[-limit:] if len(text) > limit else text


def _read_cleaning_manifest(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "cleaning_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to read material cleaning manifest %s: %s", manifest_path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _cleaning_manifest_record(manifest: dict[str, Any], source_name: str) -> dict[str, Any]:
    records = manifest.get("records") if isinstance(manifest, dict) else []
    if not isinstance(records, list):
        return {}
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("sourceFileName") or "") == source_name:
            return record
        if PurePosixPath(str(record.get("relativeSourcePath") or "")).name == source_name:
            return record
    return {}


def _compact_cleaning_manifest(manifest: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    if not manifest and not record:
        return {}
    return {
        "schemaVersion": str(manifest.get("schemaVersion") or ""),
        "generatedAt": str(manifest.get("generatedAt") or ""),
        "summary": manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {},
        "record": record,
    }


def _resolve_cleaned_output(output_dir: Path, manifest_record: dict[str, Any]) -> Path | None:
    """优先按 manifest 的 relativeOutputPath 精确定位清洗产物，避免按 mtime 取错文件。"""
    relative_output = str(manifest_record.get("relativeOutputPath") or "").strip() if manifest_record else ""
    if relative_output:
        candidate = output_dir / PurePosixPath(relative_output.replace("\\", "/"))
        if candidate.exists():
            return candidate
    # 回退：manifest 缺失或路径对不上时，取输出目录中最新生成的 docx。
    fallback = sorted(
        output_dir.rglob("*.docx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return fallback[0] if fallback else None


async def set_material_clean_status(
    file_id: str,
    status: str,
    message: str,
    *,
    source_version: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    numeric_id = _numeric_raw_file_id(file_id)
    async with async_session() as session:
        result = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "素材文件不存在。", "RAW_FILE_NOT_FOUND")
        expected_version = int(source_version if source_version is not None else item.version or 1)
        current_version = int(item.version or 1)
        if current_version != expected_version:
            await session.rollback()
            return _stale_cleaning_result(expected_version, current_version)
        ext = dict(item.ext_fields or {})
        ext.update(
            {
                "cleanStatus": status,
                "cleanMessage": message,
                "cleanUpdatedAt": _now_iso(),
            }
        )
        if extra:
            ext.update(extra)
        update_result = await session.execute(
            update(RawFile)
            .where(RawFile.id == numeric_id, RawFile.version == expected_version)
            .values(ext_fields=ext)
            .execution_options(synchronize_session=False)
        )
        if update_result.rowcount != 1:
            await session.rollback()
            current_result = await session.execute(select(RawFile).where(RawFile.id == numeric_id))
            current_item = current_result.scalar_one_or_none()
            return _stale_cleaning_result(
                expected_version,
                int(current_item.version or 0) if current_item is not None else 0,
            )
        set_committed_value(item, "ext_fields", ext)
        payload = item.to_dict()
        await session.commit()
        return payload


async def _requeue_latest_cleaning(file_id: str, *, stale_version: int) -> dict[str, Any]:
    numeric_id = _numeric_raw_file_id(file_id)
    async with async_session() as session:
        result = await session.execute(
            select(RawFile).options(selectinload(RawFile.folder)).where(RawFile.id == numeric_id)
        )
        item = result.scalar_one_or_none()
        if item is None:
            return {"queued": False, "reason": "missing"}
        current_version = int(item.version or 1)
        ext = item.ext_fields or {}
        if current_version <= stale_version or str(ext.get("cleanStatus") or "") != "pending":
            return {"queued": False, "reason": "not_pending"}
        source_bucket = str(item.minio_bucket or settings.minio_buckets["materials"])
        source_key = str(item.minio_key or "")
        raw_bid_type = str(raw_file_bid_type(item) or "").strip()
        bid_type = normalize_material_bid_type(raw_bid_type)
    if not raw_bid_type:
        # 升级前历史素材可能完全缺失标类，兼容原有技术标链路。
        bid_type = TECHNICAL_BID_TYPE
    elif not bid_type:
        logger.warning("清洗补排发现素材 %s 携带非法 bidType=%r，已拒绝入队。", file_id, raw_bid_type)
        return {"queued": False, "reason": "invalid_bid_type"}
    return enqueue_cleaning_job(
        numeric_id,
        bid_type=bid_type,
        source_version=current_version,
        source_bucket=source_bucket,
        source_key=source_key,
    )


def _remove_cleaned_object_with_retries(bucket: str, key: str, *, attempts: int = 3) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            minio_client.remove_object(bucket, key)
            return True
        except Exception as exc:  # pragma: no cover - 重试失败路径依赖 MinIO 故障
            logger.warning(
                "清理 cleaned 对象 %s/%s 失败（%d/%d）：%s",
                bucket,
                key,
                attempt,
                attempts,
                exc,
            )
    return False


async def _discard_stale_artifact(
    file_id: str,
    *,
    source_version: int,
    bucket: str,
    key: str,
) -> None:
    _remove_cleaned_object_with_retries(bucket, key)
    await _requeue_latest_cleaning(file_id, stale_version=source_version)


async def _set_task_clean_status(
    file_id: str,
    source_version: int,
    status: str,
    message: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await set_material_clean_status(
        file_id,
        status,
        message,
        source_version=source_version,
        extra=extra,
    )
    if result.get("cleanStatus") == "stale":
        await _requeue_latest_cleaning(file_id, stale_version=source_version)
    return result


async def clean_material_file(
    file_id: str,
    data: dict[str, Any] | None = None,
    *,
    allow_convert: bool = False,
) -> dict[str, Any]:
    numeric_id = _numeric_raw_file_id(file_id)

    async with async_session() as session:
        result = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "素材文件不存在。", "RAW_FILE_NOT_FOUND")
        source_name = _safe_file_name(item.name, f"RAW-{numeric_id:04d}.bin")
        source_bucket = str(item.minio_bucket or settings.minio_buckets["materials"])
        source_key = str(item.minio_key or "")
        source_version = int(item.version or 1)

    task_data = data or {}
    task_source_version = task_data.get("sourceVersion")
    if task_data and task_source_version is None and source_version > 1:
        stale = _stale_cleaning_result(0, source_version)
        await _requeue_latest_cleaning(file_id, stale_version=0)
        return stale
    if task_source_version is not None:
        expected_version = int(task_source_version)
        if expected_version != source_version:
            stale = _stale_cleaning_result(expected_version, source_version)
            await _requeue_latest_cleaning(file_id, stale_version=expected_version)
            return stale
        source_version = expected_version

    # 非 Word 素材默认不清洗，直接标记保留原件（同时兜底修正历史 pending 任务）；
    # allow_convert=True（后台深度解析任务）时，PDF/XLSX 走 driver 转换出 Word。
    if not is_cleanable_material(source_name):
        if not (allow_convert and is_deep_convertible_material(source_name)):
            return await _set_task_clean_status(
                file_id,
                source_version,
                "original_only",
                "非 Word 素材保留原件，不触发自动清洗。",
            )

    converting_doc = PurePosixPath(source_name).suffix.lower() == ".doc"
    converting_non_word = not is_cleanable_material(source_name)
    cleaning_status = await _set_task_clean_status(
        file_id,
        source_version,
        "cleaning",
        (
            "正在通过 OnlyOffice 将 DOC 转换为 DOCX。"
            if converting_doc
            else ("正在后台转换为 Word 素材。" if converting_non_word else "正在清洗 Word 素材。")
        ),
    )
    if cleaning_status.get("cleanStatus") == "stale":
        return cleaning_status

    driver_path = _skill_driver_path()
    if not driver_path.exists():
        return await _set_task_clean_status(
            file_id,
            source_version,
            "failed",
            "bid-material-format-cleaner skill 未安装到后端镜像。",
            extra={"cleanError": str(driver_path)},
        )

    with tempfile.TemporaryDirectory(prefix=f"material-clean-RAW-{numeric_id:04d}-") as temp_root:
        root = Path(temp_root)
        source_dir = root / "source"
        output_dir = root / "cleaned"
        try:
            source_path = await _prepare_cleaning_source(
                source_name=source_name,
                source_bucket=source_bucket,
                source_key=source_key,
                source_version=source_version,
                source_dir=source_dir,
            )
        except Exception as exc:
            message = f"DOC 转 DOCX 失败：{exc}" if converting_doc else f"素材原件读取失败：{exc}"
            return await _set_task_clean_status(
                file_id,
                source_version,
                "failed",
                message,
                extra={"cleanError": message, "cleanResultStatus": "FAIL"},
            )
        driver_source_name = source_path.name

        env = os.environ.copy()
        env["FORMAT_CLEANER_ALLOW_SYSTEM_PY"] = "1"
        env.setdefault("PYTHONIOENCODING", "utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(driver_path),
                str(source_dir),
                "--output-dir",
                str(output_dir),
                "--no-feishu",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=int((data or {}).get("timeoutSec") or 30 * 60),
        )

        report_tail = _tail_output(proc.stdout, proc.stderr)
        manifest = _read_cleaning_manifest(output_dir)
        manifest_record = _cleaning_manifest_record(manifest, driver_source_name)
        driver_status, driver_detail = _extract_driver_line(proc.stdout, driver_source_name)
        if manifest_record:
            driver_status = str(manifest_record.get("status") or driver_status)
            driver_detail = str(manifest_record.get("detail") or driver_detail)

        cleaned_path = _resolve_cleaned_output(output_dir, manifest_record)

        if cleaned_path is None:
            message = "清洗失败，未生成 Word 文件。"
            if driver_detail:
                message = f"清洗失败：{driver_detail}"
            elif proc.stderr.strip():
                message = f"清洗失败：{proc.stderr.strip()[-300:]}"
            return await _set_task_clean_status(
                file_id,
                source_version,
                "failed",
                message,
                extra={
                    "cleanError": message,
                    "cleanLogTail": report_tail,
                    "cleanResultStatus": driver_status or "FAIL",
                    "cleanReport": _compact_cleaning_manifest(manifest, manifest_record),
                    "cleanRelativeSourcePath": str(manifest_record.get("relativeSourcePath") or ""),
                    "cleanRelativeOutputPath": str(manifest_record.get("relativeOutputPath") or ""),
                },
            )

        key = cleaned_object_key(numeric_id, source_name, source_version=source_version)
        bucket = settings.minio_buckets["materials"]
        minio_client.upload_file(bucket, key, cleaned_path, WORD_MEDIA_TYPE)
        size = cleaned_path.stat().st_size
        detail = driver_detail or ("清洗完成" if proc.returncode == 0 else "已生成 Word，需复核清洗日志")
        if converting_doc:
            detail = f"DOC 已通过 OnlyOffice 转换为 DOCX；{detail}"
        try:
            result = await set_material_clean_status(
                file_id,
                "cleaned",
                detail,
                source_version=source_version,
                extra={
                    "cleanResultStatus": driver_status or ("OK" if proc.returncode == 0 else "REVIEW"),
                    "cleanedMinioBucket": bucket,
                    "cleanedMinioKey": key,
                    "cleanedFileName": f"{PurePosixPath(source_name).stem}.docx",
                    "cleanedSize": size,
                    "cleanedAt": _now_iso(),
                    "cleanedSourceVersion": source_version,
                    "cleanedSourceKey": source_key,
                    "cleanLogTail": report_tail,
                    "cleanReport": _compact_cleaning_manifest(manifest, manifest_record),
                    "cleanRelativeSourcePath": source_name,
                    "cleanRelativeOutputPath": str(manifest_record.get("relativeOutputPath") or cleaned_path.name),
                    "cleanNeedsHumanReview": bool(manifest_record.get("needsHumanReview")),
                    "cleanUsableForRetrieval": bool(manifest_record.get("isUsableForRetrieval", True)),
                },
            )
            if result.get("cleanStatus") == "stale":
                await _discard_stale_artifact(
                    file_id,
                    source_version=source_version,
                    bucket=bucket,
                    key=key,
                )
            return result
        except Exception:
            # 状态写库失败时补偿删除刚上传的 cleaned 对象，避免孤儿文件（L6）
            _remove_cleaned_object_with_retries(bucket, key)
            raise


def clean_material_file_sync(file_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _get_sync_cleaning_loop().run_until_complete(clean_material_file(file_id, data))
