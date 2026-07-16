from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.document_nav_docx_renderer import render_document_nav_templates
from scripts.docx_slicer import slice_docx_by_boundaries

from . import doc_browser, paths, submission_store
from .validator import validate


SCHEMA_VERSION = "bid-business-template-extractor-v1"
SKILL_NAME = "bid-business-template-extractor"


def _templates_from_submissions(manifest_path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    submissions = submission_store.load(manifest_path, manifest)
    targets = submissions.get("targets") if isinstance(submissions.get("targets"), dict) else {}
    raw = targets.get("templates")
    if isinstance(raw, dict):
        raw = raw.get("templates")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _quality(
    *,
    submitted_template_count: int,
    validated_template_count: int,
    sliced_template_count: int,
    warning_count: int,
) -> dict[str, Any]:
    return {
        "agentSubmittedTemplateCount": submitted_template_count,
        "structurallyValidatedTemplateCount": validated_template_count,
        "slicedTemplateCount": sliced_template_count,
        "scriptFallbackUsed": False,
        "warningCount": warning_count,
    }


def _document_map(nav: dict[str, Any]) -> dict[str, dict[str, Any]]:
    docs = nav.get("documents") if isinstance(nav.get("documents"), list) else []
    return {str(item.get("id") or ""): item for item in docs if isinstance(item, dict)}


def _blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks_path = Path(str(document.get("blocksPath") or ""))
    payload = paths.read_json(blocks_path) if blocks_path.is_file() else []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _boundary_templates(templates: list[dict[str, Any]], document_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, template in enumerate([item for item in templates if str(item.get("sourceDocumentId") or item.get("documentId") or "") == document_id], start=1):
        title = str(template.get("title") or template.get("templateTitle") or f"商务模板{index}").strip()
        items.append(
            {
                "id": f"TPL-{index:04d}",
                "title": title,
                "templateTitle": title,
                "templateType": str(template.get("templateType") or "business_template"),
                "startBlockId": int(template.get("startBlockId")),
                "endBlockId": int(template.get("endBlockId")),
                "confidence": float(template.get("confidence") or 0),
                "reason": str(template.get("reason") or ""),
                "needsReview": bool(template.get("needsReview")),
                "decisionSource": "executing_agent",
                "quality": {
                    "confidence": float(template.get("confidence") or 0),
                    "reason": str(template.get("reason") or ""),
                },
            }
        )
    return items


def _appendix_from_rendered(
    raw: dict[str, Any],
    *,
    document: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    title = str(raw.get("title") or raw.get("templateTitle") or f"商务模板{index}").strip()
    docx_path = Path(str(raw.get("outputPath") or ""))
    document_output = Path(str(document.get("outputDir") or ""))
    if not docx_path.is_absolute():
        docx_path = document_output / docx_path
    return {
        "id": f"APPX-{index:04d}",
        "title": title,
        "evidence": title,
        "artifactType": "business_attachment_template",
        "templateType": str(raw.get("templateType") or "business_template"),
        "templateSectionTitle": "",
        "status": "generated",
        "rowCount": int(raw.get("rowCount") or 0),
        "docxPath": str(docx_path),
        "workspacePath": "",
        "sourceDocumentId": str(document.get("id") or ""),
        "sourceDocumentName": str(document.get("name") or ""),
        "sourcePath": str(document.get("sourcePath") or ""),
        "extractionMode": "business_template_extractor_skill",
        "startBlockIndex": raw.get("startBlockId"),
        "endBlockIndex": raw.get("endBlockId"),
        "sourceEngine": str(raw.get("sourceEngine") or document.get("documentParseEngine") or document.get("sourceEngine") or ""),
        "quality": raw.get("quality") if isinstance(raw.get("quality"), dict) else {},
    }


def _render_templates_for_document(
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    boundaries: dict[str, Any],
    document_output: Path,
) -> dict[str, Any]:
    source_path = Path(str(document.get("sourcePath") or ""))
    if str(document.get("documentNavPath") or "").strip() or source_path.suffix.lower() == ".pdf":
        return render_document_nav_templates(
            source_document=document,
            blocks=blocks,
            boundaries=boundaries,
            output_dir=document_output,
        )
    return slice_docx_by_boundaries(source_path, blocks, boundaries, document_output)


def finalize(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    validation = validate(manifest_path, manifest)
    nav = doc_browser.load_nav(manifest_path, manifest)
    templates = _templates_from_submissions(manifest_path, manifest)
    documents = _document_map(nav)
    appendices: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if validation.get("status") != "passed":
        warnings.append(
            {
                "code": "validation_failed",
                "message": "AI 提交的模板范围未通过结构校验，未执行 Word 切片。",
                "validationErrors": validation.get("validationErrors") or [],
            }
        )
    else:
        for document_id, document in documents.items():
            document_output = Path(str(document.get("outputDir") or ""))
            boundaries = {"templates": _boundary_templates(templates, document_id)}
            if not boundaries["templates"]:
                continue
            sliced = _render_templates_for_document(document, _blocks(document), boundaries, document_output)
            for raw in sliced.get("templates") or []:
                if isinstance(raw, dict):
                    appendices.append(_appendix_from_rendered(raw, document=document, index=len(appendices) + 1))
            paths.write_json(document_output / "boundaries.json", {**boundaries, "templates": sliced.get("templates") or []})

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "skillName": SKILL_NAME,
        "projectId": str(manifest.get("projectId") or ""),
        "outputDir": str(paths.output_dir(manifest_path, manifest)),
        "stage": "finalize",
        "summary": {
            "documentCount": len(documents),
            "templateCount": len(appendices),
            "warningCount": len(warnings),
        },
        "formatRegions": [],
        "excludedRegions": [],
        "documents": [
            {
                "id": str(document.get("id") or ""),
                "name": str(document.get("name") or ""),
                "sourcePath": str(document.get("sourcePath") or ""),
                "documentNavPath": str(document.get("documentNavPath") or ""),
                "documentParseEngine": str(document.get("documentParseEngine") or document.get("sourceEngine") or ""),
                "outputDir": str(document.get("outputDir") or ""),
                "summary": {"blockCount": int(document.get("blockCount") or 0)},
            }
            for document in documents.values()
        ],
        "appendices": appendices,
        "warnings": warnings,
        "rejectedCandidates": [],
        "quality": _quality(
            submitted_template_count=len(templates),
            validated_template_count=0 if validation.get("status") != "passed" else len(templates),
            sliced_template_count=len(appendices),
            warning_count=len(warnings),
        )
        | {
            "sourceEngine": "docling"
            if any(str(item.get("sourceEngine") or "") == "docling" for item in appendices)
            else "",
        },
        "workflow": {
            "mode": "opencode-agentic-navigation",
            "navPath": str(paths.nav_path(manifest_path, manifest)),
            "submissionPath": str(paths.submission_path(manifest_path, manifest)),
            "validationReportPath": str(paths.validation_report_path(manifest_path, manifest)),
        },
    }
    paths.write_json(paths.extraction_result_path(manifest_path, manifest), result)
    return result


def summary(result: dict[str, Any], output_file: Path) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillName": SKILL_NAME,
        "outputFile": str(output_file),
        "summary": {
            "documentCount": int((result.get("summary") or {}).get("documentCount") or 0),
            "templateCount": len(result.get("appendices") or []),
            "warningCount": len(result.get("warnings") or []),
        },
    }
