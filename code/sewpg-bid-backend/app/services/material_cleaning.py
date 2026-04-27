from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import BASE_DIR, settings
from app.models import async_session
from app.models.materials import RawFile
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError

logger = logging.getLogger(__name__)

WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CLEANABLE_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".docx", ".doc"}
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


def is_cleanable_material(name: str) -> bool:
    return PurePosixPath(str(name or "")).suffix.lower() in CLEANABLE_SUFFIXES


def cleaned_object_key(raw_file_id: int, file_name: str) -> str:
    stem = PurePosixPath(_safe_file_name(file_name, f"RAW-{raw_file_id:04d}.docx")).stem
    return f"cleaned/RAW-{raw_file_id:04d}/{uuid4().hex}-{stem}.docx"


def _get_sync_cleaning_loop() -> asyncio.AbstractEventLoop:
    global _sync_cleaning_loop
    if _sync_cleaning_loop is None or _sync_cleaning_loop.is_closed():
        _sync_cleaning_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_sync_cleaning_loop)
    return _sync_cleaning_loop


def _skill_driver_path() -> Path:
    return BASE_DIR / "opencode" / "skill" / "format-cleaner-v4" / "scripts" / "driver.py"


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


async def set_material_clean_status(
    file_id: str,
    status: str,
    message: str,
    *,
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
        item.ext_fields = ext
        await session.flush()
        await session.refresh(item, attribute_names=["updated_at"])
        payload = item.to_dict()
        await session.commit()
        return payload


async def clean_material_file(file_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    numeric_id = _numeric_raw_file_id(file_id)
    await set_material_clean_status(file_id, "cleaning", "正在清洗素材并转换为 Word。")

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

    if not is_cleanable_material(source_name):
        return await set_material_clean_status(
            file_id,
            "failed",
            "当前格式暂不支持自动清洗转换。",
            extra={"cleanError": f"unsupported suffix: {PurePosixPath(source_name).suffix.lower() or 'none'}"},
        )

    driver_path = _skill_driver_path()
    if not driver_path.exists():
        return await set_material_clean_status(
            file_id,
            "failed",
            "format-cleaner-v4 skill 未安装到后端镜像。",
            extra={"cleanError": str(driver_path)},
        )

    with tempfile.TemporaryDirectory(prefix=f"material-clean-RAW-{numeric_id:04d}-") as temp_root:
        root = Path(temp_root)
        source_dir = root / "source"
        output_dir = root / "cleaned"
        source_path = source_dir / source_name
        minio_client.download_file(source_bucket, source_key, source_path)

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

        candidates = sorted(output_dir.rglob("*.docx"), key=lambda path: path.stat().st_mtime, reverse=True)
        report_tail = _tail_output(proc.stdout, proc.stderr)
        driver_status, driver_detail = _extract_driver_line(proc.stdout, source_name)

        if not candidates:
            message = "清洗失败，未生成 Word 文件。"
            if driver_detail:
                message = f"清洗失败：{driver_detail}"
            elif proc.stderr.strip():
                message = f"清洗失败：{proc.stderr.strip()[-300:]}"
            return await set_material_clean_status(
                file_id,
                "failed",
                message,
                extra={
                    "cleanError": message,
                    "cleanLogTail": report_tail,
                    "cleanResultStatus": driver_status or "FAIL",
                },
            )

        cleaned_path = candidates[0]
        key = cleaned_object_key(numeric_id, source_name)
        bucket = settings.minio_buckets["materials"]
        minio_client.upload_file(bucket, key, cleaned_path, WORD_MEDIA_TYPE)
        size = cleaned_path.stat().st_size
        detail = driver_detail or ("清洗完成" if proc.returncode == 0 else "已生成 Word，需复核清洗日志")
        return await set_material_clean_status(
            file_id,
            "cleaned",
            detail,
            extra={
                "cleanResultStatus": driver_status or ("OK" if proc.returncode == 0 else "REVIEW"),
                "cleanedMinioBucket": bucket,
                "cleanedMinioKey": key,
                "cleanedFileName": f"{PurePosixPath(source_name).stem}.docx",
                "cleanedSize": size,
                "cleanedAt": _now_iso(),
                "cleanLogTail": report_tail,
            },
        )


def clean_material_file_sync(file_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _get_sync_cleaning_loop().run_until_complete(clean_material_file(file_id, data))
