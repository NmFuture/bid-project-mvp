from __future__ import annotations

from scripts.text_rules import clean_text, is_catalog_heading


class BoundaryValidationError(ValueError):
    pass


def _has_catalog_contamination(content_blocks: list[dict]) -> bool:
    return any(
        block.get("type") != "table" and is_catalog_heading(clean_text(block.get("text")))
        for block in content_blocks
    )


def _rejected_template(template: dict, code: str, reason: str) -> dict:
    return {
        "candidateId": template.get("candidateId"),
        "candidateBlockId": template.get("candidateBlockId") or template.get("anchorBlockId"),
        "templateTitle": template.get("title") or template.get("templateTitle"),
        "startBlockId": template.get("startBlockId"),
        "endBlockId": template.get("endBlockId"),
        "confidence": template.get("confidence"),
        "rejectCode": code,
        "rejectReason": reason,
        "decisionSource": template.get("decisionSource") or "script",
    }


def validate_boundaries(
    blocks: list[dict],
    regions: list[dict],
    boundaries: dict,
    *,
    min_confidence: float = 0.75,
    reject_low_confidence: bool = False,
    strict: bool = True,
    raise_on_empty: bool = True,
) -> dict:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    regions_by_id = {str(region["id"]): region for region in regions}
    validated: list[dict] = []
    rejected: list[dict] = []
    previous_end = 0

    def reject(template: dict, code: str, reason: str) -> None:
        if strict:
            raise BoundaryValidationError(reason)
        rejected.append(_rejected_template(template, code, reason))

    def template_order(template: dict) -> tuple[int, int]:
        try:
            return int(template.get("startBlockId")), int(template.get("endBlockId"))
        except (TypeError, ValueError):
            return 10**9, 10**9

    for template in sorted(boundaries.get("templates") or [], key=template_order):
        try:
            start = int(template["startBlockId"])
            end = int(template["endBlockId"])
        except (KeyError, TypeError, ValueError):
            reject(template, "invalid_boundary", f"模板 {template.get('id')} 缺少有效起止 block。")
            continue
        if start not in blocks_by_id or end not in blocks_by_id:
            reject(template, "missing_block", f"模板 {template.get('id')} 的边界 block 不存在。")
            continue
        if end < start:
            reject(template, "invalid_boundary", f"模板 {template.get('id')} 的结束位置不得早于起点。")
            continue
        if start <= previous_end:
            reject(template, "overlap", f"模板 {template.get('id')} 与前一个模板边界重叠。")
            continue
        region = regions_by_id.get(str(template.get("regionId") or ""))
        if region is None:
            reject(template, "outside_format_region", f"模板 {template.get('id')} 缺少有效格式章节。")
            continue
        if not (int(region["startBlockId"]) <= start <= end <= int(region["endBlockId"])):
            reject(template, "outside_format_region", f"模板 {template.get('id')} 超出格式章节范围。")
            continue
        confidence = template.get("confidence")
        if reject_low_confidence and isinstance(confidence, (int, float)) and float(confidence) < min_confidence:
            rejected.append(
                _rejected_template(
                    template,
                    "low_confidence",
                    f"低置信度模板进入 review，不生成正式模板：confidence={float(confidence):.2f}。",
                )
            )
            continue
        if reject_low_confidence and bool(template.get("needsReview")):
            rejected.append(
                _rejected_template(
                    template,
                    "needs_review",
                    "agent 标记 needsReview，进入 review，不生成正式模板。",
                )
            )
            continue
        content_blocks = [
            blocks_by_id[block_id]
            for block_id in range(start, end + 1)
            if block_id in blocks_by_id
        ]
        content_text = "\n".join(clean_text(block.get("text")) for block in content_blocks)
        body_blocks = [
            block
            for block in content_blocks[1:]
            if block.get("type") == "table" or clean_text(block.get("text"))
        ]
        has_table = any(block.get("type") == "table" for block in content_blocks)
        if end > start and len(content_text.replace("\n", "")) < 20 and not (has_table or body_blocks):
            rejected.append(_rejected_template(template, "empty_template", "标题后缺少正文、表格、填写字段或签章栏。"))
            continue
        if _has_catalog_contamination(content_blocks):
            rejected.append(_rejected_template(template, "catalog_contamination", "模板边界包含目录标题或目录污染。"))
            continue
        item = dict(template)
        item["blockCount"] = end - start + 1
        item["preview"] = content_text[:300]
        validated.append(item)
        previous_end = end
    if not validated and raise_on_empty:
        raise BoundaryValidationError("未生成任何有效模板边界。")
    return {"templates": validated, "rejectedTemplates": rejected}
