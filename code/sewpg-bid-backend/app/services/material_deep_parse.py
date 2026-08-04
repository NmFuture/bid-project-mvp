"""素材后台深度解析：PDF 全文提取、XLSX 后台转 Word、超大 docx 后台解析画像。

Wiki 整理请求内只做轻量同步解析（MAX_SYNC_DOCX_BYTES 上限）。以下素材过去
在 Wiki 整理时被直接 fallback 跳过：

- PDF/XLSX：清洗链路收束 Word-only 后永远没有清洗稿，"非 docx 无可解析正文"；
- 超上限 docx（含清洗稿）：parseError 终态，只有索引卡片。

本模块提供 ``material_deep_parse`` 后台任务（Redis 队列 + 本地线程兜底）：

1. PDF → extract 全文提取（优先于 convert）：PyMuPDF 文字层优先、扫描页 OCR 兜底，
   全文写 MinIO ``parsed/RAW-xxx/v<n>/fulltext.md``，同构画像回写 ext_fields；
2. XLSX 无清洗稿 → 复用 bid-material-format-cleaner driver 转出 cleaned docx
   （extract 关闭时 PDF 也回落到该分支）；
3. 目标 docx 仍超上限 → 后台流式解析，画像写入 ``ext_fields["deepParseProfile"]``。

转换分支只响应带 ``allowConvert`` 标记的排队请求（技术标预览闸口）；
商务标闸口不带该标记，非 Word 素材维持"暂不支持"终态。

Wiki 预览/画像下次刷新时自动采用产物升级，不再终态跳过。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import async_session
from app.models.materials import RawFile
from app.services.material_cleaned_artifact import cleaned_artifact_is_current
from app.services.job_queue import enqueue_generation_job
from app.services.local_job_executor import submit_local_job
from app.services.material_cleaning import (
    clean_material_file,
    is_cleanable_material,
    is_deep_convertible_material,
)
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError
from app.services.wiki_blueprint_common import MAX_SYNC_DOCX_BYTES, extract_docx_profile

logger = logging.getLogger(__name__)

DEEP_PARSE_JOB_TYPE = "material_deep_parse"
DEEP_PARSE_PROFILE_FIELD = "deepParseProfile"
DEEP_PARSE_STATUS_FIELD = "deepParseStatus"
DEEP_PARSE_MESSAGE_FIELD = "deepParseMessage"
DEEP_PARSE_UPDATED_AT_FIELD = "deepParseUpdatedAt"
DEEP_PARSE_FAIL_COUNT_FIELD = "deepParseFailCount"
DEEP_PARSE_PROFILE_SCHEMA = 1


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except ValueError:
        return default


# PDF 全文提取（kind="extract"）配置：默认值为本地安全值，
# 5090 实测取值只写 docker-compose.5090.yml，不动这里。
PDF_EXTRACT_ENABLED = os.getenv("TECH_WIKI_PDF_EXTRACT_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "off",
    "no",
}
PDF_EXTRACT_MAX_PAGES = _env_int("TECH_WIKI_EXTRACT_MAX_PAGES", 80)
PDF_EXTRACT_OCR_PAGE_CONCURRENCY = _env_int("TECH_WIKI_EXTRACT_OCR_PAGE_CONCURRENCY", 4)
# 闸口侧：extract 连续失败达到上限后转终态，不再每次刷新都补排。
PDF_EXTRACT_MAX_FAILURES = 3
# 单页文字层低于该字数判定为扫描页，走 OCR 兜底（沿用证书台账的文字层优先模式）。
PDF_TEXT_LAYER_MIN_CHARS = 20
# 摘录截断策略：防预览签名与 LLM prompt 膨胀。
EXCERPT_PARAGRAPH_LIMIT = 20
EXCERPT_PARAGRAPH_CHARS = 200
EXCERPT_TOTAL_CHARS = 4000
_HEADING_NUMBER_PATTERN = re.compile(
    r"^(?:第[一二三四五六七八九十百\d]+[章节条篇]|\d+(?:\.\d+){0,3}[、.．\s]|[一二三四五六七八九十]+[、.．])"
)

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
    """判断素材需要的后台处理：extract（PDF 全文提取）/ convert（XLSX 转 Word）/ parse（超大 docx 解析）/ ""。"""

    ext = ext_fields if isinstance(ext_fields, dict) else {}
    suffix = PurePosixPath(str(name or "")).suffix.lower()
    has_cleaned = bool(str(ext.get("cleanedMinioKey") or ""))
    # PDF 优先 extract 全文提取：convert 链的图片 docx 无文本，Wiki 链只依赖
    # extract（设计文档 §3.1）；extract 关闭时 PDF 回落到下面的 convert 分支。
    if suffix == ".pdf" and PDF_EXTRACT_ENABLED:
        return "extract"
    if is_deep_convertible_material(name) and not has_cleaned:
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
            ext[DEEP_PARSE_FAIL_COUNT_FIELD] = 0
            ext[DEEP_PARSE_PROFILE_FIELD] = {
                "schemaVersion": DEEP_PARSE_PROFILE_SCHEMA,
                "sourceKey": source_key,
                "sourceSize": source_size,
                "parsedAt": _now_iso(),
                "profile": profile,
            }
        elif status == "failed":
            # 连续失败计数供闸口判断何时转终态，成功（产物回写）时清零。
            try:
                ext[DEEP_PARSE_FAIL_COUNT_FIELD] = int(ext.get(DEEP_PARSE_FAIL_COUNT_FIELD) or 0) + 1
            except (TypeError, ValueError):
                ext[DEEP_PARSE_FAIL_COUNT_FIELD] = 1
        item.ext_fields = ext
        await session.commit()


def _pdf_text_layers(data_bytes: bytes, max_pages: int) -> tuple[int, list[str]]:
    """逐页抽 PDF 文字层（同步 CPU 调用，调用方放线程执行）。"""

    import fitz

    document = fitz.open(stream=data_bytes, filetype="pdf")
    try:
        total_pages = len(document)
        processed = min(total_pages, max_pages)
        texts = [str(document.load_page(index).get_text() or "").strip() for index in range(processed)]
        return total_pages, texts
    finally:
        document.close()


def _render_pages_png(data_bytes: bytes, page_indexes: list[int]) -> dict[int, bytes]:
    """把指定页渲染成 PNG（同步 CPU 调用，调用方放线程执行）。"""

    import fitz

    document = fitz.open(stream=data_bytes, filetype="pdf")
    try:
        out: dict[int, bytes] = {}
        for index in page_indexes:
            page = document.load_page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            out[index] = pix.tobytes("png")
        return out
    finally:
        document.close()


def _guess_pdf_headings(lines: list[str], fallback_title: str) -> list[dict[str, Any]]:
    """PDF 无样式信息，用短行 + 编号前缀启发式猜 Heading；猜不到以文件名兜底。"""

    headings: list[dict[str, Any]] = []
    for raw_line in lines:
        text = raw_line.strip()
        if not 4 <= len(text) <= 60:
            continue
        if text.endswith(("。", "；", ";", "，", ",")):
            continue
        if _HEADING_NUMBER_PATTERN.match(text) or (text.isupper() and any(char.isalpha() for char in text)):
            headings.append({"level": 1, "title": text[:80]})
        if len(headings) >= 30:
            break
    if not headings and fallback_title:
        headings = [{"level": 1, "title": fallback_title[:80]}]
    return headings


def _excerpt_paragraphs(lines: list[str]) -> list[str]:
    """摘录截断：首段 + 中段均匀采样 + 尾段，段数/单段/总量均有上限。"""

    candidates = [re.sub(r"\s+", " ", line).strip() for line in lines]
    candidates = [line for line in candidates if len(line) >= 8]
    if not candidates:
        return []
    picked: list[str] = []
    total = 0

    def add(text: str) -> None:
        nonlocal total
        text = text[:EXCERPT_PARAGRAPH_CHARS]
        if text in picked or len(picked) >= EXCERPT_PARAGRAPH_LIMIT:
            return
        if total + len(text) > EXCERPT_TOTAL_CHARS:
            return
        picked.append(text)
        total += len(text)

    for line in candidates[:3]:
        add(line)
    middle = candidates[3:-1]
    if middle:
        budget = max(1, EXCERPT_PARAGRAPH_LIMIT - len(picked) - 1)
        step = max(1, len(middle) // budget)
        for line in middle[::step]:
            add(line)
    add(candidates[-1])
    return picked


def fulltext_object_key(raw_file_id: int, source_version: int) -> str:
    return f"parsed/RAW-{raw_file_id:04d}/v{int(source_version or 1)}/fulltext.md"


async def _run_extract_job(
    numeric_id: int,
    *,
    source_name: str,
    source_bucket: str,
    source_key: str,
    source_size: int,
    source_version: int,
) -> dict[str, Any]:
    """PDF 全文提取：文字层优先、扫描页 OCR 兜底，全文落 MinIO，画像回写。"""

    await _write_deep_parse_status(numeric_id, "running", "后台全文提取中（文字层优先，扫描页 OCR 兜底）。")
    try:
        data_bytes = await asyncio.to_thread(minio_client.get_object, source_bucket, source_key)
        total_pages, page_texts = await asyncio.to_thread(_pdf_text_layers, data_bytes, PDF_EXTRACT_MAX_PAGES)
        if not total_pages:
            message = "后台全文提取失败：PDF 无页面。"
            await _write_deep_parse_status(numeric_id, "failed", message)
            return {"deepParseStatus": "failed", "deepParseMessage": message}
        processed_pages = len(page_texts)
        truncated = total_pages > processed_pages

        ocr_page_indexes = [
            index for index, text in enumerate(page_texts) if len(text) < PDF_TEXT_LAYER_MIN_CHARS
        ]
        ocr_failed_pages = 0
        if ocr_page_indexes:
            page_pngs = await asyncio.to_thread(_render_pages_png, data_bytes, ocr_page_indexes)
            semaphore = asyncio.Semaphore(PDF_EXTRACT_OCR_PAGE_CONCURRENCY)
            stem = PurePosixPath(source_name).stem or f"RAW-{numeric_id:04d}"

            async def _ocr_one(page_index: int) -> tuple[int, str]:
                # 按页送 OCR：绕开整本 maxTokens 上限，OCR 服务自身有并发与重试。
                from app.services.ocr_service import ocr_service

                async with semaphore:
                    try:
                        text, _info = await ocr_service.recognize_text_for_parse(
                            file_name=f"{stem}-p{page_index + 1}.png",
                            content=page_pngs[page_index],
                            mime_type="image/png",
                        )
                        return page_index, str(text or "").strip()
                    except Exception as exc:  # noqa: BLE001 - 单页 OCR 失败不拖垮整本
                        logger.warning("extract OCR page %s failed for RAW-%04d: %s", page_index + 1, numeric_id, exc)
                        return page_index, ""

            for page_index, text in await asyncio.gather(*[_ocr_one(i) for i in ocr_page_indexes]):
                if text:
                    page_texts[page_index] = text
                else:
                    ocr_failed_pages += 1

        if not any(page_texts):
            message = "后台全文提取失败：文字层为空且 OCR 未获得任何文本（请检查 OCR 配置）。"
            await _write_deep_parse_status(numeric_id, "failed", message)
            return {"deepParseStatus": "failed", "deepParseMessage": message}

        parts = [
            f"<!-- 第 {index + 1} 页 -->\n\n{text or '（本页未提取到文本）'}"
            for index, text in enumerate(page_texts)
        ]
        fulltext = "\n\n".join(parts)
        bucket = str(settings.minio_buckets["materials"])
        fulltext_key = fulltext_object_key(numeric_id, source_version)
        await asyncio.to_thread(
            minio_client.put_object,
            bucket,
            fulltext_key,
            fulltext.encode("utf-8"),
            "text/markdown; charset=utf-8",
        )

        content_lines = [line for line in fulltext.splitlines() if not line.startswith("<!--")]
        profile: dict[str, Any] = {
            "headings": _guess_pdf_headings(content_lines, PurePosixPath(source_name).stem),
            "bodyHeadings": [],
            "paragraphs": _excerpt_paragraphs(content_lines),
            "tables": [],
            "tableCount": 0,
            "parseError": "",
            "source": "pdfExtract",
            "pageCount": total_pages,
            "processedPages": processed_pages,
            "truncated": truncated,
            "ocrPages": len(ocr_page_indexes),
            "ocrFailedPages": ocr_failed_pages,
            "charCount": len(fulltext),
            "fulltextBucket": bucket,
            "fulltextKey": fulltext_key,
        }
        message = (
            f"后台全文提取完成：{processed_pages}/{total_pages} 页，"
            f"OCR {len(ocr_page_indexes)} 页，全文 {len(fulltext)} 字。"
        )
        if truncated:
            message += f"（超过页数护栏 {PDF_EXTRACT_MAX_PAGES} 页，已截断）"
        await _write_deep_parse_status(
            numeric_id,
            "parsed",
            message,
            profile=profile,
            source_key=source_key,
            source_size=source_size,
        )
        return {"deepParseStatus": "parsed", "deepParseMessage": message}
    except PeripheralError:
        raise
    except Exception as exc:  # noqa: BLE001 - 任务失败要显式写状态，不能静默
        logger.exception("extract job failed for RAW-%04d", numeric_id)
        message = f"后台全文提取失败：{exc}"
        await _write_deep_parse_status(numeric_id, "failed", message)
        return {"deepParseStatus": "failed", "deepParseMessage": message}


async def pdf_fulltext_for_raw_file(file_id: str) -> dict[str, Any]:
    """读取 PDF extract 产物全文，供 Wiki 卡片「查看全文」。"""

    numeric_id = _numeric_raw_file_id(file_id)
    async with async_session() as session:
        item = await session.get(RawFile, numeric_id)
        if item is None:
            raise PeripheralError(404, "素材文件不存在。", "RAW_FILE_NOT_FOUND")
        name = str(item.name or "")
        ext_fields = dict(item.ext_fields or {})
        source_key = str(item.minio_key or "")
        source_version = int(getattr(item, "version", 1) or 1)

    if PurePosixPath(name).suffix.lower() != ".pdf":
        raise PeripheralError(400, "仅 PDF 素材支持查看提取全文。", "FULLTEXT_FILE_TYPE_INVALID")
    profile = deep_parse_profile_for(ext_fields, source_key)
    if not profile or not str(profile.get("fulltextKey") or ""):
        raise PeripheralError(404, "该素材尚未生成全文提取产物，请先触发 Wiki 刷新排队提取。", "FULLTEXT_NOT_READY")
    # 不信任元数据里的 fulltextBucket/fulltextKey（extFields 可被外部写入，越界读其他对象）：
    # bucket 固定取配置里的 materials 桶，key 按素材 id+版本本地重算，profile 仅作存在性判断。
    bucket = str(settings.minio_buckets["materials"])
    fulltext_key = fulltext_object_key(numeric_id, source_version)
    data = await asyncio.to_thread(minio_client.get_object, bucket, fulltext_key)
    text = data.decode("utf-8", errors="replace")
    return {
        "fileId": f"RAW-{numeric_id:04d}",
        "name": name,
        "text": text,
        "pageCount": int(profile.get("pageCount") or 0),
        "processedPages": int(profile.get("processedPages") or 0),
        "truncated": bool(profile.get("truncated")),
        "charCount": int(profile.get("charCount") or len(text)),
    }


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
        source_size = int(item.size_bytes or 0)
        source_version = int(getattr(item, "version", 1) or 1)
        ext_fields = dict(item.ext_fields or {})

    # PDF 走全文提取作业（文字层 + OCR 兜底），与超大 DOCX 画像解析共用同一任务框架。
    if raw_file_deep_parse_kind(source_name, ext_fields) == "extract":
        return await _run_extract_job(
            numeric_id,
            source_name=source_name,
            source_bucket=source_bucket,
            source_key=source_key,
            source_size=source_size,
            source_version=source_version,
        )

    await _write_deep_parse_status(numeric_id, "running", "后台深度解析中。")

    try:
        suffix = PurePosixPath(source_name).suffix.lower()
        cleaned_key = (
            str(ext_fields.get("cleanedMinioKey") or "")
            if (is_cleanable_material(source_name) or is_deep_convertible_material(source_name))
            and cleaned_artifact_is_current(int(getattr(item, "version", 1) or 1), ext_fields)
            else ""
        )
        cleaned_bucket = str(ext_fields.get("cleanedMinioBucket") or source_bucket)

        # 1) PDF/XLSX 无清洗稿 → 后台转 Word（复用清洗 driver 与产物约定）。
        # 仅技术标预览闸口排队时带 allowConvert 标记才走转换；商务侧排队不带
        # 该标记，维持"暂不支持"终态，不改变商务标现有行为。
        if suffix != ".docx" and not cleaned_key:
            if not ((data or {}).get("allowConvert") and is_deep_convertible_material(source_name)):
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

        # 2) 目标 DOCX 仍超同步上限时，后台解析画像写入 ext_fields。
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
