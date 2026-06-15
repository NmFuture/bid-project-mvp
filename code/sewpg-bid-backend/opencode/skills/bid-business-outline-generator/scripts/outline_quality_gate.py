from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_outline
from document_structure_index import build_document_structure_index, compact, is_toc_text

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def iter_sections(sections: list[dict[str, Any]], prefix: str = "sections"):
    for index, section in enumerate(sections or []):
        path = f"{prefix}[{index}]"
        yield path, section
        yield from iter_sections(section.get("children", []) or [], f"{path}.children")


def section_count(outline: dict[str, Any]) -> int:
    return sum(1 for _path, _section in iter_sections(outline.get("sections", []) or []))


def level_distribution(outline: dict[str, Any]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for _path, section in iter_sections(outline.get("sections", []) or []):
        key = str(section.get("level") or "")
        dist[key] = dist.get(key, 0) + 1
    return dist


def status_distribution(outline: dict[str, Any]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for _path, section in iter_sections(outline.get("sections", []) or []):
        key = str(section.get("required_status") or "")
        dist[key] = dist.get(key, 0) + 1
    return dist


def score_match(needle: str, haystack: str) -> float:
    n = compact(needle)
    h = compact(haystack)
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


def best_current_match(source_text: str, index: dict[str, Any]) -> tuple[dict[str, Any] | None, float]:
    best = None
    best_score = 0.0
    for block in index.get("blocks", []) or []:
        score = score_match(source_text, block.get("source_text", ""))
        if score > best_score:
            best_score = score
            best = block
    if best and (best_score >= 1.0 or (len(compact(source_text)) >= 24 and best_score >= 0.6)):
        return best, best_score
    return None, best_score


def fallback_has_reason(section: dict[str, Any]) -> bool:
    reason = str(section.get("reason") or "")
    return bool(reason) and ("历史" in reason or "fallback" in reason.lower() or "人工确认" in reason)


def evaluate_quality(
    outline: dict[str, Any],
    tender_map_inputs: dict[str, Any],
    *,
    baseline_outline: dict[str, Any] | None = None,
    min_current_evidence_ratio: float = 0.8,
    max_history_fallback_ratio: float = 0.4,
    max_elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    issues: list[dict[str, Any]] = []
    schema_errors = validate_outline.validate(outline)
    for error in schema_errors:
        issues.append({"severity": "error", "message": f"schema: {error}"})

    index = build_document_structure_index(tender_map_inputs)
    total = 0
    matched_current = 0
    toc_only = 0
    history_fallback = 0
    unmatched = 0
    fallback_without_reason = 0
    strong_evidence = 0
    weak_evidence = 0

    for path, section in iter_sections(outline.get("sections", []) or []):
        total += 1
        evidence_scope = str(section.get("evidence_scope") or "")
        evidence_strength = str(section.get("evidence_strength") or "")
        source_text = str(section.get("source_text") or "")
        match, _score = best_current_match(source_text, index)
        if match and match.get("is_toc"):
            toc_only += 1
            if evidence_strength == "strong":
                issues.append({"severity": "error", "path": path, "message": "目录页文本不能作为 strong 当前证据。"})
        elif match:
            matched_current += 1
        elif evidence_scope == "history_fallback" or evidence_strength == "fallback" or not section.get("source_refs"):
            history_fallback += 1
            if not fallback_has_reason(section):
                fallback_without_reason += 1
                issues.append({"severity": "error", "path": path, "message": "history_fallback 节点缺少 fallback/人工确认 reason。"})
        else:
            unmatched += 1
            issues.append({"severity": "warning", "path": path, "message": "source_text 未能匹配当前招标文件，且未标记 history_fallback。"})
        if evidence_strength == "strong":
            strong_evidence += 1
        if evidence_strength in {"weak", "fallback"} or str(section.get("required_status")) == "待确认":
            weak_evidence += 1
        if source_text and is_toc_text(source_text, []) and evidence_scope != "history_fallback" and evidence_strength != "fallback":
            issues.append({"severity": "error", "path": path, "message": "source_text 疑似目录页文本。"})

    baseline_count = section_count(baseline_outline) if baseline_outline else total
    if baseline_count and total < baseline_count * 0.95:
        issues.append({"severity": "error", "message": f"节点数量低于基线 95%：current={total}, baseline={baseline_count}。"})
    current_ratio = matched_current / max(total, 1)
    fallback_ratio = history_fallback / max(total, 1)
    if current_ratio < min_current_evidence_ratio:
        issues.append({"severity": "error", "message": f"当前原文证据覆盖率不足：{current_ratio:.3f} < {min_current_evidence_ratio:.3f}。"})
    if fallback_ratio > max_history_fallback_ratio:
        issues.append({"severity": "error", "message": f"history_fallback 比例过高：{fallback_ratio:.3f} > {max_history_fallback_ratio:.3f}。"})
    pending = status_distribution(outline).get("待确认", 0)
    if total and pending == total:
        issues.append({"severity": "error", "message": "required_status 全部为待确认，状态判定没有形成有效区分。"})
    elapsed = round(time.perf_counter() - start, 3)
    if max_elapsed_seconds is not None and elapsed > max_elapsed_seconds:
        issues.append({"severity": "error", "message": f"质量门禁耗时超过上限：{elapsed:.3f}s > {max_elapsed_seconds:.3f}s。"})

    metrics = {
        "outline_section_count": total,
        "level_distribution": level_distribution(outline),
        "source_text_total": total,
        "source_text_matched_current": matched_current,
        "source_text_matched_toc_only": toc_only,
        "source_text_history_fallback": history_fallback,
        "source_text_unmatched": unmatched,
        "required_status_distribution": status_distribution(outline),
        "history_fallback_without_reason": fallback_without_reason,
        "strong_evidence_count": strong_evidence,
        "weak_evidence_count": weak_evidence,
        "elapsed_seconds": elapsed,
    }
    return {"passed": not any(issue.get("severity") == "error" for issue in issues), "metrics": metrics, "issues": issues}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate business outline evidence quality.")
    parser.add_argument("--outline", required=True)
    parser.add_argument("--tender-map", required=True)
    parser.add_argument("--output-report", required=True)
    parser.add_argument("--baseline-outline")
    parser.add_argument("--min-current-evidence-ratio", type=float, default=0.8)
    parser.add_argument("--max-history-fallback-ratio", type=float, default=0.4)
    parser.add_argument("--max-elapsed-seconds", type=float)
    args = parser.parse_args()

    outline = load_json(args.outline)
    tender = load_json(args.tender_map)
    baseline = load_json(args.baseline_outline) if args.baseline_outline else None
    report = evaluate_quality(
        outline,
        tender,
        baseline_outline=baseline,
        min_current_evidence_ratio=args.min_current_evidence_ratio,
        max_history_fallback_ratio=args.max_history_fallback_ratio,
        max_elapsed_seconds=args.max_elapsed_seconds,
    )
    Path(args.output_report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "metrics": report["metrics"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
