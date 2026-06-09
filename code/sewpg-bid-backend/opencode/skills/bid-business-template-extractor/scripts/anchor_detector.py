from __future__ import annotations

from scripts.text_rules import (
    has_numbering_prefix,
    has_short_heading_shape,
    looks_like_body_sentence,
    looks_like_list_item_or_field,
    title_strength,
)


def _region_for_block(regions: list[dict], block_id: int) -> dict | None:
    for region in regions:
        if int(region["startBlockId"]) <= block_id <= int(region["endBlockId"]):
            return region
    return None


def _has_near_following_table(blocks: list[dict], region: dict, block_id: int, *, limit: int = 4) -> bool:
    region_end = int(region["endBlockId"])
    scanned = 0
    for block in blocks:
        current_id = int(block["blockId"])
        if current_id <= block_id or current_id > region_end:
            continue
        if scanned >= limit:
            return False
        scanned += 1
        if block.get("type") == "table":
            return True
        text = str(block.get("text") or "").strip()
        if text:
            if (
                block.get("hasPageBreakBefore")
                or block.get("isPageFirstNonEmpty")
                or block.get("isLikelyHeading")
                or has_numbering_prefix(text)
            ):
                return False
            continue
    return False


def detect_candidate_anchors(blocks: list[dict], regions: list[dict]) -> list[dict]:
    anchors: list[dict] = []
    for block in blocks:
        if block.get("type") != "paragraph":
            continue
        region = _region_for_block(regions, int(block["blockId"]))
        if region is None or int(block["blockId"]) == int(region["startBlockId"]):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        score, signals = title_strength(text, block)
        has_near_table = _has_near_following_table(blocks, region, int(block["blockId"]))
        has_heading_shape = bool(
            block.get("isLikelyHeading")
            or block.get("isCentered")
            or block.get("isPageFirstNonEmpty")
            or block.get("hasPageBreakBefore")
            or "heading_style" in signals
            or has_numbering_prefix(text)
            or has_short_heading_shape(text)
            or has_near_table
        )
        if not has_heading_shape:
            continue
        if looks_like_body_sentence(text):
            continue
        if looks_like_list_item_or_field(text) and not (
            block.get("isPageFirstNonEmpty")
            or block.get("isLikelyHeading")
            or has_numbering_prefix(text)
            or "format_code" in signals
            or "letter_prefix_code" in signals
            or block.get("hasPageBreakAfter")
        ):
            continue
        if has_numbering_prefix(text) and "numbering_prefix" not in signals:
            signals.append("numbering_prefix")
            score += 18
        if has_short_heading_shape(text) and "short_heading_shape" not in signals:
            signals.append("short_heading_shape")
            score += 12
        if has_near_table and "near_following_table" not in signals:
            signals.append("near_following_table")
            score += 16
        if block.get("hasPageBreakBefore") and "page_break_before" not in signals:
            signals.append("page_break_before")
            score += 10
        if score < 20 and not (has_near_table or has_numbering_prefix(text) or block.get("isLikelyHeading")):
            continue
        anchors.append(
            {
                "id": f"ANC-{len(anchors) + 1:04d}",
                "blockId": block["blockId"],
                "bodyIndex": block["bodyIndex"],
                "text": text,
                "score": score,
                "signals": signals,
                "regionId": region["id"],
                "regionTitle": region["title"],
            }
        )
    return anchors


def write_candidate_windows(
    blocks: list[dict],
    regions: list[dict],
    anchors: list[dict],
    *,
    before: int = 5,
    after: int = 80,
) -> list[dict]:
    by_id = {int(block["blockId"]): block for block in blocks}
    windows: list[dict] = []
    for anchor in anchors:
        block_id = int(anchor["blockId"])
        region = next(region for region in regions if region["id"] == anchor["regionId"])
        start = max(int(region["startBlockId"]), block_id - before)
        end = min(int(region["endBlockId"]), block_id + after)
        window_blocks = [by_id[item] for item in range(start, end + 1) if item in by_id]
        page_breaks = [
            {
                "blockId": block["blockId"],
                "hasPageBreakBefore": block.get("hasPageBreakBefore"),
                "hasPageBreakAfter": block.get("hasPageBreakAfter"),
                "isPageFirstNonEmpty": block.get("isPageFirstNonEmpty"),
            }
            for block in window_blocks
            if block.get("hasPageBreakBefore")
            or block.get("hasPageBreakAfter")
            or block.get("isPageFirstNonEmpty")
        ]
        windows.append(
            {
                "windowId": f"WIN-{len(windows) + 1:04d}",
                "candidateId": anchor.get("candidateId") or anchor.get("id") or "",
                "candidateBlockId": anchor.get("blockId"),
                "regionTitle": anchor["regionTitle"],
                "candidateAnchor": anchor,
                "blocks": window_blocks,
                "pageBreakSignals": page_breaks,
                "agentInstruction": (
                    "判断 candidateAnchor 是否为商务模板片段起点，并在 blocks 中找出该模板片段的结束 block。"
                    "不要只按关键词切断；应识别下一个真实模板标题，保留当前模板的正文、表格、注释、填写说明和尾部字段。"
                ),
            }
        )
    return windows
