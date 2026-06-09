from __future__ import annotations

from scripts.text_rules import is_excluded_format_region_heading, is_format_region_heading, is_major_section_heading


def _is_real_format_region_heading(block: dict) -> bool:
    text = str(block.get("text") or "").strip()
    if not is_format_region_heading(text):
        return False
    style_name = str(block.get("styleName") or "").lower()
    if style_name.startswith("toc"):
        return False
    return bool(
        block.get("isLikelyHeading")
        or block.get("isCentered")
        or block.get("isPageFirstNonEmpty")
        or "heading" in style_name
        or "标题" in style_name
    )


def _is_real_excluded_format_region_heading(block: dict) -> bool:
    text = str(block.get("text") or "").strip()
    if not is_excluded_format_region_heading(text):
        return False
    style_name = str(block.get("styleName") or "").lower()
    if style_name.startswith("toc"):
        return False
    return bool(
        block.get("isLikelyHeading")
        or block.get("isCentered")
        or block.get("isPageFirstNonEmpty")
        or "heading" in style_name
        or "标题" in style_name
    )


def detect_format_regions(blocks: list[dict]) -> list[dict]:
    regions: list[dict] = []
    active: dict | None = None
    for index, block in enumerate(blocks):
        if block.get("type") != "paragraph":
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        if _is_real_format_region_heading(block):
            if active is not None:
                active["endBlockId"] = block["blockId"] - 1
                regions.append(active)
            active = {
                "id": f"REG-{len(regions) + 1:04d}",
                "title": text,
                "startBlockId": block["blockId"],
                "endBlockId": blocks[-1]["blockId"],
            }
            continue
        if active is not None and is_major_section_heading(text) and block["blockId"] > active["startBlockId"]:
            active["endBlockId"] = block["blockId"] - 1
            regions.append(active)
            active = None
    if active is not None:
        regions.append(active)
    return regions


def detect_excluded_format_regions(blocks: list[dict]) -> list[dict]:
    regions: list[dict] = []
    active: dict | None = None
    for block in blocks:
        if block.get("type") != "paragraph":
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        if _is_real_excluded_format_region_heading(block):
            if active is not None:
                active["endBlockId"] = block["blockId"] - 1
                regions.append(active)
            active = {
                "id": f"EXC-{len(regions) + 1:04d}",
                "title": text,
                "startBlockId": block["blockId"],
                "endBlockId": blocks[-1]["blockId"],
                "reason": "不是投标文件格式章节，禁止进入商务模板提取结果。",
            }
            continue
        if active is not None and is_major_section_heading(text) and block["blockId"] > active["startBlockId"]:
            active["endBlockId"] = block["blockId"] - 1
            regions.append(active)
            active = None
    if active is not None:
        regions.append(active)
    return regions
