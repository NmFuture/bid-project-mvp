from __future__ import annotations

from typing import Any


FONT_FAMILY_ALIASES = {
    "等线": "Noto Sans CJK SC",
    "等线 Light": "Noto Sans CJK SC",
    "微软雅黑": "Noto Sans CJK SC",
    "黑体": "Noto Sans CJK SC",
    "宋体": "Noto Serif CJK SC",
    "SimSun": "Noto Serif CJK SC",
    "NSimSun": "Noto Serif CJK SC",
    "Times New Roman": "Liberation Serif",
    "Arial": "Liberation Sans",
}


def normalize_font_family(value: str) -> str:
    family = value.strip()
    return FONT_FAMILY_ALIASES.get(family, family)


def normalize_font_style_overrides(overrides: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(overrides or {})
    for key, value in normalized.items():
        if key.endswith("Font") and isinstance(value, str):
            normalized[key] = normalize_font_family(value)
    return normalized
