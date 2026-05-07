import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BODY_TEXT_LIMIT = 12000
MAX_UNBOUNDED_BLOCKS = 220


ATTACHED_MATERIAL_RE = re.compile(
    r"(后附|应附|须附|随附|须提供|应提供|需提供|提交|提供.{0,30}?(复印件|扫描件|证明材料|证书|截图|合同|报告)|附.{0,30}?(证书|截图|合同|报告|复印件|扫描件|证明材料))"
)
RULE_LIKE_RE = re.compile(r"(报价唯一|否则否决|否决投标|签字盖章|签字|盖章|不得偏离|评分|得分|扣分|无效投标)")
MATERIAL_WORD_RE = re.compile(r"(表|函|书|证明|材料|证书|执照|许可|承诺|声明|授权|业绩|财务|报告|清单|报价|摘要|复印件|扫描件|截图|合同)")

EXPLICIT_PATTERNS = [
    r"^[A-Z](?:\s+|[、．.])\S+",
    r"^[A-Z]-\d+(?:\s+|[、．.])\S+",
    r"^\d+[A-Z](?:[-－]?\d+)?(?:表)?(?:\s+|[、．.]|\S)",
    r"^\d+(?:\.\d+)+(?:\s+|[、．.])\S+",
    r"^表\s*\d+\s*[A-Z](?:[-－]?\d+)?(?:\s+|[、．.]|\S)",
    r"^[一二三四五六七八九十]+[、．.]\s*\S+",
    r"^[（(][一二三四五六七八九十]+[）)]\s*\S+",
    r"^[（(]\d+[）)]\s*\S+",
    r"^附件\s*\d+[A-Z]?(?:[-－]?\d+)?(?:\s+|[、．.]|\S)",
]
TABLE_TITLE_PATTERNS = [
    r"^\d+[A-Z](?:[-－]?\d+)?\s*表\s*\S*",
    r"^\d+[A-Z](?:[-－]?\d+)?表\s*\S+",
    r"^表\s*\d+\s*[A-Z](?:[-－]?\d+)?\s*\S*",
]


def normalize(text):
    return re.sub(r"\s+", "", text or "").lower()


