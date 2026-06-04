from __future__ import annotations

import re
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree

from scripts.blank_page_cleaner import clean_blank_edge_pages


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def safe_name(value: str, fallback: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", str(value or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or fallback)[:80]


def _load_docx_state(source_docx: Path) -> dict[str, Any]:
    with zipfile.ZipFile(source_docx, "r") as zf:
        parts = {info.filename: (info, zf.read(info.filename)) for info in zf.infolist()}
    root = etree.fromstring(parts["word/document.xml"][1])
    body = root.find(f"{WORD_NS}body")
    if body is None:
        raise ValueError("DOCX document.xml 缺少 body。")
    return {
        "parts": parts,
        "rootTag": root.tag,
        "rootAttrib": dict(root.attrib),
        "rootNsmap": dict(root.nsmap),
        "rootChildrenBeforeBody": [deepcopy(child) for child in root.iterchildren() if child.tag != f"{WORD_NS}body"],
        "bodyTag": body.tag,
        "bodyAttrib": dict(body.attrib),
        "bodyChildren": list(body.iterchildren()),
        "sectPr": body.find(f"{WORD_NS}sectPr"),
    }


def slice_docx_by_boundaries(
    source_docx: Path,
    blocks: list[dict],
    boundaries: dict,
    output_dir: Path,
) -> dict:
    templates_dir = output_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    state = _load_docx_state(source_docx)
    body_by_block = {int(block["blockId"]): int(block["bodyIndex"]) for block in blocks}
    rendered: list[dict] = []
    for template in boundaries.get("templates") or []:
        start_body = body_by_block[int(template["startBlockId"])]
        end_body = body_by_block[int(template["endBlockId"])]
        filename = f"{template['id']}-{safe_name(template['title'], '商务模板')}.docx"
        target = templates_dir / filename
        _write_slice(state, start_body, end_body, target)
        clean_blank_edge_pages(target)
        item = dict(template)
        item["outputPath"] = str(Path("templates") / filename).replace("\\", "/")
        rendered.append(item)
    return {"templates": rendered}


def _write_slice(state: dict[str, Any], start_body: int, end_body: int, target: Path) -> None:
    new_root = etree.Element(
        state["rootTag"],
        attrib=state["rootAttrib"],
        nsmap=state["rootNsmap"],
    )
    for sibling in state["rootChildrenBeforeBody"]:
        new_root.append(deepcopy(sibling))
    new_body = etree.SubElement(new_root, state["bodyTag"], attrib=state["bodyAttrib"])
    body_children = state["bodyChildren"]
    sect_pr = state["sectPr"]
    sect_pr_tag = f"{WORD_NS}sectPr"
    for index in range(max(0, start_body), min(len(body_children) - 1, end_body) + 1):
        child = body_children[index]
        if child.tag == sect_pr_tag:
            continue
        new_body.append(deepcopy(child))
    if sect_pr is not None:
        new_body.append(deepcopy(sect_pr))
    document_xml = etree.tostring(new_root, xml_declaration=True, encoding="UTF-8", standalone=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for filename, (info, data) in state["parts"].items():
            if filename == "word/document.xml":
                dst.writestr(info, document_xml)
            else:
                dst.writestr(info, data)
