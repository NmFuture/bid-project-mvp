from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.onlyoffice_documents import download_document_from_onlyoffice


def _allowed_download_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("OnlyOffice 转换结果 URL 协议不受信任。")
    if parsed.username or parsed.password:
        raise RuntimeError("OnlyOffice 转换结果 URL 不允许包含认证信息。")
    allowed = {host.lower() for host in settings.onlyoffice_download_allowed_hosts}
    if "*" not in allowed and str(parsed.hostname or "").lower() not in allowed:
        raise RuntimeError("OnlyOffice 转换结果 URL 主机不在白名单内。")
    return url


def _conversion_result(response: httpx.Response) -> dict[str, object]:
    content_type = str(response.headers.get("content-type") or "").lower()
    if "json" in content_type:
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    root = ET.fromstring(response.text)
    return {
        "error": root.findtext("Error") or root.findtext("error") or "",
        "fileUrl": root.findtext("FileUrl") or root.findtext("fileUrl") or root.findtext("fileurl") or "",
    }


def _is_valid_docx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return "word/document.xml" in archive.namelist()
    except (FileNotFoundError, OSError, zipfile.BadZipFile):
        return False


async def convert_doc_to_docx(
    *,
    source_url: str,
    source_name: str,
    source_version: int,
    target_path: Path,
) -> Path:
    base_url = settings.onlyoffice_internal_url.rstrip("/")
    if not base_url:
        raise RuntimeError("OnlyOffice 内部服务地址未配置。")

    conversion_key = hashlib.sha256(
        f"{source_name}:{source_version}:{source_url}:docx".encode("utf-8")
    ).hexdigest()
    payload = {
        "async": False,
        "filetype": "doc",
        "key": conversion_key,
        "outputtype": "docx",
        "title": source_name,
        "url": source_url,
    }

    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        response = await client.post(f"{base_url}/ConvertService.ashx", json=payload)
        response.raise_for_status()
        result = _conversion_result(response)

    error = result.get("error")
    if error not in (None, "", 0, "0"):
        raise RuntimeError(f"OnlyOffice DOC 转 DOCX 失败：{error}")
    download_url = str(result.get("fileUrl") or result.get("fileurl") or "").strip()
    if not download_url:
        raise RuntimeError("OnlyOffice DOC 转 DOCX 未返回下载地址。")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await download_document_from_onlyoffice(
            _allowed_download_url(download_url),
            target_path,
            max_bytes=settings.onlyoffice_download_max_bytes,
        )
        if not _is_valid_docx(target_path):
            raise RuntimeError("OnlyOffice DOC 转换结果不是有效 DOCX。")
        return target_path
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
