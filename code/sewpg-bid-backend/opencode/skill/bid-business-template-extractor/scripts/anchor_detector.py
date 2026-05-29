from __future__ import annotations

from scripts.text_rules import looks_like_body_sentence, looks_like_list_item_or_field, title_strength


def _region_for_block(regions: list[dict], block_id: int) -> dict | None:
    for region in regions:
        if int(region["startBlockId"]) <= block_id <= int(region["endBlockId"]):
            return region
    return None


def detect_candidate_anchors(blocks: list[dict], regions: list[dict]) -> list[dict]:
    anchors: list[dict] = []
    for block in blocks:
        if block.get("type") != "paragraph":
            continue
        region = _region_for_block(regions, int(block["blockId"]))
        if region is None or int(block["blockId"]) == int(region["startBlockId"]):
            continue
        text = str(block.get("text") or "").strip()
        score, signals = title_strength(text, block)
        has_template_shape = bool(
            "appendix_prefix" in signals
            or "format_code" in signals
            or "sub_table_code" in signals
            or "letter_prefix_code" in signals
            or "template_word" in signals
            or "structured_business_topic" in signals
            or ("business_topic" in signals and block.get("isLikelyHeading"))
        )
        if not has_template_shape:
            continue
        if looks_like_body_sentence(text):
            continue
        strong_structure = bool(
            block.get("isPageFirstNonEmpty")
            or block.get("isLikelyHeading")
            or "format_code" in signals
            or "sub_table_code" in signals
            or "letter_prefix_code" in signals
            or ("appendix_prefix" in signals and block.get("hasPageBreakAfter"))
        )
        if not strong_structure:
            continue
        if looks_like_list_item_or_field(text) and not (
            block.get("isPageFirstNonEmpty")
            or block.get("isLikelyHeading")
            or "format_code" in signals
            or "letter_prefix_code" in signals
            or block.get("hasPageBreakAfter")
        ):
            continue
        if score < 50:
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
