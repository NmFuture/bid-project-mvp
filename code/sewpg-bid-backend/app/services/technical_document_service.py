from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import threading
from typing import Any
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from app.services import bid_document_flow
from app.services.bid_document_state import apply_technical_document_format_to_project
from app.services.bid_document_flow import PDF_MEDIA_TYPE, BidDocumentService
from app.services.bid_document_flow import _build_document_payload
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.bid_project_service import technical_project_service
from app.services.onlyoffice_documents import (
    WORD_MEDIA_TYPE,
    document_object_key,
    ensure_document,
    refresh_document_session,
    sync_document_to_minio,
)
from app.services.technical_document_format import TECH_FORMAT_PRESETS, apply_technical_document_format_preset
from app.services.technical_export_color_cleaner import ensure_clean_export_document
from app.services.url_utils import absolute_url, now_message, onlyoffice_backend_base_url
from app.services.workspace_project_access import persist_workspace_project_state, require_workspace_project_for_update


MARKED_EXPORT_VERSION = "marked"
CLEAN_EXPORT_VERSION = "clean"
EXPORT_VERSIONS = {MARKED_EXPORT_VERSION, CLEAN_EXPORT_VERSION}
PDF_GENERATION_ATTEMPTS = 3


def _file_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"mtimeNs": stat.st_mtime_ns, "size": stat.st_size}


