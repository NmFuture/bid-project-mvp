from __future__ import annotations

import zipfile
from copy import deepcopy
from pathlib import Path

from lxml import etree


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CONTENT_TAGS = {
    f"{WORD_NS}drawing",
    f"{WORD_NS}fldSimple",
    f"{WORD_NS}footnoteReference",
    f"{WORD_NS}endnoteReference",
    f"{WORD_NS}instrText",
    f"{WORD_NS}object",
    f"{WORD_NS}pict",
    "{urn:schemas-microsoft-com:vml}shape",
    "{urn:schemas-microsoft-com:vml}imagedata",
}


def clean_blank_edge_pages(docx_path: Path) -> int:
    """Remove blank page carriers from the start and end of a sliced DOCX."""

    docx_path = Path(docx_path)
    with zipfile.ZipFile(docx_path, "r") as src:
        parts = [(info, src.read(info.filename)) for info in src.infolist()]

    document_xml = next((data for info, data in parts if info.filename == "word/document.xml"), None)
    if document_xml is None:
        return 0

    root = etree.fromstring(document_xml)
    body = root.find(f"{WORD_NS}body")
    if body is None:
        return 0

    changes = _clean_body_edges(body)
    if changes <= 0:
        return 0

    cleaned_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    tmp_path = docx_path.with_name(f"{docx_path.name}.tmp")
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in parts:
            if info.filename == "word/document.xml":
                dst.writestr(info, cleaned_xml)
            else:
                dst.writestr(info, data)
    tmp_path.replace(docx_path)
    return changes


def _clean_body_edges(body: etree._Element) -> int:
    changes = 0
    trailing_sect_pr: etree._Element | None = None

    children = _content_children(body)
    leading_blanks = _leading_blank_paragraphs(children)
    first_content = children[len(leading_blanks)] if len(leading_blanks) < len(children) else None
    if leading_blanks and (_has_page_carrier(leading_blanks) or (first_content is not None and _has_page_break_before(first_content))):
        for paragraph in leading_blanks:
            body.remove(paragraph)
            changes += 1

    children = _content_children(body)
    if children and _remove_page_break_before(children[0]):
        changes += 1

    children = _content_children(body)
    trailing_blanks = _trailing_blank_paragraphs(children)
    if trailing_blanks and _has_page_carrier(trailing_blanks):
        for paragraph in trailing_blanks:
            sect_pr = paragraph.find(f".//{WORD_NS}sectPr")
            if sect_pr is not None:
                trailing_sect_pr = deepcopy(sect_pr)
            body.remove(paragraph)
            changes += 1

    if trailing_sect_pr is not None:
        existing_sect_pr = body.find(f"{WORD_NS}sectPr")
        if existing_sect_pr is not None:
            body.remove(existing_sect_pr)
        body.append(trailing_sect_pr)
        changes += 1

    return changes


def _content_children(body: etree._Element) -> list[etree._Element]:
    return [child for child in body.iterchildren() if child.tag != f"{WORD_NS}sectPr"]


def _leading_blank_paragraphs(children: list[etree._Element]) -> list[etree._Element]:
    blanks: list[etree._Element] = []
    for child in children:
        if not _is_blank_paragraph(child):
            break
        blanks.append(child)
    return blanks


def _trailing_blank_paragraphs(children: list[etree._Element]) -> list[etree._Element]:
    blanks: list[etree._Element] = []
    for child in reversed(children):
        if not _is_blank_paragraph(child):
            break
        blanks.append(child)
    blanks.reverse()
    return blanks


def _is_blank_paragraph(element: etree._Element) -> bool:
    if element.tag != f"{WORD_NS}p":
        return False
    if any((node.text or "").strip() for node in element.iter(f"{WORD_NS}t")):
        return False
    return not any(node.tag in CONTENT_TAGS for node in element.iter())


def _has_page_carrier(elements: list[etree._Element]) -> bool:
    return any(
        element.find(f".//{WORD_NS}sectPr") is not None
        or any(_xml_attr(br, "type").lower() == "page" for br in element.iter(f"{WORD_NS}br"))
        or _has_page_break_before(element)
        for element in elements
    )


def _remove_page_break_before(element: etree._Element) -> bool:
    if element.tag != f"{WORD_NS}p":
        return False
    p_pr = element.find(f"{WORD_NS}pPr")
    if p_pr is None:
        return False
    page_break_before = p_pr.find(f"{WORD_NS}pageBreakBefore")
    if page_break_before is None:
        return False
    p_pr.remove(page_break_before)
    return True


def _has_page_break_before(element: etree._Element) -> bool:
    if element.tag != f"{WORD_NS}p":
        return False
    p_pr = element.find(f"{WORD_NS}pPr")
    return p_pr is not None and p_pr.find(f"{WORD_NS}pageBreakBefore") is not None


def _xml_attr(element: etree._Element, name: str) -> str:
    return str(element.get(f"{WORD_NS}{name}") or element.get(name) or "").strip()
