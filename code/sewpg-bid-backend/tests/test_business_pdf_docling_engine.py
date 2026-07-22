from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from app.services.docling_engine import DoclingParseEngine
from app.services.docling_engine import _REQUIRED_DOCLING_LAYOUT_ARTIFACTS
from app.services.docling_engine import _REQUIRED_DOCLING_TABLE_ARTIFACTS
from app.services.document_parse_engine import create_document_parse_engine


def test_create_document_parse_engine_defaults_to_docling_provider() -> None:
    engine = create_document_parse_engine(parse_engine="docling")

    assert isinstance(engine, DoclingParseEngine)


def test_configure_docling_auto_pipeline_prefers_rapidocr_onnxruntime_when_available(monkeypatch) -> None:
    from app.services.docling_engine import _configure_docling_auto_pipeline_options

    class FakeOcrOptions:
        force_full_page_ocr = True
        bitmap_area_threshold = 1

    class FakeRapidOcrOptions:
        def __init__(
            self,
            *,
            backend: str,
            force_full_page_ocr: bool,
            bitmap_area_threshold: float,
            lang: list[str],
            det_model_path: str | None = None,
            cls_model_path: str | None = None,
            rec_model_path: str | None = None,
            rec_keys_path: str | None = None,
            font_path: str | None = None,
            rapidocr_params: dict[str, object] | None = None,
        ) -> None:
            self.backend = backend
            self.force_full_page_ocr = force_full_page_ocr
            self.bitmap_area_threshold = bitmap_area_threshold
            self.lang = lang
            self.det_model_path = det_model_path
            self.cls_model_path = cls_model_path
            self.rec_model_path = rec_model_path
            self.rec_keys_path = rec_keys_path
            self.font_path = font_path
            self.rapidocr_params = rapidocr_params or {}

    class FakeTableFormerMode:
        ACCURATE = "accurate"

    class FakeTableOptions:
        do_cell_matching = False
        mode = "fast"

    class FakePdfPipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = False
            self.do_table_structure = False
            self.ocr_options = FakeOcrOptions()
            self.table_structure_options = FakeTableOptions()

    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options.RapidOcrOptions = FakeRapidOcrOptions
    pipeline_options.TableFormerMode = FakeTableFormerMode
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object() if name == "onnxruntime" else None)

    options = _configure_docling_auto_pipeline_options(FakePdfPipelineOptions())

    assert options.do_ocr is True
    assert options.do_table_structure is True
    assert options.ocr_options.backend == "onnxruntime"
    assert options.ocr_options.lang == ["chinese", "english"]
    assert options.ocr_options.force_full_page_ocr is False
    assert options.ocr_options.bitmap_area_threshold == 0.05
    assert options.table_structure_options.do_cell_matching is True
    assert options.table_structure_options.mode == "accurate"


def test_configure_docling_auto_pipeline_forces_cpu(monkeypatch) -> None:
    from app.services.docling_engine import _configure_docling_auto_pipeline_options

    class FakeAcceleratorDevice:
        CPU = "cpu"

    class FakeAcceleratorOptions:
        def __init__(self, *, device: str = "cuda") -> None:
            self.device = device

    class FakePdfPipelineOptions:
        def __init__(self) -> None:
            self.accelerator_options = FakeAcceleratorOptions()

    accelerator_options = types.ModuleType("docling.datamodel.accelerator_options")
    accelerator_options.AcceleratorDevice = FakeAcceleratorDevice
    accelerator_options.AcceleratorOptions = FakeAcceleratorOptions
    monkeypatch.setitem(sys.modules, "docling.datamodel.accelerator_options", accelerator_options)

    options = _configure_docling_auto_pipeline_options(FakePdfPipelineOptions())

    assert options.accelerator_options.device == "cpu"


def test_configure_docling_auto_pipeline_ignores_empty_artifacts_path(tmp_path, monkeypatch) -> None:
    from app.core.config import settings
    from app.services.docling_engine import _configure_docling_auto_pipeline_options

    empty_artifacts = tmp_path / "docling-models"
    empty_artifacts.mkdir()

    class FakeOcrOptions:
        force_full_page_ocr = True
        bitmap_area_threshold = 1

    class FakeTableOptions:
        do_cell_matching = False
        mode = "fast"

    class FakePdfPipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = False
            self.do_table_structure = False
            self.ocr_options = FakeOcrOptions()
            self.table_structure_options = FakeTableOptions()
            self.artifacts_path = None

    monkeypatch.setattr(settings, "docling_artifacts_path", empty_artifacts, raising=False)

    options = _configure_docling_auto_pipeline_options(FakePdfPipelineOptions())

    assert options.artifacts_path is None


