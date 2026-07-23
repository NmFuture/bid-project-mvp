from __future__ import annotations

import copy
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.bid_type import TECHNICAL_BID_TYPE, require_bid_type
from app.services.docling_engine import (
    DOCLING_LOCKED_VERSION,
    DOCLING_PIPELINE_OPTIONS_VERSION,
    DoclingParseEngine,
)
from app.services.job_queue import (
    EnqueueResult,
    enqueue_internal_job,
    is_job_cancel_requested,
    mark_job_status,
    renew_generation_lock,
)


DOCLING_BATCH_JOB_TYPE = "s1_docling_batch"
S1_CONTINUE_JOB_TYPE = "s1_parse_continue"
_RETRYABLE_ERROR_MARKERS = (
    "429",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "out of memory",
    "oom",
)


def _pdf_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in data.get("tenderFiles") or []
        if isinstance(item, dict) and Path(str(item.get("path") or "")).suffix.lower() == ".pdf"
    ]


def _enqueue_continue(project_id: str, data: dict[str, Any], run_id: str) -> EnqueueResult:
    payload = copy.deepcopy(data)
    payload["__runId"] = run_id
    payload["__doclingPrepared"] = True
    parent = {"id": run_id, "type": "s1_parse", "projectId": project_id}
    renew_generation_lock(parent, settings.redis_job_queue_lock_ttl_sec)
    result = enqueue_internal_job(
        S1_CONTINUE_JOB_TYPE,
        project_id,
        payload,
        job_id=f"{run_id}:continue",
        parent_job_id=run_id,
        # Lua 脚本会在入队前原子写父状态；重复投递则不覆盖已有终态。
        parent_status="waiting_continuation",
    )
    if not result.accepted:
        mark_job_status(parent, "waiting_docling", "continuation 暂时无法投递，等待 Docling Worker 重试。")
    return result


def enqueue_docling_failure(job: dict[str, Any], message: str) -> EnqueueResult:
    project_id = str(job.get("projectId") or "")
    run_id = str(job.get("parentJobId") or (job.get("data") or {}).get("__runId") or "")
    data = copy.deepcopy(job.get("data") if isinstance(job.get("data"), dict) else {})
    data["__doclingError"] = str(message or "Docling 任务未完成")
    return _enqueue_continue(project_id, data, run_id)


