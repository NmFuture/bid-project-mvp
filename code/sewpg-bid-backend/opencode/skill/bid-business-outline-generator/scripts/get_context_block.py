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


def load_data(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def block_index(blocks):
    return {block.get("block_id"): index for index, block in enumerate(blocks)}


def table_index(tables):
    return {table.get("table_id"): table for table in tables}


def zone_index(zones):
    return {zone.get("zone_id"): zone for zone in zones}


def collect_related_tables(blocks, tables_by_id):
    table_ids = []
    for block in blocks:
        table_id = block.get("table_id")
        if table_id and table_id not in table_ids:
            table_ids.append(table_id)
    return [tables_by_id[table_id] for table_id in table_ids if table_id in tables_by_id]


def context_by_block(data, block_id, before, after):
    blocks = data.get("blocks", [])
    indexes = block_index(blocks)
    if block_id not in indexes:
        raise SystemExit(f"ERROR: block_id not found: {block_id}")
    index = indexes[block_id]
    start = max(0, index - before)
    end = min(len(blocks), index + after + 1)
    selected = blocks[start:end]
    tables_by_id = table_index(data.get("tables", []))
    return {
        "target": {"type": "block", "id": block_id},
        "heading_path": blocks[index].get("heading_path", []),
        "blocks": selected,
        "tables": collect_related_tables(selected, tables_by_id),
    }


def context_by_table(data, table_id):
    tables_by_id = table_index(data.get("tables", []))
    if table_id not in tables_by_id:
        raise SystemExit(f"ERROR: table_id not found: {table_id}")
    blocks = [block for block in data.get("blocks", []) if block.get("table_id") == table_id]
    return {
        "target": {"type": "table", "id": table_id},
        "heading_path": blocks[0].get("heading_path", []) if blocks else [],
        "blocks": blocks,
        "tables": [tables_by_id[table_id]],
    }


def context_by_zone(data, zone_id):
    zones_by_id = zone_index(data.get("zones", []))
    if zone_id not in zones_by_id:
        raise SystemExit(f"ERROR: zone_id not found: {zone_id}")
    zone = zones_by_id[zone_id]
    wanted = set(zone.get("block_ids", []))
    blocks = [block for block in data.get("blocks", []) if block.get("block_id") in wanted]
    tables_by_id = table_index(data.get("tables", []))
    tables = [tables_by_id[table_id] for table_id in zone.get("table_ids", []) if table_id in tables_by_id]
    return {
        "target": {"type": "zone", "id": zone_id},
        "zone": zone,
        "heading_path": zone.get("heading_path", []),
        "blocks": blocks,
        "tables": tables,
    }


def context_by_text(data, text, before, after):
    needle = normalize(text)
    candidates = []
    for zone in data.get("zones", []):
        if needle and needle in normalize(zone.get("text", "")):
            candidates.append({
                "kind": "zone",
                "id": zone["zone_id"],
                "score": candidate_score(zone),
            })
    for table in data.get("tables", []):
        table_text = "\n".join(row.get("row_text", "") for row in table.get("rows", []))
        if needle and needle in normalize(table_text):
            candidates.append({
                "kind": "table",
                "id": table["table_id"],
                "score": table_candidate_score(table),
            })
    for block in data.get("blocks", []):
        if needle and needle in normalize(block.get("text", "")):
            candidates.append({
                "kind": "block",
                "id": block["block_id"],
                "score": block_candidate_score(block),
            })
    if candidates:
        best = max(candidates, key=lambda item: item["score"])
        if best["kind"] == "zone":
            result = context_by_zone(data, best["id"])
        elif best["kind"] == "table":
            result = context_by_table(data, best["id"])
        else:
            result = context_by_block(data, best["id"], before, after)
        result["text_query_candidates"] = sorted(candidates, key=lambda item: item["score"], reverse=True)[:10]
        return result
    raise SystemExit(f"ERROR: text not found: {text}")


def is_probable_toc(block):
    text = block.get("text", "")
    if re.search(r"\d+\s*$", text) and len(text) <= 80:
        return True
    heading_path = " / ".join(block.get("heading_path", []))
    return "目录" in heading_path and not block.get("table_id")


def block_candidate_score(block):
    score = 10
    if block.get("table_id"):
        score += 30
    if block.get("type") == "table_row":
        score += 15
    if block.get("type") == "table_cell_marker":
        score += 8
    if block.get("heading_level"):
        score += 10
    if is_probable_toc(block):
        score -= 40
    return score


def table_candidate_score(table):
    score = 45
    heading = table.get("nearby_heading", "")
    if "目录" in heading:
        score -= 30
    if table.get("rows"):
        score += min(len(table["rows"]), 20)
    return score


def candidate_score(zone):
    score = 20
    zone_type = zone.get("zone_type")
    if zone_type == "table_scope":
        score += 50
    elif zone_type == "heading_scope":
        score += 30
    elif zone_type == "local_context":
        score += 5
    if zone.get("table_ids"):
        score += 20
    if zone.get("is_probable_toc"):
        score -= 50
    score += min(len(zone.get("block_ids", [])), 20)
    return score


def table_to_md(table):
    lines = [f"### Table {table.get('table_id')} {table.get('nearby_heading', '')}".rstrip()]
    for row in table.get("rows", []):
        cells = [cell.get("text", "") for cell in row.get("cells", [])]
        lines.append(f"- row {row.get('row_index')}: " + " | ".join(cells))
    return "\n".join(lines)


def to_markdown(result):
    lines = [f"# Context: {result['target']['type']} {result['target']['id']}"]
    heading = result.get("heading_path") or []
    if heading:
        lines.append("\nHeading path: " + " / ".join(heading))
    if result.get("zone"):
        zone = result["zone"]
        lines.append(f"\nZone: {zone.get('title')} ({zone.get('matched_checklist_item')})")
    lines.append("\n## Blocks")
    for block in result.get("blocks", []):
        location = block.get("block_id")
        if block.get("table_id"):
            location += f" {block.get('table_id')} r{block.get('row_index')}"
            if block.get("col_index"):
                location += f"c{block.get('col_index')}"
        lines.append(f"- {location}: {block.get('text', '')}")
    if result.get("tables"):
        lines.append("\n## Tables")
        lines.extend(table_to_md(table) for table in result["tables"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Read contextual source blocks from tender_map_inputs.json.")
    parser.add_argument("tender_map_inputs", help="Path to tender_map_inputs.json")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--block-id")
    target.add_argument("--table-id")
    target.add_argument("--zone-id")
    target.add_argument("--text")
    parser.add_argument("--before", type=int, default=3)
    parser.add_argument("--after", type=int, default=8)
    parser.add_argument("--format", choices=["json", "md"], default="json")
    args = parser.parse_args()

    data = load_data(args.tender_map_inputs)
    if args.block_id:
        result = context_by_block(data, args.block_id, args.before, args.after)
    elif args.table_id:
        result = context_by_table(data, args.table_id)
    elif args.zone_id:
        result = context_by_zone(data, args.zone_id)
    else:
        result = context_by_text(data, args.text, args.before, args.after)

    if args.format == "md":
        print(to_markdown(result), end="")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
