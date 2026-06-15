from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from scripts.docx_blocks import extract_blocks

from . import paths


SCHEMA_VERSION = "bid-business-template-nav-v1"
TEXT_LIMIT = 260


def _short(text: Any, limit: int = TEXT_LIMIT) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _block_preview(block: dict[str, Any], *, limit: int = TEXT_LIMIT) -> dict[str, Any]:
    item = {
        "blockId": int(block.get("blockId") or 0),
        "bodyIndex": int(block.get("bodyIndex") or 0),
        "type": str(block.get("type") or ""),
        "text": _short(block.get("text"), limit),
        "styleName": str(block.get("styleName") or ""),
        "isLikelyHeading": bool(block.get("isLikelyHeading")),
        "pageSegment": int(block.get("pageSegment") or 0),
        "isPageFirstNonEmpty": bool(block.get("isPageFirstNonEmpty")),
    }
    if block.get("rows"):
        item["rows"] = block.get("rows")
    return item


def _document_meta(raw: dict[str, Any], source_path: Path, document_output: Path, blocks: list[dict[str, Any]], index: int) -> dict[str, Any]:
    document_id = str(raw.get("id") or f"DOC-{index}")
    return {
        "id": document_id,
        "name": str(raw.get("name") or source_path.name),
        "sourcePath": str(source_path),
        "outputDir": str(document_output),
        "blockCount": len(blocks),
        "blocksPath": str(document_output / "blocks.json"),
        "blocksPreview": [_block_preview(block) for block in blocks[:80]],
    }


def prepare(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    root = paths.output_dir(manifest_path, manifest)
    if root.exists():
        for child in root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    root.mkdir(parents=True, exist_ok=True)

    documents: list[dict[str, Any]] = []
    for index, raw in enumerate(manifest.get("documents") if isinstance(manifest.get("documents"), list) else [], start=1):
        if not isinstance(raw, dict):
            continue
        source_path = Path(str(raw.get("sourcePath") or "")).resolve()
        if source_path.suffix.lower() != ".docx" or not source_path.is_file():
            continue
        document_output = paths.document_output_dir(manifest_path, manifest, raw, index)
        document_output.mkdir(parents=True, exist_ok=True)
        blocks = extract_blocks(source_path)
        paths.write_json(document_output / "blocks.json", blocks)
        documents.append(_document_meta(raw, source_path, document_output, blocks, index))

    nav = {
        "schemaVersion": SCHEMA_VERSION,
        "projectId": str(manifest.get("projectId") or ""),
        "outputDir": str(root),
        "documentCount": len(documents),
        "documents": documents,
    }
    paths.write_json(paths.nav_path(manifest_path, manifest), nav)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "stage": "prepared",
        "navPath": str(paths.nav_path(manifest_path, manifest)),
        "submissionPath": str(paths.submission_path(manifest_path, manifest)),
        "validationReportPath": str(paths.validation_report_path(manifest_path, manifest)),
        "outputFile": str(paths.extraction_result_path(manifest_path, manifest)),
        "documentCount": len(documents),
        "documents": documents,
    }