def enqueue_docling_batch(project_id: str, data: dict[str, Any], run_id: str) -> EnqueueResult:
    payload = copy.deepcopy(data)
    payload["__runId"] = run_id
    if not _pdf_records(payload):
        return _enqueue_continue(project_id, payload, run_id)
    return enqueue_internal_job(
        DOCLING_BATCH_JOB_TYPE,
        project_id,
        payload,
        job_id=f"{run_id}:docling",
        parent_job_id=run_id,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _shared_pdf_path(raw_path: Any) -> Path:
    path = Path(str(raw_path or "")).resolve(strict=True)
    allowed_roots = (settings.uploads_dir.resolve(), settings.documents_dir.resolve())
    if not any(path == root or root in path.parents for root in allowed_roots):
        raise RuntimeError(f"Docling 拒绝读取共享卷之外的文件：{path}")
    if path.suffix.lower() != ".pdf":
        raise RuntimeError(f"Docling 任务只接受 PDF：{path.name}")
    return path


def _document_id(record: dict[str, Any]) -> str:
    value = str(record.get("id") or "").strip()
    if not value or Path(value).name != value or value in {".", ".."}:
        raise RuntimeError("Docling 任务缺少合法 documentId")
    return value


def _read_quality(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cached_result_ready(project_dir: Path, document_id: str, source_sha256: str, run_id: str) -> bool:
    quality_path = project_dir / "document_parse" / "docling" / document_id / "parse_quality.json"
    nav_path = project_dir / f"{document_id}_document_nav.json"
    quality = _read_quality(quality_path)
    if not (
        nav_path.is_file()
        and str(quality.get("status") or "").lower() == "completed"
        and str(quality.get("sourceSha256") or "").lower() == source_sha256.lower()
        and str(quality.get("doclingVersion") or "") == DOCLING_LOCKED_VERSION
        and str(quality.get("pipelineOptionsVersion") or "") == DOCLING_PIPELINE_OPTIONS_VERSION
    ):
        return False
    return str(quality.get("runId") or "") == run_id


def _clear_previous_result(project_dir: Path, document_id: str) -> None:
    docling_dir = project_dir / "document_parse" / "docling" / document_id
    nav_path = project_dir / f"{document_id}_document_nav.json"
    if docling_dir.is_dir():
        shutil.rmtree(docling_dir)
    nav_path.unlink(missing_ok=True)


def _parse_one_pdf(
    *,
    project_id: str,
    project_dir: Path,
    record: dict[str, Any],
    run_id: str,
    fallback: str,
    merge_technical_text_layer: bool,
) -> None:
    pdf_path = _shared_pdf_path(record.get("path"))
    document_id = _document_id(record)
    source_sha256 = str(record.get("sha256") or "").strip().lower() or _sha256(pdf_path)
    record["sha256"] = source_sha256
    record["runId"] = run_id
    if _cached_result_ready(project_dir, document_id, source_sha256, run_id):
        return

    max_attempts = max(1, int(settings.s1_parse_job_max_attempts or 1))
    backoffs = tuple(settings.s1_parse_job_retry_backoff_sec) or (30, 120)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        _clear_previous_result(project_dir, document_id)
        result = DoclingParseEngine(fallback=fallback).parse_pdf(
            project_id=project_id,
            document={
                "id": document_id,
                "name": str(record.get("name") or pdf_path.name),
                "path": str(pdf_path),
                "sourcePath": str(pdf_path),
                "sourceSha256": source_sha256,
                "runId": run_id,
                "mergeTechnicalTextLayer": merge_technical_text_layer,
            },
            output_dir=project_dir,
        )
        if str(result.get("status") or "").lower() == "completed":
            return
        last_error = str(result.get("fallbackReason") or "Docling 解析失败")
        retryable = any(marker in last_error.lower() for marker in _RETRYABLE_ERROR_MARKERS)
        if attempt < max_attempts and retryable:
            time.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])
            continue
        break
    raise RuntimeError(last_error)


def execute_docling_batch(job: dict[str, Any]) -> dict[str, Any]:
    project_id = str(job.get("projectId") or "")
    run_id = str(job.get("parentJobId") or (job.get("data") or {}).get("__runId") or "")
    data = copy.deepcopy(job.get("data") if isinstance(job.get("data"), dict) else {})
    if not project_id or not run_id:
        raise RuntimeError("Docling 批任务缺少 projectId 或 runId")
    bid_type = require_bid_type(data.get("__bidType"))
    fallback = "none" if bid_type == TECHNICAL_BID_TYPE else settings.business_pdf_engine_fallback
    merge_technical_text_layer = bid_type == TECHNICAL_BID_TYPE
    project_dir = (settings.parsed_dir / project_id).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    try:
        pdfs = _pdf_records(data)
        for record in pdfs:
            if is_job_cancel_requested(run_id):
                return {"status": "cancelled", "runId": run_id}
            _parse_one_pdf(
                project_id=project_id,
                project_dir=project_dir,
                record=record,
                run_id=run_id,
                fallback=fallback,
                merge_technical_text_layer=merge_technical_text_layer,
            )
        if is_job_cancel_requested(run_id):
            return {"status": "cancelled", "runId": run_id}
    except Exception as exc:
        data["__doclingError"] = str(exc)

    result = _enqueue_continue(project_id, data, run_id)
    if not result.accepted:
        raise RuntimeError("Docling 完成后无法投递 S1 continuation")
    return {
        "status": "failed" if data.get("__doclingError") else "succeeded",
        "runId": run_id,
        "nextJobId": result.job_id,
        "message": str(data.get("__doclingError") or ""),
    }
