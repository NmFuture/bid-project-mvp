from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DocumentParseEngine:
    def parse_pdf(self, *, project_id: str, document: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        raise NotImplementedError


class DisabledParseEngine(DocumentParseEngine):
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def parse_pdf(self, *, project_id: str, document: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        _ = project_id
        document_id = str(document.get("id") or "DOC-1")
        quality_dir = output_dir / "document_parse" / "disabled" / document_id
        quality_dir.mkdir(parents=True, exist_ok=True)
        quality_path = quality_dir / "parse_quality.json"
        quality_path.write_text(
            json.dumps(
                {
                    "engine": "disabled",
                    "status": "failed",
                    "fallbackUsed": True,
                    "warnings": [self.reason],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "documentParseEngine": "disabled",
            "status": "failed",
            "fallbackReason": self.reason,
            "parseQualityPath": str(quality_path),
        }


def create_document_parse_engine(
    *,
    parse_engine: str = "docling",
    fallback: str = "none",
    **_: Any,
) -> DocumentParseEngine:
    _ = fallback
    if parse_engine.strip().lower() == "docling":
        from app.services.docling_engine import DoclingParseEngine

        return DoclingParseEngine(fallback=fallback)
    return DisabledParseEngine("Docling 解析未启用")
