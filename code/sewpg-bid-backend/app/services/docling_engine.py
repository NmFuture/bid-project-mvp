from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.docling_nav_adapter import convert_docling_output_to_document_nav
from app.services.document_nav import nav_to_text
from app.services.document_parse_engine import DocumentParseEngine


AUTO_DOCLING_MODE = "auto-layout-table-ocr"
LOCAL_TEXT_LAYER_MODE = "local-text-layer"


def _docling_document_to_dict(document: Any) -> dict[str, Any]:
    for method_name in ("export_to_dict", "model_dump", "dict"):
        method = getattr(document, method_name, None)
        if not callable(method):
            continue
        try:
            payload = method(mode="json") if method_name == "model_dump" else method()
        except TypeError:
            payload = method()
        if isinstance(payload, dict):
            return payload
    return {}


def _docling_document_to_markdown(document: Any) -> str:
    method = getattr(document, "export_to_markdown", None)
    if callable(method):
        return str(method())
    return ""


def _configure_docling_auto_pipeline_options(pipeline_options: Any) -> Any:
    artifacts_path = getattr(settings, "docling_artifacts_path", None)
    if artifacts_path and hasattr(pipeline_options, "artifacts_path"):
        pipeline_options.artifacts_path = Path(artifacts_path)

    if hasattr(pipeline_options, "do_table_structure"):
        pipeline_options.do_table_structure = True
    if hasattr(pipeline_options, "do_ocr"):
        pipeline_options.do_ocr = True

    table_options = getattr(pipeline_options, "table_structure_options", None)
    if table_options is not None:
        if hasattr(table_options, "do_cell_matching"):
            table_options.do_cell_matching = True
        if hasattr(table_options, "mode"):
            try:
                from docling.datamodel.pipeline_options import TableFormerMode

                table_options.mode = TableFormerMode.ACCURATE
            except Exception:
                table_options.mode = "accurate"

    if importlib.util.find_spec("onnxruntime") is not None:
        try:
            from docling.datamodel.pipeline_options import RapidOcrOptions

            pipeline_options.ocr_options = RapidOcrOptions(
                backend="onnxruntime",
                force_full_page_ocr=False,
                bitmap_area_threshold=0.05,
                lang=["chinese", "english"],
            )
        except Exception:
            pass

    ocr_options = getattr(pipeline_options, "ocr_options", None)
    if ocr_options is not None:
        if hasattr(ocr_options, "force_full_page_ocr"):
            ocr_options.force_full_page_ocr = False
        if hasattr(ocr_options, "bitmap_area_threshold"):
            ocr_options.bitmap_area_threshold = 0.05

    return pipeline_options


def run_docling_conversion(pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    output_dir.mkdir(parents=True, exist_ok=True)
    pipeline_options = _configure_docling_auto_pipeline_options(PdfPipelineOptions())
    result = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    ).convert(str(pdf_path))
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError("Docling 未返回 document 结果")

    json_path = output_dir / "docling_document.json"
    markdown_path = output_dir / "docling.md"
    payload = _docling_document_to_dict(document)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_docling_document_to_markdown(document), encoding="utf-8")
    pages = payload.get("pages") if isinstance(payload.get("pages"), (dict, list)) else []
    tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    return {
        "markdownPath": str(markdown_path),
        "jsonPath": str(json_path),
        "pageCount": len(pages),
        "tableCount": len(tables),
        "mode": AUTO_DOCLING_MODE,
        "warnings": [],
    }


def _is_heading_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith(("第", "一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、")):
        return len(stripped) <= 80
    return bool(stripped[:4].replace(".", "").isdigit() and len(stripped) <= 100)


