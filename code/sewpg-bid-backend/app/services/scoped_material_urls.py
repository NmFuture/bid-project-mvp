from __future__ import annotations

from typing import Any

INTERNAL_RAW_URL_PREFIX = "__scoped_material_raw__"
INTERNAL_WIKI_URL_PREFIX = "__scoped_material_wiki__"


def rewrite_material_urls(payload: Any, *, raw_prefix: str, wiki_prefix: str) -> Any:
    if isinstance(payload, dict):
        return {
            key: rewrite_material_urls(value, raw_prefix=raw_prefix, wiki_prefix=wiki_prefix)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [rewrite_material_urls(item, raw_prefix=raw_prefix, wiki_prefix=wiki_prefix) for item in payload]
    if isinstance(payload, str):
        return (
            payload.replace(INTERNAL_RAW_URL_PREFIX, raw_prefix)
            .replace(INTERNAL_WIKI_URL_PREFIX, wiki_prefix)
        )
    return payload