def load_nav(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path = paths.nav_path(manifest_path, manifest)
    if not path.is_file():
        raise RuntimeError("template navigation index is missing; run btplnav prepare first")
    payload = paths.read_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError("template navigation index is invalid")
    return payload


def _all_blocks(nav: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for document in nav.get("documents") if isinstance(nav.get("documents"), list) else []:
        if not isinstance(document, dict):
            continue
        blocks_path = Path(str(document.get("blocksPath") or ""))
        blocks = paths.read_json(blocks_path) if blocks_path.is_file() else []
        if not isinstance(blocks, list):
            blocks = []
        for block in blocks:
            if isinstance(block, dict):
                items.append((document, block))
    return items


def overview(manifest_path: Path, manifest: dict[str, Any], *, page: int = 1, page_size: int = 30) -> dict[str, Any]:
    nav = load_nav(manifest_path, manifest)
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    all_items = _all_blocks(nav)
    start = (page - 1) * page_size
    page_items = all_items[start : start + page_size]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "page": page,
        "pageSize": page_size,
        "totalBlocks": len(all_items),
        "documents": nav.get("documents") or [],
        "blocks": [
            {
                **_block_preview(block),
                "sourceDocumentId": str(document.get("id") or ""),
                "sourceDocumentName": str(document.get("name") or ""),
            }
            for document, block in page_items
        ],
    }


def search(manifest_path: Path, manifest: dict[str, Any], query: str, *, limit: int = 20) -> dict[str, Any]:
    nav = load_nav(manifest_path, manifest)
    compact_query = "".join(str(query or "").split()).lower()
    tokens = [token.lower() for token in str(query or "").split() if token.strip()]
    matches: list[dict[str, Any]] = []
    for document, block in _all_blocks(nav):
        text = str(block.get("text") or "")
        compact_text = "".join(text.split()).lower()
        if compact_query and compact_query in compact_text:
            score = 100
        else:
            score = sum(20 for token in tokens if token in text.lower())
        if not score and compact_query:
            matched_chars = sum(1 for char in set(compact_query) if char and char in compact_text)
            score = matched_chars if matched_chars >= max(1, len(set(compact_query)) // 2) else 0
        if score:
            matches.append(
                {
                    **_block_preview(block),
                    "sourceDocumentId": str(document.get("id") or ""),
                    "sourceDocumentName": str(document.get("name") or ""),
                    "score": score,
                }
            )
    matches.sort(key=lambda item: (-int(item.get("score") or 0), item.get("sourceDocumentId") or "", int(item.get("blockId") or 0)))
    limit = max(1, min(100, limit))
    return {"schemaVersion": SCHEMA_VERSION, "query": query, "matchCount": min(len(matches), limit), "matches": matches[:limit]}


def window(
    manifest_path: Path,
    manifest: dict[str, Any],
    document_id: str,
    block_id: int,
    *,
    before: int = 4,
    after: int = 8,
) -> dict[str, Any]:
    nav = load_nav(manifest_path, manifest)
    document = _document_by_id(nav, document_id)
    blocks = _blocks_for_document(document)
    start = max(1, block_id - max(0, before))
    end = block_id + max(0, after)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceDocumentId": document_id,
        "centerBlockId": block_id,
        "blocks": [_block_preview(block, limit=520) for block in blocks if start <= int(block.get("blockId") or 0) <= end],
    }


def read(
    manifest_path: Path,
    manifest: dict[str, Any],
    document_id: str,
    start_block_id: int,
    end_block_id: int,
    *,
    max_chars: int = 4000,
) -> dict[str, Any]:
    nav = load_nav(manifest_path, manifest)
    document = _document_by_id(nav, document_id)
    blocks = [
        block
        for block in _blocks_for_document(document)
        if start_block_id <= int(block.get("blockId") or 0) <= end_block_id
    ]
    text = "\n".join(str(block.get("text") or "") for block in blocks if str(block.get("text") or "").strip())
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceDocumentId": document_id,
        "startBlockId": start_block_id,
        "endBlockId": end_block_id,
        "text": _short(text, max_chars),
        "blocks": [_block_preview(block, limit=520) for block in blocks[:120]],
    }


def _document_by_id(nav: dict[str, Any], document_id: str) -> dict[str, Any]:
    for document in nav.get("documents") if isinstance(nav.get("documents"), list) else []:
        if isinstance(document, dict) and str(document.get("id") or "") == str(document_id):
            return document
    raise RuntimeError(f"unknown sourceDocumentId: {document_id}")


def _blocks_for_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks_path = Path(str(document.get("blocksPath") or ""))
    blocks = paths.read_json(blocks_path) if blocks_path.is_file() else []
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []
