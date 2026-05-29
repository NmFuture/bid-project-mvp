from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "bid-business-template-extractor"
SCHEMA_VERSION = "bid-business-template-extractor-v1"


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skill_runner_path() -> Path:
    return backend_root() / "opencode" / "skill" / SKILL_NAME / "scripts" / "run_from_manifest.py"


def build_business_template_extractor_manifest(
    *,
    project_id: str,
    documents: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    manifest_documents: list[dict[str, Any]] = []
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".docx":
            continue
        manifest_documents.append(
            {
                "id": str(document.get("id") or ""),
                "name": str(document.get("name") or source_path.name),
                "sourcePath": str(source_path),
                "textPath": str(document.get("textPath") or ""),
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillName": SKILL_NAME,
        "projectId": project_id,
        "outputDir": str(output_dir),
        "documents": manifest_documents,
    }


def convert_extractor_appendices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for raw in payload.get("appendices") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("evidence") or "").strip()
        docx_path = str(raw.get("docxPath") or "").strip()
        if not title or not docx_path:
            continue
        converted.append(
            {
                "id": str(raw.get("id") or f"APPX-{len(converted) + 1:04d}"),
                "title": title,
                "evidence": str(raw.get("evidence") or title),
                "artifactType": "business_attachment_template",
                "templateType": str(raw.get("templateType") or "business_template"),
                "templateSectionTitle": str(raw.get("templateSectionTitle") or ""),
                "status": str(raw.get("status") or "generated"),
                "rowCount": int(raw.get("rowCount") or 0),
                "docxPath": docx_path,
                "workspacePath": str(raw.get("workspacePath") or ""),
                "sourceDocumentId": str(raw.get("sourceDocumentId") or ""),
                "sourceDocumentName": str(raw.get("sourceDocumentName") or ""),
                "sourcePath": str(raw.get("sourcePath") or ""),
                "extractionMode": "business_template_extractor_skill",
                "startBlockIndex": raw.get("startBlockIndex"),
                "endBlockIndex": raw.get("endBlockIndex"),
                "quality": raw.get("quality") if isinstance(raw.get("quality"), dict) else {},
            }
        )
    return converted


def run_business_template_extractor(
    *,
    project_id: str,
    documents: list[dict[str, Any]],
    project_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    output_dir = project_dir / "business_template_extraction"
    manifest_path = project_dir / "business_template_extraction_manifest.json"
    manifest = build_business_template_extractor_manifest(
        project_id=project_id,
        documents=documents,
        output_dir=output_dir,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not manifest["documents"]:
        return [], None, "未找到可用于商务模板提取的 DOCX 招标文件。"

    runner = skill_runner_path()
    completed = subprocess.run(
        [sys.executable, str(runner), str(manifest_path)],
        cwd=str(backend_root()),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"退出码 {completed.returncode}"
        return [], None, f"商务模板提取 skill 调用失败，已回退旧逻辑：{message}"

    result_path = output_dir / "business_template_extraction.json"
    if not result_path.is_file():
        return [], None, "商务模板提取 skill 未生成 business_template_extraction.json，已回退旧逻辑。"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    appendices = convert_extractor_appendices(payload)
    if not appendices:
        return [], payload, "商务模板提取 skill 未识别到模板，已回退旧逻辑。"
    return appendices, payload, ""
