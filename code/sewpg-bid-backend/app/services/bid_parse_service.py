from __future__ import annotations

import asyncio
import copy
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from uuid import uuid4

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.bid_parse_state import (
    TERMINAL_PARSE_STATUSES,
    cancel_parse_progress_state,
    complete_parse_state,
    parse_progress_snapshot_state,
    start_parse_progress_state,
    update_parse_result_state,
    update_parse_progress_state,
    update_template_files_state,
)
from app.services.bid_runtime_state import now_iso, read_json_file
from app.services.bid_project_state import project_parse_input_records
from app.services.bid_project_service import BidProjectService, business_project_service, technical_project_service
from app.services.bid_type import require_bid_type
from app.services.business_parse_assets import (
    BusinessParseAssetError,
    approve_all_business_appendix_assets,
    approve_all_business_commitment_letter_assets,
    approve_business_appendix_asset,
    approve_business_commitment_letter_asset,
    approve_business_scoring_asset,
)
from app.services.business_template_extractor import convert_extractor_appendices
from app.services.file_utils import format_size_mb
from app.services.onlyoffice_documents import WORD_MEDIA_TYPE, build_editor_session_key
from app.services.opencode_client import OpencodeClient
from app.services.parse_profiles import BUSINESS_PARSE_PROFILE, TECHNICAL_PARSE_PROFILE
from app.services.technical_parse_assets import (
    TechnicalParseAssetError,
    set_all_technical_appendix_assets_selected,
    set_technical_appendix_asset_selected,
)
from app.services.job_queue import enqueue_generation_job, find_active_jobs_of_type, is_generation_locked
from app.services.local_job_executor import submit_local_job
from app.services.url_utils import absolute_url, onlyoffice_backend_base_url
from app.services.parsing import (
    IMAGE_SUFFIXES,
    _project_basics_project_prefill,
    extract_docx_text,
    materialize_appendix_docx,
    materialize_business_commitment_letter_docx,
    materialize_parse_appendix_docx_assets,
    materialize_parse_business_commitment_letter_docx_assets,
    parse_tender_documents,
)
from app.services.workspace_artifacts import cleanup_parse_temp_workspace, promote_parse_artifacts_to_workspace
from app.services.workspace_project_access import persist_workspace_project_state, require_workspace_project_for_update


_CHUNK_SIZE = 1024 * 1024


async def _parse_tender_documents_async(
    project_id: str,
    tender_files: list[dict[str, Any]],
    *,
    bid_type: str,
    progress_callback=None,
    cancel_check=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return await asyncio.to_thread(
        parse_tender_documents,
        project_id,
        tender_files,
        bid_type=bid_type,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


S1_PARSE_JOB_TYPE = "s1_parse"
S1_PARSE_LOCKED_DETAIL = "当前项目已有解析任务在进行中，请等待完成后再发起。"
S1_PARSE_QUEUED_MESSAGE = "解析任务已提交，后台运行中，可随时离开本页。"


def _parse_file_names(tender_files: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("name") or "").strip() for item in tender_files if str(item.get("name") or "").strip()]


def _parse_files_label(tender_files: list[dict[str, Any]]) -> str:
    """给用户看的解析目标简述：1 个写文件名，多个写「a」「b」，超过 3 个写「a」等 N 个。"""

    names = _parse_file_names(tender_files)
    if not names:
        return f"{len(tender_files)} 个招标文件"
    if len(names) <= 3:
        return "、".join(f"「{name}」" for name in names)
    return f"「{names[0]}」等 {len(names)} 个文件"


def _s1_parse_global_busy_detail(project_id: str) -> str:
    """同一时间只允许一个解析任务（opencode 全局并发=1）。发现其他项目的任务在
    执行/排队时返回 409 文案（含正在解析的文件名），否则返回空串。"""

    for job in find_active_jobs_of_type(S1_PARSE_JOB_TYPE):
        if str(job.get("projectId") or "") == str(project_id):
            continue  # 同项目冲突由项目锁 409 覆盖
        data = job.get("data") if isinstance(job.get("data"), dict) else {}
        tender_files = data.get("tenderFiles") if isinstance(data.get("tenderFiles"), list) else []
        label = _parse_files_label(tender_files) if tender_files else ""
        if label:
            return f"当前正在解析{label}，每次只能解析一个任务，请等待完成后再发起。"
        return "当前已有其他项目的解析任务在进行中，每次只能解析一个任务，请等待完成后再发起。"
    return ""

# 命中以下特征的异常按瞬时错误处理并自动重试；HTTPException（入参/状态类错误）与取消不重试。
_RETRYABLE_PARSE_ERROR_MARKERS = (
    "429",
    "502",
    "503",
    "504",
    "too many requests",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "database is locked",
    "deadlock",
)


def _is_retryable_parse_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPException):
        return False
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE_PARSE_ERROR_MARKERS)


def _schedule_s1_parse_job(project_id: str, data: dict[str, Any]) -> tuple[str, str]:
    """调度 S1 解析任务：优先 Redis 队列，Redis 不可用时降级本地串行线程（与目录/正文生成一致）。

    返回 (mode, job_id)：queued=已入队；local=本地兜底；locked=同项目已有任务。
    """

    queue_result = enqueue_generation_job(S1_PARSE_JOB_TYPE, project_id, data)
    if queue_result.queued:
        return "queued", queue_result.job_id
    if queue_result.locked:
        return "locked", ""
    submit_local_job(_run_s1_parse_job, project_id, data)
    return "local", ""


def _run_s1_parse_job(project_id: str, data: dict[str, Any]) -> None:
    """worker/本地线程入口：按任务绑定的标类分发到对应解析服务执行。"""

    bid_type = require_bid_type(
        data.get("__bidType"),
        error_message="解析任务必须显式绑定技术标或商务标。",
    )
    service = business_parse_service if bid_type == BUSINESS_PARSE_PROFILE.bid_type else technical_parse_service
    service.execute_s1_parse_job(project_id, data)


def _add_callback_token(url: str) -> str:
    token = settings.onlyoffice_callback_token
    if not token:
        return url
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("oo_callback_token", token))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _validate_callback_token(request: Request) -> None:
    expected = settings.onlyoffice_callback_token
    if not expected:
        return
    supplied = request.query_params.get("oo_callback_token", "")
    if supplied != expected:
        raise HTTPException(status_code=403, detail="OnlyOffice callback token 无效。")


def _safe_display_name(filename: str | None, index: int) -> str:
    name = Path(filename or f"file-{index}").name.strip().replace("\x00", "")
    name = name.replace("/", "_").replace("\\", "_")
    if not name or name in {".", ".."}:
        name = f"file-{index}"

    suffix = Path(name).suffix
    stem = Path(name).stem or f"file-{index}"
    if len(name) > 180:
        stem = stem[:120]
        suffix = suffix[:20]
        name = f"{stem}{suffix}"
    return name


def _validate_upload_name(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.allowed_upload_extensions:
        allowed = ", ".join(settings.allowed_upload_extensions)
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix or '无扩展名'}。当前仅允许：{allowed}",
        )
    return suffix


async def _save_one_upload(
    target_dir: Path,
    folder: str,
    index: int,
    upload: UploadFile,
) -> dict[str, Any]:
    display_name = _safe_display_name(upload.filename, index)
    _validate_upload_name(display_name)
    stored_name = f"{folder}-{index}-{uuid4().hex}{Path(display_name).suffix}"
    path = target_dir / stored_name
    temp_path = target_dir / f".{stored_name}.part"

    size = 0
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_file_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"文件 {display_name} 超过大小限制 "
                            f"{format_size_mb(settings.max_upload_file_size_bytes)}。"
                        ),
                    )
                handle.write(chunk)
        if size <= 0:
            raise HTTPException(status_code=400, detail=f"文件 {display_name} 为空。")
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    return {
        "id": f"{folder[:3].upper()}-{index}",
        "name": display_name,
        "stored_name": stored_name,
        "size_bytes": size,
        "size_label": format_size_mb(size),
        "content_type": upload.content_type or "",
        "path": str(path),
    }


def _docx_has_extractable_text(path: Path) -> bool:
    try:
        return bool(extract_docx_text(path).strip())
    except Exception:
        return False


def _mark_deferred_ocr_for_templates(template_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in template_files:
        path = Path(str(item.get("path") or ""))
        if path.suffix.lower() in {".pdf", *IMAGE_SUFFIXES}:
            item["visualParsing"] = {
                "status": "deferred",
                "message": "模板文件为图片或 PDF，后续解析或目录生成将按需使用视觉模型读取。",
            }
        elif path.suffix.lower() == ".docx" and not _docx_has_extractable_text(path):
            item["visualParsing"] = {
                "status": "deferred",
                "message": "模板 DOCX 未提取到可用文本，后续解析或目录生成将按需使用视觉模型读取。",
            }
    return template_files


async def _save_uploads(project_id: str, folder: str, files: list[UploadFile]) -> list[dict[str, Any]]:
    return await _save_uploads_with_offset(project_id, folder, files, start_index=1)


async def _save_uploads_with_offset(
    project_id: str,
    folder: str,
    files: list[UploadFile],
    start_index: int,
) -> list[dict[str, Any]]:
    target_dir = settings.uploads_dir / project_id / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict[str, Any]] = []
    try:
        for index, upload in enumerate(files, start=start_index):
            saved.append(await _save_one_upload(target_dir, folder, index, upload))
    except HTTPException:
        for item in saved:
            Path(str(item.get("path", ""))).unlink(missing_ok=True)
        raise
    return saved


def _document_type_by_suffix(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".") or "docx"
    if suffix == "pdf":
        return "pdf", "pdf"
    if suffix in {"xlsx", "xls"}:
        return suffix, "cell"
    if suffix in {"pptx", "ppt"}:
        return suffix, "slide"
    return suffix, "word"


