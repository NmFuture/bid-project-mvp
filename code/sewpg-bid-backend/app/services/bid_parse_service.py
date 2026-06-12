from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from uuid import uuid4

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.services.bid_parse_state import (
    complete_parse_state,
    ensure_parse_progress_state,
    start_parse_progress_state,
    update_parse_progress_state,
    update_template_files_state,
)
from app.services.bid_project_state import project_parse_input_records
from app.services.bid_project_service import BidProjectService, business_project_service, technical_project_service
from app.services.business_parse_assets import (
    BusinessParseAssetError,
    approve_all_business_appendix_assets,
    approve_all_business_commitment_letter_assets,
    approve_business_appendix_asset,
    approve_business_commitment_letter_asset,
    approve_business_scoring_asset,
)
from app.services.file_utils import format_size_mb
from app.services.onlyoffice_documents import WORD_MEDIA_TYPE, build_editor_session_key
from app.services.parse_profiles import BUSINESS_PARSE_PROFILE
from app.services.url_utils import absolute_url, onlyoffice_backend_base_url
from app.services.parsing import (
    IMAGE_SUFFIXES,
    extract_docx_text,
    materialize_appendix_docx,
    materialize_business_commitment_letter_docx,
    materialize_parse_appendix_docx_assets,
    materialize_parse_business_commitment_letter_docx_assets,
    parse_tender_documents,
)
from app.services.workspace_project_access import persist_workspace_project_state, require_workspace_project_for_update


_CHUNK_SIZE = 1024 * 1024


