from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"manifest must be a JSON object: {manifest_path}")
    return payload


def output_dir(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    output = Path(str(manifest.get("structuredResultPath") or manifest_path.with_name("s1_structured_result.json")))
    return output.parent


def structured_result_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    return Path(str(manifest.get("structuredResultPath") or manifest_path.with_name("s1_structured_result.json")))


def nav_store_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("navStorePath") or "").strip()
    return Path(value) if value else output_dir(manifest_path, manifest) / "s1_nav.sqlite"


def document_map_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("documentMapPath") or "").strip()
    return Path(value) if value else output_dir(manifest_path, manifest) / "document_map.json"


def submission_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("submissionPath") or "").strip()
    return Path(value) if value else output_dir(manifest_path, manifest) / "agentic_submissions.json"


def validation_report_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("validationReportPath") or "").strip()
    return Path(value) if value else output_dir(manifest_path, manifest) / "validation_report.json"