def compact_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def load_data(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def block_number(block_id):
    match = re.search(r"(\d+)$", block_id or "")
    return int(match.group(1)) if match else 0


def make_block_index(blocks):
    return {block.get("block_id"): index for index, block in enumerate(blocks)}


def text_similarity(a, b):
    a_norm = normalize(a)
    b_norm = normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm in b_norm or b_norm in a_norm:
        return 1.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def find_best_block(blocks, text=None, section_id=None, block_id=None):
    if block_id:
        for index, block in enumerate(blocks):
            if block.get("block_id") == block_id:
                return index, block, 1.0
        raise SystemExit(f"ERROR: start block not found: {block_id}")
    if section_id:
        for index, block in enumerate(blocks):
            if block.get("section_id") == section_id:
                return index, block, 1.0
    if not text:
        raise SystemExit("ERROR: provide --parent-source-text, --parent-title, --parent-section-id, or --start-block-id")
    scored = []
    for index, block in enumerate(blocks):
        if block.get("table_id") and block.get("type") != "table_row":
            continue
        score = text_similarity(text, block.get("text", ""))
        if score:
            if block.get("heading_level"):
                score += 0.08
            if block.get("type") == "paragraph":
                score += 0.04
            scored.append((score, index, block))
    if not scored:
        raise SystemExit(f"ERROR: parent text not found: {text}")
    score, index, block = max(scored, key=lambda item: item[0])
    if score < 0.45:
        raise SystemExit(f"ERROR: parent text match too weak: {text}")
    return index, block, score


def find_next_sibling_index(blocks, start_index, next_text=None, end_before_block_id=None):
    if end_before_block_id:
        for index, block in enumerate(blocks):
            if block.get("block_id") == end_before_block_id:
                return index
        raise SystemExit(f"ERROR: end-before block not found: {end_before_block_id}")
    if not next_text:
        return None
    candidates = []
    for index in range(start_index + 1, len(blocks)):
        block = blocks[index]
        if block.get("table_id") and block.get("type") != "table_row":
            continue
        score = text_similarity(next_text, block.get("text", ""))
        if score:
            if block.get("heading_level"):
                score += 0.08
            if block.get("type") == "paragraph":
                score += 0.04
            candidates.append((score, index))
    if not candidates:
        return None
    score, index = max(candidates, key=lambda item: item[0])
    return index if score >= 0.45 else None


def same_or_child_heading_path(block, parent_heading_path):
    path = block.get("heading_path") or []
    if not parent_heading_path:
        return True
    return path[: len(parent_heading_path)] == parent_heading_path or path == parent_heading_path[:-1]


def infer_heading_boundary(blocks, start_index, parent_block):
    parent_level = parent_block.get("heading_level")
    if not parent_level:
        return None
    parent_path = parent_block.get("heading_path") or []
    for index in range(start_index + 1, len(blocks)):
        block = blocks[index]
        level = block.get("heading_level")
        if level is not None and level <= parent_level and not same_or_child_heading_path(block, parent_path):
            return index
    return None


def likely_major_boundary(block, parent_block):
    text = compact_text(block.get("text", ""))
    if block.get("table_id") or len(text) > 80:
        return False
    parent_text = parent_block.get("text", "")
    if re.match(r"^附件\s*\d+[A-Z]?(?:[-－]?\d+)?(?:\s+|[、．.]|\S)", text) and text_similarity(text, parent_text) < 0.8:
        return True
    if re.match(r"^\d+[A-Z](?:[-－]?\d+)?\s*表\s*\S+", text) and text_similarity(text, parent_text) < 0.8:
        return True
    return False


def infer_structural_boundary(blocks, start_index, parent_block):
    parent_path = parent_block.get("heading_path") or []
    for index in range(start_index + 1, min(len(blocks), start_index + MAX_UNBOUNDED_BLOCKS + 1)):
        block = blocks[index]
        if parent_path and block.get("heading_path") and not same_or_child_heading_path(block, parent_path):
            return index
        if likely_major_boundary(block, parent_block):
            return index
    return None


def determine_scope(blocks, args):
    parent_text = args.parent_source_text or args.parent_title
    start_index, parent_block, parent_score = find_best_block(
        blocks,
        text=parent_text,
        section_id=args.parent_section_id,
        block_id=args.start_block_id,
    )
    warnings = []
    end_before = find_next_sibling_index(blocks, start_index, args.next_sibling_source_text, args.end_before_block_id)
    boundary_reason = "next_sibling_source_text" if end_before is not None else None
    if end_before is None:
        end_before = infer_heading_boundary(blocks, start_index, parent_block)
        boundary_reason = "heading_level" if end_before is not None else None
    if end_before is None:
        end_before = infer_structural_boundary(blocks, start_index, parent_block)
        boundary_reason = "structural_hint" if end_before is not None else None
    if end_before is None:
        warnings.append("无法确定下一个同级边界；已按有限后续块扩大父章节范围，避免依赖输出窗口。")
        end_before = min(len(blocks), start_index + MAX_UNBOUNDED_BLOCKS + 1)
        boundary_reason = "bounded_fallback"
    if end_before <= start_index:
        end_before = start_index + 1
    selected = blocks[start_index:end_before]
    return selected, parent_block, parent_score, boundary_reason, warnings


def explicit_level(text):
    stripped = compact_text(text)
    if re.match(r"^[A-Z]-\d+", stripped):
        return 3
    if re.match(r"^\d+[A-Z][-－]\d+", stripped):
        return 3
    if re.match(r"^\d+(?:\.\d+)+", stripped):
        return 3
    if re.match(r"^[（(](?:\d+|[一二三四五六七八九十]+)[）)]", stripped):
        return 3
    return 2


def is_explicit_numbered_heading(text):
    stripped = compact_text(text)
    if len(stripped) > 120:
        return False
    return any(re.match(pattern, stripped) for pattern in EXPLICIT_PATTERNS)


def is_table_title(text):
    stripped = compact_text(text)
    if len(stripped) > 100:
        return False
    return any(re.match(pattern, stripped) for pattern in TABLE_TITLE_PATTERNS)


def is_style_heading(block, next_block=None):
    text = compact_text(block.get("text", ""))
    if block.get("table_id") or not text or len(text) > 40:
        return False
    if is_explicit_numbered_heading(text) or is_table_title(text):
        return False
    if block.get("heading_level") and MATERIAL_WORD_RE.search(text):
        return True
    style = block.get("style", "")
    if style and re.search(r"heading|标题|title", style, re.I) and MATERIAL_WORD_RE.search(text):
        return True
    if MATERIAL_WORD_RE.search(text) and not RULE_LIKE_RE.search(text):
        if next_block and next_block.get("table_id"):
            return True
        return text.endswith(("表", "函", "书", "证明", "承诺书", "证明文件", "报告"))
    return False


def title_hint_from_attached(text):
    value = compact_text(text)
    value = re.sub(r"^(投标人|申请人|供应商)?(应|须|需)?(后附|应附|须附|随附|提交|提供|须提供|应提供|需提供)", "", value)
    value = re.sub(r"^附", "", value)
    value = value.strip("：:，,。；; ")
    return value or compact_text(text)


def title_hint_from_heading(text):
    stripped = compact_text(text)
    replacements = [
        r"^附件\s*\d+[A-Z]?(?:[-－]?\d+)?\s*",
        r"^\d+[A-Z](?:[-－]?\d+)?\s*表\s*",
        r"^\d+[A-Z](?:[-－]?\d+)?表\s*",
        r"^表\s*\d+\s*[A-Z](?:[-－]?\d+)?\s*",
        r"^[A-Z](?:-\d+)?[、．.\s]+",
        r"^\d+(?:\.\d+)+[、．.\s]+",
        r"^[一二三四五六七八九十]+[、．.]\s*",
        r"^[（(](?:\d+|[一二三四五六七八九十]+)[）)]\s*",
    ]
    for pattern in replacements:
        stripped = re.sub(pattern, "", stripped)
    return stripped or compact_text(text)


def confidence_for(anchor_type, text):
    if anchor_type == "rule_like":
        return "low"
    if anchor_type in {"explicit_numbered_heading", "table_title"}:
        return "high"
    if anchor_type in {"table_attached_material", "paragraph_attached_material"}:
        return "medium"
    return "medium"


def build_candidate(anchor_type, source_text, block, level_hint, **extra):
    candidate = {
        "anchor_type": anchor_type,
        "source_text": source_text,
        "title_hint": title_hint_from_attached(source_text) if "attached_material" in anchor_type else title_hint_from_heading(source_text),
        "level_hint": level_hint,
        "block_id": block.get("block_id"),
        "heading_path": block.get("heading_path", []),
        "confidence": confidence_for(anchor_type, source_text),
    }
    candidate.update({key: value for key, value in extra.items() if value is not None})
    return candidate


def table_lookup(tables):
    return {table.get("table_id"): table for table in tables}


def row_lookup(tables):
    rows = {}
    for table in tables:
        table_id = table.get("table_id")
        for row in table.get("rows", []):
            rows[(table_id, row.get("row_index"))] = row
    return rows


def extract_table_attached_candidate(block, rows_by_key):
    text = compact_text(block.get("text", ""))
    if block.get("type") != "table_cell_marker" or not ATTACHED_MATERIAL_RE.search(text):
        return None
    row = rows_by_key.get((block.get("table_id"), block.get("row_index")), {})
    row_text = row.get("row_text") or text
    if RULE_LIKE_RE.search(text) and not MATERIAL_WORD_RE.search(text):
        anchor_type = "rule_like"
        level_hint = 3
    else:
        anchor_type = "table_attached_material"
        level_hint = 3
    return build_candidate(
        anchor_type,
        text,
        block,
        level_hint,
        table_id=block.get("table_id"),
        row_index=block.get("row_index"),
        col_index=block.get("col_index"),
        row_text=row_text,
    )


def extract_paragraph_attached_candidate(block):
    text = compact_text(block.get("text", ""))
    if block.get("table_id") or not ATTACHED_MATERIAL_RE.search(text):
        return None
    if RULE_LIKE_RE.search(text) and not MATERIAL_WORD_RE.search(text):
        return build_candidate("rule_like", text, block, 3)
    return build_candidate("paragraph_attached_material", text, block, 3)


def dedupe_candidates(candidates):
    seen = set()
    deduped = []
    for candidate in candidates:
        key = (
            candidate.get("anchor_type"),
            candidate.get("source_text"),
            candidate.get("block_id"),
            candidate.get("table_id"),
            candidate.get("row_index"),
            candidate.get("col_index"),
        )
        if key in seen:
            continue
        seen.add(key)
        candidate["candidate_id"] = f"cand-{len(deduped) + 1:03d}"
        deduped.append(candidate)
    return deduped


def extract_candidates(scope_blocks, tables):
    rows_by_key = row_lookup(tables)
    candidates = []
    for index, block in enumerate(scope_blocks):
        text = compact_text(block.get("text", ""))
        if not text:
            continue
        if block.get("type") == "table_cell_marker":
            candidate = extract_table_attached_candidate(block, rows_by_key)
            if candidate:
                candidates.append(candidate)
            continue
        if block.get("table_id"):
            continue
        if is_table_title(text):
            candidates.append(build_candidate("table_title", text, block, explicit_level(text)))
        elif is_explicit_numbered_heading(text):
            candidates.append(build_candidate("explicit_numbered_heading", text, block, explicit_level(text)))
        else:
            next_block = scope_blocks[index + 1] if index + 1 < len(scope_blocks) else None
            if is_style_heading(block, next_block):
                candidates.append(build_candidate("style_heading", text, block, 2))
        paragraph_candidate = extract_paragraph_attached_candidate(block)
        if paragraph_candidate:
            candidates.append(paragraph_candidate)
        elif RULE_LIKE_RE.search(text) and not MATERIAL_WORD_RE.search(text):
            candidates.append(build_candidate("rule_like", text, block, 3))
    return dedupe_candidates(candidates)


def body_scope_text(scope_blocks):
    lines = [f"{block.get('block_id')}: {block.get('text', '')}" for block in scope_blocks]
    text = "\n".join(lines)
    if len(text) <= BODY_TEXT_LIMIT:
        return text
    return text[:BODY_TEXT_LIMIT] + "\n...[truncated; block_ids retained above]"


def related_tables(scope_blocks, tables):
    table_ids = {block.get("table_id") for block in scope_blocks if block.get("table_id")}
    return [table for table in tables if table.get("table_id") in table_ids]


def make_output(data, args):
    blocks = data.get("blocks", [])
    if not blocks:
        raise SystemExit("ERROR: tender_map_inputs.json has no blocks")
    scope_blocks, parent_block, parent_score, boundary_reason, warnings = determine_scope(blocks, args)
    tables = related_tables(scope_blocks, data.get("tables", []))
    candidates = extract_candidates(scope_blocks, tables)
    output = {
        "parent": {
            "section_id": args.parent_section_id,
            "title": args.parent_title or title_hint_from_heading(parent_block.get("text", "")),
            "source_text": args.parent_source_text or parent_block.get("text", ""),
            "matched_block_id": parent_block.get("block_id"),
            "match_score": round(parent_score, 3),
        },
        "body_scope": {
            "start_block_id": scope_blocks[0].get("block_id"),
            "end_block_id": scope_blocks[-1].get("block_id"),
            "block_ids": [block.get("block_id") for block in scope_blocks],
            "boundary_reason": boundary_reason,
            "text": body_scope_text(scope_blocks),
        },
        "candidates": candidates,
    }
    if warnings:
        output["warnings"] = warnings
    return output


def main():
    parser = argparse.ArgumentParser(description="Extract possible children candidates from a parent format section in tender_map_inputs.json.")
    parser.add_argument("tender_map_inputs", help="Path to tender_map_inputs.json")
    parser.add_argument("--parent-source-text")
    parser.add_argument("--next-sibling-source-text")
    parser.add_argument("--output", default="children_candidates.json")
    parser.add_argument("--parent-title")
    parser.add_argument("--parent-section-id")
    parser.add_argument("--start-block-id")
    parser.add_argument("--end-before-block-id")
    args = parser.parse_args()

    data = load_data(args.tender_map_inputs)
    output = make_output(data, args)
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: wrote {args.output} with {len(output['candidates'])} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
