from __future__ import annotations

import json
import importlib.util
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.docling_nav_adapter import convert_docling_output_to_document_nav
from app.services.document_nav import nav_to_text
from app.services.document_parse_engine import DocumentParseEngine


AUTO_DOCLING_MODE = "auto-layout-table-ocr"
AUTO_DOCLING_PAGE_RANGE_MODE = "auto-layout-table-page-range"
LOCAL_TEXT_LAYER_MODE = "local-text-layer"
_DOCLING_PAGE_WINDOW_MIN_SOURCE_PAGES = 120
_DOCLING_PAGE_WINDOW_SKIP_FIRST_PAGES = 20
_DOCLING_PAGE_WINDOW_MAX_PAGES = 120
_DOCLING_PAGE_WINDOW_END_PADDING = 2
_DOCLING_LAYOUT_REPO_FOLDER = "docling-project--docling-layout-heron"
_DOCLING_TABLE_REPO_FOLDER = "docling-project--docling-models"
_DOCLING_TABLE_ACCURATE_DIR = "model_artifacts/tableformer/accurate"
_REQUIRED_DOCLING_LAYOUT_ARTIFACTS = (
    f"{_DOCLING_LAYOUT_REPO_FOLDER}/config.json",
    f"{_DOCLING_LAYOUT_REPO_FOLDER}/model.safetensors",
    f"{_DOCLING_LAYOUT_REPO_FOLDER}/preprocessor_config.json",
)
_REQUIRED_DOCLING_TABLE_ARTIFACTS = (
    f"{_DOCLING_TABLE_REPO_FOLDER}/{_DOCLING_TABLE_ACCURATE_DIR}/tm_config.json",
    f"{_DOCLING_TABLE_REPO_FOLDER}/{_DOCLING_TABLE_ACCURATE_DIR}/tableformer_accurate.safetensors",
)
_RAPIDOCR_BUNDLED_MODEL_FILES = {
    "det_model_path": "PP-OCRv6_det_small.onnx",
    "cls_model_path": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "rec_model_path": "PP-OCRv6_rec_small.onnx",
}
_RAPIDOCR_ARTIFACT_PATH_OVERRIDES = {
    "Global.font_path": None,
    "Rec.font_path": None,
    "Rec.rec_keys_path": None,
}
_APPENDIX_START_MARKERS = (
    "三、附表",
    "技术附表A",
    "附表A.1",
    "投标机型总方案信息表",
)
_APPENDIX_HEADING_RE = re.compile(r"附表[A-I](?:[.．]\d+|[.．]|[0-9])")


def _docling_artifacts_path_is_usable(artifacts_path: Any) -> bool:
    if not artifacts_path:
        return False
    path = Path(artifacts_path)
    if not path.is_dir():
        return False
    has_layout_model = all((path / relative_path).is_file() for relative_path in _REQUIRED_DOCLING_LAYOUT_ARTIFACTS)
    has_table_model = all((path / relative_path).is_file() for relative_path in _REQUIRED_DOCLING_TABLE_ARTIFACTS)
    return has_layout_model and has_table_model


def _bundled_rapidocr_model_paths() -> dict[str, str]:
    try:
        import rapidocr
    except Exception:
        return {}

    package_file = getattr(rapidocr, "__file__", None)
    if not package_file:
        return {}
    models_dir = Path(str(package_file)).parent / "models"
    model_paths: dict[str, str] = {}
    for option_name, file_name in _RAPIDOCR_BUNDLED_MODEL_FILES.items():
        model_path = models_dir / file_name
        if not model_path.is_file():
            return {}
        model_paths[option_name] = str(model_path)
    return model_paths