def _pdf_source_metadata_path(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(f"{pdf_path.suffix}.source.json")


def _read_pdf_source_signature(pdf_path: Path) -> dict[str, int] | None:
    try:
        payload = json.loads(_pdf_source_metadata_path(pdf_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return {"mtimeNs": int(payload["mtimeNs"]), "size": int(payload["size"])}
    except (KeyError, TypeError, ValueError):
        return None


def _write_pdf_source_signature(pdf_path: Path, signature: dict[str, int]) -> None:
    metadata_path = _pdf_source_metadata_path(pdf_path)
    temp_path = metadata_path.with_name(f".{metadata_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(signature, ensure_ascii=True), encoding="utf-8")
        os.replace(temp_path, metadata_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _pdf_matches_source(pdf_path: Path, source_path: Path) -> bool:
    return pdf_path.exists() and _read_pdf_source_signature(pdf_path) == _file_signature(source_path)


def _normalize_export_version(value: str | None) -> str:
    version = str(value or MARKED_EXPORT_VERSION).strip().lower()
    if version not in EXPORT_VERSIONS:
        raise HTTPException(status_code=400, detail="导出版本仅支持 marked 或 clean。")
    return version


def _export_file_name(file_name: str, export_version: str, suffix: str) -> str:
    stem = Path(file_name).stem
    version_suffix = "-清洁版" if export_version == CLEAN_EXPORT_VERSION else ""
    return f"{stem}{version_suffix}{suffix}"


def _technical_project_for_update(project_id: str) -> dict[str, Any]:
    return require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=lambda _project_id: HTTPException(
            status_code=404,
            detail=technical_project_service.not_found_message,
        ),
        wrong_type_error=lambda _project_id: HTTPException(
            status_code=400,
            detail=technical_project_service.wrong_type_message,
        ),
    )


class TechnicalDocumentService(BidDocumentService):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pdf_export_locks: dict[str, asyncio.Lock] = {}
        self._pdf_export_locks_guard = threading.Lock()

    def _pdf_export_lock(self, pdf_path: Path) -> asyncio.Lock:
        key = str(pdf_path.resolve())
        with self._pdf_export_locks_guard:
            return self._pdf_export_locks.setdefault(key, asyncio.Lock())

    async def _export_document_path(self, project_id: str, export_version: str) -> tuple[dict[str, Any], Path]:
        payload = self.document_state(project_id)
        source_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
        if export_version == CLEAN_EXPORT_VERSION:
            source_path = await asyncio.to_thread(ensure_clean_export_document, source_path)
        return payload, source_path

    async def _ensure_export_pdf(self, source_url: str, doc_path: Path, pdf_path: Path) -> None:
        async with self._pdf_export_lock(pdf_path):
            if _pdf_matches_source(pdf_path, doc_path):
                return
            for _attempt in range(PDF_GENERATION_ATTEMPTS):
                source_signature = _file_signature(doc_path)
                temp_path = pdf_path.with_name(f".{pdf_path.stem}.{uuid.uuid4().hex}.pdf")
                try:
                    try:
                        await bid_document_flow._convert_document_to_pdf_via_onlyoffice(
                            source_url,
                            doc_path,
                            temp_path,
                        )
                    except Exception as exc:
                        try:
                            await bid_document_flow._convert_document_to_pdf_locally(doc_path, temp_path)
                        except Exception as fallback_exc:
                            raise HTTPException(
                                status_code=502,
                                detail=f"PDF 生成失败：{exc}；本地兜底也失败：{fallback_exc}",
                            ) from fallback_exc

                    if _file_signature(doc_path) != source_signature:
                        continue
                    os.replace(temp_path, pdf_path)
                    _write_pdf_source_signature(pdf_path, source_signature)
                    if _file_signature(doc_path) == source_signature:
                        return
                finally:
                    temp_path.unlink(missing_ok=True)

            raise HTTPException(status_code=409, detail="技术标源文档在 PDF 生成期间持续变化，请稍后重试。")

    async def final_document(
        self,
        project_id: str,
        request: Request,
        version: str = MARKED_EXPORT_VERSION,
    ) -> dict[str, Any]:
        export_version = _normalize_export_version(version)
        payload = await super().final_document(project_id, request)
        if export_version == CLEAN_EXPORT_VERSION:
            await self._export_document_path(project_id, export_version)
        payload["exportVersion"] = export_version
        payload["fileName"] = _export_file_name(payload["fileName"], export_version, ".docx")
        payload["fileUrl"] = absolute_url(
            request,
            f"{self.api_prefix}/{project_id}/final-document/file?version={export_version}",
        )
        return payload

    async def final_document_file(
        self,
        project_id: str,
        version: str = MARKED_EXPORT_VERSION,
    ) -> FileResponse:
        export_version = _normalize_export_version(version)
        payload, doc_path = await self._export_document_path(project_id, export_version)
        return FileResponse(
            path=doc_path,
            media_type=WORD_MEDIA_TYPE,
            filename=_export_file_name(payload["fileName"], export_version, ".docx"),
        )

    async def final_document_pdf(
        self,
        project_id: str,
        request: Request,
        version: str = MARKED_EXPORT_VERSION,
    ) -> dict[str, Any]:
        export_version = _normalize_export_version(version)
        payload, doc_path = await self._export_document_path(project_id, export_version)
        pdf_path = doc_path.with_suffix(".pdf")
        source_url = (
            f"{onlyoffice_backend_base_url(request).rstrip('/')}{self.api_prefix}/{project_id}"
            f"/final-document/file?version={export_version}"
        )
        await self._ensure_export_pdf(source_url, doc_path, pdf_path)
        return {
            "message": "PDF 已生成。",
            "fileUrl": absolute_url(
                request,
                f"{self.api_prefix}/{project_id}/final-document/pdf/file?version={export_version}",
            ),
            "fileName": _export_file_name(payload["fileName"], export_version, ".pdf"),
            "format": "pdf",
            "exportVersion": export_version,
        }

    async def final_document_pdf_file(
        self,
        project_id: str,
        version: str = MARKED_EXPORT_VERSION,
    ) -> FileResponse:
        export_version = _normalize_export_version(version)
        payload, doc_path = await self._export_document_path(project_id, export_version)
        pdf_path = doc_path.with_suffix(".pdf")
        async with self._pdf_export_lock(pdf_path):
            if not _pdf_matches_source(pdf_path, doc_path):
                raise HTTPException(status_code=404, detail="PDF 尚未生成，请先点击下载 PDF。")
            return FileResponse(
                path=pdf_path,
                media_type=PDF_MEDIA_TYPE,
                filename=_export_file_name(payload["fileName"], export_version, ".pdf"),
            )

    async def apply_format(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project_id)
        preset = str((data or {}).get("preset") or "standard").strip() or "standard"
        if preset not in TECH_FORMAT_PRESETS:
            raise HTTPException(status_code=400, detail="未知技术标格式预设。")
        style_overrides = (data or {}).get("styleOverrides") if isinstance((data or {}).get("styleOverrides"), dict) else None
        try:
            result = await asyncio.to_thread(
                apply_technical_document_format_preset,
                project_id,
                preset,
                style_overrides,
            )
            project_state = _technical_project_for_update(project_id)
            state = apply_technical_document_format_to_project(project_state, result)
            persist_workspace_project_state(project_state)
            doc_path = ensure_document(project_id, state["fileName"], state["fallback"]["content"])
            refresh_document_session(doc_path)
            sync_document_to_minio(doc_path, document_object_key(project_id))
            return now_message(
                f"已应用{result.get('label') or '技术标格式'}。",
                {
                    "format": result,
                    "document": _build_document_payload(project_id, request, self.api_prefix, state),
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"技术标格式切换失败：{exc}") from exc


technical_document_service = TechnicalDocumentService(technical_project_service, "/api/technical/projects")
