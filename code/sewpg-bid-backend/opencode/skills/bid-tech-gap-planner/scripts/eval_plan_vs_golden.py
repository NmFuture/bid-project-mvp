#!/usr/bin/env python3
"""金标逐节点素材一致率评估：gap_plan.json 对照人工核实的金标 fixture。

与 eval_golden_baseline.py（路由决策一致率、需要正式标书 docx）互补：
本脚本消费 eval/ 下已固化的金标 fixture（仅目录标题+素材文件名），
逐节点比对 plan 的素材归因，输出四档分类与定案正确率，作为匹配逻辑
改动的回归基线。支持多套 fixture 以防单客户过拟合。

用法：
    python eval_plan_vs_golden.py --plan gap_plan.json \
        [--golden ../eval/golden-huaneng-wengniute-204.json] [--out report.json]

分类口径：
- primary  : 节点自身 matchedMaterials / fillTasks.blankSource 命中金标任一素材
- coverage : primary 未中，但 coveredByParent 链上根节点的素材命中金标
- candidate: 前两者未中，但金标素材出现在 candidateMaterials（召回未定案）
- miss     : 金标有素材而 plan 全线未给出
金标标记 structural / none 的节点不计入分母。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_DEFAULT_GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden-huaneng-wengniute-204.json"


def _base_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.rsplit("/", 1)[-1]


def _material_names(refs: Any) -> list[str]:
    names: list[str] = []
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        for key in ("name", "cleanedFileName", "sourceFile", "title"):
            value = _base_name(ref.get(key))
            if value:
                names.append(value)
                break
    return names


def _own_materials(item: dict[str, Any]) -> set[str]:
    names = _material_names(item.get("matchedMaterials"))
    for task in item.get("fillTasks") or []:
        blank = task.get("blankSource")
        if isinstance(blank, dict):
            names.extend(_material_names([blank]))
    return set(names)


def evaluate(plan: dict[str, Any], golden: dict[str, Any]) -> dict[str, Any]:
    plan_items = plan.get("items") or []
    by_number: dict[str, dict[str, Any]] = {}
    for item in plan_items:
        by_number.setdefault(str(item.get("number") or "").strip(), item)
    by_id = {str(item.get("id") or ""): item for item in plan_items}

    stats = {"primary": 0, "coverage": 0, "candidate": 0, "miss": 0, "denominator": 0}
    rows: list[dict[str, Any]] = []
    for entry in golden.get("items") or []:
        golden_materials = {_base_name(name) for name in entry.get("materials") or []}
        if entry.get("kind") != "materials" or not golden_materials:
            continue
        stats["denominator"] += 1
        number = str(entry.get("number") or "")
        item = by_number.get(number)
        verdict = "miss"
        if item is not None:
            if _own_materials(item) & golden_materials:
                verdict = "primary"
            else:
                cover_id = str(item.get("coveredByParent") or "")
                seen: set[str] = set()
                while cover_id and cover_id not in seen:
                    seen.add(cover_id)
                    root = by_id.get(cover_id)
                    if root is None:
                        break
                    if _own_materials(root) & golden_materials:
                        verdict = "coverage"
                        break
                    cover_id = str(root.get("coveredByParent") or "")
                if verdict == "miss" and set(_material_names(item.get("candidateMaterials"))) & golden_materials:
                    verdict = "candidate"
        stats[verdict] += 1
        if verdict in {"candidate", "miss"}:
            rows.append({"number": number, "title": entry.get("title"), "verdict": verdict,
                         "golden": sorted(golden_materials)})

    denominator = stats["denominator"] or 1
    stats["decidedAccuracy"] = round((stats["primary"] + stats["coverage"]) / denominator, 4)
    return {"stats": stats, "problems": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--golden", default=str(_DEFAULT_GOLDEN))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    report = evaluate(plan, golden)
    report["golden"] = str(args.golden)
    report["fixture"] = golden.get("fixture")
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["stats"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
