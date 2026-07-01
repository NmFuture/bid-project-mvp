from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from app.services.docling_engine import DoclingParseEngine
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
        ) -> None:
            self.backend = backend
            self.force_full_page_ocr = force_full_page_ocr
            self.bitmap_area_threshold = bitmap_area_threshold
            self.lang = lang

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


def test_run_docling_conversion_keeps_docling_auto_layout_table_and_ocr_options(tmp_path, monkeypatch) -> None:
    from app.services.docling_engine import run_docling_conversion

    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    artifacts_path = tmp_path / "docling-models"
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

    options = captured["pipeline_options"]
    assert captured["source"] == str(pdf_path)
    assert result["mode"] == "auto-layout-table-ocr"
    assert options.do_ocr is True
    assert options.do_table_structure is True
    assert options.artifacts_path == artifacts_path
    assert options.ocr_options.force_full_page_ocr is False
    assert options.table_structure_options.do_cell_matching is True
    assert str(options.table_structure_options.mode).lower().endswith("accurate")


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
        document={"id": "DOC-1", "path": str(pdf_path)},
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
