from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_name(value: str, fallback: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = read_json(manifest_path)
    if not isinstance(payload, dict):
        raise RuntimeError("manifest must be a JSON object")
    return payload


def output_dir(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    return Path(str(manifest.get("outputDir") or manifest_path.parent / "business_template_extraction")).resolve()


def nav_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("templateNavPath") or "").strip()
    return Path(value).resolve() if value else output_dir(manifest_path, manifest) / "template_nav.json"


def submission_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("templateSubmissionPath") or "").strip()
    return Path(value).resolve() if value else output_dir(manifest_path, manifest) / "template_submissions.json"


def validation_report_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("templateValidationPath") or "").strip()
    return Path(value).resolve() if value else output_dir(manifest_path, manifest) / "template_validation.json"


def extraction_result_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("businessTemplateExtractionPath") or "").strip()
    return Path(value).resolve() if value else output_dir(manifest_path, manifest) / "business_template_extraction.json"


def document_output_dir(manifest_path: Path, manifest: dict[str, Any], document: dict[str, Any], index: int) -> Path:
    raw = str(document.get("id") or "").strip()
    source = Path(str(document.get("sourcePath") or ""))
    name = safe_name(raw or source.stem, f"document-{index}")
    return output_dir(manifest_path, manifest) / name
