from __future__ import annotations

from scripts.header_cluster_detector import detect_header_clusters
from scripts.text_rules import clean_text


MIN_STANDALONE_TEXT_LENGTH = 20


def _last_content_block_before(
    blocks_by_id: dict[int, dict],
    start_block_id: int,
    end_exclusive: int,
) -> int:
    last = start_block_id
    for block_id in range(start_block_id, end_exclusive):
        block = blocks_by_id.get(block_id)
        if not block:
            continue
        if block.get("type") == "table" or clean_text(block.get("text")):
            last = block_id
    return last


def _content_text_between(blocks_by_id: dict[int, dict], start_block_id: int, end_block_id: int) -> str:
    return "".join(
        clean_text(blocks_by_id[block_id].get("text"))
        for block_id in range(start_block_id, end_block_id + 1)
        if block_id in blocks_by_id
    )


def _has_table_between(blocks_by_id: dict[int, dict], start_block_id: int, end_block_id: int) -> bool:
    return any(
        blocks_by_id[block_id].get("type") == "table"
        for block_id in range(start_block_id, end_block_id + 1)
        if block_id in blocks_by_id
    )


def _should_skip_container_cluster(
    blocks_by_id: dict[int, dict],
    cluster: dict,
    next_cluster: dict | None,
    content_text: str,
    *,
    start_block_id: int,
    end_block_id: int,
) -> bool:
    if next_cluster is None:
        return False
    signals = set(cluster.get("signals") or [])
    next_signals = set(next_cluster.get("signals") or [])
    if len(content_text) >= MIN_STANDALONE_TEXT_LENGTH:
        return False
    if _has_table_between(blocks_by_id, start_block_id, end_block_id):
        return False
    if "appendix_prefix" not in signals:
        return False
    if {"format_code", "template_word", "sub_table_code", "synthetic_structural_title"} & signals:
        return False
    return bool({"format_code", "sub_table_code", "template_word", "synthetic_structural_title"} & next_signals)


def plan_boundaries(blocks: list[dict], regions: list[dict], anchors: list[dict]) -> dict:
    blocks_by_id = {int(block["blockId"]): block for block in blocks}
    clusters_by_region = detect_header_clusters(blocks, regions, anchors)
    templates: list[dict] = []
    for region in regions:
        clusters = clusters_by_region.get(str(region["id"]), [])
        for index, cluster in enumerate(clusters):
            anchor = cluster["anchor"]
            start_block_id = int(cluster["startBlockId"])
            next_cluster = clusters[index + 1] if index + 1 < len(clusters) else None
            if next_cluster is not None:
                next_start = int(next_cluster["startBlockId"])
                end_block_id = _last_content_block_before(blocks_by_id, start_block_id, next_start)
                next_template_start = next_start
            else:
                end_block_id = _last_content_block_before(
                    blocks_by_id,
                    start_block_id,
                    int(region["endBlockId"]) + 1,
                )
                next_template_start = None
            if end_block_id <= start_block_id:
                continue
            content_text = _content_text_between(blocks_by_id, start_block_id, end_block_id)
            if _should_skip_container_cluster(
                blocks_by_id,
                cluster,
                next_cluster,
                content_text,
                start_block_id=start_block_id,
                end_block_id=end_block_id,
            ):
                continue
            templates.append(
                {
                    "id": f"TPL-{len(templates) + 1:04d}",
                    "title": anchor["text"],
                    "templateType": infer_template_type(anchor["text"]),
                    "regionId": region["id"],
                    "regionTitle": region["title"],
                    "startBlockId": start_block_id,
                    "endBlockId": end_block_id,
                    "anchorBlockId": cluster["anchorBlockId"],
                    "headerBlockIds": cluster["headerBlockIds"],
                    "nextTemplateStartBlockId": next_template_start,
                    "confidence": min(0.98, 0.62 + int(anchor.get("score") or 0) / 200),
                    "decisionSource": cluster.get("decisionSource") or "script_header_cluster",
                    "reason": (
                        "以候选标题簇作为模板起点，以同一格式章节内下一个真实标题簇前的最后一个非空 block "
                        "作为模板终点；该策略先识别附件级标题、表号标题和描述标题的归属关系，再切分正文、表格、说明和尾部字段。"
                    ),
                    "signals": anchor.get("signals") or [],
                }
            )
    return {"templates": templates}


def infer_template_type(title: str) -> str:
    text = str(title or "")
    if "投标函" in text:
        return "bid_letter"
    if "授权" in text:
        return "authorization"
    if "身份证明" in text:
        return "legal_representative_identity"
    if "廉洁" in text:
        return "integrity_commitment"
    if "开标价格" in text:
        return "opening_price"
    if "投标价格" in text or "价格表" in text:
        return "bid_price"
    if "商务" in text and "偏差" in text:
        return "commercial_deviation"
    if "货物规格" in text:
        return "specification"
    if "供货范围" in text:
        return "supply_scope"
    if "保证金" in text or "保函" in text:
        return "bond_or_guarantee"
    if "履约" in text:
        return "performance_bond"
    if "资格" in text:
        return "qualification"
    if "业绩" in text:
        return "performance_table"
    if "财务" in text:
        return "financial"
    if "保密" in text:
        return "confidentiality"
    return "business_template"
