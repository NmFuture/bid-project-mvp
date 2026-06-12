#!/usr/bin/env python3
"""读取并扁平化 business_bid_outline.v1 目录。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA = "business_bid_outline.v1"


def load_outline(path: str | Path) -> dict[str, Any]:
    outline_path = Path(path)
    data = json.loads(outline_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("outlineFile 必须是 JSON object")
    schema = data.get("schema_version")
    if schema and schema != SUPPORTED_SCHEMA:
        raise ValueError(f"不支持的 outline schema_version: {schema}")
    return data


def flatten_outline(outline: dict[str, Any]) -> list[dict[str, Any]]:
    """递归读取 sections/children，输出 id/title/number/level 顺序列表。"""
    items: list[dict[str, Any]] = []

    def visit(nodes: Any, inherited_level: int = 1) -> None:
        if not isinstance(nodes, list):
            return
        for index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                continue
            title = str(node.get("title") or "").strip()
            if not title:
                visit(node.get("children"), inherited_level + 1)
                continue
            level = _coerce_level(node.get("level"), inherited_level)
            items.append(
                {
                    "id": str(node.get("id") or f"outline-{len(items) + 1:04d}"),
                    "title": title,
                    "number": str(node.get("number") or "").strip(),
                    "level": level,
                    "order": len(items) + 1,
                    "source_index": index,
                }
            )
            visit(node.get("children"), level + 1)

    visit(outline.get("sections"), 1)
    return items


def _coerce_level(value: Any, default: int) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = default
    return max(1, min(level, 9))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="扁平化 business_bid_outline.v1 目录")
    parser.add_argument("outline_file")
    args = parser.parse_args(argv)

    items = flatten_outline(load_outline(args.outline_file))
    print(json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
