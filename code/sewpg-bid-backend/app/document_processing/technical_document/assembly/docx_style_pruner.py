"""删除 DOCX 中未被使用的样式，避免超大样式表拖慢 python-docx。"""

from __future__ import annotations

from collections.abc import Iterable

from docx.oxml import parse_xml
from docx.oxml.ns import qn


_STYLE_REFERENCE_TAGS = (
    "w:pStyle",
    "w:rStyle",
    "w:tblStyle",
)
_STYLE_DEPENDENCY_TAGS = _STYLE_REFERENCE_TAGS + (
    "w:basedOn",
    "w:next",
    "w:link",
)
_PIPELINE_STYLE_NAMES = {
    "normal",
    "正文",
    "toc heading",
    "目录标题",
    *(f"heading {level}" for level in range(1, 10)),
    *(f"标题 {level}" for level in range(1, 10)),
}
_PIPELINE_STYLE_IDS = {
    "Normal",
    "TOC",
    *(f"Heading{level}" for level in range(1, 10)),
}


def _xml_roots(doc) -> Iterable:
    styles_part = doc.part.styles
    for part in doc.part.package.iter_parts():
        if part is styles_part:
            continue
        element = getattr(part, "element", None)
        if element is not None:
            yield element
            continue
        content_type = str(getattr(part, "content_type", "") or "")
        if not (content_type.endswith("+xml") or content_type.endswith("/xml")):
            continue
        try:
            yield parse_xml(part.blob)
        except (TypeError, ValueError):
            continue


def _referenced_style_ids(doc) -> set[str]:
    referenced: set[str] = set()
    for root in _xml_roots(doc):
        for tag in _STYLE_REFERENCE_TAGS:
            for element in root.iter(qn(tag)):
                style_id = element.get(qn("w:val"))
                if style_id:
                    referenced.add(style_id)
    return referenced


def _style_name(style) -> str:
    name = style.find(qn("w:name"))
    return str(name.get(qn("w:val")) or "") if name is not None else ""


def prune_unused_styles(doc) -> dict[str, int]:
    """保留所有实际引用、依赖、默认及流水线必需样式，删除其余样式。"""
    styles_root = doc.styles.element
    styles = list(styles_root.findall(qn("w:style")))
    styles_by_id = {
        style_id: style
        for style in styles
        if (style_id := style.get(qn("w:styleId")))
    }
    retained = _referenced_style_ids(doc)
    for style_id, style in styles_by_id.items():
        name = _style_name(style).casefold()
        if (
            style.get(qn("w:default")) in {"1", "true", "on"}
            or style_id in _PIPELINE_STYLE_IDS
            or name in _PIPELINE_STYLE_NAMES
        ):
            retained.add(style_id)

    pending = list(retained)
    while pending:
        style = styles_by_id.get(pending.pop())
        if style is None:
            continue
        for tag in _STYLE_DEPENDENCY_TAGS:
            for dependency in style.iter(qn(tag)):
                dependency_id = dependency.get(qn("w:val"))
                if dependency_id and dependency_id not in retained:
                    retained.add(dependency_id)
                    pending.append(dependency_id)

    removed = 0
    for style_id, style in styles_by_id.items():
        if style_id in retained:
            continue
        styles_root.remove(style)
        removed += 1

    return {
        "before": len(styles),
        "after": len(styles) - removed,
        "removed": removed,
    }
