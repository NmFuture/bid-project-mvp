from __future__ import annotations

from pathlib import Path
from typing import Any

from . import doc_browser, paths, submission_store


SCHEMA_VERSION = "bid-business-template-validation-v1"


def _templates(targets: dict[str, Any]) -> list[dict[str, Any]]:
    raw = targets.get("templates")
    if isinstance(raw, dict):
        raw = raw.get("templates")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _document_map(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nav = doc_browser.load_nav(manifest_path, manifest)
    docs = nav.get("documents") if isinstance(nav.get("documents"), list) else []
    return {str(item.get("id") or ""): item for item in docs if isinstance(item, dict)}


def _document_block_ids(document: dict[str, Any]) -> set[int]:
    blocks_path = Path(str(document.get("blocksPath") or ""))
    blocks = paths.read_json(blocks_path) if blocks_path.is_file() else []
    ids: set[int] = set()
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        try:
            ids.add(int(block.get("blockId")))
        except (TypeError, ValueError):
            continue
    return ids


def _validate_template(template: dict[str, Any], index: int, documents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    title = str(template.get("title") or template.get("templateTitle") or "").strip()
    document_id = str(template.get("sourceDocumentId") or template.get("documentId") or "").strip()
    reason = str(template.get("reason") or "").strip()
    if not title:
        errors.append({"code": "missing_title", "rowIndex": index, "message": "模板缺少 title。"})
    if not document_id:
        errors.append({"code": "missing_source_document", "rowIndex": index, "message": "模板缺少 sourceDocumentId。"})
        return errors
    document = documents.get(document_id)
    if not document:
        errors.append({"code": "unknown_source_document", "rowIndex": index, "sourceDocumentId": document_id, "message": "sourceDocumentId 不在导航索引中。"})
        return errors
    try:
        start = int(template.get("startBlockId"))
        end = int(template.get("endBlockId"))
    except (TypeError, ValueError):
        errors.append({"code": "invalid_block_range", "rowIndex": index, "message": "startBlockId/endBlockId 必须是整数。"})
        return errors
    if end < start:
        errors.append({"code": "invalid_block_range", "rowIndex": index, "message": "endBlockId 不得早于 startBlockId。"})
    block_ids = _document_block_ids(document)
    if start not in block_ids or end not in block_ids:
        errors.append({"code": "unknown_block_id", "rowIndex": index, "startBlockId": start, "endBlockId": end, "message": "起止块必须存在于同一源文档。"})
    if not reason:
        errors.append({"code": "missing_reason", "rowIndex": index, "message": "模板缺少 AI 判断理由 reason。"})
    return errors


def _overlap_errors(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    by_doc: dict[str, list[tuple[int, int, int]]] = {}
    for index, template in enumerate(templates, start=1):
        try:
            start = int(template.get("startBlockId"))
            end = int(template.get("endBlockId"))
        except (TypeError, ValueError):
            continue
        by_doc.setdefault(str(template.get("sourceDocumentId") or template.get("documentId") or ""), []).append((start, end, index))
    for document_id, ranges in by_doc.items():
        previous_end = 0
        previous_index = 0
        for start, end, index in sorted(ranges):
            if start <= previous_end:
                errors.append(
                    {
                        "code": "overlapping_templates",
                        "sourceDocumentId": document_id,
                        "rowIndex": index,
                        "previousRowIndex": previous_index,
                        "message": "同一源文档内模板范围不得交叉或重叠。",
                    }
                )
            if end > previous_end:
                previous_end = end
                previous_index = index
    return errors


def validate(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    submissions = submission_store.load(manifest_path, manifest)
    targets = submissions.get("targets") if isinstance(submissions.get("targets"), dict) else {}
    templates = _templates(targets)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not templates:
        warnings.append({"code": "missing_templates", "message": "尚未提交 templates；finalize 将输出空模板清单。"})
    try:
        documents = _document_map(manifest_path, manifest)
    except Exception as exc:
        documents = {}
        errors.append({"code": "missing_navigation", "message": f"导航索引不可用：{exc}"})
    for index, template in enumerate(templates, start=1):
        errors.extend(_validate_template(template, index, documents))
    errors.extend(_overlap_errors(templates))
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "failed" if errors else "passed",
        "templateCount": len(templates),
        "submissionPath": str(paths.submission_path(manifest_path, manifest)),
        "navPath": str(paths.nav_path(manifest_path, manifest)),
        "validationErrors": errors,
        "validationWarnings": warnings,
    }
    paths.write_json(paths.validation_report_path(manifest_path, manifest), report)
    return report
