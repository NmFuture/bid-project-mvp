from __future__ import annotations

import re
from typing import Any

from scripts.text_rules import clean_text, has_business_topic, looks_like_body_sentence, looks_like_list_item_or_field, title_strength


MAX_PREFIX_LOOKBACK_BLOCKS = 4

APPENDIX_CODE_RE = re.compile(r"^(特殊)?附件\s*([0-9]+[A-Z]?)", re.IGNORECASE)
TABLE_HEADING_CODE_RE = re.compile(r"^表\s*([0-9]+)\s*([A-Z](?:-\d+)?)", re.IGNORECASE)
NUMBERED_TABLE_CODE_RE = re.compile(r"^([0-9]+[A-Z])(?:-(\d+))?\s*表?", re.IGNORECASE)
LETTER_PREFIX_CODE_RE = re.compile(r"^([A-Z](?:-\d+)?)(?=\s|\(|（|[\u4e00-\u9fff])", re.IGNORECASE)


def detect_header_clusters(blocks: list[dict], regions: list[dict], anchors: list[dict]) -> dict[str, list[dict]]:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    anchors_by_region = _anchors_by_region(anchors)
    synthetic_by_region = _synthetic_anchors_by_region(blocks, regions, anchors)
    clusters_by_region: dict[str, list[dict]] = {}

    for region in regions:
        region_id = str(region["id"])
        region_anchors = anchors_by_region.get(region_id, []) + synthetic_by_region.get(region_id, [])
        region_anchors.sort(key=lambda item: (int(item["blockId"]), 0 if item.get("source") == "script" else 1))
        region_anchors = _dedupe_anchors(region_anchors)
        raw_clusters = [_cluster_for_anchor(blocks_by_id, anchor) for anchor in region_anchors]
        prefix_block_ids = {
            block_id
            for cluster in raw_clusters
            for block_id in cluster["headerBlockIds"]
            if int(block_id) != int(cluster["anchorBlockId"])
        }
        clusters = [
            cluster
            for cluster in raw_clusters
            if int(cluster["anchorBlockId"]) not in prefix_block_ids
        ]
        clusters.sort(key=lambda item: (int(item["startBlockId"]), int(item["anchorBlockId"])))
        clusters_by_region[region_id] = clusters

    return clusters_by_region


def heading_code(text: str) -> dict[str, str]:
    normalized = clean_text(text).replace("　", " ")
    compact = re.sub(r"\s+", "", normalized)
    result: dict[str, str] = {}

    appendix_match = APPENDIX_CODE_RE.match(normalized)
    if appendix_match:
        result["appendix"] = appendix_match.group(2).upper()
        if appendix_match.group(1):
            result["specialAppendix"] = result["appendix"]

    table_match = TABLE_HEADING_CODE_RE.match(normalized)
    if table_match:
        result["tableNumber"] = table_match.group(1).upper()
        result["tableSuffix"] = table_match.group(2).upper()

    numbered_match = NUMBERED_TABLE_CODE_RE.match(compact)
    if numbered_match:
        result["numberedGroup"] = numbered_match.group(1).upper()
        if numbered_match.group(2):
            result["numberedFull"] = f"{numbered_match.group(1)}-{numbered_match.group(2)}".upper()
        else:
            result["numberedFull"] = numbered_match.group(1).upper()

    letter_match = LETTER_PREFIX_CODE_RE.match(normalized)
    if letter_match:
        result["letterPrefix"] = letter_match.group(1).upper()

    if has_business_topic(compact) and compact.endswith(("函", "表", "书", "文件")) and len(compact) <= 36:
        result["businessDocumentTitle"] = "1"

    return result


