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

SCOPE_PARENT = "parent_context"
SCOPE_FORMAT = "format_area"
SCOPE_HIGH_VALUE = "high_value_area"
SCOPE_BROAD = "broad_clause"
SCOPE_FULL_TEXT = "full_text"

STRONG_FORMAT_TERMS = [
    "投标文件格式",
    "响应文件格式",
    "商务文件格式",
    "格式及附件",
    "格式文件",
    "表单",
    "承诺书",
    "声明函",
]
WEAK_FORMAT_TERMS = ["附件", "附表"]
HIGH_VALUE_TERMS = [
    "投标文件组成",
    "提交要求",
    "资格要求",
    "资格审查",
    "符合性审查",
    "响应性审查",
    "否决条款",
    "否决投标",
    "实质性响应",
    "实质性要求",
    "评标办法",
    "评分标准",
    "商务评分",
    "商务评审",
    "技术评分",
    "必须承诺",
    "必须提交",
    "必须说明",
]
BROAD_TERMS = ["其他材料", "完整性", "应当提交", "认为应当提交", "补充资料"]
MATERIAL_TERMS = ["表", "函", "书", "证明", "材料", "证书", "执照", "许可", "承诺", "声明", "授权", "业绩", "财务", "报告", "清单", "报价", "摘要", "复印件", "扫描件", "截图", "合同"]
ATTACHED_TERMS = ["后附", "另附", "应附", "须附", "随附", "提供", "提交", "包括", "包含", "复印件", "扫描件", "证明材料"]

FORMAT_BODY_TERMS = ["投标文件格式", "响应文件格式", "商务文件格式", "格式及附件", "格式文件"]
NON_FORMAT_CONTEXT_TERMS = ["投标人须知", "前附表", "评标办法", "评分标准", "商务评分", "商务评审", "技术评分"]
CROSS_REFERENCE_RE = re.compile(r"(见|详见|按|参见).{0,12}(第[一二三四五六七八九十百\d]+章|附件\s*\d+|附表\s*\d+|格式)")
FORMAT_HEADING_RE = re.compile(
    r"^(附件\s*\d+[A-Za-z]?(?:[-－]?\d+)?|附表\s*\d*[A-Za-z]?|表\s*\d+[A-Za-z]?(?:[-－]?\d+)?|\d+[A-Za-z](?:[-－]?\d+)?\s*表?|[A-Z](?:-\d+)?)[\s、．.]*\S*"
)
TOC_LINE_RE = re.compile(r"(?:\.{2,}|…{2,}|\s{2,}|\t)\s*\d+\s*$")
SIMPLE_PAGE_LINE_RE = re.compile(r"^.{2,80}\s+\d{1,4}\s*$")
NUMBERED_ITEM_RE = re.compile(r"^\s*(?:\d+|[一二三四五六七八九十]+)[、．.]\s*\S+")


class SourceSet:
    def __init__(self, sources):
        self.sources = sources
        self.by_scope = {
            SCOPE_FORMAT: [source for source in sources if source["scope_hint"] == SCOPE_FORMAT],
            SCOPE_HIGH_VALUE: [source for source in sources if source["scope_hint"] == SCOPE_HIGH_VALUE],
        }
        self.indexed = [source for source in sources if source.get("index") is not None]
        self.broad = [source for source in sources if has_any(source["source_text"], BROAD_TERMS)]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def compact(text):
    text = re.sub(r"\s+", "", text or "").lower()
    return re.sub(r"[，。；：、,。.\-—_:;()（）\[\]【】《》\"'“”‘’/\\|]", "", text)


