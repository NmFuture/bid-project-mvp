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
    parse_engine: str = "mineru",
    mineru_enabled: bool = True,
    fallback: str = "lightweight",
) -> DocumentParseEngine:
    if parse_engine.strip().lower() == "mineru" and mineru_enabled:
        from app.services.mineru_engine import MineruParseEngine

        return MineruParseEngine(fallback=fallback)
    return DisabledParseEngine("MinerU 解析未启用")