def run_docling_local_text_layer_conversion(pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    import fitz

    output_dir.mkdir(parents=True, exist_ok=True)
    pages: dict[str, dict[str, Any]] = {}
    texts: list[dict[str, Any]] = []
    markdown_parts: list[str] = []
    with fitz.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf, start=1):
            rect = page.rect
            pages[str(page_index)] = {"size": {"width": float(rect.width), "height": float(rect.height)}}
            page_lines: list[str] = []
            raw = page.get_text("dict")
            blocks = raw.get("blocks") if isinstance(raw, dict) else []
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != 0:
                    continue
                bbox = block.get("bbox") if isinstance(block.get("bbox"), (list, tuple)) else [0, 0, 0, 0]
                lines = block.get("lines") if isinstance(block.get("lines"), list) else []
                for line in lines:
                    spans = line.get("spans") if isinstance(line, dict) and isinstance(line.get("spans"), list) else []
                    text = "".join(str(span.get("text") or "") for span in spans if isinstance(span, dict)).strip()
                    if not text:
                        continue
                    label = "section_header" if _is_heading_text(text) else "text"
                    texts.append(
                        {
                            "label": label,
                            "text": text,
                            "prov": [
                                {
                                    "page_no": page_index,
                                    "bbox": {
                                        "l": float(bbox[0]),
                                        "t": float(bbox[1]),
                                        "r": float(bbox[2]),
                                        "b": float(bbox[3]),
                                    },
                                }
                            ],
                        }
                    )
                    page_lines.append(("# " if label == "section_header" else "") + text)
            if page_lines:
                markdown_parts.append(f"--- PAGE {page_index} ---\n" + "\n".join(page_lines))

    if not texts:
        raise RuntimeError("Docling 本地文本层模式未提取到 PDF 文本")

    payload = {
        "schema_name": "DoclingDocument",
        "name": pdf_path.name,
        "pages": pages,
        "texts": texts,
        "tables": [],
        "conversion_mode": LOCAL_TEXT_LAYER_MODE,
    }
    json_path = output_dir / "docling_document.json"
    markdown_path = output_dir / "docling.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text("\n\n".join(markdown_parts), encoding="utf-8")
    return {
        "markdownPath": str(markdown_path),
        "jsonPath": str(json_path),
        "pageCount": len(pages),
        "tableCount": 0,
        "mode": LOCAL_TEXT_LAYER_MODE,
        "warnings": ["Docling 标准 PDF pipeline 不可用，已使用本地文本层兜底。"],
    }


class DoclingParseEngine(DocumentParseEngine):
    def __init__(self, *, fallback: str = "none") -> None:
        self.fallback = fallback.strip().lower() or "none"

    def parse_pdf(self, *, project_id: str, document: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        _ = project_id
        document_id = str(
            document.get("id") or Path(str(document.get("path") or document.get("sourcePath") or "")).stem or "DOC-1"
        )
        pdf_path = Path(str(document.get("path") or document.get("sourcePath") or ""))
        docling_output_dir = output_dir / "document_parse" / "docling" / document_id
        docling_output_dir.mkdir(parents=True, exist_ok=True)
        quality_path = docling_output_dir / "parse_quality.json"
        fallback_reason = ""

        try:
            try:
                conversion_result = run_docling_conversion(pdf_path, docling_output_dir)
                fallback_used = False
            except Exception as exc:
                if self.fallback != "lightweight":
                    raise
                fallback_reason = str(exc)
                conversion_result = run_docling_local_text_layer_conversion(pdf_path, docling_output_dir)
                fallback_used = True
            document_nav = convert_docling_output_to_document_nav(
                document_id=document_id,
                source_path=pdf_path,
                docling_output_dir=docling_output_dir,
            )
            document_nav_path = output_dir / f"{document_id}_document_nav.json"
            document_nav_path.write_text(json.dumps(document_nav, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            quality = {
                "engine": "docling",
                "status": "failed",
                "pageCount": 0,
                "lowQualityPages": [],
                "tableCount": 0,
                "fallbackUsed": False,
                "warnings": [str(exc)],
            }
            quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "documentParseEngine": "docling",
                "status": "failed",
                "doclingOutputDir": str(docling_output_dir),
                "parseQualityPath": str(quality_path),
                "fallbackReason": str(exc),
            }

        docling_mode = str(conversion_result.get("mode") or AUTO_DOCLING_MODE)
        quality = dict(document_nav.get("quality") if isinstance(document_nav.get("quality"), dict) else {})
        quality.update(
            {
                "engine": "docling",
                "status": "completed",
                "fallbackUsed": fallback_used,
                "markdownPath": str(conversion_result.get("markdownPath") or ""),
                "jsonPath": str(conversion_result.get("jsonPath") or ""),
                "doclingMode": docling_mode,
            }
        )
        if fallback_reason:
            quality["fallbackReason"] = fallback_reason
        warnings = list(quality.get("warnings") or [])
        warnings.extend(str(item) for item in conversion_result.get("warnings") or [])
        quality["warnings"] = list(dict.fromkeys(warnings))
        quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "documentParseEngine": "docling",
            "status": "completed",
            "doclingOutputDir": str(docling_output_dir),
            "parseQualityPath": str(quality_path),
            "documentNavPath": str(document_nav_path),
            "markdownPath": str(conversion_result.get("markdownPath") or ""),
            "jsonPath": str(conversion_result.get("jsonPath") or ""),
            "doclingMode": docling_mode,
            "text": nav_to_text(document_nav),
        }