def _resolve_appendix_docx(
    project_id: str,
    appendix_id: str,
    parse_result: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    structured = parse_result.get("structured") if isinstance(parse_result, dict) else {}
    appendices = structured.get("appendices") if isinstance(structured, dict) else []
    for appendix in appendices if isinstance(appendices, list) else []:
        if not isinstance(appendix, dict):
            continue
        if str(appendix.get("id") or "") != appendix_id:
            continue
        item = materialize_appendix_docx(project_id, appendix)
        path = Path(str(item.get("docxPath") or ""))
        if not path.exists():
            raise HTTPException(status_code=404, detail="附表 Word 文件不存在。")
        return item, path
    raise HTTPException(status_code=404, detail="未找到对应的附表。")


def _resolve_commitment_letter_docx(
    project_id: str,
    letter_id: str,
    parse_result: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    parse_result = materialize_parse_business_commitment_letter_docx_assets(
        project_id,
        parse_result,
        bid_type=BUSINESS_PARSE_PROFILE.bid_type,
    )
    structured = parse_result.get("structured") if isinstance(parse_result, dict) else {}
    letters = structured.get("commitmentLetters") if isinstance(structured, dict) else []
    project_name = ""
    field_groups = structured.get("fieldGroups") if isinstance(structured, dict) else {}
    for field in field_groups.get("projectBasics") if isinstance(field_groups, dict) and isinstance(field_groups.get("projectBasics"), list) else []:
        if isinstance(field, dict) and str(field.get("key") or "") == "projectName":
            project_name = str(field.get("value") or "").strip()
            break
    for letter in letters if isinstance(letters, list) else []:
        if not isinstance(letter, dict):
            continue
        if str(letter.get("id") or "") != letter_id:
            continue
        item = materialize_business_commitment_letter_docx(
            project_id,
            letter,
            project_name=project_name,
        )
        path = Path(str(item.get("docxPath") or ""))
        if not path.exists():
            raise HTTPException(status_code=404, detail="承诺函 Word 文件不存在。")
        return item, path
    raise HTTPException(status_code=404, detail="未找到对应的承诺函。")


def _progress_ratio(current: Any, total: Any) -> int:
    try:
        current_value = max(0, int(current))
        total_value = max(0, int(total))
    except (TypeError, ValueError):
        return 0
    if total_value <= 0:
        return 0
    return max(0, min(100, round(current_value * 100 / total_value)))


def _progress_between(start: int, end: int, phase_percent: int) -> int:
    bounded = max(0, min(100, int(phase_percent)))
    return max(0, min(100, start + round((end - start) * bounded / 100)))


TECHNICAL_PROGRESS_PHASES: dict[str, dict[str, tuple[int, int]]] = {
    "word": {
        "extract": (8, 24),
        "local_structure": (24, 34),
        "appendix_scan": (34, 40),
        "appendix": (40, 62),
        "prepare": (62, 68),
        "structured": (68, 96),
    },
    "pdf": {
        "extract": (8, 42),
        "local_structure": (42, 50),
        "appendix_scan": (50, 52),
        "appendix": (52, 62),
        "prepare": (62, 68),
        "structured": (68, 96),
    },
}


def _progress_document_kind_from_extension(value: Any) -> str:
    extension = str(value or "").strip().lower()
    return "pdf" if extension == ".pdf" else "word"


def _progress_document_kind_from_payload(payload: dict[str, Any], fallback: str = "word") -> str:
    extension = str(payload.get("fileExtension") or "").strip().lower()
    if not extension:
        file_name = str(payload.get("fileName") or "").strip().lower()
        extension = Path(file_name).suffix.lower() if file_name else ""
    if extension:
        return _progress_document_kind_from_extension(extension)
    return fallback if fallback in TECHNICAL_PROGRESS_PHASES else "word"


def _technical_phase_range(document_kind: str, phase: str) -> tuple[int, int]:
    profile = TECHNICAL_PROGRESS_PHASES.get(document_kind) or TECHNICAL_PROGRESS_PHASES["word"]
    return profile[phase]


def _technical_phase_progress(document_kind: str, phase: str, phase_percent: int) -> int:
    start, end = _technical_phase_range(document_kind, phase)
    return _progress_between(start, end, phase_percent)


def _pdf_extract_phase_percent(payload: dict[str, Any]) -> int:
    page_percent = _progress_ratio(payload.get("currentPage"), payload.get("totalPages"))
    try:
        elapsed_seconds = max(0, int(payload.get("elapsedSeconds") or 0))
    except (TypeError, ValueError):
        elapsed_seconds = 0
    elapsed_percent = min(95, 5 + elapsed_seconds // 4) if elapsed_seconds else 5
    return max(page_percent, elapsed_percent)


def _format_elapsed_duration(seconds: Any) -> str:
    try:
        elapsed_seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        elapsed_seconds = 0
    if elapsed_seconds <= 0:
        return ""
    minutes, remaining_seconds = divmod(elapsed_seconds, 60)
    if minutes:
        return f"{minutes} 分 {remaining_seconds} 秒"
    return f"{remaining_seconds} 秒"


def _opencode_elapsed_seconds(payload: dict[str, Any]) -> int:
    values: list[int] = []
    for key in ("elapsedSeconds", "idleSeconds"):
        try:
            values.append(max(0, int(payload.get(key) or 0)))
        except (TypeError, ValueError):
            values.append(0)
    return max(values or [0])


def _file_extract_phase_percent(current: Any, total: Any, in_file_percent: Any = 25) -> int:
    try:
        current_index = max(1, int(current))
        total_count = max(0, int(total))
        in_file = max(0, min(99, int(in_file_percent)))
    except (TypeError, ValueError):
        return 0
    if total_count <= 0:
        return 0
    completed_before_current = max(0, min(total_count, current_index - 1))
    weighted_current = min(total_count, completed_before_current + in_file / 100)
    return max(0, min(99, round(weighted_current * 100 / total_count)))


def _opencode_progress_from_payload(payload: dict[str, Any]) -> tuple[int, int, int]:
    parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []
    part_count = len(parts)
    trace_status = str(payload.get("status") or "").lower()
    try:
        heartbeat_index = max(0, int(payload.get("heartbeatIndex") or 0))
    except (TypeError, ValueError):
        heartbeat_index = 0
    try:
        idle_seconds = max(0, int(payload.get("idleSeconds") or payload.get("elapsedSeconds") or 0))
    except (TypeError, ValueError):
        idle_seconds = 0
    try:
        elapsed_seconds = max(0, int(payload.get("elapsedSeconds") or 0))
    except (TypeError, ValueError):
        elapsed_seconds = 0
    progress_seconds = max(idle_seconds, elapsed_seconds)
    if trace_status in {"received", "completed"}:
        phase_percent = 100
    elif trace_status in {"waiting", "idle"}:
        phase_percent = 5
    else:
        phase_percent = min(95, 12 + part_count * 6)
    if payload.get("heartbeat") or elapsed_seconds:
        heartbeat_credit = max(heartbeat_index * 3, progress_seconds // 2)
        phase_percent = min(99, max(phase_percent, 12 + part_count * 6 + heartbeat_credit))
    return _technical_phase_progress("word", "structured", phase_percent), phase_percent, part_count


def _progress_callback(service: "BidParseService", project_id: str):
    document_kind = "word"

    def update(event: str, details: dict[str, Any] | None = None) -> None:
        nonlocal document_kind
        service.raise_if_parse_cancel_requested(project_id)
        payload = details or {}
        document_kind = _progress_document_kind_from_payload(payload, document_kind)
        if event == "upload_ready":
            file_count = int(payload.get("fileCount") or 0)
            service.update_parse_progress(
                project_id,
                percentage=8,
                summary=f"正在保存招标文件，已保存 {payload.get('fileCount', 0)} / {payload.get('fileCount', 0)}。",
                event_step="upload",
                event_message=f"已保存 {payload.get('fileCount', 0)} 个招标文件。",
                phase_key="upload",
                phase_label="上传文件中",
                phase_percent=100,
                current=file_count,
                total=file_count,
                stale_after_seconds=180,
            )
        elif event == "extract_started":
            total = int(payload.get("fileCount") or 0)
            phase_label = "PDF 处理中" if document_kind == "pdf" else "Word 处理中"
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", 0),
                summary="正在准备读取招标文件。",
                event_step="extract",
                event_message=f"开始提取 {payload.get('fileCount', 0)} 个招标文件。",
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=0,
                current=0,
                total=total,
                stale_after_seconds=300,
            )
        elif event == "extracting_file":
            total = int(payload.get("total") or payload.get("fileCount") or 0)
            current = max(1, int(payload.get("current") or 1))
            is_pdf = document_kind == "pdf"
            phase_percent = _file_extract_phase_percent(current, total, 0 if is_pdf else 5)
            stale_after_seconds = 1800 if is_pdf else 300
            file_name = payload.get("fileName", "招标文件")
            phase_label = "PDF 处理中" if is_pdf else "Word 处理中"
            summary = f"正在解析 {file_name} 的页面与表格。" if is_pdf else f"正在读取 {file_name}，提取可解析文本。"
            event_message = f"开始解析 {file_name} 的页面与表格。" if is_pdf else f"开始读取 {file_name}。"
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", phase_percent),
                summary=summary,
                event_step="extract",
                event_message=event_message,
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=phase_percent,
                current=current,
                total=total,
                stale_after_seconds=stale_after_seconds,
            )
        elif event == "pdf_extracting_progress":
            file_name = payload.get("fileName", "PDF 招标文件")
            phase_percent = _pdf_extract_phase_percent(payload)
            elapsed_text = _format_elapsed_duration(payload.get("elapsedSeconds"))
            page_text = ""
            try:
                current_page = int(payload.get("currentPage") or 0)
                total_pages = int(payload.get("totalPages") or 0)
            except (TypeError, ValueError):
                current_page = 0
                total_pages = 0
            if current_page > 0 and total_pages > 0:
                page_text = f"，已处理 {current_page} / {total_pages} 页"
            elapsed_suffix = f"，已执行 {elapsed_text}" if elapsed_text else ""
            table_count = int(payload.get("tableCount") or 0)
            table_suffix = f"，已识别 {table_count} 个表格" if table_count > 0 else ""
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress("pdf", "extract", phase_percent),
                summary=f"正在解析页面与表格{page_text}{table_suffix}{elapsed_suffix}。",
                event_step="extract",
                event_message=f"正在解析 {file_name} 的页面与表格{page_text}{elapsed_suffix}。",
                phase_key="extract",
                phase_label="PDF 处理中",
                phase_percent=phase_percent,
                current=current_page,
                total=total_pages,
                stale_after_seconds=1800,
            )
        elif event == "extracting_file_progress":
            total = int(payload.get("total") or payload.get("fileCount") or 0)
            current = max(1, int(payload.get("current") or 1))
            in_file_percent = int(payload.get("progress") or 25)
            phase_percent = _file_extract_phase_percent(current, total, in_file_percent)
            file_name = payload.get("fileName", "招标文件")
            is_pdf = document_kind == "pdf"
            phase_label = "PDF 处理中" if is_pdf else "Word 处理中"
            summary = (
                f"正在解析 {file_name} 的页面与表格，已执行 {_format_elapsed_duration(payload.get('elapsedSeconds'))}。"
                if is_pdf and payload.get("elapsedSeconds")
                else f"正在读取 {file_name}，已提取约 {payload.get('textLength', 0)} 字。"
            )
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", phase_percent),
                summary=summary,
                event_step="extract",
                event_message=f"{file_name} 文本读取进度 {max(0, min(99, in_file_percent))}%。",
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=phase_percent,
                current=current,
                total=total,
                stale_after_seconds=1800 if is_pdf else 300,
            )
        elif event == "file_extracted":
            total = int(payload.get("total") or payload.get("fileCount") or 0)
            current = int(payload.get("current") or total or 1)
            phase_percent = _progress_ratio(current, total)
            is_pdf = document_kind == "pdf"
            phase_label = "PDF 处理中" if is_pdf else "Word 处理中"
            summary = (
                f"PDF 页面与表格解析完成，已提取约 {payload.get('textLength', 0)} 字。"
                if is_pdf
                else f"Word 正文读取完成，已提取约 {payload.get('textLength', 0)} 字。"
            )
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", phase_percent),
                summary=summary,
                event_step="extract",
                event_message=f"{payload.get('fileName', '招标文件')} 已提取 {payload.get('textLength', 0)} 字。",
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=phase_percent,
                current=current,
                total=total or current,
                stale_after_seconds=300,
            )
        elif event == "local_structure_started":
            start, _ = _technical_phase_range(document_kind, "local_structure")
            service.update_parse_progress(
                project_id,
                percentage=start,
                summary="正在整理正文、表格和原文位置。",
                event_step="local_structure",
                event_message="开始整理文档线索。",
                phase_key="local_structure",
                phase_label="整理文档线索中",
                phase_percent=0,
                current=0,
                total=0,
                stale_after_seconds=300,
            )
        elif event == "local_structure_finished":
            _, end = _technical_phase_range(document_kind, "local_structure")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary=f"文档线索整理完成，已发现 {payload.get('itemCount', 0)} 条候选要求。",
                event_step="local_structure",
                event_message=f"文档线索整理完成，已发现 {payload.get('itemCount', 0)} 条候选要求。",
                phase_key="local_structure",
                phase_label="整理文档线索中",
                phase_percent=100,
                current=int(payload.get("itemCount") or 0),
                total=int(payload.get("itemCount") or 0),
                stale_after_seconds=300,
            )
        elif event == "appendices_started":
            document_count = int(payload.get("documentCount") or 0)
            start, _ = _technical_phase_range(document_kind, "appendix_scan")
            service.update_parse_progress(
                project_id,
                percentage=start,
                summary="正在提取附表。",
                event_step="appendix",
                event_message=f"开始从 {document_count} 个招标文件识别附表。",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=0,
                current=0,
                total=0,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_scanning":
            file_name = payload.get("fileName", "DOCX 招标文件")
            is_heartbeat = bool(payload.get("heartbeat"))
            heartbeat_index = int(payload.get("heartbeatIndex") or 0)
            elapsed_seconds = int(payload.get("elapsedSeconds") or 0)
            phase_percent = min(30, 5 + heartbeat_index * 5) if is_heartbeat else 3
            summary = (
                f"正在扫描 {file_name} 的附表候选，已等待约 {elapsed_seconds} 秒。"
                if is_heartbeat and elapsed_seconds > 0
                else f"正在扫描 {file_name} 的附表候选。"
            )
            event_message = (
                f"扫描 {file_name} 的附表候选中，已等待约 {elapsed_seconds} 秒。"
                if is_heartbeat and elapsed_seconds > 0
                else f"开始扫描 {file_name} 的附表候选。"
            )
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "appendix_scan", phase_percent),
                summary=summary,
                event_step="appendix",
                event_message=event_message,
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=phase_percent,
                current=0,
                total=0,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_started":
            total = int(payload.get("total") or 0)
            start, _ = _technical_phase_range(document_kind, "appendix")
            service.update_parse_progress(
                project_id,
                percentage=start,
                summary=f"正在扫描 {payload.get('fileName', 'DOCX 招标文件')} 的附表。",
                event_step="appendix",
                event_message=f"开始生成 {payload.get('fileName', 'DOCX 招标文件')} 的附表 Word。",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=0,
                current=0,
                total=total,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_materializing":
            current = int(payload.get("current") or 0)
            total = int(payload.get("total") or current or 0)
            is_heartbeat = bool(payload.get("heartbeat"))
            heartbeat_index = int(payload.get("heartbeatIndex") or 0)
            elapsed_seconds = int(payload.get("elapsedSeconds") or 0)
            completed_before_current = max(0, current - 1)
            in_current_credit = min(0.9, heartbeat_index * 0.05) if is_heartbeat else 0
            phase_percent = max(
                0,
                min(
                    99,
                    round((completed_before_current + in_current_credit) * 100 / total) if total > 0 else 0,
                ),
            )
            wait_suffix = f"，已等待约 {elapsed_seconds} 秒" if is_heartbeat and elapsed_seconds > 0 else ""
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "appendix", phase_percent),
                summary=f"正在提取附表，已生成 {current} / {total or current}{wait_suffix}。",
                event_step="appendix",
                event_message=(
                    f"正在提取附表 {current} / {total or current}："
                    f"{payload.get('title', '附表')}{wait_suffix}"
                ),
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=phase_percent,
                current=current,
                total=total or current,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_progress":
            current = int(payload.get("current") or 0)
            total = int(payload.get("total") or current or 0)
            phase_percent = _progress_ratio(current, total)
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "appendix", phase_percent),
                summary=f"正在提取附表，已生成 {current} / {total or current}。",
                event_step="appendix",
                event_message=f"附表已生成 {current} / {total or current}：{payload.get('title', '附表')}",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=phase_percent,
                current=current,
                total=total or current,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_finished":
            total = int(payload.get("total") or payload.get("current") or 0)
            _, end = _technical_phase_range(document_kind, "appendix")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary=f"附表提取完成，已生成 {total} 个附表。",
                event_step="appendix",
                event_message=f"{payload.get('fileName', 'DOCX 招标文件')} 附表提取完成，共 {total} 个。",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=100,
                current=total,
                total=total,
                stale_after_seconds=300,
            )
        elif event == "business_template_extraction_started":
            service.update_parse_progress(
                project_id,
                percentage=45,
                summary="正在识别商务附件模板。",
                event_step="template",
                event_message=f"开始对 {payload.get('documentCount', 0)} 个招标文件进行商务模板抽取。",
                phase_key="business_template",
                phase_label="识别商务模板",
                phase_percent=0,
                current=0,
                total=int(payload.get("documentCount") or 0),
                stale_after_seconds=600,
            )
        elif event == "business_template_extraction_agent":
            service.update_parse_progress(
                project_id,
                percentage=50,
                summary="opencode 正在识别商务模板。",
                event_step="template",
                event_message="收到商务模板提取进度。",
                opencode_output=payload,
                phase_key="business_template",
                phase_label="识别商务模板",
                phase_percent=50,
                stale_after_seconds=900,
            )
        elif event == "business_template_extraction_finished":
            service.update_parse_progress(
                project_id,
                percentage=55,
                summary="商务附件模板识别已完成。",
                event_step="template",
                event_message=(
                    f"商务模板识别 {payload.get('appendixCount', 0)} 个，"
                    f"警告 {payload.get('warningCount', 0)} 条。"
                ),
                phase_key="business_template",
                phase_label="识别商务模板",
                phase_percent=100,
                current=int(payload.get("appendixCount") or 0),
                total=int(payload.get("appendixCount") or 0),
                stale_after_seconds=300,
            )
        elif event == "appendices_extracted":
            appendix_count = int(payload.get("appendixCount") or 0)
            generated_count = int(payload.get("generatedCount") or 0)
            _, end = _technical_phase_range(document_kind, "appendix")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary=f"附表提取完成，已生成 {generated_count} / {appendix_count or generated_count}。",
                event_step="appendix",
                event_message=(
                    f"识别附表 {appendix_count} 个，已生成 {generated_count} 个。"
                ),
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=100,
                current=generated_count,
                total=appendix_count or generated_count,
                stale_after_seconds=300,
            )
        elif event == "skill_manifest_ready":
            _, end = _technical_phase_range(document_kind, "prepare")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary="正在整理结构化解析输入。",
                event_step="skill",
                event_message="结构化解析输入已准备。",
                phase_key="skill",
                phase_label="准备结构化解析中",
                phase_percent=100,
                current=1,
                total=1,
                stale_after_seconds=300,
            )
        elif event == "opencode_delta":
            percentage, phase_percent, part_count = _opencode_progress_from_payload(payload)
            elapsed_text = _format_elapsed_duration(_opencode_elapsed_seconds(payload))
            summary = (
                f"正在识别招标文件中的技术要求和原文依据，已执行 {elapsed_text}。"
                if elapsed_text
                else "正在识别招标文件中的技术要求和原文依据，请稍候。"
            )
            event_message = (
                f"结构化解析仍在执行，已执行 {elapsed_text}。"
                if elapsed_text
                else "结构化解析正在执行。"
            )
            service.update_parse_progress(
                project_id,
                percentage=percentage,
                summary=summary,
                event_step="opencode",
                event_message=event_message,
                opencode_output=payload,
                phase_key="opencode",
                phase_label="结构化解析中",
                phase_percent=phase_percent,
                current=part_count,
                total=0,
                stale_after_seconds=900,
            )
        elif event == "opencode_finished":
            service.update_parse_progress(
                project_id,
                percentage=96,
                summary="结构化解析已完成，正在整理结构化结果。",
                event_step="opencode",
                event_message="结构化解析已完成。",
                phase_key="opencode",
                phase_label="结构化解析中",
                phase_percent=100,
                current=1,
                total=1,
                stale_after_seconds=300,
            )
        elif event == "complete":
            service.update_parse_progress(
                project_id,
                percentage=97,
                summary=f"解析输出已生成，正在写入 {payload.get('extractedCount', 0)} 条结构化要求。",
                event_step="complete",
                event_level="success",
                event_message=(
                    f"解析输出已生成，提取 {payload.get('extractedCount', 0)} 条结构化要求，"
                    f"附表 {payload.get('appendixCount', 0)} 个。"
                ),
                phase_key="finalize",
                phase_label="写入解析结果中",
                phase_percent=50,
                current=int(payload.get("extractedCount") or 0),
                total=int(payload.get("extractedCount") or 0),
                stale_after_seconds=300,
            )
        elif event == "result_persisting":
            extracted_count = int(payload.get("extractedCount") or 0)
            service.update_parse_progress(
                project_id,
                percentage=98,
                summary=f"正在同步 {extracted_count} 条解析结果到项目状态。",
                event_step="finalize",
                event_message=f"正在同步 {extracted_count} 条解析结果到项目状态。",
                phase_key="finalize",
                phase_label="写入解析结果中",
                phase_percent=70,
                current=extracted_count,
                total=extracted_count,
                stale_after_seconds=300,
            )
        elif event == "result_assets_materializing":
            appendix_count = int(payload.get("appendixCount") or 0)
            service.update_parse_progress(
                project_id,
                percentage=99,
                summary=f"正在生成解析结果资产，附表 {appendix_count} 个。",
                event_step="finalize",
                event_message=f"正在生成解析结果资产，附表 {appendix_count} 个。",
                phase_key="finalize",
                phase_label="生成结果资产中",
                phase_percent=90,
                current=appendix_count,
                total=appendix_count,
                stale_after_seconds=300,
            )

    return update


