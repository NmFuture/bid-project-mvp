from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_DOCUMENT_FAMILIES = {
    "等线",
    "等线 Light",
    "宋体",
    "Times New Roman",
    "Arial",
}
RUNTIME_FONT_FAMILIES = {
    "Noto Sans CJK SC",
    "Noto Serif CJK SC",
    "Liberation Serif",
    "Liberation Sans",
}


def _declared_families(value: Any) -> set[str]:
    families: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"zh_font", "en_font"} and isinstance(nested, str):
                families.add(nested)
            else:
                families.update(_declared_families(nested))
    elif isinstance(value, list):
        for nested in value:
            families.update(_declared_families(nested))
    return families


def test_production_style_specs_only_write_official_document_families() -> None:
    style_paths = (
        BACKEND_ROOT / "app/document_processing/technical_document/resources/heading_style.json",
        BACKEND_ROOT / "opencode/skills/bid-tech-assembler/references/heading_style.json",
        BACKEND_ROOT / "opencode/skills/bid-business-format-cleaner/references/business_heading_style.json",
        BACKEND_ROOT / "opencode/skills/bid-business-format-cleaner/references/business_toc_style.json",
    )

    for style_path in style_paths:
        style = json.loads(style_path.read_text(encoding="utf-8"))
        families = _declared_families(style)
        assert families
        assert families <= OFFICIAL_DOCUMENT_FAMILIES
        assert families.isdisjoint(RUNTIME_FONT_FAMILIES)