def test_configure_docling_auto_pipeline_uses_layout_and_table_artifacts(tmp_path, monkeypatch) -> None:
    from app.core.config import settings
    from app.services.docling_engine import _configure_docling_auto_pipeline_options

    artifacts_path = tmp_path / "docling-models"
    for relative_path in [*_REQUIRED_DOCLING_LAYOUT_ARTIFACTS, *_REQUIRED_DOCLING_TABLE_ARTIFACTS]:
        artifact = artifacts_path / relative_path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"model")

    class FakeOcrOptions:
        force_full_page_ocr = True
        bitmap_area_threshold = 1

    class FakeTableOptions:
        do_cell_matching = False
        mode = "fast"

    class FakePdfPipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = False
            self.do_table_structure = False
            self.ocr_options = FakeOcrOptions()
            self.table_structure_options = FakeTableOptions()
            self.artifacts_path = None

    monkeypatch.setattr(settings, "docling_artifacts_path", artifacts_path, raising=False)

    options = _configure_docling_auto_pipeline_options(FakePdfPipelineOptions())

    assert options.artifacts_path == artifacts_path


def test_configure_docling_auto_pipeline_pins_bundled_rapidocr_models_when_artifacts_path_is_used(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core.config import settings
    from app.services.docling_engine import _configure_docling_auto_pipeline_options

    artifacts_path = tmp_path / "docling-models"
    for relative_path in [*_REQUIRED_DOCLING_LAYOUT_ARTIFACTS, *_REQUIRED_DOCLING_TABLE_ARTIFACTS]:
        artifact = artifacts_path / relative_path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"model")

    rapidocr_package = tmp_path / "site-packages" / "rapidocr" / "__init__.py"
    rapidocr_models = rapidocr_package.parent / "models"
    rapidocr_models.mkdir(parents=True)
    rapidocr_package.write_text("", encoding="utf-8")
    rapidocr_expected_paths = {
        "det_model_path": rapidocr_models / "PP-OCRv6_det_small.onnx",
        "cls_model_path": rapidocr_models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "rec_model_path": rapidocr_models / "PP-OCRv6_rec_small.onnx",
    }
    for model_path in rapidocr_expected_paths.values():
        model_path.write_bytes(b"onnx")

    class FakeOcrOptions:
        force_full_page_ocr = True
        bitmap_area_threshold = 1

    class FakeRapidOcrOptions:
        def __init__(
            self,
            *,
            backend: str,
            force_full_page_ocr: bool,
            bitmap_area_threshold: float,
            lang: list[str],
            det_model_path: str | None = None,
            cls_model_path: str | None = None,
            rec_model_path: str | None = None,
            rec_keys_path: str | None = None,
            font_path: str | None = None,
            rapidocr_params: dict[str, object] | None = None,
        ) -> None:
            self.backend = backend
            self.force_full_page_ocr = force_full_page_ocr
            self.bitmap_area_threshold = bitmap_area_threshold
            self.lang = lang
            self.det_model_path = det_model_path
            self.cls_model_path = cls_model_path
            self.rec_model_path = rec_model_path
            self.rec_keys_path = rec_keys_path
            self.font_path = font_path
            self.rapidocr_params = rapidocr_params or {}

    class FakeTableFormerMode:
        ACCURATE = "accurate"

    class FakeTableOptions:
        do_cell_matching = False
        mode = "fast"

    class FakePdfPipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = False
            self.do_table_structure = False
            self.ocr_options = FakeOcrOptions()
            self.table_structure_options = FakeTableOptions()
            self.artifacts_path = None

    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options.RapidOcrOptions = FakeRapidOcrOptions
    pipeline_options.TableFormerMode = FakeTableFormerMode
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options)
    monkeypatch.setitem(
        sys.modules,
        "rapidocr",
        types.SimpleNamespace(__file__=str(rapidocr_package)),
    )
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object() if name == "onnxruntime" else None)
    monkeypatch.setattr(settings, "docling_artifacts_path", artifacts_path, raising=False)

    options = _configure_docling_auto_pipeline_options(FakePdfPipelineOptions())

    assert options.artifacts_path == artifacts_path
    assert options.ocr_options.det_model_path == str(rapidocr_expected_paths["det_model_path"])
    assert options.ocr_options.cls_model_path == str(rapidocr_expected_paths["cls_model_path"])
    assert options.ocr_options.rec_model_path == str(rapidocr_expected_paths["rec_model_path"])
    assert options.ocr_options.rec_keys_path is None
    assert options.ocr_options.font_path is None
    assert options.ocr_options.rapidocr_params["Rec.rec_keys_path"] is None
    assert options.ocr_options.rapidocr_params["Rec.font_path"] is None
    assert options.ocr_options.rapidocr_params["Global.font_path"] is None


