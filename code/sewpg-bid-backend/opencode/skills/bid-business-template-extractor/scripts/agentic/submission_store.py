from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths


TARGET_KEYS = {"templates"}


def empty() -> dict[str, Any]:
    return {
        "schemaVersion": "bid-business-template-submissions-v1",
        "updatedAt": "",
        "targets": {},
    }


def load(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path = paths.submission_path(manifest_path, manifest)
    if not path.is_file():
        return empty()
    payload = paths.read_json(path)
    return payload if isinstance(payload, dict) else empty()


def save(manifest_path: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> Path:
    path = paths.submission_path(manifest_path, manifest)
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    paths.write_json(path, payload)
    return path


def submit(manifest_path: Path, manifest: dict[str, Any], target_key: str, value: Any) -> dict[str, Any]:
    if target_key not in TARGET_KEYS:
        raise RuntimeError(f"unsupported targetKey: {target_key}")
    payload = load(manifest_path, manifest)
    targets = payload.setdefault("targets", {})
    if not isinstance(targets, dict):
        targets = {}
        payload["targets"] = targets
    targets[target_key] = value
    path = save(manifest_path, manifest, payload)
    templates = _templates_from_value(value)
    return {
        "schemaVersion": "bid-business-template-submit-v1",
        "status": "saved",
        "targetKey": target_key,
        "submissionPath": str(path),
        "templateCount": len(templates),
    }


def _templates_from_value(value: Any) -> list[dict[str, Any]]:
    raw_templates = value.get("templates") if isinstance(value, dict) else value
    if not isinstance(raw_templates, list):
        return []
    return [item for item in raw_templates if isinstance(item, dict)]
