import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def normalize(text):
    return re.sub(r"\s+", "", text or "").lower()


def compact_for_match(text):
    text = normalize(text)
    text = re.sub(r"[，。；：、,.\-—_:;()（）\[\]【】《》\"'“”‘’]", "", text)
    return text


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def iter_source_texts(outline):
    source = outline.get("outline_source", {})
    yield "outline_source.source_text", source.get("source_text")

    def walk_sections(sections, prefix):
        for index, section in enumerate(sections or []):
            path = f"{prefix}[{index}].source_text"
            yield path, section.get("source_text")
            yield from walk_sections(section.get("children", []), f"{prefix}[{index}].children")

    yield from walk_sections(outline.get("sections", []), "sections")
    for index, item in enumerate(outline.get("review_items", []) or []):
        yield f"review_items[{index}].source_text", item.get("source_text")


def build_sources(tender_map_inputs):
    sources = []
    for block in tender_map_inputs.get("blocks", []) or []:
        sources.append({
            "type": "block",
            "id": block.get("block_id"),
            "text": block.get("text", ""),
            "heading_path": block.get("heading_path", []),
            "table_id": block.get("table_id"),
        })
    for table in tender_map_inputs.get("tables", []) or []:
        table_text = "\n".join(row.get("row_text", "") for row in table.get("rows", []) or [])
        sources.append({
            "type": "table",
            "id": table.get("table_id"),
            "text": table_text,
            "nearby_heading": table.get("nearby_heading", ""),
        })
    for zone in tender_map_inputs.get("zones", []) or []:
        sources.append({
            "type": "zone",
            "id": zone.get("zone_id"),
            "text": zone.get("text", ""),
            "heading_path": zone.get("heading_path", []),
        })
    return sources


def score_match(needle, haystack):
    if not needle:
        return 0.0
    n = compact_for_match(needle)
    h = compact_for_match(haystack)
    if not n or not h:
        return 0.0
    if n in h:
        return 1.0
    if len(n) >= 24:
        chunk_size = max(12, min(40, len(n) // 2))
        chunks = [n[i:i + chunk_size] for i in range(0, len(n), chunk_size) if len(n[i:i + chunk_size]) >= 12]
        if chunks:
            return sum(1 for chunk in chunks if chunk in h) / len(chunks)
    return 0.0


def best_match(source_text, sources):
    best = None
    best_score = 0.0
    for source in sources:
        score = score_match(source_text, source.get("text", ""))
        if score > best_score:
            best_score = score
            best = source
    if best and (best_score >= 1.0 or (len(compact_for_match(source_text)) >= 24 and best_score >= 0.6)):
        return best, best_score
    return None, best_score


def main():
    parser = argparse.ArgumentParser(description="Check whether outline source_text values are traceable to tender_map_inputs.json.")
    parser.add_argument("outline_json", help="Path to outline.json")
    parser.add_argument("tender_map_inputs", help="Path to tender_map_inputs.json")
    args = parser.parse_args()

    outline = load_json(args.outline_json)
    tender_map_inputs = load_json(args.tender_map_inputs)
    sources = build_sources(tender_map_inputs)
    results = []
    unmatched = []
    for path, source_text in iter_source_texts(outline):
        match, score = best_match(source_text or "", sources)
        item = {
            "path": path,
            "source_text": source_text,
            "status": "matched" if match else "unmatched",
            "score": round(score, 3),
        }
        if match:
            item["matched_type"] = match["type"]
            item["matched_id"] = match["id"]
            if match.get("table_id"):
                item["table_id"] = match["table_id"]
        else:
            unmatched.append(path)
        results.append(item)
    output = {"results": results, "unmatched": unmatched}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if unmatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