def _parse_result_opencode_output(parse_result: dict[str, Any]) -> dict[str, Any] | None:
    structured = parse_result.get("structured") if isinstance(parse_result, dict) else {}
    trace = structured.get("opencodeOutput") if isinstance(structured, dict) else {}
    return copy.deepcopy(trace) if isinstance(trace, dict) and trace else None


def _completed_opencode_output(trace: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(trace, dict) or not trace:
        return None
    closed = copy.deepcopy(trace)
    if str(closed.get("status") or "").strip().lower() in {"", "waiting", "running", "streaming"}:
        closed["status"] = "received"
    return closed


def _load_structured_result_file(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return None
    items = payload.get("items")
    return copy.deepcopy(items if isinstance(items, list) else []), copy.deepcopy(structured)


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _strip_nul_chars(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul_chars(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_nul_chars(item) for key, item in value.items()}
    return value


def _business_recoverable_parse_dirs(project_id: str, parse_storage: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for raw in (
        parse_storage.get("parseDir"),
        Path(str(parse_storage.get("structuredResultPath") or "")).parent if parse_storage.get("structuredResultPath") else "",
        settings.parsed_dir / project_id,
        settings.documents_dir / project_id / BUSINESS_PARSE_PROFILE.workspace_dirname / "parse",
    ):
        if not raw:
            continue
        candidates.append(Path(str(raw)))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _recover_business_parse_artifact(
    project_id: str,
    parse_storage: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for parse_dir in _business_recoverable_parse_dirs(project_id, parse_storage):
        structured_path = parse_dir / "s1_structured_result.json"
        loaded = _load_structured_result_file(structured_path)
        if loaded is None:
            continue
        structured_payload = read_json_file(structured_path)
        items, structured = loaded
        items = _strip_nul_chars(items)
        structured = _strip_nul_chars(structured)
        summary = structured_payload.get("summary") if isinstance(structured_payload.get("summary"), dict) else {}
        summary = _strip_nul_chars(summary)
        manifest = read_json_file(parse_dir / "manifest.json")
        recovered_result = {
            "status": "completed",
            "parsedAt": now_iso(),
            "sourceFiles": [],
            "items": items,
            "structured": structured,
            "summary": summary
            or {
                "fileCount": 0,
                "extractedCount": len(items),
                "textLength": 0,
                "textPreview": "",
                "warnings": ["解析结果已从 S1 产物自动恢复。"],
            },
        }
        recovered_storage = copy.deepcopy(parse_storage)
        recovered_storage.update(
            {
                "projectDir": str(parse_dir.parent) if parse_dir.exists() else "",
                "parseDir": str(parse_dir),
                "combinedTextPath": str(parse_dir / "combined.txt") if (parse_dir / "combined.txt").exists() else "",
                "manifestPath": str(parse_dir / "manifest.json") if (parse_dir / "manifest.json").exists() else "",
                "structuredResultPath": str(structured_path),
                "skillManifestPath": str(parse_dir / "s1_parse_manifest.json") if (parse_dir / "s1_parse_manifest.json").exists() else "",
                "documents": _strip_nul_chars(list(manifest.get("documents") or [])) if isinstance(manifest.get("documents"), list) else [],
                "items": copy.deepcopy(items),
                "structured": copy.deepcopy(structured),
            }
        )
        recovered_result = _strip_nul_chars(recovered_result)
        recovered_storage = _strip_nul_chars(recovered_storage)
        return recovered_result, recovered_storage
    return None


def _business_template_extraction_candidates(parse_storage: dict[str, Any], structured_path: Path) -> list[Path]:
    candidates: list[Path] = []

    direct_path = str(parse_storage.get("businessTemplateExtractionPath") or "").strip()
    if direct_path:
        candidates.append(Path(direct_path))

    skill_manifest_path = Path(str(parse_storage.get("skillManifestPath") or ""))
    skill_manifest = _load_json_file(skill_manifest_path)
    manifest_path = str((skill_manifest or {}).get("businessTemplateExtractionPath") or "").strip()
    if manifest_path:
        candidates.append(Path(manifest_path))

    if structured_path:
        candidates.append(structured_path.parent / "business_template_extraction" / "business_template_extraction.json")

    project_dir = str(parse_storage.get("projectDir") or "").strip()
    if project_dir:
        candidates.append(Path(project_dir) / "business_template_extraction" / "business_template_extraction.json")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _load_business_template_appendices(
    parse_storage: dict[str, Any],
    structured_path: Path,
) -> tuple[list[dict[str, Any]], Path | None]:
    for candidate in _business_template_extraction_candidates(parse_storage, structured_path):
        payload = _load_json_file(candidate)
        if not payload:
            continue
        appendices = convert_extractor_appendices(payload)
        if appendices:
            return appendices, candidate
    return [], None


def _hydrate_business_template_appendices(
    structured: dict[str, Any],
    parse_storage: dict[str, Any],
    structured_path: Path,
) -> tuple[dict[str, Any], Path | None]:
    if isinstance(structured.get("appendices"), list) and structured.get("appendices"):
        return structured, None
    appendices, extraction_path = _load_business_template_appendices(parse_storage, structured_path)
    if not appendices:
        return structured, None
    hydrated = copy.deepcopy(structured)
    hydrated["appendices"] = copy.deepcopy(appendices)
    return hydrated, extraction_path


def _compact_source_text(value: Any) -> str:
    return "".join(str(value or "").split())


def _source_documents_by_id(structured: dict[str, Any]) -> dict[str, dict[str, Any]]:
    documents = structured.get("sourceDocuments") if isinstance(structured, dict) else []
    if isinstance(documents, dict):
        documents = [documents]
    if not isinstance(documents, list):
        return {}
    return {
        str(document.get("id") or ""): document
        for document in documents
        if isinstance(document, dict) and str(document.get("id") or "").strip()
    }


def _resolve_business_nav_store_path(structured: dict[str, Any], structured_path: Path | None = None) -> Path | None:
    workflow = structured.get("workflow") if isinstance(structured, dict) else {}
    raw_path = str(workflow.get("navStorePath") or "").strip() if isinstance(workflow, dict) else ""
    if raw_path:
        return Path(raw_path)
    if structured_path is not None:
        return structured_path.parent / "s1_nav.sqlite"
    return None


def _readable_business_section(heading_path: Any, evidence_text: str) -> str:
    parts = [part.strip() for part in str(heading_path or "").split(">") if part.strip()]
    if not parts:
        return ""
    evidence_compact = _compact_source_text(evidence_text)
    if evidence_compact and len(parts) > 1:
        last_compact = _compact_source_text(parts[-1])
        if last_compact and (last_compact in evidence_compact or evidence_compact in last_compact):
            parts = parts[:-1]
    filtered_parts = []
    for index, part in enumerate(parts):
        if index > 0 and len(part) > 80:
            continue
        if index > 0 and part.startswith(("(", "（")):
            continue
        if index > 0 and part.endswith(("。", "；", ";")):
            continue
        filtered_parts.append(part)
    return " > ".join(filtered_parts or parts[:1])


_BUSINESS_CLAUSE_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\s*(.+)$")
_BUSINESS_LIST_PREFIX_RE = re.compile(r"^\s*[（(]\s*[0-9一二三四五六七八九十]+\s*[）)]\s*(.+)$")
_BUSINESS_PHYSICAL_LOCATION_RE = re.compile(r"(正文第\d+段|表格第\d+行(?:第\d+列)?|表格第\d+列)")


def _strip_business_source_caption(value: Any) -> str:
    return str(value or "").strip().strip(" \t\r\n|:：,，;；。")


def _short_business_source_caption(value: Any, max_length: int = 56) -> str:
    text = " ".join(str(value or "").replace("\u3000", " ").split())
    text = _strip_business_source_caption(text)
    if len(text) <= max_length:
        return text
    return _strip_business_source_caption(text[: max_length - 3]) + "..."


def _business_caption_head(value: Any) -> str:
    text = " ".join(str(value or "").replace("\u3000", " ").split())
    for separator in ("：", ":", "；", ";", "。", "，", ",", "\n"):
        if separator in text:
            text = text.split(separator, 1)[0]
            break
    return _short_business_source_caption(text)


def _business_evidence_caption(evidence_text: Any) -> str:
    text = " ".join(str(evidence_text or "").replace("\u3000", " ").split())
    if not text:
        return ""

    if "|" in text:
        parts = [_strip_business_source_caption(part) for part in text.split("|")]
        parts = [part for part in parts if part and part not in {":", "："}]
        if len(parts) >= 2:
            if re.fullmatch(r"\d+(?:\.\d+)+", parts[0]):
                return _short_business_source_caption(f"{parts[0]} {_business_caption_head(parts[1])}")
            return _business_caption_head(parts[0])

    clause_match = _BUSINESS_CLAUSE_PREFIX_RE.match(text)
    if clause_match:
        clause_no, clause_text = clause_match.groups()
        return _short_business_source_caption(f"{clause_no} {_business_caption_head(clause_text)}")

    list_match = _BUSINESS_LIST_PREFIX_RE.match(text)
    if list_match:
        return _business_caption_head(list_match.group(1))

    return _business_caption_head(text)


def _business_evidence_location(record: dict[str, Any], evidence_text: str) -> str:
    caption = _business_evidence_caption(evidence_text)
    if caption:
        return caption
    kind = str(record.get("kind") or "")
    row_index = record.get("row_index")
    col_index = record.get("col_index")
    if kind in {"table_row", "table_cell"} or row_index is not None:
        return "表格内容" if col_index is None else "表格单元格"
    return "正文内容"


def _business_source_text(parts: list[str]) -> str:
    return " / ".join(part for part in parts if str(part or "").strip())


def _looks_like_business_evidence_id(value: Any) -> bool:
    text = str(value or "").strip()
    return ":B" in text or ":T" in text or text.startswith("TEN-") or text.startswith("DOC-")


def _business_source_value_needs_refresh(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or _looks_like_business_evidence_id(text) or bool(_BUSINESS_PHYSICAL_LOCATION_RE.search(text))


def _business_evidence_ids(row: dict[str, Any]) -> list[str]:
    raw_ids = row.get("evidenceIds")
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in raw_ids if str(item or "").strip()))


def _fetch_business_evidence_records(
    conn: sqlite3.Connection,
    evidence_ids: list[str],
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        evidence_row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if evidence_row is None:
            continue
        record = dict(evidence_row)
        document_id = str(record.get("document_id") or "")
        table_id = str(record.get("table_id") or "")
        heading_path = ""
        if table_id:
            table_row = conn.execute("SELECT * FROM tables WHERE id = ?", (table_id,)).fetchone()
            if table_row is not None:
                table_record = dict(table_row)
                heading_path = str(table_record.get("heading_path") or table_record.get("title") or "")
        if not heading_path:
            block_row = conn.execute(
                "SELECT * FROM blocks WHERE document_id = ? AND body_index = ? LIMIT 1",
                (document_id, record.get("body_index")),
            ).fetchone()
            if block_row is not None:
                block_record = dict(block_row)
                heading_path = str(block_record.get("heading_path") or "")
        document = documents_by_id.get(document_id) or {}
        evidence_text = str(record.get("text") or "")
        records.append(
            {
                "sourceDocumentId": document_id,
                "sourceFile": str(document.get("name") or document_id or "招标文件"),
                "section": _readable_business_section(heading_path, evidence_text),
                "evidence": evidence_text,
                "evidenceLocation": _business_evidence_location(record, evidence_text),
            }
        )
    return records


def _apply_business_readable_source(row: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    changed = False
    first = records[0]
    for key in ("sourceFile", "sourceDocumentId", "section", "evidenceLocation"):
        current = str(row.get(key) or "").strip()
        if _business_source_value_needs_refresh(current) and str(first.get(key) or "").strip():
            row[key] = first[key]
            changed = True

    evidence_text = "；".join(
        dict.fromkeys(str(record.get("evidence") or "").strip() for record in records if str(record.get("evidence") or "").strip())
    )
    if evidence_text and not str(row.get("evidence") or "").strip():
        row["evidence"] = evidence_text
        changed = True

    source_text = _business_source_text(
        [
            str(first.get("sourceFile") or ""),
            str(first.get("section") or ""),
            str(first.get("evidenceLocation") or ""),
        ]
    )
    if source_text:
        for key in ("sourceText", "sourceLabel", "source"):
            current = str(row.get(key) or "").strip()
            if _business_source_value_needs_refresh(current):
                row[key] = source_text
                changed = True
    return changed


def _materialize_business_readable_sources(
    structured: dict[str, Any],
    *,
    structured_path: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(structured, dict):
        return structured
    nav_path = _resolve_business_nav_store_path(structured, structured_path)
    if nav_path is None or not nav_path.is_file():
        return structured
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    target_group_keys = ("projectBasics", "qualificationRequirements")
    rows_by_group = {
        key: field_groups.get(key)
        for key in target_group_keys
        if isinstance(field_groups.get(key), list)
    }
    if not rows_by_group:
        return structured

    materialized = copy.deepcopy(structured)
    materialized_field_groups = materialized.get("fieldGroups") if isinstance(materialized.get("fieldGroups"), dict) else {}
    documents_by_id = _source_documents_by_id(materialized)
    try:
        conn = sqlite3.connect(str(nav_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return structured
    try:
        for group_key in target_group_keys:
            rows = materialized_field_groups.get(group_key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                records = _fetch_business_evidence_records(conn, _business_evidence_ids(row), documents_by_id)
                _apply_business_readable_source(row, records)
    except sqlite3.Error:
        return structured
    finally:
        conn.close()
    return materialized


def _resolve_technical_nav_store_path(structured: dict[str, Any], structured_path: Path | None = None) -> Path | None:
    workflow = structured.get("workflow") if isinstance(structured, dict) else {}
    raw_path = str(workflow.get("navStorePath") or "").strip() if isinstance(workflow, dict) else ""
    if raw_path:
        return Path(raw_path)
    if structured_path is not None:
        return structured_path.parent / "s1_nav.sqlite"
    return None


def _technical_evidence_ids(item: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    raw_ids = item.get("evidenceIds")
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if isinstance(raw_ids, list):
        ids.extend(str(value).strip() for value in raw_ids if str(value or "").strip())
    raw_refs = item.get("evidenceRefs")
    if isinstance(raw_refs, list):
        for ref in raw_refs:
            if isinstance(ref, dict):
                value = str(ref.get("id") or ref.get("evidenceId") or "").strip()
                if value:
                    ids.append(value)
            elif str(ref or "").strip():
                ids.append(str(ref).strip())
    return list(dict.fromkeys(ids))


def _technical_heading_path_for_record(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    table_id = str(record.get("table_id") or "").strip()
    if table_id:
        table_row = conn.execute("SELECT heading_path, title FROM tables WHERE id = ?", (table_id,)).fetchone()
        if table_row is not None:
            table_record = dict(table_row)
            return str(table_record.get("heading_path") or table_record.get("title") or "").strip()
    block_row = conn.execute(
        "SELECT heading_path FROM blocks WHERE document_id = ? AND body_index = ? LIMIT 1",
        (record.get("document_id"), record.get("body_index")),
    ).fetchone()
    if block_row is not None:
        return str(dict(block_row).get("heading_path") or "").strip()
    return ""


def _technical_evidence_location(record: dict[str, Any]) -> str:
    kind = str(record.get("kind") or "").strip()
    body_index = record.get("body_index")
    row_index = record.get("row_index")
    col_index = record.get("col_index")
    if kind == "table_cell" and row_index is not None and col_index is not None:
        return f"表格第{row_index}行第{col_index}列"
    if kind == "table_row" and row_index is not None:
        return f"表格第{row_index}行"
    if kind == "table":
        return "表格"
    if body_index is not None:
        return f"正文第{body_index}段"
    return "正文内容"


def _fetch_technical_evidence_records(
    conn: sqlite3.Connection,
    evidence_ids: list[str],
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        evidence_row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if evidence_row is None:
            continue
        record = dict(evidence_row)
        document_id = str(record.get("document_id") or "").strip()
        document = documents_by_id.get(document_id) or {}
        records.append(
            {
                "id": evidence_id,
                "sourceDocumentId": document_id,
                "sourceFile": str(document.get("name") or document_id or "招标文件"),
                "section": _technical_heading_path_for_record(conn, record),
                "evidenceLocation": _technical_evidence_location(record),
                "text": str(record.get("text") or ""),
            }
        )
    return records


def _merge_technical_evidence_refs(existing_refs: Any, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    existing_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(existing_refs, list):
        for ref in existing_refs:
            if not isinstance(ref, dict):
                continue
            ref_id = str(ref.get("id") or ref.get("evidenceId") or "").strip()
            copied = copy.deepcopy(ref)
            if ref_id:
                copied["id"] = ref_id
                existing_by_id[ref_id] = copied
            merged.append(copied)

    seen_ids = {str(ref.get("id") or "").strip() for ref in merged if isinstance(ref, dict)}
    for record in records:
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            continue
        current = existing_by_id.get(record_id)
        if current is None:
            merged.append(copy.deepcopy(record))
            seen_ids.add(record_id)
            continue
        for key, value in record.items():
            if str(value or "").strip() and not str(current.get(key) or "").strip():
                current[key] = value
        if record_id not in seen_ids:
            merged.append(current)
            seen_ids.add(record_id)
    return merged


def _technical_source_text(parts: list[str]) -> str:
    return " / ".join(part for part in parts if str(part or "").strip())


_TECHNICAL_PHYSICAL_LOCATION_RE = re.compile(
    r"(正文第\d+段|表格第\d+行(?:第\d+列)?|表格第\d+列|(?:^|[/\s])(?:B|L)\d+(?:$|[/\s]))"
)


def _technical_source_value_needs_refresh(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or "原文" in text or bool(_TECHNICAL_PHYSICAL_LOCATION_RE.search(text))


def _technical_evidence_caption(value: Any) -> str:
    return _business_evidence_caption(value)


def _technical_readable_source_text(row: dict[str, Any], records: list[dict[str, Any]] | None = None) -> str:
    first = records[0] if records else {}
    source_file = str(row.get("sourceFile") or first.get("sourceFile") or "").strip()
    section = str(row.get("section") or first.get("section") or "").strip()
    evidence_location = str(row.get("evidenceLocation") or first.get("evidenceLocation") or "").strip()
    return _technical_source_text(
        [
            source_file,
            section,
            evidence_location,
        ]
    )


def _apply_existing_technical_readable_source(row: dict[str, Any]) -> None:
    caption = _technical_evidence_caption(row.get("evidence"))
    if caption and _technical_source_value_needs_refresh(row.get("evidenceLocation")):
        row["evidenceLocation"] = caption
    source_text = _technical_readable_source_text(row)
    if not source_text:
        return
    for key in ("sourceText", "sourceLabel", "source"):
        if _technical_source_value_needs_refresh(row.get(key)):
            row[key] = source_text


def _apply_technical_readable_source(row: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if not records:
        return
    first = records[0]
    for key in ("sourceFile", "sourceDocumentId", "section", "evidenceLocation"):
        if not str(row.get(key) or "").strip() and str(first.get(key) or "").strip():
            row[key] = first[key]

    evidence_text = "；".join(
        dict.fromkeys(str(record.get("text") or "").strip() for record in records if str(record.get("text") or "").strip())
    )
    if evidence_text and not str(row.get("evidence") or "").strip():
        row["evidence"] = evidence_text

    caption = _technical_evidence_caption(row.get("evidence") or first.get("text"))
    if caption and _technical_source_value_needs_refresh(row.get("evidenceLocation")):
        row["evidenceLocation"] = caption

    source_text = _technical_readable_source_text(row, records)
    if source_text:
        for key in ("sourceText", "sourceLabel", "source"):
            if _technical_source_value_needs_refresh(row.get(key)):
                row[key] = source_text


def _sync_technical_categories_from_items(interpretation: dict[str, Any]) -> None:
    items = interpretation.get("items") if isinstance(interpretation.get("items"), list) else []
    categories = interpretation.get("categories") if isinstance(interpretation.get("categories"), list) else []
    if not items or not categories:
        return
    by_id = {str(item.get("id") or ""): item for item in items if isinstance(item, dict) and str(item.get("id") or "")}
    by_row = {str(item.get("rowNo") or ""): item for item in items if isinstance(item, dict) and str(item.get("rowNo") or "")}
    for category in categories:
        if not isinstance(category, dict) or not isinstance(category.get("items"), list):
            continue
        synced_items = []
        for item in category["items"]:
            if not isinstance(item, dict):
                synced_items.append(item)
                continue
            replacement = by_id.get(str(item.get("id") or "")) or by_row.get(str(item.get("rowNo") or ""))
            synced_items.append(copy.deepcopy(replacement or item))
        category["items"] = synced_items


def _materialize_technical_evidence_refs(
    structured: dict[str, Any],
    *,
    structured_path: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(structured, dict):
        return structured
    interpretation = structured.get("technicalInterpretation")
    items = interpretation.get("items") if isinstance(interpretation, dict) and isinstance(interpretation.get("items"), list) else []
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups.get("projectBasics"), list) else []
    if not items and not project_basics:
        return structured

    materialized = copy.deepcopy(structured)
    materialized_interpretation = materialized.get("technicalInterpretation")
    materialized_items = (
        materialized_interpretation.get("items")
        if isinstance(materialized_interpretation, dict) and isinstance(materialized_interpretation.get("items"), list)
        else []
    )
    materialized_field_groups = materialized.get("fieldGroups") if isinstance(materialized.get("fieldGroups"), dict) else {}
    materialized_project_basics = (
        materialized_field_groups.get("projectBasics")
        if isinstance(materialized_field_groups.get("projectBasics"), list)
        else []
    )
    for row in materialized_project_basics:
        if isinstance(row, dict):
            _apply_existing_technical_readable_source(row)
    if materialized_project_basics and isinstance(materialized.get("projectFactFields"), list):
        materialized["projectFactFields"] = copy.deepcopy(materialized_project_basics)

    nav_path = _resolve_technical_nav_store_path(structured, structured_path)
    if nav_path is None or not nav_path.is_file():
        return materialized if materialized_project_basics else structured

    documents_by_id = _source_documents_by_id(materialized)
    try:
        conn = sqlite3.connect(str(nav_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return materialized if materialized_project_basics else structured
    try:
        for row in materialized_project_basics:
            if not isinstance(row, dict):
                continue
            evidence_ids = _technical_evidence_ids(row)
            if not evidence_ids:
                continue
            records = _fetch_technical_evidence_records(conn, evidence_ids, documents_by_id)
            if not records:
                continue
            row["evidenceRefs"] = _merge_technical_evidence_refs(row.get("evidenceRefs"), records)
            _apply_technical_readable_source(row, records)
        if materialized_project_basics and isinstance(materialized.get("projectFactFields"), list):
            materialized["projectFactFields"] = copy.deepcopy(materialized_project_basics)

        for item in materialized_items:
            if not isinstance(item, dict):
                continue
            evidence_ids = _technical_evidence_ids(item)
            if not evidence_ids:
                continue
            records = _fetch_technical_evidence_records(conn, evidence_ids, documents_by_id)
            if not records:
                continue
            item["evidenceRefs"] = _merge_technical_evidence_refs(item.get("evidenceRefs"), records)
            if not str(item.get("evidenceSummary") or "").strip():
                first_text = str(records[0].get("text") or "").strip()
                if first_text:
                    item["evidenceSummary"] = first_text[:180]
        if isinstance(materialized_interpretation, dict):
            _sync_technical_categories_from_items(materialized_interpretation)
    except sqlite3.Error:
        return structured
    finally:
        conn.close()
    return materialized


class BidParseService:
    def __init__(self, project_service: BidProjectService, api_prefix: str) -> None:
        self.project_service = project_service
        self.api_prefix = api_prefix.rstrip("/")
        # 进度落库节流：project_id -> (上次落库 monotonic 时间, 上次落库 phaseKey)。
        # 仅进程内存；解析移到 worker 进程后同样生效。
        self._progress_persist_guard: dict[str, tuple[float, str]] = {}

    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return self.project_service.ensure_project(project_id)

    def require_project_for_update(self, project_id: str) -> dict[str, Any]:
        return require_workspace_project_for_update(
            project_id,
            bid_type=self.project_service.bid_type,
            not_found_error=lambda _project_id: HTTPException(
                status_code=404,
                detail=self.project_service.not_found_message,
            ),
            wrong_type_error=lambda _project_id: HTTPException(
                status_code=400,
                detail=self.project_service.wrong_type_message,
            ),
        )

    def parse_result(self, project_id: str) -> dict[str, Any]:
        result = copy.deepcopy(self.ensure_project(project_id)["parse_result"])
        if self.project_service.bid_type == TECHNICAL_PARSE_PROFILE.bid_type and not result.get("projectPrefill"):
            structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
            result["projectPrefill"] = _project_basics_project_prefill(structured)
        return result

    def _refresh_business_parse_result_from_structured_file(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        parse_result = project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}
        if self.project_service.bid_type != BUSINESS_PARSE_PROFILE.bid_type:
            return copy.deepcopy(parse_result)
        parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
        if parse_result.get("status") != "completed":
            recovered = _recover_business_parse_artifact(project_id, parse_storage)
            if recovered is None:
                return copy.deepcopy(parse_result)
            recovered_result, recovered_storage = recovered
            parse_result = update_parse_result_state(project, recovered_result, parse_storage=recovered_storage)
            persist_workspace_project_state(project)
            parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}

        structured_path = Path(str(parse_storage.get("structuredResultPath") or ""))
        loaded = _load_structured_result_file(structured_path)
        if loaded is None:
            return copy.deepcopy(parse_result)

        items, structured = loaded
        items = _strip_nul_chars(items)
        structured = _strip_nul_chars(structured)
        structured, template_extraction_path = _hydrate_business_template_appendices(
            structured,
            parse_storage,
            structured_path,
        )
        structured = _strip_nul_chars(_materialize_business_readable_sources(structured, structured_path=structured_path))
        if parse_result.get("items") == items and parse_result.get("structured") == structured:
            return copy.deepcopy(parse_result)

        refreshed = copy.deepcopy(parse_result)
        refreshed["items"] = items
        refreshed["structured"] = structured
        updated_storage = copy.deepcopy(parse_storage)
        updated_storage["items"] = items
        updated_storage["structured"] = structured
        if template_extraction_path:
            updated_storage["businessTemplateExtractionPath"] = str(template_extraction_path)
        payload = update_parse_result_state(project, refreshed, parse_storage=updated_storage)
        persist_workspace_project_state(project)
        return payload

    def _refresh_technical_parse_result_from_structured_file(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        parse_result = project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}
        if self.project_service.bid_type != TECHNICAL_PARSE_PROFILE.bid_type or parse_result.get("status") != "completed":
            return copy.deepcopy(parse_result)

        parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
        structured_path = Path(str(parse_storage.get("structuredResultPath") or ""))
        loaded = _load_structured_result_file(structured_path)
        if loaded is None:
            return copy.deepcopy(parse_result)

        items, structured = loaded
        structured = _materialize_technical_evidence_refs(structured, structured_path=structured_path)
        interpretation = structured.get("technicalInterpretation") if isinstance(structured, dict) else {}
        materialized_items = interpretation.get("items") if isinstance(interpretation, dict) else None
        if isinstance(materialized_items, list):
            items = copy.deepcopy(materialized_items)
        if parse_result.get("items") == items and parse_result.get("structured") == structured:
            return copy.deepcopy(parse_result)

        refreshed = copy.deepcopy(parse_result)
        refreshed["items"] = items
        refreshed["structured"] = structured
        updated_storage = copy.deepcopy(parse_storage)
        updated_storage["items"] = items
        updated_storage["structured"] = structured
        payload = update_parse_result_state(project, refreshed, parse_storage=updated_storage)
        persist_workspace_project_state(project)
        return payload

    def _materialize_completed_parse_result(self, project_id: str, parse_result: dict[str, Any]) -> dict[str, Any]:
        if self.project_service.bid_type == BUSINESS_PARSE_PROFILE.bid_type:
            return self._refresh_business_parse_result_from_structured_file(project_id)
        if self.project_service.bid_type == TECHNICAL_PARSE_PROFILE.bid_type:
            return self._refresh_technical_parse_result_from_structured_file(project_id)
        return parse_result

    def _promote_completed_parse_if_participating(self, project_id: str, parse_result: dict[str, Any]) -> dict[str, Any]:
        if parse_result.get("status") != "completed":
            return parse_result
        project = self.require_project_for_update(project_id)
        if str(project.get("reviewDecision") or "").strip().lower() != "participate":
            return parse_result
        parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
        promoted = promote_parse_artifacts_to_workspace(
            project_id,
            parse_result,
            parse_storage,
            bid_type=self.project_service.bid_type,
        )
        project["parse_result"] = promoted["parseResult"]
        project["parse_storage"] = promoted["parseStorage"]
        if promoted["stageArtifacts"]:
            project["stageArtifacts"] = promoted["stageArtifacts"]
        project["workspaceArtifacts"] = promoted["artifacts"]
        cleanup_parse_temp_workspace(project_id)
        persist_workspace_project_state(project)
        return copy.deepcopy(project["parse_result"])

    def parse_inputs(
        self,
        project_id: str,
        *,
        include_fallback: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        project = self.ensure_project(project_id)
        return project_parse_input_records(project_id, project, include_fallback=include_fallback)

    def parse_progress(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        existed = isinstance(project.get("parse_progress"), dict)
        progress = parse_progress_snapshot_state(project)
        if not existed:
            persist_workspace_project_state(project)
        return progress

    def is_parse_cancel_requested(self, project_id: str) -> bool:
        project = self.require_project_for_update(project_id)
        progress = project.get("parse_progress") if isinstance(project.get("parse_progress"), dict) else {}
        return bool(progress.get("cancelRequested")) or str(progress.get("status") or "") == "cancelled"

    def raise_if_parse_cancel_requested(self, project_id: str) -> None:
        if self.is_parse_cancel_requested(project_id):
            raise ParseCancelledError("解析已取消。")

    def start_parse_progress(
        self,
        project_id: str,
        message: str = "已开始招标文件解析。",
        file_names: list[str] | None = None,
    ) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        progress = start_parse_progress_state(project, message, file_names=file_names)
        persist_workspace_project_state(project)
        self._progress_persist_guard[project_id] = (time.monotonic(), str(progress.get("phaseKey") or ""))
        return progress

    def update_parse_progress(
        self,
        project_id: str,
        *,
        status: str | None = None,
        percentage: int | None = None,
        summary: str | None = None,
        event_message: str = "",
        event_step: str = "general",
        event_level: str = "info",
        opencode_output: dict[str, Any] | None = None,
        phase_key: str | None = None,
        phase_label: str | None = None,
        phase_percent: int | None = None,
        current: int | None = None,
        total: int | None = None,
        stale_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        progress = update_parse_progress_state(
            project,
            status=status,
            percentage=percentage,
            summary=summary,
            event_message=event_message,
            event_step=event_step,
            event_level=event_level,
            opencode_output=opencode_output,
            phase_key=phase_key,
            phase_label=phase_label,
            phase_percent=phase_percent,
            current=current,
            total=total,
            stale_after_seconds=stale_after_seconds,
        )
        # 落库节流：终态/跨阶段/告警错误事件必写，其余按时间间隔合并，
        # 避免每个进度事件都整行 JSONB upsert Postgres。被跳过的更新只影响
        # 展示层（最多滞后一个间隔），心跳刷新间隔远小于各阶段 stale 阈值。
        now_monotonic = time.monotonic()
        last_persist = self._progress_persist_guard.get(project_id)
        is_terminal = status is not None and status in TERMINAL_PARSE_STATUSES
        phase_changed = phase_key is not None and (last_persist is None or phase_key != last_persist[1])
        should_persist = (
            last_persist is None
            or is_terminal
            or phase_changed
            or event_level in {"warning", "error"}
            or (now_monotonic - last_persist[0]) >= settings.parse_progress_persist_interval_sec
        )
        if should_persist:
            persist_workspace_project_state(project)
            if is_terminal:
                self._progress_persist_guard.pop(project_id, None)
            else:
                self._progress_persist_guard[project_id] = (
                    now_monotonic,
                    str(progress.get("phaseKey") or ""),
                )
        return progress

    def cancel_parse(self, project_id: str) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        progress = project.get("parse_progress") if isinstance(project.get("parse_progress"), dict) else {}
        trace = copy.deepcopy(progress.get("opencodeOutput")) if isinstance(progress.get("opencodeOutput"), dict) else {}
        session_id = str(trace.get("sessionId") or "").strip()
        opencode_abort = {
            "attempted": bool(session_id),
            "sessionId": session_id,
            "aborted": False,
        }
        if session_id:
            opencode_abort["aborted"] = OpencodeClient().abort_session(session_id)
        if trace:
            trace["status"] = "cancelled"
        cancelled = cancel_parse_progress_state(
            project,
            "已请求停止解析任务。",
            opencode_output=trace,
        )
        persist_workspace_project_state(project)
        return {
            **cancelled,
            "message": cancelled.get("summary") or "已请求停止解析任务。",
            "opencodeAbort": opencode_abort,
        }

    @staticmethod
    def _cancelled_parse_response(progress: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "cancelled",
            "message": progress.get("message") or progress.get("summary") or "解析已取消。",
            "progress": progress,
        }

    def complete_parse(
        self,
        project_id: str,
        tender_files: list[dict[str, Any]],
        template_files: list[dict[str, Any]],
        *,
        summary: dict[str, Any] | None = None,
        parse_storage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.project_service.bid_type == BUSINESS_PARSE_PROFILE.bid_type:
            summary = _strip_nul_chars(summary) if summary is not None else None
            parse_storage = _strip_nul_chars(parse_storage) if parse_storage is not None else None
        project = self.require_project_for_update(project_id)
        parse_result = complete_parse_state(
            project,
            tender_files,
            template_files,
            summary=summary,
            parse_storage=parse_storage,
        )
        persist_workspace_project_state(project)
        return parse_result

    def finalize_parse_progress(
        self,
        project_id: str,
        parse_result: dict[str, Any],
        *,
        summary: dict[str, Any] | None = None,
    ) -> None:
        extracted_count = 0
        if isinstance(summary, dict):
            extracted_count = int(summary.get("extractedCount") or 0)
        if not extracted_count and isinstance(parse_result.get("items"), list):
            extracted_count = len(parse_result.get("items") or [])
        current_progress = self.parse_progress(project_id)
        current_trace = current_progress.get("opencodeOutput") if isinstance(current_progress, dict) else {}
        self.update_parse_progress(
            project_id,
            status="completed",
            percentage=100,
            summary=f"解析完成，提取 {extracted_count} 条结构化要求。",
            opencode_output=_completed_opencode_output(_parse_result_opencode_output(parse_result) or current_trace),
            event_step="complete",
            event_level="success",
            event_message=f"解析完成，提取 {extracted_count} 条结构化要求。",
            phase_key="complete",
            phase_label="解析完成",
            phase_percent=100,
            current=extracted_count,
            total=extracted_count,
        )

    def update_template_files(self, project_id: str, template_files: list[dict[str, Any]]) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = update_template_files_state(project, template_files)
        persist_workspace_project_state(project)
        return payload

    async def results(self, project_id: str) -> dict[str, Any]:
        parse_result = self._materialize_completed_parse_result(project_id, self.parse_result(project_id))
        payload = materialize_parse_appendix_docx_assets(
            project_id,
            parse_result,
            bid_type=self.project_service.bid_type,
        )
        return materialize_parse_business_commitment_letter_docx_assets(
            project_id,
            payload,
            bid_type=self.project_service.bid_type,
        )

    async def progress(self, project_id: str) -> dict[str, Any]:
        return self.parse_progress(project_id)

    async def cancel(self, project_id: str) -> dict[str, Any]:
        return self.cancel_parse(project_id)

    def _mark_parse_queued(self, project_id: str, message: str, file_names: list[str] | None = None) -> dict[str, Any]:
        """入队前把进度置为排队态：前端轮询立即有反馈；任务迟迟不被消费时由 stale 机制兜底。"""

        self.start_parse_progress(project_id, message, file_names=file_names)
        return self.update_parse_progress(
            project_id,
            status="queued",
            summary=message,
            event_step="queue",
            event_message=message,
            phase_key="queue",
            phase_label="排队等待中",
            phase_percent=0,
            # worker 繁忙时排队可能较久，放宽 stale 判定，避免误报中断。
            stale_after_seconds=1800,
        )

    def _parse_schedule_response(
        self,
        project_id: str,
        *,
        mode: str,
        job_id: str,
        inline_message: str,
    ) -> dict[str, Any]:
        """调度后的统一收口。

        调度器被同步执行（测试内联补丁）时按旧契约返回完整解析结果、失败抛 500、
        取消返回 cancelled；真实异步入队时返回 queued（路由层据此置 HTTP 202）。
        """

        progress = self.parse_progress(project_id)
        status = str(progress.get("status") or "")
        if status == "completed":
            parse_result = self.parse_result(project_id)
            return {**parse_result, "message": inline_message}
        if status == "cancelled":
            return self._cancelled_parse_response(progress)
        if status == "failed":
            raise HTTPException(status_code=500, detail=str(progress.get("summary") or "解析失败"))
        return {
            "status": "queued",
            "mode": mode,
            "jobId": job_id,
            "message": S1_PARSE_QUEUED_MESSAGE,
            "progress": progress,
        }

    def execute_s1_parse_job(self, project_id: str, data: dict[str, Any]) -> None:
        """后台执行 S1 解析（Redis worker/本地线程）：瞬时错误按配置退避自动重试，取消走协作式中止。"""

        tender_files = [item for item in (data.get("tenderFiles") or []) if isinstance(item, dict)]
        template_files = [item for item in (data.get("templateFiles") or []) if isinstance(item, dict)]
        if not tender_files:
            self.update_parse_progress(
                project_id,
                status="failed",
                percentage=100,
                summary="解析失败：解析任务缺少招标文件。",
                event_step="failed",
                event_level="error",
                event_message="解析失败：解析任务缺少招标文件。",
                phase_key="failed",
                phase_label="解析失败",
                phase_percent=100,
            )
            raise RuntimeError("解析任务缺少招标文件。")

        # 从排队态进入运行态（重置进度与事件流），目标文件名随进度常驻。
        self.start_parse_progress(project_id, file_names=_parse_file_names(tender_files))
        # 补发上传阶段事件，保持与旧同步链路一致的进度事件词表。
        if str(data.get("origin") or "") == "rerun":
            upload_summary = "正在复用已上传招标文件进行解析。"
            upload_event = f"复用 {len(tender_files)} 个已上传招标文件。"
        else:
            upload_summary = f"正在保存招标文件，已保存 {len(tender_files)} / {len(tender_files)}。"
            upload_event = f"已保存 {len(tender_files)} 个招标文件。"
        self.update_parse_progress(
            project_id,
            percentage=8,
            summary=upload_summary,
            event_step="upload",
            event_message=upload_event,
            phase_key="upload",
            phase_label="上传文件中",
            phase_percent=100,
            current=len(tender_files),
            total=len(tender_files),
            stale_after_seconds=180,
        )
        max_attempts = max(1, int(settings.s1_parse_job_max_attempts or 1))
        backoffs = tuple(settings.s1_parse_job_retry_backoff_sec) or (30, 120)
        attempt = 0
        while True:
            attempt += 1
            if attempt > 1:
                self.update_parse_progress(
                    project_id,
                    status="running",
                    summary=f"正在自动重试解析（第 {attempt - 1} 次重试）。",
                    event_step="retry",
                    event_level="warning",
                    event_message=f"开始第 {attempt - 1} 次自动重试。",
                    phase_key="retry",
                    phase_label=f"自动重试 {attempt - 1}/{max_attempts - 1}",
                )
            cancel_check = lambda: self.is_parse_cancel_requested(project_id)
            try:
                summary, parse_storage = parse_tender_documents(
                    project_id,
                    tender_files,
                    bid_type=self.project_service.bid_type,
                    progress_callback=_progress_callback(self, project_id),
                    cancel_check=cancel_check,
                )
                self.raise_if_parse_cancel_requested(project_id)
            except ParseCancelledError:
                self.cancel_parse(project_id)
                return
            except Exception as exc:
                if self.is_parse_cancel_requested(project_id):
                    self.cancel_parse(project_id)
                    return
                if attempt < max_attempts and _is_retryable_parse_error(exc):
                    delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
                    self.update_parse_progress(
                        project_id,
                        status="running",
                        summary=f"解析失败：{exc}。{delay} 秒后自动重试（第 {attempt} 次，共 {max_attempts - 1} 次）。",
                        event_step="retry_wait",
                        event_level="warning",
                        event_message=f"第 {attempt} 次解析失败：{exc}。{delay} 秒后自动重试。",
                        phase_key="retry_wait",
                        phase_label="等待自动重试",
                        stale_after_seconds=int(delay) + 300,
                    )
                    # 重试等待会阻塞当前 worker/本地线程；现有执行模型按 opencode 并发=1
                    # 本来就是全局串行，短暂阻塞可接受。
                    time.sleep(delay)
                    continue
                self.update_parse_progress(
                    project_id,
                    status="failed",
                    percentage=100,
                    summary=f"解析失败：{exc}",
                    event_step="failed",
                    event_level="error",
                    event_message=f"解析失败：{exc}",
                    phase_key="failed",
                    phase_label="解析失败",
                    phase_percent=100,
                )
                raise
            self.raise_if_parse_cancel_requested(project_id)
            _progress_callback(self, project_id)(
                "result_persisting",
                {"extractedCount": int(summary.get("extractedCount") or 0) if isinstance(summary, dict) else 0},
            )
            parse_result = self.complete_parse(
                project_id,
                tender_files,
                template_files,
                summary=summary,
                parse_storage=parse_storage,
            )
            _progress_callback(self, project_id)(
                "result_assets_materializing",
                {"appendixCount": int(summary.get("appendixCount") or 0) if isinstance(summary, dict) else 0},
            )
            parse_result = self._materialize_completed_parse_result(project_id, parse_result)
            parse_result = materialize_parse_appendix_docx_assets(
                project_id,
                parse_result,
                bid_type=self.project_service.bid_type,
            )
            parse_result = self._promote_completed_parse_if_participating(project_id, parse_result)
            self.finalize_parse_progress(project_id, parse_result, summary=summary)
            return

    async def run_without_upload(self, project_id: str) -> dict[str, Any]:
        tender_files, template_files = self.parse_inputs(project_id, include_fallback=False)
        if not tender_files:
            raise HTTPException(status_code=400, detail="当前项目还没有已上传的招标文件。")
        if is_generation_locked(S1_PARSE_JOB_TYPE, project_id):
            raise HTTPException(status_code=409, detail=S1_PARSE_LOCKED_DETAIL)
        busy_detail = _s1_parse_global_busy_detail(project_id)
        if busy_detail:
            raise HTTPException(status_code=409, detail=busy_detail)
        self._mark_parse_queued(
            project_id,
            f"解析任务已提交，将复用已上传的{_parse_files_label(tender_files)}重新解析。",
            file_names=_parse_file_names(tender_files),
        )
        mode, job_id = _schedule_s1_parse_job(
            project_id,
            {
                "__bidType": self.project_service.bid_type,
                "origin": "rerun",
                "tenderFiles": tender_files,
                "templateFiles": template_files,
            },
        )
        if mode == "locked":
            raise HTTPException(status_code=409, detail=S1_PARSE_LOCKED_DETAIL)
        return self._parse_schedule_response(project_id, mode=mode, job_id=job_id, inline_message="解析完成")

    async def upload_and_parse(
        self,
        project_id: str,
        *,
        tender_files: list[UploadFile] | None = None,
        template_files: list[UploadFile] | None = None,
    ) -> dict[str, Any]:
        if is_generation_locked(S1_PARSE_JOB_TYPE, project_id):
            raise HTTPException(status_code=409, detail=S1_PARSE_LOCKED_DETAIL)
        busy_detail = _s1_parse_global_busy_detail(project_id)
        if busy_detail:
            raise HTTPException(status_code=409, detail=busy_detail)
        existing_tender, existing_template = self.parse_inputs(project_id, include_fallback=False)
        uploaded_tender_files = tender_files or []
        uploaded_template_files = template_files or []

        if uploaded_tender_files:
            active_tender = await _save_uploads(project_id, "tender", uploaded_tender_files)
        else:
            active_tender = existing_tender

        if not active_tender:
            raise HTTPException(status_code=400, detail="请至少上传 1 个招标文件。")

        if uploaded_template_files:
            saved_template = await _save_uploads_with_offset(
                project_id,
                "template",
                uploaded_template_files,
                start_index=len(existing_template) + 1,
            )
            merged_template = [*existing_template, *_mark_deferred_ocr_for_templates(saved_template)]
        else:
            merged_template = existing_template

        self._mark_parse_queued(
            project_id,
            f"解析任务已提交，后台将解析{_parse_files_label(active_tender)}。",
            file_names=_parse_file_names(active_tender),
        )
        mode, job_id = _schedule_s1_parse_job(
            project_id,
            {
                "__bidType": self.project_service.bid_type,
                "origin": "upload",
                "tenderFiles": active_tender,
                "templateFiles": merged_template,
            },
        )
        if mode == "locked":
            raise HTTPException(status_code=409, detail=S1_PARSE_LOCKED_DETAIL)
        return self._parse_schedule_response(
            project_id,
            mode=mode,
            job_id=job_id,
            inline_message="上传成功，已自动完成解析。",
        )

    async def upload_template_files(
        self,
        project_id: str,
        *,
        template_files: list[UploadFile] | None = None,
    ) -> dict[str, Any]:
        existing_tender, existing_template = self.parse_inputs(project_id, include_fallback=False)
        parse_result = self.parse_result(project_id)
        files = template_files or []

        if not existing_tender or parse_result.get("status") != "completed":
            raise HTTPException(status_code=400, detail="请先在“审核”模块完成招标文件解析并确认参与投标。")

        if not files:
            raise HTTPException(status_code=400, detail="请至少上传 1 个模板文件。")

        saved_template = await _save_uploads_with_offset(
            project_id,
            "template",
            files,
            start_index=len(existing_template) + 1,
        )
        merged_template = [*existing_template, *_mark_deferred_ocr_for_templates(saved_template)]
        payload = self.update_template_files(project_id, merged_template)
        return {
            **payload,
            "message": "模板文件上传成功。",
        }

    async def appendix_preview(self, project_id: str, appendix_id: str, request: Request) -> dict[str, Any]:
        appendix, path = _resolve_appendix_docx(project_id, appendix_id, self.parse_result(project_id))
        file_name = path.name
        file_type, document_type = _document_type_by_suffix(path)
        quoted_name = quote(file_name)
        browser_file_url = absolute_url(
            request,
            f"{self.api_prefix}/{project_id}/parse-results/appendices/{appendix_id}/file/{quoted_name}",
        )
        browser_callback_url = _add_callback_token(
            absolute_url(request, f"{self.api_prefix}/{project_id}/parse-results/appendices/callback"),
        )
        onlyoffice_base = onlyoffice_backend_base_url(request)
        onlyoffice_file_url = (
            f"{onlyoffice_base}{self.api_prefix}/{project_id}/parse-results/appendices/{appendix_id}/file/{quoted_name}"
        )
        onlyoffice_callback_url = _add_callback_token(
            f"{onlyoffice_base}{self.api_prefix}/{project_id}/parse-results/appendices/callback",
        )
        return {
            **appendix,
            "fileUrl": browser_file_url,
            "onlyoffice": {
                "documentKey": build_editor_session_key(path),
                "title": appendix.get("title") or file_name,
                "fileType": file_type,
                "documentType": document_type,
                "fileUrl": onlyoffice_file_url,
                "callbackUrl": onlyoffice_callback_url,
                "browserFileUrl": browser_file_url,
                "browserCallbackUrl": browser_callback_url,
                "user": {
                    "id": "user-1",
                    "name": "当前用户",
                },
            },
        }

    async def appendix_file(self, project_id: str, appendix_id: str, filename: str = "") -> FileResponse:
        appendix, path = _resolve_appendix_docx(project_id, appendix_id, self.parse_result(project_id))
        _ = filename
        return FileResponse(
            path=path,
            media_type=WORD_MEDIA_TYPE,
            filename=Path(str(appendix.get("workspacePath") or path.name)).name,
        )

    async def appendix_callback(
        self,
        project_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> JSONResponse:
        self.ensure_project(project_id)
        _ = data
        _validate_callback_token(request)
        return JSONResponse({"error": 0})

    async def approve_appendix_asset(
        self,
        project_id: str,
        appendix_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        try:
            return approve_business_appendix_asset(project_id, appendix_id, approved=bool((data or {}).get("approved", True)))
        except BusinessParseAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    async def approve_all_appendix_assets(
        self,
        project_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        try:
            return approve_all_business_appendix_assets(project_id, approved=bool((data or {}).get("approved", True)))
        except BusinessParseAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


class TechnicalParseService(BidParseService):
    @staticmethod
    def _compact_selection_result(result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if key != "parseResult" and not key.startswith("_")}

    async def approve_appendix_asset(
        self,
        project_id: str,
        appendix_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            result = set_technical_appendix_asset_selected(
                project_id,
                appendix_id,
                selected=bool((data or {}).get("approved", True)),
            )
            return self._compact_selection_result(result)
        except TechnicalParseAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    async def approve_all_appendix_assets(
        self,
        project_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            result = set_all_technical_appendix_assets_selected(
                project_id,
                selected=bool((data or {}).get("approved", True)),
            )
            return self._compact_selection_result(result)
        except TechnicalParseAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


class BusinessParseService(BidParseService):
    async def approve_business_scoring(
        self,
        project_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        try:
            return approve_business_scoring_asset(project_id, approved=bool((data or {}).get("approved", True)))
        except BusinessParseAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    async def commitment_letter_preview(self, project_id: str, letter_id: str, request: Request) -> dict[str, Any]:
        letter, path = _resolve_commitment_letter_docx(project_id, letter_id, self.parse_result(project_id))
        file_name = path.name
        file_type, document_type = _document_type_by_suffix(path)
        quoted_name = quote(file_name)
        browser_file_url = absolute_url(
            request,
            f"{self.api_prefix}/{project_id}/parse-results/commitment-letters/{letter_id}/file/{quoted_name}",
        )
        browser_callback_url = _add_callback_token(
            absolute_url(request, f"{self.api_prefix}/{project_id}/parse-results/commitment-letters/callback"),
        )
        onlyoffice_base = onlyoffice_backend_base_url(request)
        onlyoffice_file_url = (
            f"{onlyoffice_base}{self.api_prefix}/{project_id}/parse-results/commitment-letters/{letter_id}/file/{quoted_name}"
        )
        onlyoffice_callback_url = _add_callback_token(
            f"{onlyoffice_base}{self.api_prefix}/{project_id}/parse-results/commitment-letters/callback",
        )
        return {
            **letter,
            "fileUrl": browser_file_url,
            "onlyoffice": {
                "documentKey": build_editor_session_key(path),
                "title": letter.get("title") or file_name,
                "fileType": file_type,
                "documentType": document_type,
                "fileUrl": onlyoffice_file_url,
                "callbackUrl": onlyoffice_callback_url,
                "browserFileUrl": browser_file_url,
                "browserCallbackUrl": browser_callback_url,
                "user": {
                    "id": "user-1",
                    "name": "当前用户",
                },
            },
        }

    async def commitment_letter_file(self, project_id: str, letter_id: str, filename: str = "") -> FileResponse:
        letter, path = _resolve_commitment_letter_docx(project_id, letter_id, self.parse_result(project_id))
        _ = filename
        return FileResponse(
            path=path,
            media_type=WORD_MEDIA_TYPE,
            filename=Path(str(letter.get("workspacePath") or path.name)).name,
        )

    async def commitment_letter_callback(
        self,
        project_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> JSONResponse:
        self.ensure_project(project_id)
        _ = data
        _validate_callback_token(request)
        return JSONResponse({"error": 0})

    async def approve_commitment_letter_asset(
        self,
        project_id: str,
        letter_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        try:
            return approve_business_commitment_letter_asset(
                project_id,
                letter_id,
                approved=bool((data or {}).get("approved", True)),
            )
        except BusinessParseAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    async def approve_all_commitment_letter_assets(
        self,
        project_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        try:
            return approve_all_business_commitment_letter_assets(
                project_id,
                approved=bool((data or {}).get("approved", True)),
            )
        except BusinessParseAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


business_parse_service = BusinessParseService(business_project_service, "/api/business/projects")
technical_parse_service = TechnicalParseService(technical_project_service, "/api/technical/projects")