def _detect_pdf_appendix_page_range(pdf_path: Path) -> dict[str, Any] | None:
    try:
        import fitz
    except Exception:
        return None

    try:
        pdf = fitz.open(str(pdf_path))
    except Exception:
        return None
    try:
        source_page_count = int(getattr(pdf, "page_count", 0) or len(pdf))
        if source_page_count < _DOCLING_PAGE_WINDOW_MIN_SOURCE_PAGES:
            return None

        start_page: int | None = None
        appendix_hits: list[int] = []
        for page_index, page in enumerate(pdf, start=1):
            if page_index <= _DOCLING_PAGE_WINDOW_SKIP_FIRST_PAGES:
                continue
            try:
                text = str(page.get_text() or "")
            except Exception:
                continue
            normalized = "".join(text.split())
            if start_page is None and any(marker in normalized for marker in _APPENDIX_START_MARKERS):
                start_page = page_index
            if start_page is not None and _APPENDIX_HEADING_RE.search(normalized):
                appendix_hits.append(page_index)

        if start_page is None:
            return None
        end_page = max(appendix_hits or [start_page])
        end_page = min(source_page_count, end_page + _DOCLING_PAGE_WINDOW_END_PADDING)
        if end_page < start_page:
            end_page = start_page
        if end_page - start_page + 1 > _DOCLING_PAGE_WINDOW_MAX_PAGES:
            end_page = start_page + _DOCLING_PAGE_WINDOW_MAX_PAGES - 1
        return {
            "pageRange": (start_page, end_page),
            "sourcePageCount": source_page_count,
            "reason": "appendix-heading",
        }
    finally:
        pdf.close()


def _table_cells_from_rows(rows: list[list[Any]]) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        normalized_row = row if isinstance(row, list) else []
        for col_index, cell in enumerate(normalized_row):
            cells.append(
                {
                    "start_row_offset_idx": row_index,
                    "end_row_offset_idx": row_index + 1,
                    "start_col_offset_idx": col_index,
                    "end_col_offset_idx": col_index + 1,
                    "text": str(cell if cell is not None else "").strip(),
                }
            )
    return cells


def _point_in_bbox(point: tuple[float, float], bbox: tuple[float, float, float, float]) -> bool:
    x, y = point
    x0, y0, x1, y1 = bbox
    return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)


def _bbox_center(bbox: Any) -> tuple[float, float] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    except (TypeError, ValueError):
        return None
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def _line_inside_table(line_bbox: Any, table_bboxes: list[tuple[float, float, float, float]]) -> bool:
    center = _bbox_center(line_bbox)
    if center is None:
        return False
    return any(_point_in_bbox(center, table_bbox) for table_bbox in table_bboxes)


