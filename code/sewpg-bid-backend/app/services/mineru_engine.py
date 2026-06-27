from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.services.document_parse_engine import DocumentParseEngine


def _prepare_fasttext_ascii_shim() -> tuple[Path, Path] | None:
    try:
        import fast_langdetect.ft_detect.infer as infer
    except Exception:
        return None

    source_path = Path(str(infer.LOCAL_SMALL_MODEL_PATH))
    if not source_path.is_file():
        return None
    shim_root = Path(tempfile.gettempdir()) / "codex-mineru-fasttext"
    model_path = shim_root / "lid.176.ftz"
    sitecustomize_path = shim_root / "sitecustomize.py"
    shim_root.mkdir(parents=True, exist_ok=True)
    if not model_path.is_file() or model_path.stat().st_size != source_path.stat().st_size:
        shutil.copy2(source_path, model_path)
    sitecustomize_path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "try:",
                "    import fast_langdetect.ft_detect.infer as infer",
                f"    infer.LOCAL_SMALL_MODEL_PATH = Path({str(model_path)!r})",
                "except Exception:",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return shim_root, model_path


def _mineru_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    shim = _prepare_fasttext_ascii_shim()
    if shim:
        shim_root, model_path = shim
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            [str(shim_root)] + ([existing_pythonpath] if existing_pythonpath else [])
        )
        env["MINERU_FASTTEXT_MODEL_PATH"] = str(model_path)
        env["MINERU_DISABLE_FASTTEXT"] = "0"
    return env


def _first_mineru_file(output_dir: Path, suffix: str) -> Path | None:
    candidates = sorted(
        path
        for path in output_dir.rglob(f"*{suffix}")
        if path.is_file() and path.name != "parse_quality.json" and "__MACOSX" not in path.parts
    )
    return candidates[0] if candidates else None


def _resolve_mineru_executable(explicit_executable: str = "") -> str | None:
    explicit = explicit_executable.strip()
    if explicit:
        return explicit
    executable = shutil.which("mineru")
    if executable:
        return executable
    current_python = Path(sys.executable)
    for candidate in (
        current_python.with_name("mineru.exe"),
        current_python.with_name("mineru"),
        Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin") / ("mineru.exe" if os.name == "nt" else "mineru"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def run_mineru_command(
    pdf_path: Path,
    output_dir: Path,
    mode: str,
    *,
    backend: str = "pipeline",
    executable: str = "",
    timeout_sec: int = 21600,
) -> dict:
    executable = _resolve_mineru_executable(executable)
    if not executable:
        raise RuntimeError("MinerU CLI is unavailable")
    command = [executable, "-p", str(pdf_path), "-o", str(output_dir), "-m", mode]
    if backend:
        command.extend(["-b", backend])
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_mineru_subprocess_env(),
            timeout=max(1, int(timeout_sec or 21600)),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"MinerU CLI timed out after {int(exc.timeout or timeout_sec)} seconds") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"MinerU CLI exited with {completed.returncode}")
    markdown_path = _first_mineru_file(output_dir, ".md")
    json_path = _first_mineru_file(output_dir, ".json")
    return {
        "markdownPath": str(markdown_path or ""),
        "jsonPath": str(json_path or ""),
        "pageCount": 0,
    }


class MineruParseEngine(DocumentParseEngine):
    def __init__(
        self,
        *,
        mode: str = "auto",
        backend: str = "pipeline",
        fallback: str = "lightweight",
        executable: str = "",
        timeout_sec: int = 21600,
    ) -> None:
        self.mode = mode
        self.backend = backend
        self.fallback = fallback
        self.executable = executable
        self.timeout_sec = timeout_sec

    def parse_pdf(self, *, project_id: str, document: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        _ = project_id
        document_id = str(
            document.get("id") or Path(str(document.get("path") or document.get("sourcePath") or "")).stem or "DOC-1"
        )
        pdf_path = Path(str(document.get("path") or document.get("sourcePath") or ""))
        mineru_output_dir = output_dir / "document_parse" / "mineru" / document_id
        mineru_output_dir.mkdir(parents=True, exist_ok=True)
        quality_path = mineru_output_dir / "parse_quality.json"

        try:
            command_result = run_mineru_command(
                pdf_path,
                mineru_output_dir,
                self.mode,
                backend=self.backend,
                executable=self.executable,
                timeout_sec=self.timeout_sec,
            )
        except Exception as exc:
            quality = {
                "engine": "mineru",
                "status": "failed",
                "pageCount": 0,
                "lowQualityPages": [],
                "tableCount": 0,
                "fallbackUsed": self.fallback == "lightweight",
                "warnings": [str(exc)],
            }
            quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "documentParseEngine": "mineru",
                "status": "failed",
                "mineruOutputDir": str(mineru_output_dir),
                "parseQualityPath": str(quality_path),
                "fallbackReason": str(exc),
            }

        quality = {
            "engine": "mineru",
            "status": "completed",
            "pageCount": int(command_result.get("pageCount") or 0),
            "lowQualityPages": list(command_result.get("lowQualityPages") or []),
            "tableCount": int(command_result.get("tableCount") or 0),
            "fallbackUsed": False,
            "warnings": list(command_result.get("warnings") or []),
        }
        quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "documentParseEngine": "mineru",
            "status": "completed",
            "mineruOutputDir": str(mineru_output_dir),
            "parseQualityPath": str(quality_path),
            "markdownPath": str(command_result.get("markdownPath") or ""),
            "jsonPath": str(command_result.get("jsonPath") or ""),
            "tablePaths": list(command_result.get("tablePaths") or []),
            "imagePaths": list(command_result.get("imagePaths") or []),
        }