def test_run_docling_conversion_keeps_docling_auto_layout_table_and_ocr_options(tmp_path, monkeypatch) -> None:
    from app.services.docling_engine import run_docling_conversion

    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    artifacts_path = tmp_path / "docling-models"
    for relative_path in [*_REQUIRED_DOCLING_LAYOUT_ARTIFACTS, *_REQUIRED_DOCLING_TABLE_ARTIFACTS]:
        artifact = artifacts_path / relative_path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"model")
    captured: dict[str, object] = {}

    class FakeInputFormat:
        PDF = "pdf"

    class FakeOcrOptions:
        force_full_page_ocr = False
        bitmap_area_threshold = 0.05

    class FakeTableOptions:
        do_cell_matching = True
        mode = "accurate"

    class FakePdfPipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = True
            self.do_table_structure = True
            self.ocr_options = FakeOcrOptions()
            self.table_structure_options = FakeTableOptions()
            self.artifacts_path = None
            self.generate_page_images = False
            self.generate_picture_images = False

    class FakePdfFormatOption:
        def __init__(self, *, pipeline_options: object) -> None:
            self.pipeline_options = pipeline_options

    class FakeDocument:
        def export_to_dict(self) -> dict:
            return {"pages": {"1": {"size": {"width": 595, "height": 842}}}, "texts": [], "tables": []}

        def export_to_markdown(self) -> str:
            return ""

    class FakeDocumentConverter:
        def __init__(self, *, format_options: dict) -> None:
            captured["converter_init_count"] = int(captured.get("converter_init_count") or 0) + 1
            captured["pipeline_options"] = next(iter(format_options.values())).pipeline_options

        def convert(self, source: str) -> object:
            captured["source"] = source
            return types.SimpleNamespace(document=FakeDocument())

    base_models = types.ModuleType("docling.datamodel.base_models")
    base_models.InputFormat = FakeInputFormat
    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options.PdfPipelineOptions = FakePdfPipelineOptions
    document_converter = types.ModuleType("docling.document_converter")
    document_converter.DocumentConverter = FakeDocumentConverter
    document_converter.PdfFormatOption = FakePdfFormatOption
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options)
    monkeypatch.setitem(sys.modules, "docling.document_converter", document_converter)
    from app.core.config import settings

    monkeypatch.setattr(settings, "docling_artifacts_path", artifacts_path, raising=False)

    result = run_docling_conversion(pdf_path, tmp_path / "docling")
    second_result = run_docling_conversion(pdf_path, tmp_path / "docling-second")

    options = captured["pipeline_options"]
    assert captured["source"] == str(pdf_path)
    assert captured["converter_init_count"] == 1
    assert result["mode"] == "auto-layout-table-ocr"
    assert second_result["pipelineFingerprint"] == result["pipelineFingerprint"]
    assert result["pipelineOptionsVersion"] == "sewpg-docling-cpu-v1"
    assert len(result["pipelineFingerprint"]) == 64
    assert options.do_ocr is True
    assert options.do_table_structure is True
    assert options.artifacts_path == artifacts_path
    assert options.ocr_options.force_full_page_ocr is False
    assert options.table_structure_options.do_cell_matching is True
    assert str(options.table_structure_options.mode).lower().endswith("accurate")