async def _parse_tender_documents_async(
    project_id: str,
    tender_files: list[dict[str, Any]],
    *,
    bid_type: str,
    progress_callback=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return await asyncio.to_thread(
        parse_tender_documents,
        project_id,
        tender_files,
        bid_type=bid_type,
        progress_callback=progress_callback,
    )


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


def _progress_callback(service: "BidParseService", project_id: str):
    def update(event: str, details: dict[str, Any] | None = None) -> None:
        payload = details or {}
        if event == "upload_ready":
            service.update_parse_progress(
                project_id,
                percentage=15,
                summary=f"已保存 {payload.get('fileCount', 0)} 个招标文件，准备提取文本。",
                event_step="upload",
                event_message=f"已保存 {payload.get('fileCount', 0)} 个招标文件。",
            )
        elif event == "extract_started":
            service.update_parse_progress(
                project_id,
                percentage=25,
                summary="正在提取招标文件文本。",
                event_step="extract",
                event_message=f"开始提取 {payload.get('fileCount', 0)} 个招标文件。",
            )
        elif event == "file_extracted":
            service.update_parse_progress(
                project_id,
                percentage=40,
                summary="招标文件文本提取中。",
                event_step="extract",
                event_message=f"{payload.get('fileName', '招标文件')} 已提取 {payload.get('textLength', 0)} 字。",
            )
        elif event == "appendices_extracted":
            service.update_parse_progress(
                project_id,
                percentage=55,
                summary="正在识别附表并生成空表 Word。",
                event_step="appendix",
                event_message=(
                    f"识别附表 {payload.get('appendixCount', 0)} 个，"
                    f"已生成 {payload.get('generatedCount', 0)} 个 Word 空表。"
                ),
            )
        elif event == "skill_manifest_ready":
            service.update_parse_progress(
                project_id,
                percentage=65,
                summary="解析 Skill 输入已准备，正在调用 opencode。",
                event_step="skill",
                event_message="S1 解析 Skill manifest 已生成。",
            )
        elif event == "opencode_delta":
            service.update_parse_progress(
                project_id,
                percentage=80,
                summary="opencode 正在返回解析输出。",
                event_step="opencode",
                event_message="收到 opencode 解析输出片段。",
                opencode_output=payload,
            )
        elif event == "complete":
            service.update_parse_progress(
                project_id,
                status="completed",
                percentage=100,
                summary=f"解析完成，提取 {payload.get('extractedCount', 0)} 条结构化要求。",
                event_step="complete",
                event_level="success",
                event_message=(
                    f"解析完成，提取 {payload.get('extractedCount', 0)} 条结构化要求，"
                    f"附表 {payload.get('appendixCount', 0)} 个。"
                ),
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


class BidParseService:
    def __init__(self, project_service: BidProjectService, api_prefix: str) -> None:
        self.project_service = project_service
        self.api_prefix = api_prefix.rstrip("/")

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
        return copy.deepcopy(self.ensure_project(project_id)["parse_result"])

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
        progress = ensure_parse_progress_state(project)
        if not existed:
            persist_workspace_project_state(project)
        return progress

    def start_parse_progress(self, project_id: str, message: str = "已开始招标文件解析。") -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        progress = start_parse_progress_state(project, message)
        persist_workspace_project_state(project)
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
        )
        persist_workspace_project_state(project)
        return progress

    def complete_parse(
        self,
        project_id: str,
        tender_files: list[dict[str, Any]],
        template_files: list[dict[str, Any]],
        *,
        summary: dict[str, Any] | None = None,
        parse_storage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        )

    def update_template_files(self, project_id: str, template_files: list[dict[str, Any]]) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        payload = update_template_files_state(project, template_files)
        persist_workspace_project_state(project)
        return payload

    async def results(self, project_id: str) -> dict[str, Any]:
        payload = materialize_parse_appendix_docx_assets(
            project_id,
            self.parse_result(project_id),
            bid_type=self.project_service.bid_type,
        )
        return materialize_parse_business_commitment_letter_docx_assets(
            project_id,
            payload,
            bid_type=self.project_service.bid_type,
        )

    async def progress(self, project_id: str) -> dict[str, Any]:
        return self.parse_progress(project_id)

    async def run_without_upload(self, project_id: str) -> dict[str, Any]:
        tender_files, template_files = self.parse_inputs(project_id, include_fallback=False)
        if not tender_files:
            raise HTTPException(status_code=400, detail="当前项目还没有已上传的招标文件。")
        self.start_parse_progress(project_id)
        self.update_parse_progress(
            project_id,
            percentage=15,
            summary="正在复用已上传招标文件进行解析。",
            event_step="upload",
            event_message=f"复用 {len(tender_files)} 个已上传招标文件。",
        )
        try:
            summary, parse_storage = await _parse_tender_documents_async(
                project_id,
                tender_files,
                bid_type=self.project_service.bid_type,
                progress_callback=_progress_callback(self, project_id),
            )
        except Exception as exc:
            self.update_parse_progress(
                project_id,
                status="failed",
                percentage=100,
                summary=f"解析失败：{exc}",
                event_step="failed",
                event_level="error",
                event_message=f"解析失败：{exc}",
            )
            raise
        parse_result = self.complete_parse(
            project_id,
            tender_files,
            template_files,
            summary=summary,
            parse_storage=parse_storage,
        )
        parse_result = materialize_parse_appendix_docx_assets(
            project_id,
            parse_result,
            bid_type=self.project_service.bid_type,
        )
        self.finalize_parse_progress(project_id, parse_result, summary=summary)
        return {**parse_result, "message": "解析完成"}

    async def upload_and_parse(
        self,
        project_id: str,
        *,
        tender_files: list[UploadFile] | None = None,
        template_files: list[UploadFile] | None = None,
    ) -> dict[str, Any]:
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

        self.start_parse_progress(project_id)
        _progress_callback(self, project_id)("upload_ready", {"fileCount": len(active_tender)})
        try:
            summary, parse_storage = await _parse_tender_documents_async(
                project_id,
                active_tender,
                bid_type=self.project_service.bid_type,
                progress_callback=_progress_callback(self, project_id),
            )
        except Exception as exc:
            self.update_parse_progress(
                project_id,
                status="failed",
                percentage=100,
                summary=f"解析失败：{exc}",
                event_step="failed",
                event_level="error",
                event_message=f"解析失败：{exc}",
            )
            raise
        parse_result = self.complete_parse(
            project_id,
            active_tender,
            merged_template,
            summary=summary,
            parse_storage=parse_storage,
        )
        parse_result = materialize_parse_appendix_docx_assets(
            project_id,
            parse_result,
            bid_type=self.project_service.bid_type,
        )
        self.finalize_parse_progress(project_id, parse_result, summary=summary)
        return {
            **parse_result,
            "message": "上传成功，已自动完成解析。",
        }

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
technical_parse_service = BidParseService(technical_project_service, "/api/technical/projects")