def strip_numbering(text):
    value = re.sub(r"\s+", " ", text or "").strip()
    patterns = [
        r"^[一二三四五六七八九十百]+[、．.\s]+",
        r"^第[一二三四五六七八九十百\d]+章\s*",
        r"^附件\s*\d+[a-zA-Z]?(?:[-－]?\d+)?\s*",
        r"^\d+[a-zA-Z](?:[-－]?\d+)?\s*表\s*",
        r"^\d+[a-zA-Z](?:[-－]?\d+)?表\s*",
        r"^表\s*\d+[a-zA-Z]?(?:[-－]?\d+)?\s*",
        r"^[a-zA-Z](?:-\d+)?[、．.\s]+",
        r"^\d+(?:\.\d+)+[、．.\s]+",
        r"^[（(](?:\d+|[一二三四五六七八九十百]+)[）)]\s*",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            new_value = re.sub(pattern, "", value, flags=re.I).strip()
            if new_value != value:
                value = new_value
                changed = True
    value = re.sub(r"^(后附|另附|应附|须附|随附|提交|提供|须提供|应提供|需提供)", "", value).strip("：:，,。；; ")
    value = re.sub(r"(复印件|扫描件|证明材料)$", "", value).strip("：:，,。；; ") or value
    return value or (text or "")


def key_terms(text):
    core = compact(strip_numbering(text))
    terms = []
    if core:
        terms.append(core)
    for part in re.split(r"[、，,；;及和与\s]+", strip_numbering(text or "")):
        token = compact(part)
        if len(token) >= 2 and token not in terms:
            terms.append(token)
    return terms


def section_features(section):
    features = []
    for text in [section.get("title", ""), section.get("source_text", "")]:
        features.append({
            "raw": compact(text),
            "core": compact(strip_numbering(text)),
            "terms": [term for term in key_terms(text) if len(term) >= 2],
        })
    return features


def has_any(text, terms):
    value = compact(text)
    return any(compact(term) in value for term in terms)


def is_toc_like_text(text):
    stripped = (text or "").strip()
    if compact(stripped) in {"目录", "目次"}:
        return True
    return bool(TOC_LINE_RE.search(stripped) or SIMPLE_PAGE_LINE_RE.match(stripped))


def is_toc_source(text, heading_path):
    path_text = " ".join(heading_path or [])
    return compact(path_text) in {"目录", "目次"} or has_any(path_text, ["目录", "目次"]) or is_toc_like_text(text)


def iter_sections(sections, parent=None):
    for section in sections or []:
        item = dict(section)
        item["parent"] = parent
        yield item
        yield from iter_sections(section.get("children", []), item)


def in_format_body(heading_path, nearby_heading=""):
    context = " ".join([nearby_heading or "", " ".join(heading_path or [])])
    if has_any(context, NON_FORMAT_CONTEXT_TERMS):
        return False
    return has_any(context, FORMAT_BODY_TERMS) or any(looks_like_format_heading(item) for item in heading_path or [])


def looks_like_format_heading(text):
    stripped = (text or "").strip()
    return len(stripped) <= 90 and bool(FORMAT_HEADING_RE.match(stripped))


def is_cross_reference_text(text):
    return bool(CROSS_REFERENCE_RE.search(text or "")) or (
        bool(re.search(r"[（(]\s*附件\s*\d+[A-Za-z]?\s*[）)]", text or ""))
        and not NUMBERED_ITEM_RE.match(text or "")
    )


def is_table_source(source_or_candidate):
    return (
        source_or_candidate.get("source_type") in {"table_row", "table_cell"}
        or source_or_candidate.get("block_type") in {"table_cell_marker", "table_row"}
    )


def is_table_row_source(source_or_candidate):
    return source_or_candidate.get("source_type") == "table_row" or source_or_candidate.get("block_type") == "table_row"


def is_table_cell_source(source_or_candidate):
    return source_or_candidate.get("source_type") == "table_cell" or source_or_candidate.get("block_type") == "table_cell_marker"


def evidence_granularity_priority(source_or_candidate):
    text = source_or_candidate.get("source_text", "")
    priority = 0
    if source_or_candidate.get("scope") == SCOPE_PARENT and NUMBERED_ITEM_RE.match(text):
        priority += 6
    elif NUMBERED_ITEM_RE.match(text):
        priority += 4
    if is_table_cell_source(source_or_candidate):
        priority += 8
    elif is_table_row_source(source_or_candidate):
        priority -= 6
    elif is_table_source(source_or_candidate):
        priority += 2
    if has_any(text, ATTACHED_TERMS):
        priority += 4
    if "|" in text or len(text) > 120:
        priority -= 3
    if looks_like_format_heading(text) and not has_any(text, ATTACHED_TERMS):
        priority += 2
    return priority


def classify_scope(source_text, heading_path=None, nearby_heading=""):
    context = " ".join([nearby_heading or "", " ".join(heading_path or [])])
    combined = " ".join([source_text or "", context])
    non_format_context = has_any(context, NON_FORMAT_CONTEXT_TERMS)
    cross_reference = bool(CROSS_REFERENCE_RE.search(source_text or ""))
    if has_any(combined, HIGH_VALUE_TERMS):
        return SCOPE_HIGH_VALUE
    if non_format_context or cross_reference:
        return SCOPE_HIGH_VALUE if has_any(combined, [*HIGH_VALUE_TERMS, "提交", "组成", "资格", "评审", "评分", "附件", "格式"]) else SCOPE_FULL_TEXT
    if in_format_body(heading_path, nearby_heading):
        if looks_like_format_heading(source_text) or has_any(source_text, MATERIAL_TERMS + ATTACHED_TERMS + FORMAT_BODY_TERMS):
            return SCOPE_FORMAT
    if looks_like_format_heading(source_text) and has_any(source_text, ["附件", "附表", "表", "格式"]):
        return SCOPE_FORMAT
    return SCOPE_FULL_TEXT


def add_source(sources, source_type, source_text, **extra):
    if not source_text:
        return
    heading_path = extra.get("heading_path", []) or []
    if is_toc_source(source_text, heading_path):
        return
    scope_text = " ".join(str(value) for value in [source_text, extra.get("nearby_heading", ""), " ".join(heading_path)])
    source = {
        "source_type": source_type,
        "source_text": source_text,
        "source_compact": compact(source_text),
        "scope_hint": classify_scope(source_text, heading_path, extra.get("nearby_heading", "")),
    }
    source.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    sources.append(source)


def make_sources(tender):
    sources = []
    for index, block in enumerate(tender.get("blocks", []) or []):
        add_source(
            sources,
            "block",
            block.get("text", ""),
            block_id=block.get("block_id"),
            block_type=block.get("type"),
            heading_path=block.get("heading_path", []),
            heading_level=block.get("heading_level"),
            table_id=block.get("table_id"),
            row_index=block.get("row_index"),
            col_index=block.get("col_index"),
            index=index,
        )
    for table in tender.get("tables", []) or []:
        heading = table.get("nearby_heading", "") or table.get("nearby_caption", "")
        for row in table.get("rows", []) or []:
            row_text = row.get("row_text", "")
            add_source(sources, "table_row", row_text, table_id=table.get("table_id"), nearby_heading=heading)
            for cell in row.get("cells", []) or []:
                add_source(
                    sources,
                    "table_cell",
                    cell.get("text", ""),
                    table_id=table.get("table_id"),
                    row_index=row.get("row_index"),
                    col_index=cell.get("col_index"),
                    row_text=row_text,
                    nearby_heading=heading,
                )
    return SourceSet(sources)


def source_score(features, source):
    haystack = source["source_compact"]
    if not haystack:
        return 0.0
    best = 0.0
    for feature in features:
        core = feature["core"]
        raw = feature["raw"]
        if core and core in haystack:
            best = max(best, 1.0)
        elif raw and raw in haystack:
            best = max(best, 0.95)
        else:
            terms = feature["terms"]
            if terms:
                hit_weight = sum(len(term) for term in terms if term in haystack)
                total_weight = sum(len(term) for term in terms)
                best = max(best, hit_weight / total_weight if total_weight else 0.0)
            best = max(best, SequenceMatcher(None, core, haystack).ratio() if core else 0.0)
    if any(compact(term) in haystack for term in MATERIAL_TERMS) and best >= 0.35:
        best += 0.05
    return min(best, 1.0)


def format_key(text):
    stripped = re.sub(r"\s+", "", text or "")
    match = re.match(r"^(?:附件|附表)?(\d+)([A-Za-z]?)(?:[-－]?(\d+))?", stripped, re.I)
    if match:
        return match.group(1), (match.group(2) or "").upper(), match.group(3) or ""
    match = re.match(r"^(\d+)([A-Za-z])(?:[-－]?(\d+))?表?", stripped, re.I)
    if match:
        return match.group(1), (match.group(2) or "").upper(), match.group(3) or ""
    return None


def is_child_format_key(parent_key, next_key):
    if not parent_key or not next_key:
        return False
    if parent_key[0] != next_key[0]:
        return False
    if not parent_key[1] and next_key[1]:
        return True
    if parent_key[1] == next_key[1] and not parent_key[2] and next_key[2]:
        return True
    return False


def major_heading(source):
    heading_path = source.get("heading_path", []) or []
    return compact(heading_path[0]) if heading_path else ""


def looks_like_format_boundary(source, anchor):
    if major_heading(source) and major_heading(anchor) and major_heading(source) != major_heading(anchor):
        return True
    if source.get("block_type") == "table_cell_marker" or source.get("table_id"):
        return False
    text = source.get("source_text", "")
    if len(text.strip()) > 90:
        return False
    if source.get("heading_level") and anchor.get("heading_level") and source["heading_level"] <= anchor.get("heading_level"):
        return True
    if not FORMAT_HEADING_RE.match(text.strip()):
        return False
    anchor_key = format_key(anchor.get("source_text", ""))
    source_key = format_key(text)
    if is_child_format_key(anchor_key, source_key):
        return False
    return compact(text) != compact(anchor.get("source_text", ""))


def parent_scope_sources(section, source_set, parent_anchors):
    parent = section.get("parent")
    if not parent:
        return []
    anchors = [source for source in parent_anchors.get(parent.get("id"), []) if source.get("index") is not None]
    selected = []
    for anchor in anchors[:2]:
        start = anchor["index"]
        end = None
        for source in source_set.indexed:
            if source["index"] <= start:
                continue
            if looks_like_format_boundary(source, anchor):
                end = source["index"]
                break
        for source in source_set.indexed:
            if source["index"] > start and (end is None or source["index"] < end):
                selected.append(source)
    return selected


def scope_rank(scope):
    return {SCOPE_PARENT: 0, SCOPE_FORMAT: 1, SCOPE_HIGH_VALUE: 2, SCOPE_BROAD: 3, SCOPE_FULL_TEXT: 4}.get(scope, 5)


def candidate_from(source, score, scope):
    excluded = {"scope_hint", "source_compact", "index"}
    result = {key: value for key, value in source.items() if key not in excluded and value not in (None, "", [])}
    result["score"] = round(score, 3)
    result["scope"] = scope
    result["confidence"] = "high" if score >= 0.9 and scope in {SCOPE_PARENT, SCOPE_FORMAT} else "medium" if score >= 0.55 else "low"
    return result


def candidate_priority(candidate):
    return evidence_granularity_priority(candidate)


def collect_matches(features, sources, scope, threshold):
    matches = []
    anchors = []
    for source in sources:
        score = source_score(features, source)
        if score >= threshold:
            matches.append(candidate_from(source, score, scope))
            anchors.append(source)
    return matches, anchors


def source_anchor_priority(source):
    text = source.get("source_text", "")
    heading_path = source.get("heading_path", []) or []
    nearby_heading = source.get("nearby_heading", "")
    context = " ".join([nearby_heading, " ".join(heading_path)])
    priority = 0
    if source.get("scope_hint") == SCOPE_FORMAT and in_format_body(heading_path, nearby_heading):
        priority += 50
    elif source.get("scope_hint") == SCOPE_FORMAT:
        priority += 40
    elif is_table_cell_source(source):
        priority += 6
    elif is_table_row_source(source):
        priority += 2
    elif source.get("scope_hint") == SCOPE_HIGH_VALUE:
        priority += 20
    if looks_like_format_heading(text):
        priority += 8
    if has_any(text, ATTACHED_TERMS):
        priority += 5
    if has_any(context, NON_FORMAT_CONTEXT_TERMS) or CROSS_REFERENCE_RE.search(text or ""):
        priority -= 30
    if is_cross_reference_text(text) and not in_format_body(heading_path, nearby_heading):
        priority -= 8
    return priority


def select_anchor_sources(features, sources):
    seen = set()
    unique = []
    for source in sources:
        key = (source.get("index"), source.get("block_id"), source.get("source_text"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return sorted(
        unique,
        key=lambda source: (
            is_table_source(source),
            -source_anchor_priority(source),
            -min(source_score(features, source), 0.9),
            source.get("index", 10**9),
            source.get("source_text", ""),
        ),
    )


def find_candidates(section, source_set, parent_anchors):
    features = section_features(section)
    candidates = []
    anchors = []
    parent_sources = parent_scope_sources(section, source_set, parent_anchors)
    matches, matched_sources = collect_matches(features, parent_sources, SCOPE_PARENT, 0.55)
    candidates.extend(matches)
    anchors.extend(matched_sources)
    global_matches = []
    global_anchors = []
    for sources, scope, threshold in [
        (source_set.by_scope[SCOPE_FORMAT], SCOPE_FORMAT, 0.55),
        (source_set.by_scope[SCOPE_HIGH_VALUE], SCOPE_HIGH_VALUE, 0.55),
        (source_set.broad, SCOPE_BROAD, 0.25),
        (source_set.sources, SCOPE_FULL_TEXT, 0.55),
    ]:
        matches, matched_sources = collect_matches(features, sources, scope, threshold)
        global_matches.extend(matches)
        global_anchors.extend(matched_sources)
    anchors.extend(global_anchors)
    if not candidates:
        candidates.extend(global_matches)
    return dedupe(candidates), select_anchor_sources(features, anchors)


def dedupe(candidates):
    seen = set()
    unique = []
    for candidate in sorted(candidates, key=lambda item: (-item.get("score", 0), scope_rank(item.get("scope")), -candidate_priority(item), item.get("block_id", ""), item.get("source_text", ""))):
        key = (candidate.get("source_text"), candidate.get("scope"))
        if key in seen:
            continue
        seen.add(key)
        candidate["candidate_id"] = f"cand-{len(unique) + 1:03d}"
        unique.append(candidate)
    return unique[:8]


def summarize_areas(source_set, scope):
    areas = []
    for source in source_set.sources:
        if source.get("source_type") == "block" and source.get("scope_hint") == scope:
            areas.append({
                "block_id": source.get("block_id"),
                "source_text": source.get("source_text", ""),
                "heading_path": source.get("heading_path", []),
            })
    return areas[:30]


def add_quality_issue(issues, message, section, parent=None):
    issues.append({
        "message": message,
        "section_id": section.get("id"),
        "parent_id": parent.get("id") if parent else None,
        "source_text": section.get("source_text"),
    })


def collect_quality_issues(sections):
    issues = []

    def walk(items, parent=None):
        for section in items or []:
            source_text = section.get("source_text", "")
            if parent and source_text and compact(source_text) == compact(parent.get("source_text", "")):
                add_quality_issue(issues, "child 的 source_text 与父项 source_text 完全相同，需复核是否误用了父项标题。", section, parent)
            if is_toc_like_text(source_text):
                add_quality_issue(issues, "source_text 疑似来自目录页/目次页，需改用正文或表格原文。", section, parent)
            if len(source_text) > 800:
                add_quality_issue(issues, "source_text 过长，疑似使用了整段 zone 文本，需改用具体 block/table 原文。", section, parent)
            children = section.get("children", []) or []
            counts = {}
            for child in children:
                child_text = compact(child.get("source_text", ""))
                counts.setdefault(child_text, []).append(child)
            parent_text = compact(section.get("source_text", ""))
            for child_text, same_text_children in counts.items():
                if child_text and child_text == parent_text and len(same_text_children) > 1:
                    for child in same_text_children:
                        add_quality_issue(issues, "多个 sibling child 复用同一个父项 source_text，需复核是否误用了父项标题。", child, section)
            walk(children, section)

    walk(sections)
    return issues


def make_output(tender, outline):
    source_set = make_sources(tender)
    parent_anchors = {}
    items = []
    for section in iter_sections(outline.get("sections", [])):
        candidates, anchors = find_candidates(section, source_set, parent_anchors)
        parent_anchors[section.get("id")] = anchors
        items.append({
            "id": section.get("id"),
            "title": section.get("title"),
            "source_text": section.get("source_text"),
            "parent_id": section.get("parent", {}).get("id") if section.get("parent") else None,
            "candidates": candidates,
        })
    return {
        "format_areas": summarize_areas(source_set, SCOPE_FORMAT),
        "high_value_areas": summarize_areas(source_set, SCOPE_HIGH_VALUE),
        "items": items,
        "quality_issues": collect_quality_issues(outline.get("sections", [])),
    }


def main():
    parser = argparse.ArgumentParser(description="Recall current-tender source_text candidates for outline items without replacing them.")
    parser.add_argument("tender_map_inputs", help="Path to tender_map_inputs.json")
    parser.add_argument("outline_json", help="Path to outline.json or outline draft")
    parser.add_argument("--output", default="source_text_candidates.json")
    args = parser.parse_args()

    tender = load_json(args.tender_map_inputs)
    outline = load_json(args.outline_json)
    output = make_output(tender, outline)
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: wrote {args.output} with {len(output['items'])} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
