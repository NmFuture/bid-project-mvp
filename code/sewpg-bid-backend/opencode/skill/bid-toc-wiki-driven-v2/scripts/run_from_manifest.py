#!/usr/bin/env python3
"""Run bid-toc-wiki-driven-v2 from a backend-prepared manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_API_BASE = "http://fastapi:8000"


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("manifest must be a JSON object")
    return data


def as_path(value: Any, *, required: bool = False, label: str = "path") -> Path | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise RuntimeError(f"{label} is required")
        return None
    path = Path(text)
    if required and not path.exists():
        raise RuntimeError(f"{label} does not exist: {path}")
    return path


def run_capture(command: list[str], *, stdout_path: Path | None = None) -> str:
    if stdout_path is None:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    else:
        with stdout_path.open("w", encoding="utf-8") as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{stderr}")
    return result.stdout if stdout_path is None else ""


def ensure_wiki(manifest: dict[str, Any], wiki_dir: Path) -> None:
    cards_dir = wiki_dir / "卡片"
    has_cards = cards_dir.exists() and any(cards_dir.rglob("*.md"))
    if has_cards:
        return

    api_base = str(manifest.get("apiBaseUrl") or manifest.get("backendApiBaseUrl") or DEFAULT_API_BASE)
    bid_type = str(manifest.get("bidType") or "技术标")
    run_capture(
        [
            sys.executable,
            str(SCRIPT_DIR / "export_wiki_from_api.py"),
            "--api-base",
            api_base,
            "--bid-type",
            bid_type,
            "--out",
            str(wiki_dir),
        ]
    )


def select_tender_file(manifest: dict[str, Any]) -> Path:
    tender_files = manifest.get("tenderFiles") or []
    if isinstance(tender_files, list):
        for item in tender_files:
            if isinstance(item, dict):
                path = as_path(item.get("path"))
            else:
                path = as_path(item)
            if path and path.exists():
                return path
    path = as_path(manifest.get("tenderFile"))
    if path and path.exists():
        return path
    raise RuntimeError("no readable tender docx found in manifest")


def run_from_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    work_dir = as_path(manifest.get("workDir"), required=False) or manifest_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    tender_file = select_tender_file(manifest)
    template_file = as_path(manifest.get("templateFile"), required=True, label="templateFile")
    attach_file = as_path(manifest.get("attachFile"), required=False)
    wiki_dir = as_path(manifest.get("wikiDir"), required=False) or (work_dir / "wiki")
    output_file = as_path(manifest.get("outputFile"), required=False) or (work_dir / "toc.json")
    assert template_file is not None
    assert wiki_dir is not None
    assert output_file is not None

    ensure_wiki(manifest, wiki_dir)
    temp_dir = work_dir / ".s2_toc_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    template_json = temp_dir / "template.json"
    tender_json = temp_dir / "tender.json"
    attach_json = temp_dir / "attach.json"
    project_identity_json = temp_dir / "project_identity.json"
    directory_templates_json = temp_dir / "directory_templates.json"

    run_capture(
        [sys.executable, str(SCRIPT_DIR / "extract_template.py"), str(template_file)],
        stdout_path=template_json,
    )
    run_capture(
        [sys.executable, str(SCRIPT_DIR / "extract_tender.py"), str(tender_file)],
        stdout_path=tender_json,
    )

    build_command = [
        sys.executable,
        str(SCRIPT_DIR / "build_plan.py"),
        "--template",
        str(template_json),
        "--tender",
        str(tender_json),
        "--wiki",
        str(wiki_dir),
        "--output",
        str(output_file),
    ]
    project_identity = manifest.get("projectIdentity") or {}
    if isinstance(project_identity, dict) and project_identity:
        project_identity_json.write_text(json.dumps(project_identity, ensure_ascii=False, indent=2), encoding="utf-8")
        build_command.extend(["--project-identity", str(project_identity_json)])
    directory_templates = manifest.get("directoryTemplates") or []
    if isinstance(directory_templates, list) and directory_templates:
        directory_templates_json.write_text(
            json.dumps(directory_templates, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        build_command.extend(["--directory-templates", str(directory_templates_json)])
    if attach_file and attach_file.exists():
        run_capture(
            [sys.executable, str(SCRIPT_DIR / "extract_attach.py"), str(attach_file)],
            stdout_path=attach_json,
        )
        build_command.extend(["--attach", str(attach_json)])

    output_file.parent.mkdir(parents=True, exist_ok=True)
    run_capture(build_command)
    output = json.loads(output_file.read_text(encoding="utf-8"))
    if not isinstance(output, dict) or not isinstance(output.get("items"), list):
        raise RuntimeError("generated TOC JSON is missing items[]")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--response",
        choices=("full", "summary"),
        default="full",
        help="full prints the complete generated JSON; summary prints only metadata and outputFile.",
    )
    args = parser.parse_args()

    try:
        output = run_from_manifest(Path(args.manifest))
    except Exception as exc:
        print(f"run_from_manifest failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.response == "summary":
        source_files = output.get("source_files") if isinstance(output.get("source_files"), dict) else {}
        payload = {
            "schema_version": output.get("schema_version") or "bid-toc-json-v1",
            "document_title": output.get("document_title") or "",
            "outputFile": str(source_files.get("output") or load_manifest(Path(args.manifest)).get("outputFile") or ""),
            "summary": output.get("summary") or {},
            "itemCount": len(output.get("items") or []),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
