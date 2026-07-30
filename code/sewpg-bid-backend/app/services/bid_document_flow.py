from __future__ import annotations

import asyncio
import copy
import hashlib
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.services.bid_document_state import final_document_state, force_save_document_state, save_document_content_state
from app.services.bid_project_service import BidProjectService
from app.services.onlyoffice_documents import (
    WORD_MEDIA_TYPE,
    build_editor_session_key,
    document_object_key,
    download_document_from_onlyoffice,
    ensure_document,
    refresh_document_session,
    sync_document_to_minio,
    write_document,
)
from app.services.url_utils import absolute_url, now_message, onlyoffice_backend_base_url
from app.services.workspace_project_access import persist_workspace_project_state, require_workspace_project_for_update


PDF_MEDIA_TYPE = "application/pdf"


def _add_query_param(url: str, key: str, value: Any) -> str:
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append((key, str(value)))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _add_callback_token(url: str) -> str:
    token = settings.onlyoffice_callback_token
    if not token:
        return url
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("oo_callback_token", token))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _allowed_host(host: str | None, allowed_hosts: tuple[str, ...]) -> bool:
    if not host:
        return False
    normalized = host.lower()
    allowed = {item.lower() for item in allowed_hosts}
    return "*" in allowed or normalized in allowed


def _validate_callback_token(request: Request) -> None:
    expected = settings.onlyoffice_callback_token
    if not expected:
        return
    supplied = request.query_params.get("oo_callback_token", "")
    if supplied != expected:
        raise HTTPException(status_code=403, detail="OnlyOffice callback token 无效。")


def _validate_download_url(download_url: str) -> str:
    parsed = urlparse(download_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="OnlyOffice 回写 URL 协议不被允许。")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="OnlyOffice 回写 URL 不允许包含认证信息。")
    if not _allowed_host(parsed.hostname, settings.onlyoffice_download_allowed_hosts):
        allowed = ", ".join(settings.onlyoffice_download_allowed_hosts)
        raise HTTPException(status_code=400, detail=f"OnlyOffice 回写 URL 主机不在白名单内：{allowed}")
    return download_url


async def _convert_document_to_pdf_via_onlyoffice(source_url: str, source_path: Path, target_path: Path) -> Path:
    base_url = settings.onlyoffice_internal_url.rstrip("/")
    if not base_url:
        raise RuntimeError("OnlyOffice 内部服务地址未配置。")
    source_ext = source_path.suffix.lower().lstrip(".") or "docx"
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        payload = {
            "async": False,
            "filetype": source_ext,
            "key": hashlib.sha256(f"{source_path}:{source_path.stat().st_mtime_ns}:pdf".encode("utf-8")).hexdigest(),
            "outputtype": "pdf",
            "title": source_path.name,
            "url": source_url,
        }
        response = await client.post(f"{base_url}/ConvertService.ashx", json=payload)
        response.raise_for_status()
        content_type = str(response.headers.get("content-type") or "").lower()
        if "json" in content_type:
            result = response.json()
        else:
            root = ET.fromstring(response.text)
            result = {
                "error": root.findtext("Error") or root.findtext("error") or "",
                "fileUrl": root.findtext("FileUrl") or root.findtext("fileUrl") or root.findtext("fileurl") or "",
            }
        if result.get("error"):
            raise RuntimeError(f"OnlyOffice PDF 转换失败：{result.get('error')}")
        pdf_url = result.get("fileUrl") or result.get("fileurl")
        if not pdf_url:
            raise RuntimeError("OnlyOffice 未返回 PDF 下载地址。")
        download = await client.get(str(pdf_url))
        download.raise_for_status()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(download.content)
    return target_path


