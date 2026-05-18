from __future__ import annotations

import re
from pathlib import PurePosixPath


_UNSAFE_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
_WHITESPACE = re.compile(r"\s+")


def short_filename(value: str | None, fallback: str = "file.bin", *, max_bytes: int = 128) -> str:
    """Return a safe filename that fits within a UTF-8 byte budget.

    MinIO/S3 object keys can technically contain most characters, but keeping the
    filename segment short and path-safe prevents accidental nested keys and
    avoids oversized object names when source files use long Chinese titles.
    """

    safe_fallback = _sanitize_filename(fallback) or "file.bin"
    safe_name = _sanitize_filename(value) or safe_fallback
    if max_bytes <= 0:
        return safe_fallback
    if _byte_len(safe_name) <= max_bytes:
        return safe_name

    suffix = PurePosixPath(safe_name).suffix
    stem = safe_name[: -len(suffix)] if suffix else safe_name
    if suffix and _byte_len(suffix) >= max_bytes:
        suffix = ""
        stem = safe_name

    budget = max_bytes - _byte_len(suffix)
    trimmed_stem = _trim_utf8_bytes(stem, budget).strip(" .-_")
    if not trimmed_stem:
        fallback_stem = PurePosixPath(safe_fallback).stem or "file"
        trimmed_stem = _trim_utf8_bytes(fallback_stem, budget).strip(" .-_") or "file"
    return f"{trimmed_stem}{suffix}"


def _sanitize_filename(value: str | None) -> str:
    text = str(value or "").replace("\\", "/")
    text = PurePosixPath(text).name
    text = _UNSAFE_FILENAME_CHARS.sub("-", text)
    text = _WHITESPACE.sub(" ", text).strip(" .")
    return text


def _byte_len(value: str) -> int:
    return len(value.encode("utf-8"))


def _trim_utf8_bytes(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    output: list[str] = []
    total = 0
    for char in value:
        size = _byte_len(char)
        if total + size > max_bytes:
            break
        output.append(char)
        total += size
    return "".join(output)