def _anchors_by_region(anchors: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for anchor in anchors:
        item = dict(anchor)
        item.setdefault("source", "script")
        grouped.setdefault(str(anchor["regionId"]), []).append(item)
    return grouped


def _synthetic_anchors_by_region(blocks: list[dict], regions: list[dict], anchors: list[dict]) -> dict[str, list[dict]]:
    known_block_ids = {int(anchor["blockId"]) for anchor in anchors}
    grouped: dict[str, list[dict]] = {}
    for region in regions:
        for block in blocks:
            block_id = int(block["blockId"])
            if block_id in known_block_ids:
                continue
            if block.get("type") != "paragraph":
                continue
            if not (int(region["startBlockId"]) <= block_id <= int(region["endBlockId"])):
                continue
            if not _is_synthetic_anchor(block, blocks, region):
                continue
            text = clean_text(block.get("text"))
            score, signals = title_strength(text, block)
            grouped.setdefault(str(region["id"]), []).append(
                {
                    "id": f"SYN-{block_id:04d}",
                    "blockId": block["blockId"],
                    "bodyIndex": block["bodyIndex"],
                    "text": text,
                    "score": max(score, 55),
                    "signals": sorted(set(signals + ["synthetic_structural_title"])),
                    "regionId": region["id"],
                    "regionTitle": region["title"],
                    "source": "synthetic",
                }
            )
    return grouped


def _is_synthetic_anchor(block: dict, blocks: list[dict], region: dict) -> bool:
    text = clean_text(block.get("text"))
    if not text or len(text.replace(" ", "")) > 80:
        return False
    if looks_like_body_sentence(text) or looks_like_list_item_or_field(text):
        return False
    code = heading_code(text)
    if "appendix" in code:
        if bool(
            block.get("isPageFirstNonEmpty")
            or block.get("hasPageBreakBefore")
            or block.get("hasPageBreakAfter")
            or block.get("isLikelyHeading")
        ):
            return True
        return _has_standalone_container_shape(blocks, region, int(block["blockId"]), code)
    if "numberedGroup" in code:
        return bool(block.get("isLikelyHeading") or block.get("isCentered"))
    return False


def _dedupe_anchors(anchors: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[int] = set()
    for anchor in anchors:
        block_id = int(anchor["blockId"])
        if block_id in seen:
            continue
        seen.add(block_id)
        result.append(anchor)
    return result


def _cluster_for_anchor(blocks_by_id: dict[int, dict], anchor: dict) -> dict:
    anchor_block_id = int(anchor["blockId"])
    prefix_ids = _matching_prefix_block_ids(blocks_by_id, anchor_block_id)
    header_block_ids = sorted(set(prefix_ids + [anchor_block_id]))
    start_block_id = min(header_block_ids)
    return {
        "startBlockId": start_block_id,
        "anchorBlockId": anchor_block_id,
        "headerBlockIds": header_block_ids,
        "title": anchor["text"],
        "templateTypeTitle": anchor["text"],
        "anchor": anchor,
        "signals": anchor.get("signals") or [],
        "decisionSource": "script_header_cluster" if start_block_id != anchor_block_id else "script_anchor_sequence",
    }


def _matching_prefix_block_ids(blocks_by_id: dict[int, dict], anchor_block_id: int) -> list[int]:
    anchor_block = blocks_by_id[anchor_block_id]
    anchor_code = heading_code(anchor_block.get("text") or "")
    prefix_ids: list[int] = []
    current_code = anchor_code
    for block_id in range(anchor_block_id - 1, max(0, anchor_block_id - MAX_PREFIX_LOOKBACK_BLOCKS) - 1, -1):
        block = blocks_by_id.get(block_id)
        if not block or block.get("type") == "table":
            break
        text = clean_text(block.get("text"))
        if not text:
            continue
        if _is_compatible_prefix(block, current_code):
            prefix_ids.append(block_id)
            current_code = heading_code(text)
            continue
        if _is_structural_separator(block):
            continue
        if prefix_ids:
            break
    return prefix_ids


def _is_compatible_prefix(block: dict, anchor_code: dict[str, str]) -> bool:
    text = clean_text(block.get("text"))
    if not text or len(text.replace(" ", "")) > 80:
        return False
    if looks_like_list_item_or_field(text):
        return False
    prefix_code = heading_code(text)
    if not prefix_code:
        return False
    if not _codes_are_compatible(prefix_code, anchor_code):
        return False
    return bool(
        block.get("isPageFirstNonEmpty")
        or block.get("hasPageBreakBefore")
        or block.get("hasPageBreakAfter")
        or block.get("isLikelyHeading")
        or "appendix" in prefix_code
        or "letterPrefix" in prefix_code
    )


def _codes_are_compatible(prefix_code: dict[str, str], anchor_code: dict[str, str]) -> bool:
    if prefix_code.get("letterPrefix") and anchor_code.get("tableSuffix"):
        return _prefix_code_matches(prefix_code["letterPrefix"], anchor_code["tableSuffix"])
    if prefix_code.get("letterPrefix") and anchor_code.get("letterPrefix"):
        return _prefix_code_matches(prefix_code["letterPrefix"], anchor_code["letterPrefix"])
    if prefix_code.get("appendix") and anchor_code.get("tableNumber"):
        return prefix_code["appendix"] == anchor_code["tableNumber"]
    if prefix_code.get("appendix") and anchor_code.get("numberedGroup"):
        return _prefix_code_matches(prefix_code["appendix"], anchor_code["numberedGroup"])
    if prefix_code.get("appendix") and anchor_code.get("numberedFull"):
        return _prefix_code_matches(prefix_code["appendix"], anchor_code["numberedFull"])
    if prefix_code.get("appendix") and anchor_code.get("letterPrefix"):
        return True
    if prefix_code.get("specialAppendix") and anchor_code.get("businessDocumentTitle"):
        return True
    if prefix_code.get("specialAppendix") and not anchor_code:
        return True
    return False


def _prefix_code_matches(parent_code: str, child_code: str) -> bool:
    parent = parent_code.upper()
    child = child_code.upper()
    return child == parent or child.startswith(f"{parent}-")


def _is_structural_separator(block: dict) -> bool:
    return not clean_text(block.get("text")) and (
        block.get("hasPageBreakBefore") or block.get("hasPageBreakAfter")
    )


def _has_standalone_container_shape(blocks: list[dict], region: dict, block_id: int, code: dict[str, str]) -> bool:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    previous_id = _previous_content_block_id(blocks, region, block_id)
    next_id = _next_content_block_id(blocks, region, block_id)
    if previous_id is None or next_id is None:
        return False
    previous_block = blocks_by_id[previous_id]
    next_block = blocks_by_id[next_id]
    previous_text = clean_text(previous_block.get("text"))
    next_text = clean_text(next_block.get("text"))
    if not previous_text or not next_text:
        return False
    if heading_code(next_text).get("appendix") == code.get("appendix"):
        return False
    if not _looks_like_template_tail(previous_text, previous_block):
        return False
    return _next_blocks_reference_child_appendices(blocks, region, block_id, code["appendix"])


def _previous_content_block_id(blocks: list[dict], region: dict, block_id: int) -> int | None:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    region_start = int(region["startBlockId"])
    for candidate in range(block_id - 1, region_start - 1, -1):
        block = blocks_by_id.get(candidate)
        if block is None:
            continue
        if block.get("type") == "table" or clean_text(block.get("text")):
            return candidate
    return None


def _next_content_block_id(blocks: list[dict], region: dict, block_id: int) -> int | None:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    region_end = int(region["endBlockId"])
    for candidate in range(block_id + 1, region_end + 1):
        block = blocks_by_id.get(candidate)
        if block is None:
            continue
        if block.get("type") == "table" or clean_text(block.get("text")):
            return candidate
    return None


def _looks_like_template_tail(text: str, block: dict) -> bool:
    if block.get("type") == "table":
        return True
    compact = re.sub(r"\s+", "", text)
    return bool(
        text.endswith(("：", ":"))
        or compact.startswith("日期")
        or compact.endswith(("签字", "签字：", "签字:"))
    )


def _next_blocks_reference_child_appendices(blocks: list[dict], region: dict, block_id: int, appendix_code: str) -> bool:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    region_end = int(region["endBlockId"])
    pattern = re.compile(rf"附件\s*{re.escape(appendix_code)}[A-Z]", re.IGNORECASE)
    for candidate in range(block_id + 1, min(region_end, block_id + 14) + 1):
        block = blocks_by_id.get(candidate)
        if block is None:
            continue
        text = clean_text(block.get("text"))
        if not text:
            continue
        if pattern.search(text):
            return True
    return False