async def _convert_document_to_pdf_locally(source_path: Path, target_path: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="business-pdf-") as tmp:
        output_dir = Path(tmp)
        command = [
            "libreoffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(source_path),
        ]
        try:
            await asyncio.to_thread(
                subprocess.run,
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("本地 PDF 兜底失败：未安装 libreoffice。") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("本地 PDF 兜底失败：转换超时。") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(f"本地 PDF 兜底失败：{detail or exc}") from exc
        converted = output_dir / f"{source_path.stem}.pdf"
        if not converted.exists():
            matches = list(output_dir.glob("*.pdf"))
            converted = matches[0] if matches else converted
        if not converted.exists():
            raise RuntimeError("本地 PDF 兜底失败：未生成 PDF 文件。")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(converted.read_bytes())
        return target_path


def _build_document_payload(
    project_id: str,
    request: Request,
    api_prefix: str,
    document_state: dict[str, Any],
) -> dict[str, Any]:
    payload = copy.deepcopy(document_state)
    document_version = payload.get("version") or 1
    doc_path = ensure_document(
        project_id,
        payload["fileName"],
        payload["fallback"]["content"],
    )

    quoted_name = quote(payload["fileName"])
    browser_file_url = _add_query_param(
        absolute_url(request, f"{api_prefix}/{project_id}/document/file/{quoted_name}"),
        "doc_version",
        document_version,
    )
    browser_callback_url = _add_callback_token(
        _add_query_param(
            absolute_url(request, f"{api_prefix}/{project_id}/document/callback"),
            "oo_doc_version",
            document_version,
        )
    )
    onlyoffice_base = onlyoffice_backend_base_url(request)
    onlyoffice_file_url = _add_query_param(
        f"{onlyoffice_base}{api_prefix}/{project_id}/document/file/{quoted_name}",
        "doc_version",
        document_version,
    )
    onlyoffice_callback_url = _add_callback_token(
        _add_query_param(
            f"{onlyoffice_base}{api_prefix}/{project_id}/document/callback",
            "oo_doc_version",
            document_version,
        )
    )

    return {
        **payload,
        "fileUrl": browser_file_url,
        "sourceFileUrl": browser_file_url,
        "onlyoffice": {
            **payload["onlyoffice"],
            "fileUrl": onlyoffice_file_url,
            "callbackUrl": onlyoffice_callback_url,
            "browserFileUrl": browser_file_url,
            "browserCallbackUrl": browser_callback_url,
            "documentKey": build_editor_session_key(doc_path, payload.get("version") or 1),
        },
    }


class BidDocumentService:
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

    def document_state(self, project_id: str) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        return copy.deepcopy(project["document_state"])

    def build_document_payload(
        self,
        project_id: str,
        request: Request,
        document_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = document_state if document_state is not None else self.document_state(project_id)
        return _build_document_payload(project_id, request, self.api_prefix, state)

    async def document(self, project_id: str, request: Request) -> dict[str, Any]:
        return self.build_document_payload(project_id, request)

    async def save_document(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        content = str((data or {}).get("content") or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="保存内容不能为空。")
        payload = save_document_content_state(project, project_id, content)
        persist_workspace_project_state(project)
        doc_path = ensure_document(project_id, payload["fileName"], content)
        write_document(
            doc_path,
            payload["fileName"],
            content,
        )
        sync_document_to_minio(doc_path, document_object_key(project_id))
        response_payload = self.build_document_payload(project_id, request, payload)
        return now_message("文档已保存并回写。", response_payload)

    async def force_save_document(self, project_id: str, request: Request) -> dict[str, Any]:
        project = self.require_project_for_update(project_id)
        state = force_save_document_state(project, project_id)
        persist_workspace_project_state(project)
        doc_path = ensure_document(
            project_id,
            state["fileName"],
            state["fallback"]["content"],
        )
        refresh_document_session(doc_path)
        sync_document_to_minio(doc_path, document_object_key(project_id))
        payload = self.build_document_payload(project_id, request, state)
        return now_message("已刷新文档状态。", payload)

    async def final_document(self, project_id: str, request: Request) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        payload = final_document_state(project)
        payload["fileUrl"] = absolute_url(request, f"{self.api_prefix}/{project_id}/final-document/file")
        return payload

    async def final_document_pdf(self, project_id: str, request: Request) -> dict[str, Any]:
        payload = self.document_state(project_id)
        doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
        pdf_name = f"{Path(payload['fileName']).stem}.pdf"
        pdf_path = doc_path.with_suffix(".pdf")
        if not pdf_path.exists() or pdf_path.stat().st_mtime_ns < doc_path.stat().st_mtime_ns:
            source_url = f"{onlyoffice_backend_base_url(request).rstrip('/')}{self.api_prefix}/{project_id}/final-document/file"
            try:
                await _convert_document_to_pdf_via_onlyoffice(source_url, doc_path, pdf_path)
            except Exception as exc:
                try:
                    await _convert_document_to_pdf_locally(doc_path, pdf_path)
                except Exception as fallback_exc:
                    raise HTTPException(status_code=502, detail=f"PDF 生成失败：{exc}；本地兜底也失败：{fallback_exc}") from fallback_exc
        return {
            "message": "PDF 已生成。",
            "fileUrl": absolute_url(request, f"{self.api_prefix}/{project_id}/final-document/pdf/file"),
            "fileName": pdf_name,
            "format": "pdf",
        }

    async def document_file(self, project_id: str, filename: str = "") -> FileResponse:
        payload = self.document_state(project_id)
        doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
        return FileResponse(
            path=doc_path,
            media_type=WORD_MEDIA_TYPE,
            filename=payload["fileName"],
        )

    async def document_callback(
        self,
        project_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> JSONResponse:
        project = self.require_project_for_update(project_id)
        payload = data or {}
        _validate_callback_token(request)

        status = int(payload.get("status") or 0)
        if status not in {2, 6} or not payload.get("url"):
            return JSONResponse({"error": 0})

        document_state = project["document_state"]
        callback_version_raw = request.query_params.get("oo_doc_version")
        if callback_version_raw:
            try:
                callback_version = int(callback_version_raw)
                current_version = int(document_state.get("version") or 1)
            except (TypeError, ValueError):
                callback_version = current_version = 0
            if callback_version and current_version and callback_version < current_version:
                return JSONResponse({"error": 0, "ignored": "stale_document_version"})

        download_url = _validate_download_url(str(payload["url"]))
        target_path = ensure_document(
            project_id,
            document_state["fileName"],
            document_state["fallback"]["content"],
        )

        try:
            await download_document_from_onlyoffice(
                download_url,
                target_path,
                max_bytes=settings.onlyoffice_download_max_bytes,
            )
            sync_document_to_minio(target_path, document_object_key(project_id))
        except (httpx.HTTPError, RuntimeError) as exc:
            return JSONResponse(status_code=502, content={"error": 1, "message": str(exc)})

        force_save_document_state(project, project_id)
        persist_workspace_project_state(project)
        return JSONResponse({"error": 0})

    async def final_document_file(self, project_id: str) -> FileResponse:
        payload = self.document_state(project_id)
        doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
        return FileResponse(
            path=doc_path,
            media_type=WORD_MEDIA_TYPE,
            filename=payload["fileName"],
        )

    async def final_document_pdf_file(self, project_id: str) -> FileResponse:
        payload = self.document_state(project_id)
        doc_path = ensure_document(project_id, payload["fileName"], payload["fallback"]["content"])
        pdf_path = doc_path.with_suffix(".pdf")
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF 尚未生成，请先点击下载 PDF。")
        return FileResponse(
            path=pdf_path,
            media_type=PDF_MEDIA_TYPE,
            filename=f"{Path(payload['fileName']).stem}.pdf",
        )
