"""素材后台深度解析：PDF/XLSX 后台转 Word、超大 docx 后台解析画像。

Wiki 整理请求内只做轻量同步解析（MAX_SYNC_DOCX_BYTES 上限）。以下素材过去
在 Wiki 整理时被直接 fallback 跳过：

- PDF/XLSX：清洗链路收束 Word-only 后永远没有清洗稿，"非 docx 无可解析正文"；
- 超上限 docx（含清洗稿）：parseError 终态，只有索引卡片。

本模块提供 ``material_deep_parse`` 后台任务（Redis 队列 + 本地线程兜底）：

1. PDF/XLSX 无清洗稿 → 复用 bid-material-format-cleaner driver 转出 cleaned docx；
2. 目标 docx 仍超上限 → 后台流式解析，画像写入 ``ext_fields["deepParseProfile"]``。

Wiki 预览/画像下次刷新时自动采用产物升级，不再终态跳过。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile
from app.services.job_queue import enqueue_generation_job
from app.services.local_job_executor import submit_local_job
from app.services.material_cleaning import clean_material_file, is_deep_convertible_material
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError
from app.services.wiki_blueprint_common import MAX_SYNC_DOCX_BYTES, extract_docx_profile

logger = logging.getLogger(__name__)

DEEP_PARSE_JOB_TYPE = "material_deep_parse"
DEEP_PARSE_PROFILE_FIELD = "deepParseProfile"
DEEP_PARSE_STATUS_FIELD = "deepParseStatus"
DEEP_PARSE_MESSAGE_FIELD = "deepParseMessage"
DEEP_PARSE_UPDATED_AT_FIELD = "deepParseUpdatedAt"
DEEP_PARSE_PROFILE_SCHEMA = 1

# 本地兜底模式下正在执行的素材（Redis 模式由 job 锁天然去重）
_local_inflight: set[str] = set()
_local_inflight_lock = threading.Lock()
_sync_deep_parse_loop: asyncio.AbstractEventLoop | None = None


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


def raw_file_deep_parse_kind(name: str, ext_fields: dict[str, Any] | None) -> str:
    """判断素材需要的后台处理：convert（PDF/XLSX 转 Word）/ parse（超大 docx 解析）/ ""。"""

    ext = ext_fields if isinstance(ext_fields, dict) else {}
    suffix = PurePosixPath(str(name or "")).suffix.lower()
    has_cleaned = bool(str(ext.get("cleanedMinioKey") or ""))
    if suffix in {".pdf", ".xlsx", ".xls", ".xlsm"} and not has_cleaned:
        return "convert"
    if suffix == ".docx" or has_cleaned:
        parse_size = (
            int(ext.get("cleanedSize") or 0) if has_cleaned else 0
        ) or 0
        if not parse_size:
            return "parse"  # 无大小信息时交给后台判定，宁可多排一次
        if parse_size > MAX_SYNC_DOCX_BYTES:
            return "parse"
    return ""


def deep_parse_profile_for(ext_fields: dict[str, Any] | None, current_key: str) -> dict[str, Any] | None:
    """读取与当前 cleaned/原始对象匹配的后台解析画像；不匹配（产物已过期）返回 None。"""

    ext = ext_fields if isinstance(ext_fields, dict) else {}
    deep = ext.get(DEEP_PARSE_PROFILE_FIELD)
    if not isinstance(deep, dict):
        return None
    if str(deep.get("sourceKey") or "") != str(current_key or ""):
        return None
    profile = deep.get("profile")
    return profile if isinstance(profile, dict) else None


def _parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def deep_parse_status_allows_enqueue(ext_fields: dict[str, Any] | None, *, stale_after_sec: int = 1800) -> bool:
    """判断当前是否应再入队：worker 崩溃会把状态卡在 running，超时后允许补排。"""

    ext = ext_fields if isinstance(ext_fields, dict) else {}
    if str(ext.get(DEEP_PARSE_STATUS_FIELD) or "") != "running":
        return True
    updated = _parse_iso(ext.get(DEEP_PARSE_UPDATED_AT_FIELD))
    if updated is None:
        return True
    return (datetime.now(UTC) - updated).total_seconds() > stale_after_sec


def enqueue_deep_parse_job(file_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """入队素材深度解析；Redis 不可用走本地串行线程兜底。队列锁/本地登记表去重。"""

    value = str(file_id or "").strip()
    if not value:
        return {"queued": False, "message": "缺少素材 ID"}
    raw_id = value if value.upper().startswith("RAW-") else f"RAW-{int(value):04d}"
    payload = {"fileId": raw_id, **(data or {})}
    try:
        result = enqueue_generation_job(DEEP_PARSE_JOB_TYPE, raw_id, payload)
    except Exception as exc:  # pragma: no cover - 队列故障不应阻断 wiki 整理
        logger.warning("enqueue deep parse job failed for %s: %s", raw_id, exc)
        result = None
    if result is not None and (result.queued or result.locked):
        return {"queued": result.queued, "jobId": result.job_id, "locked": result.locked}

    with _local_inflight_lock:
        if raw_id in _local_inflight:
            return {"queued": True, "local": True, "deduped": True}
        _local_inflight.add(raw_id)
    submit_local_job(_run_local_deep_parse, raw_id, payload)
    return {"queued": True, "local": True}


def _run_local_deep_parse(file_id: str, data: dict[str, Any]) -> None:
    try:
        deep_parse_material_file_sync(file_id, data)
    except Exception:  # pragma: no cover - 本地兜底失败仅记录
        logger.exception("local deep parse job failed: %s", file_id)
    finally:
        with _local_inflight_lock:
            _local_inflight.discard(file_id)


async def _write_deep_parse_status(
    numeric_id: int,
    status: str,
    message: str,
    *,
    profile: dict[str, Any] | None = None,
    source_key: str = "",
    source_size: int = 0,
) -> None:
    async with async_session() as session:
        item = await session.get(RawFile, numeric_id)
        if item is None:
            return
        ext = dict(item.ext_fields or {})
        ext[DEEP_PARSE_STATUS_FIELD] = status
        ext[DEEP_PARSE_MESSAGE_FIELD] = message
        ext[DEEP_PARSE_UPDATED_AT_FIELD] = _now_iso()
        if profile is not None:
            ext[DEEP_PARSE_PROFILE_FIELD] = {
                "schemaVersion": DEEP_PARSE_PROFILE_SCHEMA,
                "sourceKey": source_key,
                "sourceSize": source_size,
                "parsedAt": _now_iso(),
                "profile": profile,
            }
        item.ext_fields = ext
        await session.commit()


async def deep_parse_material_file(file_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    numeric_id = _numeric_raw_file_id(file_id)
    async with async_session() as session:
        result = await session.execute(
            select(RawFile).where(RawFile.id == numeric_id).options(selectinload(RawFile.folder))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise PeripheralError(404, "素材文件不存在。", "RAW_FILE_NOT_FOUND")
        source_name = str(item.name or "")
        source_bucket = str(item.minio_bucket or "")
        source_key = str(item.minio_key or "")
        ext_fields = dict(item.ext_fields or {})

    await _write_deep_parse_status(numeric_id, "running", "后台深度解析中。")

    try:
        suffix = PurePosixPath(source_name).suffix.lower()
        cleaned_key = str(ext_fields.get("cleanedMinioKey") or "")
        cleaned_bucket = str(ext_fields.get("cleanedMinioBucket") or source_bucket)

        # 1) PDF/XLSX 无清洗稿 → 后台转 Word（复用清洗 driver 与产物约定）
        if suffix != ".docx" and not cleaned_key:
            if not is_deep_convertible_material(source_name):
                message = f"暂不支持后台解析 {suffix or '未知'} 类型素材。"
                await _write_deep_parse_status(numeric_id, "failed", message)
                return {"deepParseStatus": "failed", "deepParseMessage": message}
            convert_result = await clean_material_file(
                file_id,
                {**(data or {}), "convertNonWord": True},
                allow_convert=True,
            )
            async with async_session() as session:
                refreshed = await session.get(RawFile, numeric_id)
                ext_fields = dict(refreshed.ext_fields or {}) if refreshed is not None else {}
            cleaned_key = str(ext_fields.get("cleanedMinioKey") or "")
            cleaned_bucket = str(ext_fields.get("cleanedMinioBucket") or source_bucket)
            if not cleaned_key:
                message = str(
                    convert_result.get("cleanMessage") or "PDF/XLSX 后台转换未生成 Word 文件。"
                )
                await _write_deep_parse_status(numeric_id, "failed", message)
                return {"deepParseStatus": "failed", "deepParseMessage": message}

        # 2) 目标 docx 仍超同步上限 → 后台解析画像写入 ext_fields
        has_cleaned = bool(cleaned_key)
        if not has_cleaned and suffix != ".docx":
            message = f"暂不支持后台解析 {suffix or '未知'} 类型素材。"
            await _write_deep_parse_status(numeric_id, "failed", message)
            return {"deepParseStatus": "failed", "deepParseMessage": message}
        target_bucket = cleaned_bucket if has_cleaned else source_bucket
        target_key = cleaned_key if has_cleaned else source_key
        target_size = int(ext_fields.get("cleanedSize") or 0) if has_cleaned else 0
        if not target_size and not has_cleaned:
            async with async_session() as session:
                current = await session.get(RawFile, numeric_id)
                target_size = int(current.size_bytes or 0) if current is not None else 0

        if target_size and target_size <= MAX_SYNC_DOCX_BYTES:
            message = "已生成可同步解析的 Word 清洗稿，无需深度解析。" if has_cleaned else "素材未超同步解析上限。"
            await _write_deep_parse_status(numeric_id, "ready", message)
            return {"deepParseStatus": "ready", "deepParseMessage": message}

        data_bytes = minio_client.get_object(target_bucket, target_key)
        profile = extract_docx_profile(data_bytes, heading_limit=None)
        if profile.get("parseError"):
            message = f"后台深度解析失败：{profile['parseError']}"
            await _write_deep_parse_status(numeric_id, "failed", message)
            return {"deepParseStatus": "failed", "deepParseMessage": message}

        heading_count = len(profile.get("headings") or [])
        message = f"后台深度解析完成：抽取 Heading {heading_count} 个。"
        await _write_deep_parse_status(
            numeric_id,
            "parsed",
            message,
            profile=profile,
            source_key=target_key,
            source_size=target_size,
        )
        return {"deepParseStatus": "parsed", "deepParseMessage": message}
    except PeripheralError:
        raise
    except Exception as exc:  # noqa: BLE001 - 任务失败要显式写状态，不能静默
        logger.exception("deep parse failed for RAW-%04d", numeric_id)
        message = f"后台深度解析失败：{exc}"
        await _write_deep_parse_status(numeric_id, "failed", message)
        return {"deepParseStatus": "failed", "deepParseMessage": message}


def _get_sync_deep_parse_loop() -> asyncio.AbstractEventLoop:
    global _sync_deep_parse_loop
    if _sync_deep_parse_loop is None or _sync_deep_parse_loop.is_closed():
        _sync_deep_parse_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_sync_deep_parse_loop)
    return _sync_deep_parse_loop


def deep_parse_material_file_sync(file_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _get_sync_deep_parse_loop().run_until_complete(deep_parse_material_file(file_id, data))
