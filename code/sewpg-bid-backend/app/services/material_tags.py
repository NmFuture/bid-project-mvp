from __future__ import annotations

import json
import re
from typing import Any


MAX_MATERIAL_TAGS = 20
MAX_MATERIAL_TAG_LENGTH = 40


def normalize_material_tags(value: Any) -> list[str]:
    raw_tags = _coerce_tag_values(value)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        tag = re.sub(r"\s+", " ", str(item or "")).strip()
        if not tag:
            continue
        tag = tag[:MAX_MATERIAL_TAG_LENGTH]
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(tag)
        if len(normalized) >= MAX_MATERIAL_TAGS:
            break
    return normalized


def _coerce_tag_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values: list[Any] = []
        for item in value:
            values.extend(_coerce_tag_values(item))
        return values
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                return decoded
        return [part for part in re.split(r"[,，;；\n\r\t]+", text) if part.strip()]
    return [value]
