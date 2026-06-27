from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path

import app.services.mineru_engine as mineru_engine_module
from app.services import parsing as parsing_service
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.document_parse_engine import create_document_parse_engine
from app.services.mineru_engine import MineruParseEngine
from app.services.mineru_engine import run_mineru_command


def test_create_document_parse_engine_selects_mineru_provider() -> None:
    engine = create_document_parse_engine(
        parse_engine="mineru",
        mineru_enabled=True,
        fallback="lightweight",
    )

    assert isinstance(engine, MineruParseEngine)


def test_mineru_parse_engine_default_timeout_allows_full_business_pdf_runs() -> None:
    assert MineruParseEngine().timeout_sec >= 21600


def test_create_document_parse_engine_disabled_provider_writes_json_quality(tmp_path) -> None:
    engine = create_document_parse_engine(
        parse_engine="mineru",
        mineru_enabled=False,
        fallback="lightweight",
    )

    result = engine.parse_pdf(
        project_id="PRJ-1",
        document={"id": "DOC-1", "path": str(tmp_path / "source.pdf")},
        output_dir=tmp_path,
    )

    quality = json.loads(Path(result["parseQualityPath"]).read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert quality["engine"] == "disabled"
    assert quality["fallbackUsed"] is True
    assert quality["warnings"]


def test_mineru_parse_engine_writes_quality_report_when_command_fails(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_run_mineru_command(
        pdf_path: Path,
        output_dir: Path,
        mode: str,
        *,
        backend: str = "pipeline",
        executable: str = "",
        timeout_sec: int = 1800,
    ) -> dict:
        _ = backend
        _ = executable
        _ = timeout_sec
        raise RuntimeError("mineru missing")

    monkeypatch.setattr("app.services.mineru_engine.run_mineru_command", fake_run_mineru_command)
    engine = MineruParseEngine(mode="auto")

    result = engine.parse_pdf(
        project_id="PRJ-1",
        document={"id": "DOC-1", "path": str(pdf_path)},
        output_dir=tmp_path,
    )

    quality_path = Path(result["parseQualityPath"])
    assert result["documentParseEngine"] == "mineru"
    assert result["status"] == "failed"
    assert result["fallbackReason"] == "mineru missing"
    assert quality_path.is_file()
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    assert quality["status"] == "failed"
    assert quality["fallbackUsed"] is True


def test_mineru_parse_engine_collects_mock_outputs(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_run_mineru_command(
        pdf_path: Path,
        output_dir: Path,
        mode: str,
        *,
        backend: str = "pipeline",
        executable: str = "",
        timeout_sec: int = 1800,
    ) -> dict:
        _ = backend
        _ = executable
        _ = timeout_sec
        markdown = output_dir / "source.md"
        middle_json = output_dir / "source.json"
        markdown.write_text("# 第六章 投标文件格式\n", encoding="utf-8")
        middle_json.write_text("{}", encoding="utf-8")
        return {"markdownPath": str(markdown), "jsonPath": str(middle_json), "pageCount": 1}

    monkeypatch.setattr("app.services.mineru_engine.run_mineru_command", fake_run_mineru_command)
    engine = MineruParseEngine(mode="auto")

    result = engine.parse_pdf(
        project_id="PRJ-1",
        document={"id": "DOC-1", "path": str(pdf_path)},
        output_dir=tmp_path,
    )

    assert result["status"] == "completed"
    assert Path(result["mineruOutputDir"]).is_dir()
    assert Path(result["markdownPath"]).is_file()
    assert Path(result["jsonPath"]).is_file()
    quality = json.loads(Path(result["parseQualityPath"]).read_text(encoding="utf-8"))
    assert quality["status"] == "completed"
    assert quality["pageCount"] == 1


def test_business_pdf_mineru_failure_respects_disabled_lightweight_fallback(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "business-no-fallback.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    project_dir = tmp_path / "parsed" / "PRJ-NO-FALLBACK"

    def fake_parse_pdf(self, *, project_id: str, document: dict, output_dir: Path):
        quality_path = output_dir / "parse_quality.json"
        quality_path.parent.mkdir(parents=True, exist_ok=True)
        quality_path.write_text(
            json.dumps(
                {
                    "engine": "mineru",
                    "status": "failed",
                    "fallbackUsed": False,
                    "warnings": ["mineru failed"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {
            "documentParseEngine": "mineru",
            "status": "failed",
            "parseQualityPath": str(quality_path),
            "fallbackReason": "mineru failed",
        }

    monkeypatch.setattr(parsing_service.settings, "business_pdf_mineru_enabled", True)
    monkeypatch.setattr(parsing_service.settings, "business_pdf_engine_fallback", "none")
    monkeypatch.setattr(parsing_service.settings, "s1_parse_opencode_enabled", False)
    monkeypatch.setattr(parsing_service, "parsed_project_dir", lambda project_id: project_dir)
    monkeypatch.setattr(parsing_service.MineruParseEngine, "parse_pdf", fake_parse_pdf)
    monkeypatch.setattr(
        parsing_service,
        "extract_pdf_text",
        lambda path: (_ for _ in ()).throw(
            AssertionError("disabled business PDF fallback must not call extract_pdf_text")
        ),
    )
    monkeypatch.setattr(
        parsing_service,
        "run_business_template_extractor",
        lambda **kwargs: (
            [],
            {"schemaVersion": "bid-business-template-extractor-v1", "summary": {"templateCount": 0}},
            "",
        ),
    )
    monkeypatch.setattr(parsing_service, "_run_parse_skill", lambda *args, **kwargs: (kwargs["local_result"], ""))
    monkeypatch.setattr(parsing_service, "_needs_business_s1_finalize_guard", lambda **kwargs: False)

    summary, storage = parsing_service.parse_tender_documents(
        "PRJ-NO-FALLBACK",
        [
            {
                "id": "DOC-1",
                "name": "business-no-fallback.pdf",
                "path": str(pdf_path),
                "content_type": "application/pdf",
            }
        ],
        bid_type=BUSINESS_BID_TYPE,
    )

    document = storage["documents"][0]
    assert summary["textLength"] == 0
    assert document["documentParseEngine"] == "mineru"
    assert document["documentParseStatus"] == "failed"
    assert document["fallbackReason"] == "mineru failed"
    assert all("轻量 PDF 文本解析" not in warning for warning in document["warnings"])
    assert document["textLength"] == 0


def test_business_pdf_reuses_completed_document_nav_without_rerunning_mineru(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "business-retry.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    project_dir = tmp_path / "parsed" / "PRJ-RETRY"
    project_dir.mkdir(parents=True)
    nav_path = project_dir / "DOC-1_document_nav.json"
    quality_path = project_dir / "document_parse" / "mineru" / "DOC-1" / "parse_quality.json"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    nav_path.write_text(
        json.dumps(
            {
                "schemaVersion": "business-document-nav-v1",
                "sourceEngine": "mineru",
                "pages": [{"pageNo": 1, "textDensity": 1}],
                "blocks": [
                    {
                        "id": "DOC-1:B000001",
                        "documentId": "DOC-1",
                        "pageNo": 1,
                        "type": "paragraph",
                        "text": "MinerU 已有文本",
                        "sourceEngine": "mineru",
                    }
                ],
                "tables": [],
                "quality": {"engine": "mineru", "status": "completed", "fallbackUsed": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    quality_path.write_text(
        json.dumps(
            {"engine": "mineru", "status": "completed", "fallbackUsed": False, "warnings": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(parsing_service.settings, "business_pdf_mineru_enabled", True)
    monkeypatch.setattr(parsing_service.settings, "business_pdf_engine_fallback", "none")
    monkeypatch.setattr(
        parsing_service.MineruParseEngine,
        "parse_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("completed DocumentNav must be reused")),
    )

    text, metadata, warnings = parsing_service._parse_business_pdf_with_document_engine(
        project_id="PRJ-RETRY",
        document={"id": "DOC-1", "name": "business-retry.pdf", "path": str(pdf_path), "sourcePath": str(pdf_path)},
        file_path=pdf_path,
        project_dir=project_dir,
    )

    assert text == "MinerU 已有文本"
    assert metadata["documentParseEngine"] == "mineru"
    assert metadata["documentNavPath"] == str(nav_path)
    assert metadata["parseQualityPath"] == str(quality_path)
    assert metadata["pageCount"] == 1
    assert warnings == []


def test_run_mineru_command_passes_backend_and_ascii_fasttext_shim(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "mineru"
    output_dir.mkdir()
    seen: dict[str, object] = {}

    def fake_which(name: str) -> str:
        assert name == "mineru"
        return "mineru.exe"

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs.get("env")
        (output_dir / "source.md").write_text("# ok\n", encoding="utf-8")
        (output_dir / "source.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.mineru_engine.shutil.which", fake_which)
    monkeypatch.setattr("app.services.mineru_engine.subprocess.run", fake_run)

    result = run_mineru_command(pdf_path, output_dir, "auto", backend="pipeline")

    assert result["markdownPath"].endswith("source.md")
    assert seen["command"] == [
        "mineru.exe",
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-m",
        "auto",
        "-b",
        "pipeline",
    ]
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["MINERU_DISABLE_FASTTEXT"] == "0"
    shim_path = Path(env["MINERU_FASTTEXT_MODEL_PATH"])
    assert shim_path.is_file()
    assert shim_path.parent.as_posix().isascii()
    assert str(shim_path.parent) in env["PYTHONPATH"].split(os.pathsep)


def test_run_mineru_command_prefers_explicit_executable_over_path(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "mineru"
    output_dir.mkdir()
    external_dir = tmp_path / "ascii-mineru" / "Scripts"
    external_dir.mkdir(parents=True)
    external_mineru = external_dir / "mineru.exe"
    external_mineru.write_text("", encoding="utf-8")
    seen: dict[str, object] = {}

    monkeypatch.setattr("app.services.mineru_engine.shutil.which", lambda name: "mineru-from-path.exe")

    def fake_run(command, **kwargs):
        seen["command"] = command
        (output_dir / "source.md").write_text("# ok\n", encoding="utf-8")
        (output_dir / "source.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.mineru_engine.subprocess.run", fake_run)

    result = run_mineru_command(
        pdf_path,
        output_dir,
        "auto",
        backend="pipeline",
        executable=str(external_mineru),
    )

    assert result["markdownPath"].endswith("source.md")
    assert seen["command"][0] == str(external_mineru)


def test_run_mineru_command_reports_timeout(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "mineru"
    output_dir.mkdir()

    monkeypatch.setattr("app.services.mineru_engine.shutil.which", lambda name: "mineru")

    def fake_run(command, **kwargs):
        assert kwargs["timeout"] == 3
        raise subprocess.TimeoutExpired(command, timeout=3, output="still running", stderr="")

    monkeypatch.setattr("app.services.mineru_engine.subprocess.run", fake_run)

    try:
        run_mineru_command(pdf_path, output_dir, "auto", backend="pipeline", timeout_sec=3)
    except RuntimeError as exc:
        assert "MinerU CLI timed out after 3 seconds" in str(exc)
    else:
        raise AssertionError("run_mineru_command should fail on timeout")


def test_run_mineru_command_finds_cli_next_to_current_python_when_path_missing(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "mineru"
    output_dir.mkdir()
    scripts_dir = tmp_path / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    mineru_exe = scripts_dir / "mineru.exe"
    mineru_exe.write_text("", encoding="utf-8")
    seen: dict[str, object] = {}

    monkeypatch.setattr("app.services.mineru_engine.shutil.which", lambda name: None)
    monkeypatch.setattr(
        mineru_engine_module,
        "sys",
        SimpleNamespace(executable=str(scripts_dir / "python.exe"), prefix=str(tmp_path / ".venv")),
        raising=False,
    )

    def fake_run(command, **kwargs):
        seen["command"] = command
        (output_dir / "source.md").write_text("# ok\n", encoding="utf-8")
        (output_dir / "source.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.mineru_engine.subprocess.run", fake_run)

    result = run_mineru_command(pdf_path, output_dir, "auto", backend="pipeline")

    assert result["markdownPath"].endswith("source.md")
    assert seen["command"][0] == str(mineru_exe)
