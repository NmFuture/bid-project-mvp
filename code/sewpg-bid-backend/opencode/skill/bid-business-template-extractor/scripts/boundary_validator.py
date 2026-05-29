from __future__ import annotations

from scripts.text_rules import clean_text


class BoundaryValidationError(ValueError):
    pass


def validate_boundaries(blocks: list[dict], regions: list[dict], boundaries: dict) -> dict:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    regions_by_id = {str(region["id"]): region for region in regions}
    validated: list[dict] = []
    previous_end = 0
    for template in boundaries.get("templates") or []:
        start = int(template["startBlockId"])
        end = int(template["endBlockId"])
        if start not in blocks_by_id or end not in blocks_by_id:
            raise BoundaryValidationError(f"模板 {template.get('id')} 的边界 block 不存在。")
        if end <= start:
            raise BoundaryValidationError(f"模板 {template.get('id')} 的结束位置必须晚于起点。")
        if start <= previous_end:
            raise BoundaryValidationError(f"模板 {template.get('id')} 与前一个模板边界重叠。")
        region = regions_by_id.get(str(template.get("regionId") or ""))
        if region is None:
            raise BoundaryValidationError(f"模板 {template.get('id')} 缺少有效格式章节。")
        if not (int(region["startBlockId"]) <= start <= end <= int(region["endBlockId"])):
            raise BoundaryValidationError(f"模板 {template.get('id')} 超出格式章节范围。")
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
        if len(content_text.replace("\n", "")) < 20 and not (has_table or body_blocks):
            raise BoundaryValidationError(f"模板 {template.get('id')} 内容过少。")
        item = dict(template)
        item["blockCount"] = end - start + 1
        item["preview"] = content_text[:300]
        validated.append(item)
        previous_end = end
    if not validated:
        raise BoundaryValidationError("未生成任何有效模板边界。")
    return {"templates": validated}
