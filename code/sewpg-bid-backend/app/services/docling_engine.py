from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import re
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.docling_nav_adapter import convert_docling_output_to_document_nav
from app.services.document_nav import build_document_nav, nav_to_text
from app.services.document_parse_engine import DocumentParseEngine


AUTO_DOCLING_MODE = "auto-layout-table-ocr"
AUTO_DOCLING_PAGE_RANGE_MODE = "auto-layout-table-page-range"
LOCAL_TEXT_LAYER_MODE = "local-text-layer"
DOCLING_LOCKED_VERSION = "2.108.0"
DOCLING_PIPELINE_OPTIONS_VERSION = "sewpg-docling-v2"
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
_DOCLING_CONVERTER_CACHE: dict[tuple[Any, ...], Any] = {}
_DOCLING_CONVERTER_CACHE_LOCK = threading.Lock()
_DOCLING_CONVERSION_LOCK = threading.Lock()


def _docling_version() -> str:
    try:
        return importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        return DOCLING_LOCKED_VERSION


def docling_pipeline_fingerprint(mode: str) -> str:
    payload = {
        "doclingVersion": _docling_version(),
        "pipelineOptionsVersion": DOCLING_PIPELINE_OPTIONS_VERSION,
        "mode": str(mode or AUTO_DOCLING_MODE),
        "device": str(getattr(settings, "docling_device", "cpu") or "cpu"),
        "ocrBackend": "rapidocr-onnxruntime",
        "ocrLanguages": ["chinese", "english"],
        "tableMode": "accurate",
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    accelerator_options = getattr(pipeline_options, "accelerator_options", None)
    docling_device = str(getattr(settings, "docling_device", "cpu") or "cpu")
    try:
        from docling.datamodel.accelerator_options import AcceleratorOptions

        if accelerator_options is None and hasattr(pipeline_options, "accelerator_options"):
            pipeline_options.accelerator_options = AcceleratorOptions(device=docling_device)
        elif accelerator_options is not None and hasattr(accelerator_options, "device"):
            accelerator_options.device = docling_device
    except (ImportError, AttributeError, TypeError):
        # 测试替身或兼容版本没有 AcceleratorOptions 时，仍显式覆盖已有设备字段。
        if accelerator_options is not None and hasattr(accelerator_options, "device"):
            accelerator_options.device = docling_device

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


def _get_docling_converter(*, page_window_enabled: bool) -> Any:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    docling_mode = AUTO_DOCLING_PAGE_RANGE_MODE if page_window_enabled else AUTO_DOCLING_MODE
    artifacts_path = str(getattr(settings, "docling_artifacts_path", "") or "")
    cache_key = (
        docling_mode,
        docling_pipeline_fingerprint(docling_mode),
        artifacts_path,
        DocumentConverter,
        PdfFormatOption,
    )
    with _DOCLING_CONVERTER_CACHE_LOCK:
        converter = _DOCLING_CONVERTER_CACHE.get(cache_key)
        if converter is not None:
            return converter

        pipeline_options = _configure_docling_auto_pipeline_options(PdfPipelineOptions())
        if page_window_enabled:
            if hasattr(pipeline_options, "do_ocr"):
                pipeline_options.do_ocr = False
            if hasattr(pipeline_options, "force_backend_text"):
                pipeline_options.force_backend_text = True
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        _DOCLING_CONVERTER_CACHE[cache_key] = converter
        return converter


def prewarm_docling_converters() -> None:
    """在 worker 就绪前只初始化常用页窗 pipeline；全文 pipeline 按需加载。"""

    from docling.datamodel.base_models import InputFormat

    with _DOCLING_CONVERSION_LOCK:
        converter = _get_docling_converter(page_window_enabled=True)
        initialize_pipeline = getattr(converter, "initialize_pipeline", None)
        if not callable(initialize_pipeline):
            raise RuntimeError("当前 Docling 版本不支持 DocumentConverter.initialize_pipeline，无法完成预热")
        initialize_pipeline(InputFormat.PDF)


def run_docling_conversion(pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    page_window = _detect_pdf_appendix_page_range(pdf_path)
    convert_kwargs: dict[str, Any] = {}
    docling_mode = AUTO_DOCLING_MODE
    if page_window:
        convert_kwargs["page_range"] = tuple(page_window["pageRange"])
        docling_mode = AUTO_DOCLING_PAGE_RANGE_MODE
    converter = _get_docling_converter(page_window_enabled=bool(page_window))
    with _DOCLING_CONVERSION_LOCK:
        result = converter.convert(str(pdf_path), **convert_kwargs)
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
        "doclingVersion": _docling_version(),
        "pipelineOptionsVersion": DOCLING_PIPELINE_OPTIONS_VERSION,
        "pipelineFingerprint": docling_pipeline_fingerprint(docling_mode),
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


def build_pymupdf_text_layer_document_nav(
    *,
    document_id: str,
    pdf_path: Path,
) -> dict[str, Any]:
    """为技术标建立覆盖整份 PDF 的轻量文本层导航。"""

    import fitz

    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    with fitz.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf, start=1):
            rect = page.rect
            page_blocks: list[dict[str, Any]] = []
            raw = page.get_text("dict", sort=True)
            raw_blocks = raw.get("blocks") if isinstance(raw, dict) else []
            line_no = 0
            for raw_block in raw_blocks if isinstance(raw_blocks, list) else []:
                if not isinstance(raw_block, dict) or raw_block.get("type") != 0:
                    continue
                lines = raw_block.get("lines") if isinstance(raw_block.get("lines"), list) else []
                for line in lines:
                    spans = line.get("spans") if isinstance(line, dict) and isinstance(line.get("spans"), list) else []
                    text = "".join(str(span.get("text") or "") for span in spans if isinstance(span, dict)).strip()
                    if not text:
                        continue
                    line_no += 1
                    raw_bbox = line.get("bbox") if isinstance(line, dict) else None
                    bbox = [float(value) for value in raw_bbox] if isinstance(raw_bbox, (list, tuple)) else []
                    page_blocks.append(
                        {
                            "id": f"{document_id}:TXT:P{page_no:04d}:B{line_no:04d}",
                            "evidenceId": f"{document_id}:P{page_no:04d}:TXT{line_no:04d}",
                            "pageNo": page_no,
                            "type": "heading" if _is_heading_text(text) else "paragraph",
                            "text": text,
                            "bbox": bbox,
                            "sourceEngine": "pymupdf-text-layer",
                        }
                    )
            blocks.extend(page_blocks)
            pages.append(
                {
                    "pageNo": page_no,
                    "width": float(rect.width),
                    "height": float(rect.height),
                    "textDensity": 1 if page_blocks else 0,
                    "lowQuality": not bool(page_blocks),
                    "sourceEngine": "pymupdf-text-layer",
                }
            )

    if not pages:
        raise RuntimeError("PyMuPDF 未读取到 PDF 页面")
    return build_document_nav(
        document_id=document_id,
        source_path=str(pdf_path),
        source_engine="pymupdf-text-layer",
        pages=pages,
        blocks=blocks,
        tables=[],
        quality={
            "engine": "pymupdf-text-layer",
            "status": "completed",
            "pageCount": len(pages),
            "lowQualityPages": [int(page["pageNo"]) for page in pages if page.get("lowQuality")],
            "tableCount": 0,
            "fallbackUsed": False,
            "warnings": [],
        },
    )


def merge_technical_document_nav(
    *,
    text_layer_nav: dict[str, Any],
    docling_nav: dict[str, Any],
    page_range: list[int] | tuple[int, int] | None,
) -> dict[str, Any]:
    """用 Docling 页窗替换全文文本层对应页面，同时保留整本页码空间。"""

    documents = text_layer_nav.get("documents") if isinstance(text_layer_nav.get("documents"), list) else []
    first_document = documents[0] if documents and isinstance(documents[0], dict) else {}
    document_id = str(first_document.get("id") or "DOC-1")
    source_path = str(first_document.get("sourcePath") or "")
    text_pages = [page for page in text_layer_nav.get("pages") or [] if isinstance(page, dict)]
    source_page_count = len(text_pages)

    docling_pages = [page for page in docling_nav.get("pages") or [] if isinstance(page, dict)]
    docling_page_numbers = [int(page.get("pageNo") or 0) for page in docling_pages if int(page.get("pageNo") or 0) > 0]
    if page_range and len(page_range) >= 2:
        window_start, window_end = int(page_range[0]), int(page_range[1])
    elif docling_page_numbers:
        window_start, window_end = min(docling_page_numbers), max(docling_page_numbers)
    else:
        window_start, window_end = 1, source_page_count

    docling_pages_by_no = {int(page.get("pageNo") or 0): page for page in docling_pages}
    merged_pages: list[dict[str, Any]] = []
    for text_page in text_pages:
        page_no = int(text_page.get("pageNo") or 0)
        docling_page = docling_pages_by_no.get(page_no)
        if window_start <= page_no <= window_end and docling_page is not None:
            merged_pages.append({**text_page, **docling_page, "pageNo": page_no, "sourceEngine": "docling"})
        else:
            merged_pages.append(text_page)

    def blocks_by_page(nav: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for block in nav.get("blocks") if isinstance(nav.get("blocks"), list) else []:
            if not isinstance(block, dict):
                continue
            page_no = int(block.get("pageNo") or 0)
            grouped.setdefault(page_no, []).append(block)
        return grouped

    text_blocks = blocks_by_page(text_layer_nav)
    docling_blocks = blocks_by_page(docling_nav)
    merged_blocks: list[dict[str, Any]] = []
    for page_no in range(1, source_page_count + 1):
        if window_start <= page_no <= window_end and docling_blocks.get(page_no):
            merged_blocks.extend(docling_blocks[page_no])
        else:
            merged_blocks.extend(text_blocks.get(page_no, []))

    content_pages = {
        int(block.get("pageNo") or 0)
        for block in merged_blocks
        if str(block.get("text") or "").strip() or str(block.get("type") or "") == "table"
    }
    for page in merged_pages:
        if int(page.get("pageNo") or 0) in content_pages:
            page["textDensity"] = max(float(page.get("textDensity") or 0), 1)
            page["lowQuality"] = False

    tables = [table for table in docling_nav.get("tables") or [] if isinstance(table, dict)]
    images = [image for image in docling_nav.get("images") or [] if isinstance(image, dict)]
    docling_quality = docling_nav.get("quality") if isinstance(docling_nav.get("quality"), dict) else {}
    low_quality_pages = [
        int(page.get("pageNo") or 0)
        for page in merged_pages
        if int(page.get("pageNo") or 0) > 0 and not page.get("textDensity")
    ]
    quality = {
        **docling_quality,
        "engine": "docling+pymupdf-text-layer",
        "status": "completed",
        "pageCount": source_page_count,
        "sourcePageCount": source_page_count,
        "convertedPageCount": len(docling_pages),
        "textLayerPageCount": source_page_count,
        "lowQualityPages": low_quality_pages,
        "tableCount": len(tables),
        "fallbackUsed": False,
    }
    return build_document_nav(
        document_id=document_id,
        source_path=source_path,
        source_engine="docling+pymupdf-text-layer",
        pages=merged_pages,
        blocks=merged_blocks,
        tables=tables,
        images=images,
        quality=quality,
    )


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
        source_sha256 = str(document.get("sourceSha256") or document.get("sha256") or "").strip().lower()
        run_id = str(document.get("runId") or "").strip()
        merge_technical_text_layer = bool(document.get("mergeTechnicalTextLayer"))

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
            if merge_technical_text_layer:
                text_layer_nav = build_pymupdf_text_layer_document_nav(
                    document_id=document_id,
                    pdf_path=pdf_path,
                )
                document_nav = merge_technical_document_nav(
                    text_layer_nav=text_layer_nav,
                    docling_nav=document_nav,
                    page_range=conversion_result.get("pageRange"),
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
                "doclingVersion": _docling_version(),
                "pipelineOptionsVersion": DOCLING_PIPELINE_OPTIONS_VERSION,
                "pipelineFingerprint": docling_pipeline_fingerprint(AUTO_DOCLING_MODE),
                "warnings": [str(exc)],
            }
            if source_sha256:
                quality["sourceSha256"] = source_sha256
            if run_id:
                quality["runId"] = run_id
            quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "documentParseEngine": "docling",
                "status": "failed",
                "doclingOutputDir": str(docling_output_dir),
                "parseQualityPath": str(quality_path),
                "doclingVersion": str(quality.get("doclingVersion") or ""),
                "pipelineOptionsVersion": str(quality.get("pipelineOptionsVersion") or ""),
                "pipelineFingerprint": str(quality.get("pipelineFingerprint") or ""),
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
                "doclingVersion": str(conversion_result.get("doclingVersion") or _docling_version()),
                "pipelineOptionsVersion": str(
                    conversion_result.get("pipelineOptionsVersion") or DOCLING_PIPELINE_OPTIONS_VERSION
                ),
                "pipelineFingerprint": str(
                    conversion_result.get("pipelineFingerprint") or docling_pipeline_fingerprint(docling_mode)
                ),
            }
        )
        if source_sha256:
            quality["sourceSha256"] = source_sha256
        if run_id:
            quality["runId"] = run_id
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
            "doclingVersion": str(quality.get("doclingVersion") or ""),
            "pipelineOptionsVersion": str(quality.get("pipelineOptionsVersion") or ""),
            "pipelineFingerprint": str(quality.get("pipelineFingerprint") or ""),
            "text": nav_to_text(document_nav),
        }
