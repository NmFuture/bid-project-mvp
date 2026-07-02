"""金标反评基线：拿正式中标技术卷（答案）反评缺口决策计划的路由一致率。

用法（正式标书留在本地，不入库）：
    python eval_golden_baseline.py \
        --answer-docx /path/技术卷.docx --answer-docx /path/技术附表.docx \
        --gaps gaps.json          # GET /api/technical/projects/<id>/gaps 的响应 \
        --manifest s4_gap_input.json  # planner manifest（容器 /data/documents/<id>/technical-workspace/s4_gap_workdir/） \
        --out report.json

产出：逐项对照行 + 分类计数 + 路由一致率。分类为确定性粗判（相似度口径复用
run_from_manifest），歧义项需人工/AI 复核；跑基线的目的是看改动前后一致率涨跌。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("tech_gap_planner_for_eval", _HERE / "run_from_manifest.py")
planner = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(planner)


# ---------------------------------------------------------------------------
# 答案抽取：docx -> [{title, level, chars, tables, images, preview}]
# ---------------------------------------------------------------------------

def _style_levels(zf: zipfile.ZipFile) -> dict[str, int]:
    levels: dict[str, int] = {}
    try:
        root = ET.fromstring(zf.read("word/styles.xml"))
    except KeyError:
        return levels
    for style in root.iter(f"{_W}style"):
        sid = style.get(f"{_W}styleId") or ""
        name_el = style.find(f"{_W}name")
        name = (name_el.get(f"{_W}val") if name_el is not None else "") or ""
        match = re.match(r"(?:heading\s*|标题\s*)(\d)$", name.strip(), re.IGNORECASE)
        if match:
            levels[sid] = int(match.group(1))
    return levels


def _heading_level(p, style_levels: dict[str, int]) -> int | None:
    ppr = p.find(f"{_W}pPr")
    if ppr is None:
        return None
    st = ppr.find(f"{_W}pStyle")
    if st is not None:
        sid = st.get(f"{_W}val") or ""
        if sid in style_levels:
            return style_levels[sid]
        match = re.match(r"(?:Heading|heading)(\d)$", sid)
        if match:
            return int(match.group(1))
    ol = ppr.find(f"{_W}outlineLvl")
    if ol is not None:
        try:
            return int(ol.get(f"{_W}val")) + 1
        except (TypeError, ValueError):
            return None
    return None


def extract_answer_sections(path: Path, *, preview_chars: int = 3000) -> list[dict]:
    zf = zipfile.ZipFile(path)
    style_levels = _style_levels(zf)
    sections: list[dict] = []
    current = {"title": "(文档开头)", "level": 0, "chars": 0, "tables": 0, "images": 0, "preview": ""}
    sections.append(current)
    with zf.open("word/document.xml") as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == f"{_W}tbl":
                current["tables"] += 1
                for t in elem.iter(f"{_W}t"):
                    current["chars"] += len(t.text or "")
                elem.clear()
            elif elem.tag == f"{_W}p":
                text = "".join(t.text or "" for t in elem.iter(f"{_W}t"))
                lvl = _heading_level(elem, style_levels)
                imgs = len(list(elem.iter(f"{_W}drawing"))) + len(list(elem.iter(f"{_W}pict")))
                if lvl is not None and text.strip() and lvl <= 6:
                    current = {"title": text.strip(), "level": lvl, "chars": 0, "tables": 0, "images": 0, "preview": ""}
                    sections.append(current)
                else:
                    stripped = text.strip()
                    if stripped:
                        current["chars"] += len(stripped)
                        if len(current["preview"]) < preview_chars:
                            current["preview"] = (current["preview"] + " " + stripped)[:preview_chars]
                    current["images"] += imgs
                elem.clear()
    return sections


# ---------------------------------------------------------------------------
# 对齐：我方目录项 -> 答案标题（标题相似 + 文档顺序贪心）
# ---------------------------------------------------------------------------

def _clean_toc_title(title: str) -> str:
    text = re.sub(r"^(?:附表|附录)\s*[A-Za-z]?\.?\d*(?:\.\d+)*[-.、\s]*", "", str(title or ""))
    text = re.sub(r"^第[一二三四五六七八九十百0-9]+章[-.、\s]*", "", text)
    return text.strip() or str(title or "")


def _subtree(sections: list[dict], idx: int) -> dict:
    base = sections[idx]
    agg = {"answerTitle": base["title"], "chars": base["chars"], "tables": base["tables"],
           "images": base["images"], "preview": base["preview"], "childTitles": []}
    j = idx + 1
    while j < len(sections):
        s = sections[j]
        if s["doc"] != base["doc"] or (s["level"] or 9) <= (base["level"] or 9):
            break
        agg["chars"] += s["chars"]
        agg["tables"] += s["tables"]
        agg["images"] += s["images"]
        agg["childTitles"].append(s["title"])
        if s["preview"] and len(agg["preview"]) < 6000:
            agg["preview"] = (agg["preview"] + " " + s["preview"])[:6000]
        j += 1
    agg["childTitles"] = agg["childTitles"][:40]
    return agg


def align_items(plan_items: list[dict], sections: list[dict]) -> dict[str, dict]:
    aligned: dict[str, dict] = {}
    cursor = 0
    norm = planner._tech_normalize_text
    for item in plan_items:
        title = _clean_toc_title(str(item.get("title") or ""))
        key = norm(title)
        if not key:
            continue
        best_i, best_s = -1, 0.0
        for i in range(cursor, len(sections)):
            cand = norm(sections[i]["title"])
            if not cand:
                continue
            if cand == key:
                best_i, best_s = i, 1.0
                break
            score = planner._tech_similarity_score(title, sections[i]["title"])
            if score > best_s:
                best_i, best_s = i, score
        if best_i >= 0 and best_s >= 0.5:
            aligned[str(item.get("id"))] = {**_subtree(sections, best_i), "alignScore": round(best_s, 3)}
            cursor = best_i + 1
    return aligned


# ---------------------------------------------------------------------------
# 粗分类：答案内容 vs 我方决策 vs 素材库
# ---------------------------------------------------------------------------

def _material_name(m: dict) -> str:
    return str(m.get("name") or m.get("fileName") or m.get("id") or "")


def _lib_top(answer: dict, materials: list[dict], top: int = 3) -> list[dict]:
    probe_titles = [answer["answerTitle"], *answer["childTitles"]]
    probe = (" ".join(probe_titles) + " " + str(answer.get("preview") or ""))[:800]
    scored = []
    for material in materials:
        name = _material_name(material)
        pool = planner._material_topic_text(material)
        s_name = max((planner._tech_similarity_score(name, t) for t in probe_titles if t), default=0.0)
        s_topic = planner._tech_similarity_score(probe[:400], pool) if pool else 0.0
        score = max(s_name, s_topic)
        if score > 0.2:
            scored.append({"name": name, "score": round(score, 3),
                           "requiresFill": planner.material_requires_fill(material)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top]


def classify(row: dict) -> str:
    answer = row.get("answer")
    if not answer:
        return "unaligned"
    decision = row["decision"]
    lib = row.get("libTop") or []
    lib_names = {x["name"] for x in lib}
    top = lib[0] if lib else None
    is_appendix = row["number"].startswith(("附表", "技术附表")) or "附表" in row["title"]
    if decision == "fill_required" and is_appendix:
        return "appendix_fill"
    if decision == "fill_required":
        if top and top["score"] >= 0.5 and not top["requiresFill"]:
            return "fill_but_lib_ready"
        return "body_fill"
    if decision == "ready":
        if not row["ourMatched"]:
            if row.get("coveredByParent"):
                return "structural_ok"  # 父章整章素材覆盖，内容归属父章
            if answer["chars"] > 200 and not row.get("hasChildren"):
                return "structural_content"  # 结构项但正式文件有直挂内容
            return "structural_ok"
        if set(row["ourMatched"]) & lib_names or (top and top["score"] >= 0.5):
            return "ready_hit"
        return "ready_check"
    if decision == "review_required":
        if set(row["ourCandidates"]) & lib_names:
            return "match_covered"
        return "match_check"
    if decision == "material_required":
        if top and top["score"] >= 0.45:
            return "missing_but_lib_has"
        return "missing_ok"
    return "other"


# 路由一致：决策类型与答案内容形态匹配。match_check（已给候选、等人工勾选）在
# 路由层面一致——候选对不对由人工/AI 复核判，确定性脚本不冒判。
CONSISTENT = {"appendix_fill", "body_fill", "ready_hit", "match_covered", "match_check", "structural_ok", "missing_ok"}
# 真实差距：漏召回（库里有料判人工补料）、结构项漏内容、AI填写应改素材匹配。
GAPS = {"missing_but_lib_has", "structural_content", "fill_but_lib_ready"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-docx", action="append", required=True, dest="answer_docs")
    parser.add_argument("--gaps", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    sections: list[dict] = []
    for i, doc in enumerate(args.answer_docs):
        part = extract_answer_sections(Path(doc))
        for s in part:
            s["doc"] = i
        sections.extend(part)

    gaps = json.loads(Path(args.gaps).read_text(encoding="utf-8"))
    plan_items = [x for x in (gaps.get("gapPlan") or gaps).get("items") or [] if isinstance(x, dict)]
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    materials = [m for m in manifest.get("materialIndex") or [] if isinstance(m, dict)]

    aligned = align_items(plan_items, sections)

    rows = []
    for index, item in enumerate(plan_items):
        gid = str(item.get("id"))
        number = str(item.get("number") or "")
        # toc 顺序 + level 判容器（编号前缀对「第3章 vs 3.1」不成立）
        has_children = (
            index + 1 < len(plan_items)
            and int(plan_items[index + 1].get("level") or 1) > int(item.get("level") or 1)
        )
        row = {
            "id": gid,
            "number": number,
            "title": str(item.get("title") or ""),
            "decision": str(item.get("decision") or ""),
            "ourMatched": [_material_name(m) for m in item.get("matchedMaterials") or []],
            "ourCandidates": [_material_name(m) for m in (item.get("candidateMaterials") or [])[:8]],
            "hasChildren": has_children,
            "coveredByParent": str(item.get("coveredByParent") or ""),
            "answer": aligned.get(gid),
        }
        if row["answer"]:
            row["libTop"] = _lib_top(row["answer"], materials)
        row["category"] = classify(row)
        rows.append(row)

    cats = Counter(r["category"] for r in rows)
    aligned_total = sum(1 for r in rows if r["answer"])
    consistent = sum(cats[c] for c in CONSISTENT)
    gaps_count = sum(cats[c] for c in GAPS)
    print("分类计数:", dict(cats))
    print(f"对齐 {aligned_total}/{len(rows)}；路由一致 {consistent}/{aligned_total} = {consistent / max(aligned_total, 1):.1%}；"
          f"真实差距 {gaps_count}；待人工复核 {cats['ready_check'] + cats['match_check']}")
    for r in rows:
        if r["category"] in GAPS or r["category"] == "ready_check":
            top = (r.get("libTop") or [{}])[0]
            print(f"  [{r['category']}] {r['number']} {r['title'][:24]} libTop={top.get('name', '-')[:24]}({top.get('score', '-')})")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"逐项明细已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
