from __future__ import annotations

import json
import os
import threading
import uuid
import zipfile
from pathlib import Path

from lxml import etree


WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD = f"{{{WORD_NAMESPACE}}}"

MARKER_HIGHLIGHTS = {"yellow", "darkyellow", "green", "brightgreen", "darkgreen"}
MARKER_FILL_COLORS = {"FFF2CC"}
COLOR_CONTENT_PARTS = {"word/document.xml"}
_CLEAN_EXPORT_LOCKS: dict[str, threading.Lock] = {}
_CLEAN_EXPORT_LOCKS_GUARD = threading.Lock()


def clean_export_document_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}-clean{source_path.suffix}")


def _source_metadata_path(target_path: Path) -> Path:
    return target_path.with_suffix(f"{target_path.suffix}.source.json")


def _source_signature(source_path: Path) -> dict[str, int]:
    stat = source_path.stat()
    return {"mtimeNs": stat.st_mtime_ns, "size": stat.st_size}


def _clean_export_lock(source_path: Path) -> threading.Lock:
    key = str(source_path.resolve())
    with _CLEAN_EXPORT_LOCKS_GUARD:
        return _CLEAN_EXPORT_LOCKS.setdefault(key, threading.Lock())


def _read_source_signature(target_path: Path) -> dict[str, int] | None:
    try:
        payload = json.loads(_source_metadata_path(target_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return {"mtimeNs": int(payload["mtimeNs"]), "size": int(payload["size"])}
    except (KeyError, TypeError, ValueError):
        return None


def _write_source_signature(target_path: Path, signature: dict[str, int]) -> None:
    metadata_path = _source_metadata_path(target_path)
    temp_path = metadata_path.with_name(f".{metadata_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(signature, ensure_ascii=True), encoding="utf-8")
        os.replace(temp_path, metadata_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _is_color_content_part(name: str) -> bool:
    return name in COLOR_CONTENT_PARTS


def _normalized_color(value: str | None) -> str:
    return str(value or "").strip().lstrip("#").upper()


def _clean_part_colors(content: bytes) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    root = etree.fromstring(content, parser=parser)
    changed = False

    for highlight in root.iter(f"{WORD}highlight"):
        value = str(highlight.get(f"{WORD}val") or "").strip().lower()
        if value not in MARKER_HIGHLIGHTS:
            continue
        parent = highlight.getparent()
        if parent is not None:
            parent.remove(highlight)
            changed = True

    for shading in root.iter(f"{WORD}shd"):
        fill = _normalized_color(shading.get(f"{WORD}fill"))
        if fill not in MARKER_FILL_COLORS:
            continue
        for attribute in ("fill", "themeFill", "themeFillTint", "themeFillShade"):
            shading.attrib.pop(f"{WORD}{attribute}", None)
        changed = True

    if not changed:
        return content

    declaration = content.lstrip().startswith(b"<?xml")
    header = content[:160]
    standalone = True if b"standalone=\"yes\"" in header or b"standalone='yes'" in header else None
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=declaration,
        standalone=standalone,
    )


def build_clean_export_document(source_path: Path, target_path: Path | None = None) -> Path:
    source = Path(source_path)
    target = Path(target_path) if target_path is not None else clean_export_document_path(source)
    if not source.exists():
        raise FileNotFoundError(f"技术标导出源文件不存在：{source}")
    if source.resolve() == target.resolve():
        raise ValueError("清洁版不能覆盖标记版源文件。")

    target.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(3):
        signature = _source_signature(source)
        temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with zipfile.ZipFile(source, "r") as source_zip, zipfile.ZipFile(temp_path, "w") as target_zip:
                for item in source_zip.infolist():
                    content = source_zip.read(item.filename)
                    if _is_color_content_part(item.filename):
                        content = _clean_part_colors(content)
                    target_zip.writestr(item, content)
            if _source_signature(source) != signature:
                continue
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)

        if _source_signature(source) == signature:
            _write_source_signature(target, signature)
            if _source_signature(source) == signature:
                return target

    raise RuntimeError("技术标源文件在清洁版生成期间持续变化，请稍后重试。")


def ensure_clean_export_document(source_path: Path) -> Path:
    source = Path(source_path)
    with _clean_export_lock(source):
        target = clean_export_document_path(source)
        if target.exists() and _read_source_signature(target) == _source_signature(source):
            return target
        return build_clean_export_document(source, target)
