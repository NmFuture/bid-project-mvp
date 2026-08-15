"""S1 招标文件解析服务门面：作业调度、上传保存、进度落库与附表/承诺函资产。

进度计算族与商务/技术 evidence 可读来源物化分别拆到
bid_parse_progress / bid_parse_evidence_sources，本文件 re-export 全部原符号，
外部调用方与 patch 目标（app.services.bid_parse_service.<符号>）无需改动。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
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
from app.services.file_utils import format_size_mb, run_awaitable_sync
from app.services.onlyoffice_documents import WORD_MEDIA_TYPE, build_editor_session_key
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.parse_profiles import BUSINESS_PARSE_PROFILE, TECHNICAL_PARSE_PROFILE
from app.services.technical_parse_assets import (
    TechnicalParseAssetError,
    set_all_technical_appendix_assets_selected,
    set_technical_appendix_asset_selected,
)
from app.services.job_queue import enqueue_generation_job, is_generation_locked, request_job_cancel
from app.services.job_timing import record_phase, record_timing_meta
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
from app.services.workspace_project_access import (
    persist_workspace_project_fields,
    persist_workspace_project_state,
    require_workspace_project_for_update,
)
# 拆分搬迁：进度计算族已移至 bid_parse_progress，此处 re-export
# 保持 app.services.bid_parse_service.<符号> 可解析、可 patch。
from app.services.bid_parse_progress import (
    TECHNICAL_PROGRESS_PHASES,
    _file_extract_phase_percent,
    _format_elapsed_duration,
    _opencode_elapsed_seconds,
    _opencode_progress_from_payload,
    _pdf_extract_phase_percent,
    _progress_between,
    _progress_callback,
    _progress_document_kind_from_extension,
    _progress_document_kind_from_payload,
    _progress_ratio,
    _technical_phase_progress,
    _technical_phase_range,
)
# 拆分搬迁：商务/技术 evidence 可读来源物化已移至 bid_parse_evidence_sources，门面 re-export。
from app.services.bid_parse_evidence_sources import (
    _apply_business_readable_source,
    _apply_existing_technical_readable_source,
    _apply_technical_readable_source,
    _business_caption_head,
    _business_evidence_caption,
    _business_evidence_ids,
    _business_evidence_location,
    _business_recoverable_parse_dirs,
    _business_source_text,
    _business_source_value_needs_refresh,
    _business_template_extraction_candidates,
    _compact_source_text,
    _evidence_source_text,
    _fetch_business_evidence_records,
    _fetch_technical_evidence_records,
    _hydrate_business_template_appendices,
    _load_business_template_appendices,
    _load_json_file,
    _load_structured_result_file,
    _looks_like_business_evidence_id,
    _materialize_business_readable_sources,
    _materialize_technical_evidence_refs,
    _merge_technical_appendix_runtime_state,
    _merge_technical_evidence_refs,
    _readable_business_section,
    _recover_business_parse_artifact,
    _resolve_business_nav_store_path,
    _resolve_nav_store_path,
    _resolve_technical_nav_store_path,
    _short_business_source_caption,
    _source_documents_by_id,
    _strip_business_source_caption,
    _strip_nul_chars,
    _sync_technical_categories_from_items,
    _technical_evidence_caption,
    _technical_evidence_ids,
    _technical_evidence_location,
    _technical_heading_path_for_record,
    _technical_readable_source_text,
    _technical_source_text,
    _technical_source_value_needs_refresh,
    _BUSINESS_CLAUSE_PREFIX_RE,
    _BUSINESS_LIST_PREFIX_RE,
    _BUSINESS_PHYSICAL_LOCATION_RE,
    _TECHNICAL_APPENDIX_RUNTIME_FIELDS,
    _TECHNICAL_PHYSICAL_LOCATION_RE,
)

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
    """调度 S1 解析任务；独立 Docling Worker 要求 Redis 必须可用。"""

    bid_type = require_bid_type(data.get("__bidType"))
    service = business_parse_service if bid_type == BUSINESS_PARSE_PROFILE.bid_type else technical_parse_service
    queue_result = enqueue_generation_job(S1_PARSE_JOB_TYPE, project_id, data)
    if queue_result.queued:
        service.bind_parse_run(project_id, queue_result.job_id)
        return "queued", queue_result.job_id
    if queue_result.locked:
        return "locked", ""
    service.update_parse_progress(
        project_id,
        status="failed",
        percentage=100,
        summary="解析队列暂不可用，请稍后重试。",
        event_step="failed",
        event_level="error",
        event_message="解析队列暂不可用，请稍后重试。",
        phase_key="failed",
        phase_label="解析失败",
        phase_percent=100,
    )
    raise HTTPException(status_code=503, detail="解析队列暂不可用，请稍后重试。")


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
    digest = hashlib.sha256()
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
                digest.update(chunk)
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
        "sha256": digest.hexdigest(),
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
            persist_workspace_project_fields(project, "parse_result", "parse_storage")
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
        persist_workspace_project_fields(project, "parse_result", "parse_storage")
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
        current_structured = (
            parse_result.get("structured")
            if isinstance(parse_result.get("structured"), dict)
            else {}
        )
        structured = _merge_technical_appendix_runtime_state(structured, current_structured)
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
        persist_workspace_project_fields(project, "parse_result", "parse_storage")
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
        persist_workspace_project_fields(project, "parse_result", "parse_storage", "workspaceArtifacts", "stageArtifacts")
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
            persist_workspace_project_fields(project, "parse_progress")
        return progress

    def bind_parse_run(self, project_id: str, run_id: str) -> None:
        project = self.require_project_for_update(project_id)
        progress = project.get("parse_progress") if isinstance(project.get("parse_progress"), dict) else {}
        progress["runId"] = str(run_id)
        project["parse_progress"] = progress
        persist_workspace_project_fields(project, "parse_progress")

    def is_current_parse_run(self, project_id: str, run_id: str) -> bool:
        progress = self.parse_progress(project_id)
        current = str(progress.get("runId") or "")
        return not current or current == str(run_id)

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
        persist_workspace_project_fields(project, "parse_progress")
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
        # 耗时埋点：按解析 runId 记录阶段首达时间（同 step 只记首次），失败仅降级日志。
        existing_progress = project.get("parse_progress") if isinstance(project.get("parse_progress"), dict) else {}
        parse_run_id = str(existing_progress.get("runId") or "")
        if parse_run_id:
            record_phase(parse_run_id, event_step, phase_label or event_step)
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
            persist_workspace_project_fields(project, "parse_progress")
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
        request_job_cancel(str(progress.get("runId") or ""))
        trace = copy.deepcopy(progress.get("opencodeOutput")) if isinstance(progress.get("opencodeOutput"), dict) else {}
        session_id = str(trace.get("sessionId") or "").strip()
        opencode_abort = {
            "attempted": bool(session_id),
            "sessionId": session_id,
            "aborted": False,
        }
        if session_id:
            # 保留直建：按 opencode 会话 trace 里的 sessionId 取消在跑会话，opencode 专有语义。
            opencode_abort["aborted"] = run_awaitable_sync(OpencodeEngine().abort_session(session_id))
        if trace:
            trace["status"] = "cancelled"
        cancelled = cancel_parse_progress_state(
            project,
            "已请求停止解析任务。",
            opencode_output=trace,
        )
        persist_workspace_project_fields(project, "parse_progress")
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
        persist_workspace_project_fields(project, "parse_result", "parse_storage", "templateFiles", "templateFileRecords", "files", "fileRecords", "currentStage")
        return parse_result

    def finalize_parse_progress(
        self,
        project_id: str,
        parse_result: dict[str, Any],
        *,
        summary: dict[str, Any] | None = None,
    ) -> None:
        extracted_count = 0
        failed_names: list[str] = []
        if isinstance(summary, dict):
            extracted_count = int(summary.get("extractedCount") or 0)
            failed_names = [
                str(item.get("name") or "")
                for item in summary.get("failedDocuments") or []
                if isinstance(item, dict) and str(item.get("name") or "")
            ]
        if not extracted_count and isinstance(parse_result.get("items"), list):
            extracted_count = len(parse_result.get("items") or [])
        # 部分文件解析失败时，完成提示中显式列出，避免用户误以为全部成功。
        failed_suffix = f"；{len(failed_names)} 个文件解析失败（{'、'.join(failed_names[:3])}{' 等' if len(failed_names) > 3 else ''}），结果仅基于成功文件" if failed_names else ""
        finish_message = f"解析完成，提取 {extracted_count} 条结构化要求{failed_suffix}。"
        current_progress = self.parse_progress(project_id)
        current_trace = current_progress.get("opencodeOutput") if isinstance(current_progress, dict) else {}
        self.update_parse_progress(
            project_id,
            status="completed",
            percentage=100,
            summary=finish_message,
            opencode_output=_completed_opencode_output(_parse_result_opencode_output(parse_result) or current_trace),
            event_step="complete",
            event_level="warning" if failed_names else "success",
            event_message=finish_message,
            phase_key="complete",
            phase_label="解析完成",
            phase_percent=100,
            current=extracted_count,
            total=extracted_count,
        )

    def update_template_files(self, project_id: str, template_files: list[dict[str, Any]]) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = update_template_files_state(project, template_files)
        persist_workspace_project_fields(project, "parse_result", "templateFiles", "templateFileRecords", "currentStage")
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
        # cancel_parse 内部经 run_awaitable_sync 桥接 abort opencode 会话，
        # 放工作线程执行，不在事件循环线程上直接桥接。
        return await asyncio.to_thread(self.cancel_parse, project_id)

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

    def _fail_parse_progress(self, project_id: str, exc: Exception) -> None:
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

    def execute_s1_parse_job(self, project_id: str, data: dict[str, Any]) -> None:
        """后台执行 S1 解析（Redis worker/本地线程）：瞬时错误按配置退避自动重试，取消走协作式中止。"""

        # 排队期间用户可能已取消：检查必须先于进度重置，否则 cancelled 状态会被
        # start_parse_progress 整体抹掉，任务在取消后仍被执行。
        if self.is_parse_cancel_requested(project_id):
            self.cancel_parse(project_id)
            return

        tender_files = [item for item in (data.get("tenderFiles") or []) if isinstance(item, dict)]
        template_files = [item for item in (data.get("templateFiles") or []) if isinstance(item, dict)]
        run_id = str(data.get("__runId") or "")
        is_continuation = bool(data.get("__doclingPrepared"))
        if run_id and not self.is_current_parse_run(project_id, run_id):
            return
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

        if not is_continuation:
            # 测试和非 Docker 调用仍可直接执行完整解析链路。
            self.start_parse_progress(project_id, file_names=_parse_file_names(tender_files))
            if run_id:
                self.bind_parse_run(project_id, run_id)
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
        else:
            self.update_parse_progress(
                project_id,
                status="running",
                summary="Docling 解析完成，正在继续结构化处理。",
                event_step="docling_complete",
                event_message="Docling 解析结果已就绪。",
                phase_key="local_structure",
                phase_label="结构化处理中",
                phase_percent=0,
                stale_after_seconds=1800,
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
                    require_preparsed_pdf=is_continuation,
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
                    # 重试等待会阻塞当前 worker/本地线程；opencode 请求并发上限为全局预算
                    # （settings.agent_concurrency_budget，默认 8），单项目的解析任务本身串行执行，
                    # 短暂阻塞只影响本项目，可接受。
                    time.sleep(delay)
                    continue
                self._fail_parse_progress(project_id, exc)
                raise
            # 后处理（结果落库/资产物化/进度收尾）与解析本体一样需要兜底：
            # 异常时把进度置为 failed，否则项目进度永远停在 running，只能靠 stale 兜底。
            try:
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
            except ParseCancelledError:
                self.cancel_parse(project_id)
                return
            except Exception as exc:
                if self.is_parse_cancel_requested(project_id):
                    self.cancel_parse(project_id)
                    return
                self._fail_parse_progress(project_id, exc)
                raise
            return

    async def run_without_upload(self, project_id: str) -> dict[str, Any]:
        tender_files, template_files = self.parse_inputs(project_id, include_fallback=False)
        if not tender_files:
            raise HTTPException(status_code=400, detail="当前项目还没有已上传的招标文件。")
        if is_generation_locked(S1_PARSE_JOB_TYPE, project_id):
            raise HTTPException(status_code=409, detail=S1_PARSE_LOCKED_DETAIL)
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
        upload_started_at = time.monotonic()
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
        if job_id:
            # 耗时埋点：上传落盘阶段；上传耗时作为元数据随 finalize 写入 job_timings.meta。
            record_phase(job_id, "upload", "文件上传落盘")
            record_timing_meta(job_id, uploadMs=int((time.monotonic() - upload_started_at) * 1000))
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
