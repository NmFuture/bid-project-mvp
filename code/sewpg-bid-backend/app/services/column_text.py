from __future__ import annotations

from typing import Any

from sqlalchemy import Table


ELLIPSIS = "…"


def varchar_limits(table: Table) -> dict[str, int]:
    """取表中所有定长字符列的长度上限，供入库前截断使用。"""
    return {
        column.name: column.type.length
        for column in table.columns
        if getattr(column.type, "length", None)
    }


def fit_text(value: Any, limit: int | None) -> str:
    """把文本压到列长以内；超长时保留首尾、中间用省略号，避免丢掉路径尾部的文件名。"""
    text = str(value or "")
    if limit is None or len(text) <= limit:
        return text
    head = (limit - 1) * 2 // 3
    tail = limit - 1 - head
    if tail <= 0:
        return text[:limit]
    return f"{text[:head]}{ELLIPSIS}{text[-tail:]}"
