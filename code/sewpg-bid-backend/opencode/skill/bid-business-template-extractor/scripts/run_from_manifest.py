from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
SKILL_DIR = CURRENT_DIR.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.pipeline import run_pipeline  # noqa: E402


SCHEMA_VERSION = "bid-business-template-extractor-v1"
SKILL_NAME = "bid-business-template-extractor"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_name(value: str, fallback: str) -> str:
    text = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in value).strip()
    return text or fallback


def _build_empty_result(project_id: str, output_dir: Path) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillName": SKILL_NAME,
        "projectId": project_id,
        "outputDir": str(output_dir),
        "summary": {
            "documentCount": 0,
            "templateCount": 0,
            "warningCount": 0,
        },
        "documents": [],
        "appendices": [],
        "warnings": [],
    }


def _cluster_title(raw: dict[str, Any], blocks_by_id: dict[int, dict[str, Any]]) -> str:
    header_ids = raw.get("headerBlockIds") if isinstance(raw.get("headerBlockIds"), list) else []
    titles: list[str] = []
    for block_id in header_ids:
        try:
            block = blocks_by_id.get(int(block_id))
        except (TypeError, ValueError):
            block = None
        text = str((block or {}).get("text") or "").strip()
        if text:
            titles.append(text)
    if titles:
        return "\n".join(dict.fromkeys(titles))
    return str(raw.get("title") or raw.get("evidence") or "").strip()


def _normalize_appendix(
    raw: dict[str, Any],
    *,
    document: dict[str, Any],
    index: int,
    output_dir: Path,
    blocks_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    title = _cluster_title(raw, blocks_by_id) or f"商务附件模板{index}"
    docx_path = Path(str(raw.get("docxPath") or raw.get("outputPath") or ""))
    if not docx_path.is_absolute():
        docx_path = output_dir / docx_path
    return {
        "id": f"APPX-{index:04d}",
        "title": title,
        "evidence": title,
        "artifactType": "business_attachment_template",
        "templateType": str(raw.get("templateType") or "business_template"),
        "templateSectionTitle": str(raw.get("templateSectionTitle") or raw.get("regionTitle") or ""),
        "status": "generated",
        "rowCount": int(raw.get("rowCount") or 0),
        "docxPath": str(docx_path),
        "workspacePath": "",
        "sourceDocumentId": str(document.get("id") or ""),
        "sourceDocumentName": str(document.get("name") or ""),
        "sourcePath": str(document.get("sourcePath") or ""),
        "extractionMode": "business_template_extractor_skill",
        "startBlockIndex": raw.get("startBlockIndex"),
        "endBlockIndex": raw.get("endBlockIndex"),
        "quality": raw.get("quality") if isinstance(raw.get("quality"), dict) else {},
    }


def run_from_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    project_id = str(manifest.get("projectId") or "")
    output_dir = Path(str(manifest.get("outputDir") or manifest_path.parent / "business_template_extraction")).resolve()
    documents = manifest.get("documents") if isinstance(manifest.get("documents"), list) else []
    output_dir.mkdir(parents=True, exist_ok=True)

    result = _build_empty_result(project_id, output_dir)
    result["summary"]["documentCount"] = len(documents)

    appendices: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        source = Path(str(document.get("sourcePath") or ""))
        if source.suffix.lower() != ".docx" or not source.is_file():
            continue
        document_output = output_dir / _safe_name(
            str(document.get("id") or source.stem),
            f"document-{len(result['documents']) + 1}",
        )
        try:
            pipeline_result = run_pipeline(source, document_output)
            boundaries_path = document_output / "boundaries.json"
            blocks_path = document_output / "blocks.json"
            boundaries = json.loads(boundaries_path.read_text(encoding="utf-8")) if boundaries_path.is_file() else {"templates": []}
            raw_blocks = json.loads(blocks_path.read_text(encoding="utf-8")) if blocks_path.is_file() else []
            blocks_by_id = {
                int(block["blockId"]): block
                for block in raw_blocks
                if isinstance(block, dict) and isinstance(block.get("blockId"), int)
            }
            result["documents"].append(
                {
                    "id": str(document.get("id") or ""),
                    "name": str(document.get("name") or source.name),
                    "sourcePath": str(source),
                    "outputDir": str(document_output),
                    "summary": pipeline_result.get("summary") or {},
                }
            )
            for raw in boundaries.get("templates") or []:
                if isinstance(raw, dict):
                    appendices.append(
                        _normalize_appendix(
                            raw,
                            document=document,
                            index=len(appendices) + 1,
                            output_dir=document_output,
                            blocks_by_id=blocks_by_id,
                        )
                    )
        except Exception as exc:
            result["warnings"].append(
                {
                    "documentId": str(document.get("id") or ""),
                    "documentName": str(document.get("name") or source.name),
                    "message": f"商务模板提取失败：{exc}",
                }
            )

    result["appendices"] = appendices
    result["summary"]["templateCount"] = len(appendices)
    result["summary"]["warningCount"] = len(result["warnings"])
    _write_json(output_dir / "business_template_extraction.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: run_from_manifest.py <manifest>", file=sys.stderr)
        return 2
    result = run_from_manifest(Path(args[0]).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