def test_run_docling_conversion_uses_detected_appendix_page_range(tmp_path, monkeypatch) -> None:
    from app.services.docling_engine import run_docling_conversion

    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    captured: dict[str, object] = {}

    class FakeInputFormat:
        PDF = "pdf"

    class FakeOcrOptions:
        force_full_page_ocr = False
        bitmap_area_threshold = 0.05

    class FakeTableOptions:
        do_cell_matching = True
        mode = "accurate"

    class FakePdfPipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = True
            self.do_table_structure = True
            self.ocr_options = FakeOcrOptions()
            self.table_structure_options = FakeTableOptions()
            self.artifacts_path = None

    class FakePdfFormatOption:
        def __init__(self, *, pipeline_options: object) -> None:
            self.pipeline_options = pipeline_options

    class FakeDocument:
        def export_to_dict(self) -> dict:
            return {
                "pages": {"178": {"size": {"width": 595, "height": 842}}},
                "texts": [{"text": "附表A.1 投标机型总方案信息表"}],
                "tables": [{"data": {"table_cells": []}}],
            }

        def export_to_markdown(self) -> str:
            return "附表A.1 投标机型总方案信息表"

    class FakeDocumentConverter:
        def __init__(self, *, format_options: dict) -> None:
            captured["pipeline_options"] = next(iter(format_options.values())).pipeline_options

        def convert(self, source: str, *, page_range: tuple[int, int] | None = None) -> object:
            captured["source"] = source
            captured["page_range"] = page_range
            return types.SimpleNamespace(document=FakeDocument())

    base_models = types.ModuleType("docling.datamodel.base_models")
    base_models.InputFormat = FakeInputFormat
    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options.PdfPipelineOptions = FakePdfPipelineOptions
    document_converter = types.ModuleType("docling.document_converter")
    document_converter.DocumentConverter = FakeDocumentConverter
    document_converter.PdfFormatOption = FakePdfFormatOption
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options)
    monkeypatch.setitem(sys.modules, "docling.document_converter", document_converter)
    monkeypatch.setattr(
        "app.services.docling_engine._detect_pdf_appendix_page_range",
        lambda path: {"pageRange": (178, 221), "sourcePageCount": 555, "reason": "appendix-heading"},
    )

    result = run_docling_conversion(pdf_path, tmp_path / "docling")

    assert captured["source"] == str(pdf_path)
    assert captured["page_range"] == (178, 221)
    assert result["pageCount"] == 555
    assert result["convertedPageCount"] == 1
    assert result["pageRange"] == [178, 221]
    assert result["mode"] == "auto-layout-table-page-range"
    assert captured["pipeline_options"].do_ocr is False


def test_run_docling_local_text_layer_conversion_keeps_pymupdf_table_structure(tmp_path) -> None:
    import fitz

    from app.services.docling_engine import run_docling_local_text_layer_conversion

    pdf_path = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    xs = [50, 120, 240, 350]
    ys = [80, 115, 150]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    page.insert_text((60, 102), "No.", fontsize=10)
    page.insert_text((130, 102), "Item", fontsize=10)
    page.insert_text((250, 102), "Response", fontsize=10)
    page.insert_text((60, 137), "1", fontsize=10)
    page.insert_text((130, 137), "Capacity", fontsize=10)
    doc.save(pdf_path)
    doc.close()

    result = run_docling_local_text_layer_conversion(pdf_path, tmp_path / "docling")

    payload = json.loads(Path(result["jsonPath"]).read_text(encoding="utf-8"))
    assert result["mode"] == "local-text-layer"
    assert result["tableCount"] == 1
    assert len(payload["tables"]) == 1
    cells = payload["tables"][0]["data"]["table_cells"]
    assert [cell["text"] for cell in cells[:6]] == ["No.", "Item", "Response", "1", "Capacity", ""]


def test_docling_parse_engine_writes_nav_and_quality_report(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_run_docling_conversion(pdf_path: Path, output_dir: Path) -> dict:
        (output_dir / "docling.md").write_text("# 第六章 投标文件格式\n\n一、投标函\n", encoding="utf-8")
        (output_dir / "docling_document.json").write_text(
            json.dumps(
                {
                    "pages": {"1": {"size": {"width": 595, "height": 842}}},
                    "texts": [
                        {
                            "label": "section_header",
                            "text": "第六章 投标文件格式",
                            "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 20, "r": 300, "b": 40}}],
                        }
                    ],
                    "tables": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {
            "markdownPath": str(output_dir / "docling.md"),
            "jsonPath": str(output_dir / "docling_document.json"),
            "mode": "auto-layout-table-ocr",
        }

    monkeypatch.setattr("app.services.docling_engine.run_docling_conversion", fake_run_docling_conversion)
    engine = DoclingParseEngine()

    result = engine.parse_pdf(
        project_id="PRJ-1",
        document={"id": "DOC-1", "path": str(pdf_path), "sourceSha256": "ABC123", "runId": "run-1"},
        output_dir=tmp_path,
    )

    assert result["documentParseEngine"] == "docling"
    assert result["status"] == "completed"
    assert Path(result["doclingOutputDir"]).is_dir()
    assert Path(result["documentNavPath"]).is_file()
    quality = json.loads(Path(result["parseQualityPath"]).read_text(encoding="utf-8"))
    nav = json.loads(Path(result["documentNavPath"]).read_text(encoding="utf-8"))
    assert quality["engine"] == "docling"
    assert quality["status"] == "completed"
    assert quality["fallbackUsed"] is False
    assert quality["doclingMode"] == "auto-layout-table-ocr"
    assert quality["sourceSha256"] == "abc123"
    assert quality["runId"] == "run-1"
    assert quality["pipelineOptionsVersion"] == "sewpg-docling-cpu-v1"
    assert len(quality["pipelineFingerprint"]) == 64
    assert nav["sourceEngine"] == "docling"
    assert nav["blocks"][0]["text"] == "第六章 投标文件格式"


def test_docling_parse_engine_failure_is_explicit_and_does_not_fallback(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_run_docling_conversion(pdf_path: Path, output_dir: Path) -> dict:
        raise RuntimeError("docling missing")

    monkeypatch.setattr("app.services.docling_engine.run_docling_conversion", fake_run_docling_conversion)
    engine = DoclingParseEngine()

    result = engine.parse_pdf(
        project_id="PRJ-1",
        document={"id": "DOC-1", "path": str(pdf_path)},
        output_dir=tmp_path,
    )

    assert result["documentParseEngine"] == "docling"
    assert result["status"] == "failed"
    assert result["fallbackReason"] == "docling missing"
    quality = json.loads(Path(result["parseQualityPath"]).read_text(encoding="utf-8"))
    assert quality["engine"] == "docling"
    assert quality["status"] == "failed"
    assert quality["fallbackUsed"] is False


def test_docling_parse_engine_does_not_mask_pipeline_failure_as_local_text_success(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_run_docling_conversion(pdf_path: Path, output_dir: Path) -> dict:
        raise RuntimeError("Network is unreachable")

    monkeypatch.setattr("app.services.docling_engine.run_docling_conversion", fake_run_docling_conversion)

    result = DoclingParseEngine().parse_pdf(
        project_id="PRJ-1",
        document={"id": "DOC-1", "path": str(pdf_path)},
        output_dir=tmp_path,
    )

    quality = json.loads(Path(result["parseQualityPath"]).read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["documentParseEngine"] == "docling"
    assert "Network is unreachable" in result["fallbackReason"]
    assert quality["engine"] == "docling"
    assert quality["fallbackUsed"] is False
    assert quality["status"] == "failed"


def test_docling_parse_engine_marks_local_text_layer_as_explicit_fallback(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_run_docling_conversion(pdf_path: Path, output_dir: Path) -> dict:
        raise RuntimeError("Network is unreachable")

    def fake_run_docling_local_text_layer_conversion(pdf_path: Path, output_dir: Path) -> dict:
        (output_dir / "docling.md").write_text("# 第一章 采购公告\n\n采购编号：CWEME-202605PGZJ-W001\n", encoding="utf-8")
        (output_dir / "docling_document.json").write_text(
            json.dumps(
                {
                    "pages": {"1": {"size": {"width": 595, "height": 842}}},
                    "texts": [
                        {
                            "label": "section_header",
                            "text": "第一章 采购公告",
                            "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 0, "r": 595, "b": 20}}],
                        },
                        {
                            "label": "text",
                            "text": "采购编号：CWEME-202605PGZJ-W001",
                            "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 24, "r": 595, "b": 44}}],
                        },
                    ],
                    "tables": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {
            "markdownPath": str(output_dir / "docling.md"),
            "jsonPath": str(output_dir / "docling_document.json"),
            "mode": "local-text-layer",
            "warnings": ["Docling 标准 PDF pipeline 不可用，已使用本地文本层兜底。"],
        }

    monkeypatch.setattr("app.services.docling_engine.run_docling_conversion", fake_run_docling_conversion)
    monkeypatch.setattr(
        "app.services.docling_engine.run_docling_local_text_layer_conversion",
        fake_run_docling_local_text_layer_conversion,
    )

    result = DoclingParseEngine(fallback="lightweight").parse_pdf(
        project_id="PRJ-1",
        document={"id": "DOC-1", "path": str(pdf_path)},
        output_dir=tmp_path,
    )

    quality = json.loads(Path(result["parseQualityPath"]).read_text(encoding="utf-8"))
    nav = json.loads(Path(result["documentNavPath"]).read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["documentParseEngine"] == "docling"
    assert result["doclingMode"] == "local-text-layer"
    assert quality["engine"] == "docling"
    assert quality["fallbackUsed"] is True
    assert quality["doclingMode"] == "local-text-layer"
    assert quality["fallbackReason"] == "Network is unreachable"
    assert nav["sourceEngine"] == "docling"
    assert "采购编号" in "\n".join(block["text"] for block in nav["blocks"])
