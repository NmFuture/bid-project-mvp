from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.core.config import settings

WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_PREVIEW_LIMIT = 600


def parsed_project_dir(project_id: str) -> Path:
    path = settings.parsed_dir / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        compact.append(line)
        previous_blank = blank
    return "\n".join(compact).strip()


def extract_docx_text(path: Path) -> str:
    pieces: list[str] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as xml_file:
            for _, element in ET.iterparse(xml_file, events=("end",)):
                if element.tag == f"{WORD_NAMESPACE}t":
                    pieces.append(element.text or "")
                elif element.tag == f"{WORD_NAMESPACE}tab":
                    pieces.append("\t")
                elif element.tag in {f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"}:
                    pieces.append("\n")
                elif element.tag == f"{WORD_NAMESPACE}p":
                    pieces.append("\n")
                    element.clear()
    return _normalize_text("".join(pieces))


def extract_pdf_text(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("未安装 pypdf，当前无法解析 PDF。") from exc

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    empty_pages = 0
    page_texts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            empty_pages += 1
        page_texts.append(text)

    warnings: list[str] = []
    if page_count and empty_pages == page_count:
        warnings.append("PDF 未提取到文本，疑似扫描件。当前 MVP 暂不支持 OCR。")
    elif empty_pages:
        warnings.append(f"PDF 有 {empty_pages} 页未提取到文本。")

    return _normalize_text("\n\n".join(page_texts)), {
        "pageCount": page_count,
        "warnings": warnings,
    }


def parse_tender_documents(project_id: str, tender_files: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    project_dir = parsed_project_dir(project_id)
    documents: list[dict[str, Any]] = []
    combined_parts: list[str] = []
    warnings: list[str] = []

    for file_record in tender_files:
        file_path = Path(str(file_record["path"]))
        extension = file_path.suffix.lower()
        page_count: int | str = "-"
        file_warnings: list[str] = []

        if extension == ".docx":
            text = extract_docx_text(file_path)
        elif extension == ".md":
            text = file_path.read_text(encoding="utf-8", errors="replace")
        elif extension == ".pdf":
            text, pdf_meta = extract_pdf_text(file_path)
            page_count = pdf_meta["pageCount"]
            file_warnings.extend(pdf_meta["warnings"])
        else:
            text = ""
            file_warnings.append(f"当前 MVP 暂不解析 {extension or '未知'} 类型文件。")

        text = _normalize_text(text)
        text_length = len(text)
        text_path = project_dir / f"{file_record['id']}.txt"
        text_path.write_text(text, encoding="utf-8")

        metadata = {
            "id": file_record["id"],
            "name": file_record["name"],
            "textPath": str(text_path),
            "textLength": text_length,
            "pageCount": page_count,
            "warnings": file_warnings,
        }
        documents.append(metadata)
        warnings.extend(file_warnings)

        if text:
            combined_parts.append(f"# 文件：{file_record['name']}\n\n{text}")

    combined_text = _normalize_text("\n\n".join(combined_parts))
    combined_text_path = project_dir / "combined.txt"
    combined_text_path.write_text(combined_text, encoding="utf-8")

    manifest_path = project_dir / "manifest.json"
    manifest = {
        "projectId": project_id,
        "combinedTextPath": str(combined_text_path),
        "documents": documents,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "fileCount": len(tender_files),
        "extractedCount": 0,
        "textLength": len(combined_text),
        "textPreview": combined_text[:TEXT_PREVIEW_LIMIT],
        "warnings": warnings,
    }

    return summary, {
        "projectDir": str(project_dir),
        "combinedTextPath": str(combined_text_path),
        "manifestPath": str(manifest_path),
        "documents": documents,
    }