def _extract_pymupdf_tables(page: Any, page_no: int) -> tuple[list[dict[str, Any]], list[tuple[float, float, float, float]]]:
    finder = getattr(page, "find_tables", None)
    if not callable(finder):
        return [], []
    try:
        found = finder()
    except Exception:
        return [], []
    raw_tables = getattr(found, "tables", []) or []
    tables: list[dict[str, Any]] = []
    table_bboxes: list[tuple[float, float, float, float]] = []
    for raw_table in raw_tables:
        bbox = getattr(raw_table, "bbox", None)
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        try:
            normalized_bbox = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (TypeError, ValueError):
            continue
        try:
            rows = raw_table.extract()
        except Exception:
            rows = []
        normalized_rows = [row if isinstance(row, list) else [] for row in rows if isinstance(row, list)]
        if not normalized_rows:
            continue
        max_cols = max((len(row) for row in normalized_rows), default=0)
        if max_cols <= 0:
            continue
        padded_rows = [
            [str(cell if cell is not None else "").strip() for cell in [*row, *([""] * (max_cols - len(row)))]]
            for row in normalized_rows
        ]
        tables.append(
            {
                "prov": [
                    {
                        "page_no": page_no,
                        "bbox": {
                            "l": normalized_bbox[0],
                            "t": normalized_bbox[1],
                            "r": normalized_bbox[2],
                            "b": normalized_bbox[3],
                        },
                    }
                ],
                "data": {"table_cells": _table_cells_from_rows(padded_rows)},
            }
        )
        table_bboxes.append(normalized_bbox)
    return tables, table_bboxes


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
    artifacts_path_in_use = _docling_artifacts_path_is_usable(artifacts_path) and hasattr(pipeline_options, "artifacts_path")
    if artifacts_path_in_use:
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

            rapidocr_options: dict[str, Any] = {}
            if artifacts_path_in_use:
                rapidocr_model_paths = _bundled_rapidocr_model_paths()
                if rapidocr_model_paths:
                    rapidocr_options.update(rapidocr_model_paths)
                    rapidocr_options["rapidocr_params"] = dict(_RAPIDOCR_ARTIFACT_PATH_OVERRIDES)

            pipeline_options.ocr_options = RapidOcrOptions(
                backend="onnxruntime",
                force_full_page_ocr=False,
                bitmap_area_threshold=0.05,
                lang=["chinese", "english"],
                **rapidocr_options,
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
    page_window = _detect_pdf_appendix_page_range(pdf_path)
    convert_kwargs: dict[str, Any] = {}
    docling_mode = AUTO_DOCLING_MODE
    if page_window:
        convert_kwargs["page_range"] = tuple(page_window["pageRange"])
        docling_mode = AUTO_DOCLING_PAGE_RANGE_MODE
        if hasattr(pipeline_options, "do_ocr"):
            pipeline_options.do_ocr = False
        if hasattr(pipeline_options, "force_backend_text"):
            pipeline_options.force_backend_text = True
    result = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    ).convert(str(pdf_path), **convert_kwargs)
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
    converted_page_count = len(pages)
    source_page_count = int(page_window.get("sourcePageCount") or converted_page_count) if page_window else converted_page_count
    conversion = {
        "markdownPath": str(markdown_path),
        "jsonPath": str(json_path),
        "pageCount": source_page_count,
        "convertedPageCount": converted_page_count,
        "tableCount": len(tables),
        "mode": docling_mode,
        "warnings": [],
    }
    if page_window:
        page_range = tuple(page_window["pageRange"])
        conversion.update(
            {
                "pageRange": [int(page_range[0]), int(page_range[1])],
                "pageRangeReason": str(page_window.get("reason") or ""),
                "sourcePageCount": source_page_count,
            }
        )
    return conversion


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
    tables: list[dict[str, Any]] = []
    markdown_parts: list[str] = []
    with fitz.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf, start=1):
            rect = page.rect
            pages[str(page_index)] = {"size": {"width": float(rect.width), "height": float(rect.height)}}
            page_tables, table_bboxes = _extract_pymupdf_tables(page, page_index)
            tables.extend(page_tables)
            page_lines: list[str] = []
            raw = page.get_text("dict")
            blocks = raw.get("blocks") if isinstance(raw, dict) else []
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != 0:
                    continue
                lines = block.get("lines") if isinstance(block.get("lines"), list) else []
                for line in lines:
                    spans = line.get("spans") if isinstance(line, dict) and isinstance(line.get("spans"), list) else []
                    text = "".join(str(span.get("text") or "") for span in spans if isinstance(span, dict)).strip()
                    if not text:
                        continue
                    bbox = (
                        line.get("bbox")
                        if isinstance(line, dict) and isinstance(line.get("bbox"), (list, tuple))
                        else block.get("bbox")
                        if isinstance(block.get("bbox"), (list, tuple))
                        else [0, 0, 0, 0]
                    )
                    if _line_inside_table(bbox, table_bboxes):
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

    if not texts and not tables:
        raise RuntimeError("Docling 本地文本层模式未提取到 PDF 文本")

    payload = {
        "schema_name": "DoclingDocument",
        "name": pdf_path.name,
        "pages": pages,
        "texts": texts,
        "tables": tables,
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
        "tableCount": len(tables),
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
                "pageCount": conversion_result.get("pageCount") or quality.get("pageCount") or 0,
                "convertedPageCount": conversion_result.get("convertedPageCount") or quality.get("pageCount") or 0,
                "markdownPath": str(conversion_result.get("markdownPath") or ""),
                "jsonPath": str(conversion_result.get("jsonPath") or ""),
                "doclingMode": docling_mode,
            }
        )
        for key in ("pageRange", "pageRangeReason", "sourcePageCount"):
            if key in conversion_result:
                quality[key] = conversion_result[key]
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
