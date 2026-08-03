from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.font_policy import normalize_font_style_overrides


BACKEND_ROOT = Path(__file__).resolve().parents[1]
OPEN_SOURCE_FAMILIES = {
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


def test_legacy_font_names_are_normalized_before_custom_formatting() -> None:
    normalized = normalize_font_style_overrides(
        {
            "bodyZhFont": "等线 Light",
            "tableZhFont": "宋体",
            "bodyEnFont": "Times New Roman",
            "heading1EnFont": "Arial",
            "bodySizePt": 12,
        }
    )

    assert normalized == {
        "bodyZhFont": "Noto Sans CJK SC",
        "tableZhFont": "Noto Serif CJK SC",
        "bodyEnFont": "Liberation Serif",
        "heading1EnFont": "Liberation Sans",
        "bodySizePt": 12,
    }


def test_production_style_specs_only_write_font_pack_families() -> None:
    style_paths = (
        BACKEND_ROOT / "app/document_processing/technical_document/resources/heading_style.json",
        BACKEND_ROOT / "opencode/skills/bid-tech-assembler/references/heading_style.json",
        BACKEND_ROOT / "opencode/skills/bid-business-format-cleaner/references/business_heading_style.json",
        BACKEND_ROOT / "opencode/skills/bid-business-format-cleaner/references/business_toc_style.json",
    )

    for style_path in style_paths:
        style = json.loads(style_path.read_text(encoding="utf-8"))
        assert _declared_families(style)
        assert _declared_families(style) <= OPEN_SOURCE_FAMILIES
