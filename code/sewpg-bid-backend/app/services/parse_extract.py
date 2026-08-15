"""招标文件文本提取：docx/pdf 轻量提取、OCR 兜底与 Docling 文档解析引擎桥接。

来源：parsing-01 拆分，自 app/services/parsing.py 逐字搬迁，实现与行为不变；
符号经 parsing.py 门面 re-export，外部仍按 `app.services.parsing.<符号>` 访问。
"""
from __future__ import annotations

import json
import mimetypes
import zipfile
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from app.core.config import settings
from app.services.document_nav import nav_to_text
from app.services.document_parse_engine import create_document_parse_engine
from app.services.document_parse_quality import evaluate_document_nav_quality
from app.services.ocr_service import ocr_service
from app.services.parse_common import WORD_NAMESPACE, _normalize_text, _run_coroutine_blocking
from app.services.peripheral import PeripheralError


def extract_docx_text(path: Path, progress_callback: Callable[[int, int], None] | None = None) -> str:
    pieces: list[str] = []
    text_length = 0
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    total_bytes = max(1, len(document_xml))
    parser = ET.XMLPullParser(events=("end",))
    chunk_size = 512 * 1024
    next_progress = 20
    for offset in range(0, len(document_xml), chunk_size):
        chunk = document_xml[offset : offset + chunk_size]
        parser.feed(chunk)
        for _, element in parser.read_events():
            if element.tag == f"{WORD_NAMESPACE}t":
                text = element.text or ""
                pieces.append(text)
                text_length += len(text)
            elif element.tag == f"{WORD_NAMESPACE}tab":
                pieces.append("\t")
                text_length += 1
            elif element.tag in {f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"}:
                pieces.append("\n")
                text_length += 1
            elif element.tag == f"{WORD_NAMESPACE}p":
                pieces.append("\n")
                text_length += 1
                element.clear()
        if progress_callback:
            progress = max(1, min(99, round((offset + len(chunk)) * 100 / total_bytes)))
            if progress >= next_progress:
                progress_callback(progress, text_length)
                next_progress += 20
    parser.close()
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
        warnings.append("PDF 未提取到文本，疑似扫描件，已进入 OCR 兜底识别。")
    elif empty_pages:
        warnings.append(f"PDF 有 {empty_pages} 页未提取到文本。")

    return _normalize_text("\n\n".join(page_texts)), {
        "pageCount": page_count,
        "warnings": warnings,
        "requiresOcr": bool(page_count and empty_pages == page_count),
    }


def _ocr_fallback_text(project_id: str, file_record: dict[str, Any], file_path: Path) -> tuple[str, dict[str, Any]]:
    _ = project_id
    try:
        text, raw = _run_coroutine_blocking(
            ocr_service.recognize_text_for_parse(
                file_name=str(file_record.get("name") or file_path.name),
                content=file_path.read_bytes(),
                mime_type=str(file_record.get("content_type") or mimetypes.guess_type(file_path.name)[0] or ""),
            )
        )
        return _normalize_text(text), {
            "status": "completed",
            "pageCount": raw.get("pageCount") or "-",
        }
    except PeripheralError as exc:
        return "", {
            "status": "failed",
            "code": exc.code,
            "message": exc.detail,
        }
    except Exception as exc:
        return "", {
            "status": "failed",
            "code": "OCR_PARSE_FALLBACK_FAILED",
            "message": str(exc),
        }


def _ocr_business_pdf_pages(
    *,
    project_id: str,
    document: dict[str, Any],
    file_path: Path,
    page_numbers: list[int],
) -> dict[int, dict[str, Any]]:
    if not page_numbers:
        return {}
    try:
        import fitz  # type: ignore
    except Exception as exc:
        return {page_no: {"text": "", "meta": {"status": "failed", "message": str(exc)}} for page_no in page_numbers}

    results: dict[int, dict[str, Any]] = {}
    try:
        pdf = fitz.open(str(file_path))
    except Exception as exc:
        return {page_no: {"text": "", "meta": {"status": "failed", "message": str(exc)}} for page_no in page_numbers}
    with pdf:
        for page_no in page_numbers:
            if page_no < 1 or page_no > len(pdf):
                results[page_no] = {"text": "", "meta": {"status": "failed", "message": "page out of range"}}
                continue
            try:
                page = pdf.load_page(page_no - 1)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                text, raw = _run_coroutine_blocking(
                    ocr_service.recognize_text_for_parse(
                        file_name=f"{document.get('name') or file_path.stem}-page-{page_no}.png",
                        content=pix.tobytes("png"),
                        mime_type="image/png",
                    )
                )
                results[page_no] = {"text": _normalize_text(text), "meta": raw}
            except Exception as exc:
                results[page_no] = {"text": "", "meta": {"status": "failed", "message": str(exc)}}
    return results


def _append_ocr_blocks_to_document_nav(
    document_nav: dict[str, Any],
    *,
    document_id: str,
    ocr_results: dict[int, dict[str, Any]],
) -> tuple[list[int], list[str]]:
    applied_pages: list[int] = []
    warnings: list[str] = []
    blocks = document_nav.setdefault("blocks", [])
    evidence = document_nav.setdefault("evidence", [])
    if not isinstance(blocks, list) or not isinstance(evidence, list):
        return applied_pages, ["DocumentNav 结构异常，无法追加 OCR 补充文本。"]
    next_index = len([block for block in blocks if isinstance(block, dict)]) + 1
    for page_no in sorted(ocr_results):
        result = ocr_results[page_no]
        text = str((result or {}).get("text") or "").strip()
        meta = (result or {}).get("meta") if isinstance((result or {}).get("meta"), dict) else {}
        if not text:
            warnings.append(f"第 {page_no} 页 OCR 兜底未产生文本：{meta.get('message') or meta.get('status') or '未知错误'}")
            continue
        block_id = f"{document_id}:B{next_index:06d}"
        evidence_id = f"{document_id}:P{page_no:04d}:O{next_index:06d}"
        block = {
            "id": block_id,
            "documentId": document_id,
            "pageNo": page_no,
            "type": "ocr_text",
            "text": text,
            "evidenceId": evidence_id,
            "sourceEngine": "deepseek-ocr",
        }
        blocks.append(block)
        evidence.append(
            {
                "id": evidence_id,
                "documentId": document_id,
                "pageNo": page_no,
                "kind": "ocr_text",
                "blockId": block_id,
                "tableId": "",
                "imageId": "",
                "bbox": [],
                "sourceText": text,
                "sourceEngine": "deepseek-ocr",
            }
        )
        applied_pages.append(page_no)
        next_index += 1
    return applied_pages, warnings


def _merge_document_nav_quality(
    document_nav: dict[str, Any],
    *,
    source_quality: dict[str, Any],
    evaluated_quality: dict[str, Any],
    engine: str,
    docling_mode: str = "",
) -> dict[str, Any]:
    quality = dict(source_quality)
    parse_status = str(quality.get("status") or "completed")
    quality_status = str(evaluated_quality.get("status") or quality.get("qualityStatus") or parse_status)
    warnings = [
        str(warning)
        for warning in [
            *(quality.get("warnings") if isinstance(quality.get("warnings"), list) else []),
            *(evaluated_quality.get("warnings") if isinstance(evaluated_quality.get("warnings"), list) else []),
        ]
        if str(warning).strip()
    ]
    for key, value in evaluated_quality.items():
        if key in {"status", "warnings"}:
            continue
        quality[key] = value
    quality["engine"] = str(quality.get("engine") or engine or "docling")
    quality["sourceEngine"] = str(document_nav.get("sourceEngine") or quality.get("sourceEngine") or quality["engine"])
    quality["status"] = parse_status
    quality["qualityStatus"] = quality_status
    quality["fallbackUsed"] = bool(source_quality.get("fallbackUsed")) or bool(evaluated_quality.get("fallbackUsed"))
    if docling_mode:
        quality["doclingMode"] = docling_mode
    quality["warnings"] = list(dict.fromkeys(warnings))
    return quality


def _finalize_loaded_document_nav(
    *,
    project_id: str,
    document: dict[str, Any],
    file_path: Path,
    document_nav: dict[str, Any],
    document_nav_path: Path,
    quality_path: Path,
    source_quality: dict[str, Any],
    metadata: dict[str, Any],
    engine: str,
    docling_mode: str,
    apply_ocr_fallback: bool,
) -> tuple[str, dict[str, Any], list[str]]:
    """统一处理 Docling 现场结果和独立 Worker 的预解析结果。"""

    warnings: list[str] = []
    quality = _merge_document_nav_quality(
        document_nav,
        source_quality=source_quality,
        evaluated_quality=evaluate_document_nav_quality(document_nav),
        engine=engine,
        docling_mode=docling_mode,
    )
    if apply_ocr_fallback and settings.business_pdf_ocr_fallback_enabled and quality.get("ocrPages"):
        already_applied = {int(page) for page in quality.get("ocrAppliedPages") or []}
        ocr_results = _ocr_business_pdf_pages(
            project_id=project_id,
            document=document,
            file_path=file_path,
            page_numbers=[int(page) for page in quality.get("ocrPages") or [] if int(page) not in already_applied],
        )
        applied_pages, ocr_warnings = _append_ocr_blocks_to_document_nav(
            document_nav,
            document_id=str(document.get("id") or "DOC-1"),
            ocr_results=ocr_results,
        )
        if applied_pages:
            metadata["pageOcr"] = {"appliedPages": applied_pages}
            quality["ocrAppliedPages"] = sorted(already_applied | set(applied_pages))
        warnings.extend(ocr_warnings)
        quality.setdefault("warnings", [])
        if isinstance(quality["warnings"], list):
            quality["warnings"].extend(ocr_warnings)
    quality["warnings"] = list(dict.fromkeys(str(item) for item in quality.get("warnings") or [] if str(item).strip()))
    document_nav["quality"] = quality
    document_nav_path.write_text(json.dumps(document_nav, ensure_ascii=False, indent=2), encoding="utf-8")
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    warnings.extend(quality.get("warnings") or [])
    text = nav_to_text(document_nav)
    metadata["pageCount"] = len(document_nav.get("pages") or []) or quality.get("sourcePageCount") or "-"
    return text, metadata, list(dict.fromkeys(warnings))


def _parse_pdf_with_document_engine(
    *,
    project_id: str,
    document: dict[str, Any],
    file_path: Path,
    project_dir: Path,
    engine_fallback: str | None = None,
    require_preparsed: bool = False,
    technical_document_nav: bool = False,
) -> tuple[str, dict[str, Any], list[str]]:
    document_id = str(document.get("id") or "DOC-1")
    existing_document_nav_path = project_dir / f"{document_id}_document_nav.json"
    engine_name = settings.business_pdf_parse_engine.strip().lower() or "docling"
    existing_quality_path = project_dir / "document_parse" / engine_name / document_id / "parse_quality.json"
    if existing_document_nav_path.is_file() and existing_quality_path.is_file():
        try:
            existing_quality = json.loads(existing_quality_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_quality = {}
        if not isinstance(existing_quality, dict):
            existing_quality = {}
        expected_sha256 = str(document.get("sha256") or "")
        expected_run_id = str(document.get("runId") or "")
        source_matches = not expected_sha256 or str(existing_quality.get("sourceSha256") or "") == expected_sha256
        run_matches = not expected_run_id or str(existing_quality.get("runId") or "") == expected_run_id
        if (
            isinstance(existing_quality, dict)
            and str(existing_quality.get("status") or "").lower() == "completed"
            and (require_preparsed or not bool(existing_quality.get("fallbackUsed")))
            and source_matches
            and run_matches
        ):
            document_nav = json.loads(existing_document_nav_path.read_text(encoding="utf-8"))
            metadata = {
                "documentParseEngine": str(existing_quality.get("engine") or engine_name),
                "documentNavPath": str(existing_document_nav_path),
                "parseQualityPath": str(existing_quality_path),
            }
            docling_mode = str(existing_quality.get("doclingMode") or "")
            if docling_mode:
                metadata["doclingMode"] = docling_mode
            return _finalize_loaded_document_nav(
                project_id=project_id,
                document=document,
                file_path=file_path,
                document_nav=document_nav,
                document_nav_path=existing_document_nav_path,
                quality_path=existing_quality_path,
                source_quality=existing_quality,
                metadata=metadata,
                engine=str(existing_quality.get("engine") or engine_name),
                docling_mode=docling_mode,
                apply_ocr_fallback=True,
            )

    if require_preparsed:
        raise RuntimeError(f"Docling Worker 未生成文档 {document_id} 的有效解析结果。")

    effective_fallback = engine_fallback if engine_fallback is not None else settings.business_pdf_engine_fallback
    engine = create_document_parse_engine(
        parse_engine=settings.business_pdf_parse_engine,
        fallback=effective_fallback,
    )
    engine_document = {**document, "mergeTechnicalTextLayer": technical_document_nav}
    result = engine.parse_pdf(project_id=project_id, document=engine_document, output_dir=project_dir)
    metadata = {
        "documentParseEngine": str(result.get("documentParseEngine") or settings.business_pdf_parse_engine),
        "parseQualityPath": str(result.get("parseQualityPath") or ""),
    }
    warnings: list[str] = []
    status = str(result.get("status") or "").lower()
    document_nav: dict[str, Any] | None = None
    document_nav_path = Path(str(result.get("documentNavPath") or ""))

    if status == "completed":
        if document_nav_path.is_file():
            document_nav = json.loads(document_nav_path.read_text(encoding="utf-8"))

    if document_nav:
        metadata["documentNavPath"] = str(document_nav_path)
        if result.get("doclingMode"):
            metadata["doclingMode"] = str(result.get("doclingMode") or "")
        source_quality = document_nav.get("quality") if isinstance(document_nav.get("quality"), dict) else {}
        raw_quality_path = str(metadata.get("parseQualityPath") or "").strip()
        if raw_quality_path:
            previous_quality_path = Path(raw_quality_path)
            if previous_quality_path.is_file():
                try:
                    previous_quality = json.loads(previous_quality_path.read_text(encoding="utf-8"))
                    if isinstance(previous_quality, dict):
                        source_quality = {**previous_quality, **source_quality}
                except json.JSONDecodeError:
                    pass
        quality_path = (
            Path(raw_quality_path)
            if raw_quality_path
            else project_dir / f"{document['id']}_parse_quality.json"
        )
        metadata["parseQualityPath"] = str(quality_path)
        return _finalize_loaded_document_nav(
            project_id=project_id,
            document=document,
            file_path=file_path,
            document_nav=document_nav,
            document_nav_path=document_nav_path,
            quality_path=quality_path,
            source_quality=source_quality,
            metadata=metadata,
            engine=str(metadata.get("documentParseEngine") or "docling"),
            docling_mode=str(result.get("doclingMode") or source_quality.get("doclingMode") or ""),
            apply_ocr_fallback=True,
        )

    fallback_reason = str(result.get("fallbackReason") or "Docling 解析未生成 DocumentNav")
    metadata["fallbackReason"] = fallback_reason
    if effective_fallback != "lightweight":
        metadata["documentParseStatus"] = "failed"
        warnings.append(f"Docling 解析失败，未启用 PDF 解析兜底：{fallback_reason}")
        return "", metadata, warnings
    metadata["documentParseStatus"] = "fallback"
    warnings.append(f"Docling 解析失败，已回退到轻量 PDF 文本解析：{fallback_reason}")
    return "", metadata, warnings
