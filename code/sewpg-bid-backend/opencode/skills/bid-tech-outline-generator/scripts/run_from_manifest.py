from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CHINESE_NUMERAL = "[一二三四五六七八九十百千万零〇两]+"

HEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"^第(?P<num>{CHINESE_NUMERAL}|\d+)章[\s　:：、.-]*(?P<title>.+)$"),
    re.compile(r"^(?P<num>\d+(?:\.\d+)*)(?:[\s　:：、.-]+)(?P<title>.+)$"),
    re.compile(rf"^(?P<num>{CHINESE_NUMERAL})[、.．]\s*(?P<title>.+)$"),
    re.compile(r"^[（(](?P<num>\d+)[）)]\s*(?P<title>.+)$"),
)
APPENDIX_PATTERN = re.compile(
    r"^(?P<number>(?:技术\s*)?(?:附(?:件|表|录)|副表)\s*[A-Za-z0-9一二三四五六七八九十百千万零〇两.-]*)"
    r"[\s　:：、.-]*(?P<title>[^。；;\n]{2,120})"
)
REQUIREMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:投标人|供应商|响应方|报价人|申请人)?(?:应|须|必须|需|需要|应当)(?P<title>[^。；;\n]{2,90})"),
    re.compile(r"(?:提供|提交|编制|说明|承诺|响应)(?P<title>[^。；;\n]{2,90})"),
)
TITLE_KEY_DROP = re.compile(
    r"^(?:投标人|供应商|响应方|报价人|申请人)?(?:应|须|必须|需|需要|应当|提供|提交|编制|说明|承诺|响应)"
)
NOISE_TOKENS = {
    "目录",
    "正文",
    "附件",
    "附表",
    "附录",
    "投标文件",
    "招标文件",
    "要求",
    "内容",
    "说明",
    "响应",
}


@dataclass(frozen=True)
class Paragraph:
    text: str
    style_id: str
    style_name: str
    outline_level: int | None
    paragraph_index: int
    tab_count: int


@dataclass(frozen=True)
class OutlineEntry:
    number: str
    title: str
    level: int
    source_file: str
    paragraph_index: int
    raw_text: str


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    raw_text: str
    source_file: str
    file_id: str
    file_name: str
    paragraph_index: int
    kind: str
    number: str = ""
    context_title: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate S2 bid outline candidates from a manifest.")
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--manifest", dest="manifest_option")
    parser.add_argument("--response", choices=("summary", "review"), default="summary")
    args = parser.parse_args()

    manifest_path = Path(str(args.manifest_option or args.manifest or "")).expanduser()
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = run_manifest(manifest, manifest_path)
    response = result["review"] if args.response == "review" else result["summary"]
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def run_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_file = Path(str(manifest.get("outputFile") or work_dir / "toc.json")).expanduser()
    evidence_file = Path(str(manifest.get("evidenceFile") or work_dir / "toc_evidence.json")).expanduser()
    agent_review_file = work_dir / "agent_review_input.json"

    template_file = existing_path(manifest.get("templateFile"), "templateFile")
    attach_file = optional_path(manifest.get("attachFile"))
    tender_files = tender_inputs(manifest)

    template_outline = extract_outline(template_file)
    if not template_outline:
        raise SystemExit("templateFile has no usable outline entries")
    attach_outline = extract_outline(attach_file) if attach_file else []
    candidates = extract_candidates(tender_files)
    items, decisions = build_items(template_outline, attach_outline, candidates)

    # Optional AI judge layer — when ``OUTLINE_JUDGE_ENABLED=true`` plus the
    # endpoint env vars are set, send the rule-based items to an LLM for noise
    # culling before we serialize toc.json. The judge can only DROP items;
    # the rule-based path stays authoritative on shape, numbering and titles.
    items_before_judge = items
    items, judge_review = _apply_outline_judge(items, work_dir)
    review_budget = review_budget_from_manifest(manifest)

    annotation_counts = Counter(str(item.get("annotation") or "") for item in items)
    toc = {
        "schema_version": "bid-toc-json-v1",
        "document_title": "投标文件总目录",
        "project": {
            "projectId": str(manifest.get("projectId") or ""),
            "projectCode": str(manifest.get("projectCode") or ""),
            "projectName": str(manifest.get("projectName") or ""),
            "bidType": str(manifest.get("bidType") or ""),
        },
        "source_files": {
            "tender": [source_file_payload(item) for item in tender_files],
            "template": str(template_file),
            "attach": str(attach_file) if attach_file else "",
            "output": str(output_file),
            "evidence": str(evidence_file),
        },
        "summary": {
            "total_items": len(items),
            "annotation_counts": dict(annotation_counts),
            "template_heading_count": len(template_outline),
            "tender_candidate_count": len(candidates),
            "outline_judge": {
                "status": judge_review.get("status"),
                "input_item_count": judge_review.get("input_item_count"),
                "kept_item_count": judge_review.get("kept_item_count"),
                "dropped_item_count": judge_review.get("dropped_item_count"),
                "model": judge_review.get("model"),
            },
        },
        "items": items,
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
    }
    evidence = {
        "schema_version": "bid-toc-evidence-v1",
        "engine": "bid-tech-outline-generator",
        "inputs": toc["source_files"],
        "templateOutline": [outline_evidence(item) for item in template_outline],
        "attachOutline": [outline_evidence(item) for item in attach_outline],
        "tenderCandidates": [candidate_evidence(item) for item in candidates],
        "decisions": decisions,
    }
    review_candidates = review_candidate_payload(candidates, decisions, review_budget)
    review = {
        "schema_version": "bid-toc-agent-review-v1",
        "instruction": "Review this compact bundle only. Return strict JSON with outputFile/evidenceFile and optional agentDecisions; do not read full toc/evidence files unless explicitly necessary.",
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
        "summary": {
            "templateHeadingCount": len(template_outline),
            "tenderCandidateCount": len(candidates),
            "reviewCandidateCount": len(review_candidates),
            "draftItemCount": len(items),
            "appendixItemCount": sum(1 for item in items if item.get("annotation") == "新增-副表"),
        },
        "templateOutlineSample": take_budgeted(
            [slim_outline_entry(item) for item in template_outline],
            review_budget.get("templateOutlineItems"),
        ),
        "tenderCandidatesForReview": review_candidates,
        "draftItemsForReview": review_item_payload(items, review_budget),
        "scriptDecisionSample": take_budgeted(
            [slim_decision(item) for item in decisions],
            review_budget.get("scriptDecisions"),
        ),
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    agent_review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "schema_version": "bid-toc-json-v1",
        "skill": "bid-tech-outline-generator",
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
        "agentReviewFile": str(agent_review_file),
        "summary": toc["summary"],
        "itemCount": len(items),
        "agentReviewDigest": stdout_review_payload(review, review_budget),
    }
    return {"summary": summary, "review": review, "toc": toc, "evidence": evidence}


def review_budget_from_manifest(manifest: dict[str, Any]) -> dict[str, int | None]:
    raw_budget = manifest.get("reviewBudget")
    budget = raw_budget if isinstance(raw_budget, dict) else {}
    return {
        "templateOutlineItems": optional_positive_int(budget.get("templateOutlineItems")),
        "tenderCandidates": optional_positive_int(budget.get("tenderCandidates")),
        "draftItems": optional_positive_int(budget.get("draftItems")),
        "scriptDecisions": optional_positive_int(budget.get("scriptDecisions")),
        "textChars": optional_positive_int(budget.get("textChars")),
        "stdoutTenderCandidates": optional_positive_int(budget.get("stdoutTenderCandidates")),
        "stdoutDraftItems": optional_positive_int(budget.get("stdoutDraftItems")),
        "stdoutScriptDecisions": optional_positive_int(budget.get("stdoutScriptDecisions")),
    }


def optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def take_budgeted(items: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return items
    return items[:limit]


def take_stdout_budgeted(items: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return []
    return items[:limit]


def stdout_review_payload(review: dict[str, Any], review_budget: dict[str, int | None]) -> dict[str, Any]:
    candidates = review.get("tenderCandidatesForReview") if isinstance(review.get("tenderCandidatesForReview"), list) else []
    draft_items = review.get("draftItemsForReview") if isinstance(review.get("draftItemsForReview"), list) else []
    decisions = review.get("scriptDecisionSample") if isinstance(review.get("scriptDecisionSample"), list) else []
    return {
        "instruction": "Use this stdout digest for semantic review. If evidence is insufficient, return no agentDecisions instead of reading files.",
        "summary": review.get("summary") if isinstance(review.get("summary"), dict) else {},
        "tenderCandidates": take_stdout_budgeted(candidates, review_budget.get("stdoutTenderCandidates")),
        "draftItems": take_stdout_budgeted(draft_items, review_budget.get("stdoutDraftItems")),
        "scriptDecisions": take_stdout_budgeted(decisions, review_budget.get("stdoutScriptDecisions")),
    }


def review_candidate_payload(
    candidates: list[Candidate],
    decisions: list[dict[str, Any]],
    review_budget: dict[str, int | None],
) -> list[dict[str, Any]]:
    selected: list[Candidate] = []
    selected_ids: set[str] = set()
    limit = review_budget.get("tenderCandidates")
    for candidate in candidates:
        if candidate.kind in {"appendix", "appendix_group"}:
            selected.append(candidate)
            selected_ids.add(candidate.id)
            if limit is not None and len(selected) >= limit:
                return [slim_candidate(item, review_budget) for item in selected]
    for decision in decisions:
        candidate_id = str(decision.get("candidateId") or "")
        if not candidate_id or candidate_id in selected_ids:
            continue
        if decision.get("action") not in {"candidate", "covered"}:
            continue
        candidate = next((item for item in candidates if item.id == candidate_id), None)
        if candidate is None:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.id)
        if limit is not None and len(selected) >= limit:
            break
    return [slim_candidate(item, review_budget) for item in selected]


def review_item_payload(items: list[dict[str, Any]], review_budget: dict[str, int | None]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    limit = review_budget.get("draftItems")
    for item in items:
        if limit is None or item.get("annotation") == "新增-副表" or len(selected) < limit:
            selected.append(item)
        if limit is not None and len(selected) >= limit and item.get("annotation") != "新增-副表":
            continue
    return [
        {
            "itemId": item.get("itemId"),
            "number": item.get("number"),
            "title": item.get("title"),
            "level": item.get("level"),
            "annotation": item.get("annotation"),
            "source": item.get("source"),
            "sourceRefCount": len(item.get("source_refs") or []),
        }
        for item in selected
    ]


def slim_outline_entry(entry: OutlineEntry) -> dict[str, Any]:
    return {
        "number": entry.number,
        "title": entry.title,
        "level": entry.level,
        "paragraphIndex": entry.paragraph_index,
    }


def slim_candidate(candidate: Candidate, review_budget: dict[str, int | None]) -> dict[str, Any]:
    raw_text = normalize_space(candidate.raw_text)
    text_limit = review_budget.get("textChars")
    basis_text = raw_text[:text_limit] if text_limit is not None else raw_text
    return {
        "id": candidate.id,
        "title": candidate.title,
        "kind": candidate.kind,
        "number": candidate.number,
        "fileId": candidate.file_id,
        "fileName": candidate.file_name,
        "paragraphIndex": candidate.paragraph_index,
        "basisText": basis_text,
        "searchText": basis_text,
        "contextTitle": candidate.context_title,
    }


def slim_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidateId": decision.get("candidateId"),
        "title": decision.get("title"),
        "action": decision.get("action"),
        "source": decision.get("source"),
        "matchedTitle": decision.get("matchedTitle"),
        "relation": decision.get("relation"),
        "confidence": decision.get("confidence"),
        "reason": decision.get("reason"),
    }


JUDGE_PROMPT = """你是中文投标文件目录质检员。下面给你一份从客户投标模板里提取出来的目录条目列表，每条目录已带 number/title/level，以及它在原模板里的位置 paragraph_index。请逐条判断它是否真的是一条目录条目。

判断要点：
- 真正的目录条目应当是有人类可读的中文章节、节、附表标题
- 应该 DROP 的：纯数字 / 纯小数 / 风速区间 / 表头列名（如"风速 m/s"）/ 单位（如 "kg"）/ 签名行 / 备注 / 单纯说明性段落（"投标人应在投标文件中..."）/ 以图编号开头的图说明
- 不要 DROP 同名重复的目录条目（同一份模板里"认证未完成或存在待解决项"在不同附表下都应保留）
- 不要 DROP 你自己不确定的项；只 DROP 你高度确信是噪声的

严格只输出 JSON 数组，不要任何前后缀解释或代码块标记。每个元素：
{"index": <数字，输入数组里的下标>, "verdict": "KEEP" 或 "DROP", "reason": "简短原因"}

输入目录条目：
{items}
"""


def _run_outline_judge(
    items: list[dict[str, Any]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: int,
) -> dict[str, Any]:
    """Send the rule-based TOC items to an OpenAI-compatible LLM and ask it to
    drop obvious noise. Returns a dict with the parsed verdicts plus diagnostics.

    Raises on any error so the caller can fall through to the unfiltered output.
    The judge ONLY chooses KEEP or DROP; it never adds new items or modifies
    titles. That keeps the rule-based path strictly authoritative on shape and
    contents — the LLM is a noise-removal filter, nothing more."""

    if not items:
        return {"verdicts": [], "elapsed_s": 0.0, "model": model, "raw_content": ""}

    compact = [
        {
            "index": idx,
            "number": str(it.get("number") or ""),
            "title": str(it.get("title") or ""),
            "level": it.get("level"),
            "paragraph_index": it.get("paragraph_index") or it.get("paragraphIndex") or 0,
            "annotation": str(it.get("annotation") or ""),
        }
        for idx, it in enumerate(items)
    ]
    prompt = JUDGE_PROMPT.replace("{items}", json.dumps(compact, ensure_ascii=False))

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 16000,
    }).encode("utf-8")

    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    elapsed = time.monotonic() - t0

    payload = json.loads(raw)
    msg = payload["choices"][0]["message"]
    content = msg.get("content") or ""

    # Parse the JSON array from the model's content. Tolerate code-fence wrappers.
    text = content.strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if not arr_match:
        raise ValueError(f"judge returned no JSON array; content[:160]={content[:160]!r}")
    parsed = json.loads(arr_match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("judge returned non-list JSON")

    verdicts: list[dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        try:
            idx = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        verdict = str(entry.get("verdict") or "").upper().strip()
        if verdict not in {"KEEP", "DROP"}:
            continue
        verdicts.append({
            "index": idx,
            "verdict": verdict,
            "reason": str(entry.get("reason") or "")[:200],
        })

    usage = payload.get("usage", {}) or {}
    return {
        "verdicts": verdicts,
        "elapsed_s": round(elapsed, 2),
        "model": model,
        "raw_content": content[:4000],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
    }


def _judge_config_from_env() -> dict[str, Any] | None:
    """Read ``OUTLINE_JUDGE_*`` env vars. Returns ``None`` when the judge is
    disabled or any required field is missing."""

    if str(os.environ.get("OUTLINE_JUDGE_ENABLED", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    base_url = (os.environ.get("OUTLINE_JUDGE_BASE_URL") or "").strip()
    api_key = (os.environ.get("OUTLINE_JUDGE_API_KEY") or "").strip()
    model = (os.environ.get("OUTLINE_JUDGE_MODEL") or "").strip()
    if not (base_url and api_key and model):
        return None
    timeout_raw = os.environ.get("OUTLINE_JUDGE_TIMEOUT_SEC", "").strip()
    try:
        timeout_s = int(timeout_raw) if timeout_raw else 600
    except ValueError:
        timeout_s = 600
    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_s": max(60, min(timeout_s, 1800)),
    }


def _apply_outline_judge(
    items: list[dict[str, Any]],
    work_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """If the AI judge is configured, call it and DROP items it flags. Returns
    ``(filtered_items, review_payload)``. ``review_payload`` is always written
    to ``outline_judge_review.json`` for audit trail (including a "disabled" or
    "error" status when applicable). On any error, ``items`` is returned
    unchanged — the rule-based path is authoritative."""

    review: dict[str, Any] = {
        "schema_version": "bid-toc-outline-judge-v1",
        "status": "disabled",
        "input_item_count": len(items),
        "kept_item_count": len(items),
        "dropped_item_count": 0,
        "verdicts": [],
    }
    config = _judge_config_from_env()
    if config is None:
        _persist_judge_review(work_dir, review)
        return items, review

    review["status"] = "ran"
    review["model"] = config["model"]
    review["base_url"] = config["base_url"]
    try:
        result = _run_outline_judge(
            items,
            base_url=config["base_url"],
            api_key=config["api_key"],
            model=config["model"],
            timeout_s=config["timeout_s"],
        )
    except Exception as exc:  # network error / parse error / etc
        review["status"] = "error"
        review["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        _persist_judge_review(work_dir, review)
        logger.warning("outline judge failed; falling back to rule-only items: %s", review["error"])
        return items, review

    verdicts = result.get("verdicts", [])
    drop_indices: set[int] = {
        v["index"] for v in verdicts
        if v.get("verdict") == "DROP" and 0 <= v["index"] < len(items)
    }
    filtered = [it for idx, it in enumerate(items) if idx not in drop_indices]
    dropped_count = len(items) - len(filtered)
    # Safety net: never let the judge wipe out the TOC. If it tries to drop
    # more than half the items (hallucination, prompt misunderstanding, model
    # downtime returning garbage…), treat the verdict as untrusted and keep the
    # original rule-based items. The threshold is "more than half" rather than
    # "all" so a wildly aggressive judge can't get partial damage through, and
    # the audit file still records what it tried to do.
    if dropped_count > len(items) // 2:
        review["status"] = "rejected_too_aggressive"
        review["dropped_item_count"] = dropped_count
        review["verdicts"] = verdicts
        review.update({k: v for k, v in result.items() if k != "verdicts"})
        _persist_judge_review(work_dir, review)
        logger.warning(
            "outline judge tried to drop %d/%d items (>50%%); ignoring its verdicts",
            dropped_count,
            len(items),
        )
        return items, review

    review["status"] = "applied"
    review["verdicts"] = verdicts
    review["dropped_item_count"] = len(items) - len(filtered)
    review["kept_item_count"] = len(filtered)
    review["dropped_titles"] = [
        {"index": idx, "title": str(items[idx].get("title") or ""), "number": str(items[idx].get("number") or "")}
        for idx in sorted(drop_indices)
    ]
    review.update({k: v for k, v in result.items() if k != "verdicts"})
    _persist_judge_review(work_dir, review)
    return filtered, review


def _persist_judge_review(work_dir: Path, review: dict[str, Any]) -> None:
    try:
        path = work_dir / "outline_judge_review.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # pragma: no cover - audit log failure must never abort outline gen
        logger.exception("failed to persist outline_judge_review.json")


def extract_outline(path: Path) -> list[OutlineEntry]:
    paragraphs = iter_docx_paragraphs(path)
    toc_entries = outline_entries_from_toc_region(path, paragraphs)
    if toc_entries:
        return toc_entries
    heading_entries = outline_entries_from_paragraphs(
        path,
        [para for para in paragraphs if is_structural_heading_paragraph(para)],
    )
    if heading_entries:
        return heading_entries
    return outline_entries_from_paragraphs(
        path,
        [para for para in paragraphs if parse_heading_line(para.text, allow_body_list=False)],
    )


def outline_entries_from_toc_region(path: Path, paragraphs: list[Paragraph]) -> list[OutlineEntry]:
    start_index = next(
        (index for index, para in enumerate(paragraphs) if is_directory_marker(para.text)),
        -1,
    )
    if start_index < 0:
        return []

    region: list[Paragraph] = []
    found_entry = False
    explicit_toc_region = False
    for para in paragraphs[start_index + 1 :]:
        explicit_toc = is_explicit_toc_paragraph(para)
        if explicit_toc or (not explicit_toc_region and is_toc_region_paragraph(para)):
            parsed = parse_outline_paragraph(para, allow_body_list=False)
            if parsed:
                found_entry = True
                explicit_toc_region = explicit_toc_region or explicit_toc
            region.append(para)
            continue
        if found_entry:
            break
    return outline_entries_from_paragraphs(path, region, allow_body_list=False)


def outline_entries_from_paragraphs(
    path: Path,
    paragraphs: list[Paragraph],
    *,
    allow_body_list: bool = True,
) -> list[OutlineEntry]:
    entries: list[OutlineEntry] = []
    seen: set[tuple[str, str, int]] = set()
    for para in paragraphs:
        parsed = parse_outline_paragraph(para, allow_body_list=allow_body_list)
        if not parsed:
            continue
        key = (parsed["number"], parsed["title"], parsed["level"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            OutlineEntry(
                number=parsed["number"],
                title=parsed["title"],
                level=parsed["level"],
                source_file=str(path),
                paragraph_index=para.paragraph_index,
                raw_text=para.text,
            )
        )
    return normalize_levels(entries)


def is_directory_marker(text: str) -> bool:
    return re.sub(r"\s+", "", str(text or "")) == "目录"


def is_explicit_toc_paragraph(para: Paragraph) -> bool:
    style_text = f"{para.style_id} {para.style_name}".lower()
    if "toc" in style_text or "目录" in style_text:
        return True
    return para.tab_count > 0 and bool(parse_heading_line(para.text, allow_body_list=False))


def is_toc_region_paragraph(para: Paragraph) -> bool:
    if is_explicit_toc_paragraph(para):
        return True
    return bool(parse_heading_line(para.text, allow_body_list=False))


def is_structural_heading_paragraph(para: Paragraph) -> bool:
    if para.outline_level is not None:
        return True
    style_name = str(para.style_name or "")
    return bool(re.match(r"^heading\s*\d+$", style_name, flags=re.IGNORECASE))


def extract_candidates(sources: list[dict[str, Any]]) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    context_title = ""
    for source in sources:
        path = Path(str(source.get("path") or "")).expanduser()
        file_id = str(source.get("id") or "")
        file_name = str(source.get("name") or path.name)
        for para in iter_docx_paragraphs(path):
            for raw_candidate in candidates_from_line(para.text):
                if raw_candidate["kind"] in {"heading", "appendix_group"}:
                    context_title = raw_candidate["title"]
                key = title_key(raw_candidate["title"]) + "|" + raw_candidate["kind"] + "|" + file_name
                if not key.strip("|") or key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    Candidate(
                        id=f"TC-{len(candidates) + 1:04d}",
                        title=raw_candidate["title"],
                        raw_text=para.text,
                        source_file=str(path),
                        file_id=file_id,
                        file_name=file_name,
                        paragraph_index=para.paragraph_index,
                        kind=raw_candidate["kind"],
                        number=raw_candidate.get("number", ""),
                        context_title=context_title if raw_candidate["kind"] != "heading" else "",
                    )
                )
    return candidates


def build_items(
    template_outline: list[OutlineEntry],
    attach_outline: list[OutlineEntry],
    candidates: list[Candidate],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for entry in template_outline:
        item = toc_item_from_template(len(items) + 1, entry)
        items.append(item)
        decisions.append(
            {
                "title": entry.title,
                "action": "keep",
                "source": "template",
                "reason": "模板标题作为目录主骨架。",
                "sourceRef": outline_evidence(entry),
            }
        )

    template_index = [
        {
            "item": item,
            "key": title_key(str(item.get("title") or "")),
            "tokens": title_tokens(str(item.get("title") or "")),
        }
        for item in items
    ]
    appendix_candidates: list[Candidate] = []
    for candidate in candidates:
        if candidate.kind == "reference_appendix":
            decisions.append(
                {
                    "candidateId": candidate.id,
                    "title": candidate.title,
                    "action": "reference_only",
                    "source": "tender",
                    "reason": "招标文件附件/附录作为参考资料或规范附录，不自动写入投标文件目录。",
                    "sourceRef": candidate_evidence(candidate),
                }
            )
            continue
        if candidate.kind in {"appendix", "appendix_group"}:
            appendix_candidates.append(candidate)
            continue
        match = best_match(candidate, template_index)
        if match:
            ref = source_ref_from_candidate(candidate, relation=match["relation"], confidence=match["score"])
            match["item"].setdefault("source_refs", []).append(ref)
            decisions.append(
                {
                    "candidateId": candidate.id,
                    "title": candidate.title,
                    "action": "covered",
                    "source": "tender",
                    "matchedTitle": str(match["item"].get("title") or ""),
                    "relation": match["relation"],
                    "confidence": match["score"],
                    "reason": "招标要求语义上已被模板目录覆盖。",
                    "sourceRef": candidate_evidence(candidate),
                }
            )
        else:
            decisions.append(
                {
                    "candidateId": candidate.id,
                    "title": candidate.title,
                    "action": "candidate",
                    "source": "tender",
                    "reason": "招标要求未自动入目录，交给 Agent 语义审核。",
                    "sourceRef": candidate_evidence(candidate),
                }
            )

    covered_appendix_keys = {title_key(str(item.get("title") or "")) for item in items if "附" in str(item.get("title") or "")}
    for candidate in appendix_candidates:
        candidate_key = title_key(candidate.title)
        if candidate_key and candidate_key in covered_appendix_keys:
            continue
        items.append(toc_item_from_candidate(len(items) + 1, candidate))
        covered_appendix_keys.add(candidate_key)
        decisions.append(
            {
                "candidateId": candidate.id,
                "title": candidate.title,
                "action": "add",
                "source": "tender",
                "relation": "appendix_required",
                "confidence": 0.9,
                "reason": "招标文件明确出现附表/副表目录，追加到模板目录之后。",
                "sourceRef": candidate_evidence(candidate),
            }
        )

    attach_keys = {title_key(str(item.get("title") or "")) for item in items}
    for entry in attach_outline:
        key = title_key(entry.title)
        if key and key in attach_keys:
            continue
        items.append(toc_item_from_template(len(items) + 1, entry, annotation="保留", source="attachment"))
        attach_keys.add(key)

    for index, item in enumerate(items, start=1):
        item["order"] = index
        item["itemId"] = str(item.get("itemId") or f"TOC-{index:04d}")
    return items, decisions


def iter_docx_paragraphs(path: Path) -> list[Paragraph]:
    style_map = docx_styles(path)
    paragraphs: list[Paragraph] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as xml_file:
            index = 0
            for _, element in ET.iterparse(xml_file, events=("end",)):
                if element.tag != f"{WORD_NS}p":
                    continue
                index += 1
                text, tab_count = paragraph_text(element)
                style_id = paragraph_style_id(element)
                style_info = style_map.get(style_id, {})
                outline_level = paragraph_outline_level(element)
                if outline_level is None:
                    outline_level = style_info.get("outline_level")
                if text:
                    paragraphs.append(
                        Paragraph(
                            text=normalize_space(strip_page_number(text)),
                            style_id=style_id,
                            style_name=str(style_info.get("name") or style_id),
                            outline_level=outline_level,
                            paragraph_index=index,
                            tab_count=tab_count,
                        )
                    )
                element.clear()
    return paragraphs


def docx_styles(path: Path) -> dict[str, dict[str, Any]]:
    styles: dict[str, dict[str, Any]] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/styles.xml")
    except Exception:
        return styles
    root = ET.fromstring(xml)
    for style in root.findall(f".//{WORD_NS}style"):
        style_id = str(style.attrib.get(f"{WORD_NS}styleId") or "")
        if not style_id:
            continue
        name = ""
        name_el = style.find(f"{WORD_NS}name")
        if name_el is not None:
            name = str(name_el.attrib.get(f"{WORD_NS}val") or "")
        outline_level = None
        outline_el = style.find(f".//{WORD_NS}outlineLvl")
        if outline_el is not None:
            outline_level = word_outline_level(outline_el.attrib.get(f"{WORD_NS}val"))
        styles[style_id] = {"name": name, "outline_level": outline_level}
    return styles


def paragraph_text(element: ET.Element) -> tuple[str, int]:
    parts: list[str] = []
    tab_count = 0
    for child in element.iter():
        if child.tag == f"{WORD_NS}t":
            parts.append(child.text or "")
        elif child.tag == f"{WORD_NS}tab":
            tab_count += 1
            parts.append(" ")
        elif child.tag in {f"{WORD_NS}br", f"{WORD_NS}cr"}:
            parts.append(" ")
    return "".join(parts), tab_count


def paragraph_style_id(element: ET.Element) -> str:
    style = element.find(f".//{WORD_NS}pStyle")
    if style is None:
        return ""
    return str(style.attrib.get(f"{WORD_NS}val") or "")


def paragraph_outline_level(element: ET.Element) -> int | None:
    outline = element.find(f".//{WORD_NS}outlineLvl")
    if outline is None:
        return None
    return word_outline_level(outline.attrib.get(f"{WORD_NS}val"))


def word_outline_level(value: Any) -> int | None:
    try:
        return int(str(value)) + 1
    except (TypeError, ValueError):
        return None


def parse_outline_paragraph(para: Paragraph, *, allow_body_list: bool = True) -> dict[str, Any] | None:
    text = normalize_space(para.text)
    if not text or title_key(text) in {"", "目录"}:
        return None
    parsed = parse_heading_line(text, allow_body_list=allow_body_list)
    level = parsed["level"] if parsed else None
    if para.outline_level is not None:
        level = para.outline_level
    elif re.match(r"^heading\s*\d+$", para.style_name, flags=re.IGNORECASE):
        level = int(re.findall(r"\d+", para.style_name)[0])
    if parsed is None and level is None:
        return None
    number = parsed["number"] if parsed else ""
    title = clean_title(parsed["title"] if parsed else strip_heading_number(text))
    # Defense in depth against table-cell paragraphs leaking through with a
    # heading style. A real heading must contain at least one Chinese
    # ideograph or Latin letter; pure-digit / punctuation-only "titles"
    # (e.g. ``216`` from a power curve cell) are noise.
    if not re.search(r"[一-鿿A-Za-z]", title):
        return None
    return {"number": number, "title": title, "level": max(1, int(level or 1))}


def parse_heading_line(text: str, *, allow_body_list: bool = True) -> dict[str, Any] | None:
    clean = normalize_space(strip_page_number(text))
    appendix = APPENDIX_PATTERN.match(clean)
    if appendix:
        number = normalize_space(appendix.group("number"))
        title = clean_title(appendix.group("title"))
        return {"number": number, "title": title, "level": 1}
    patterns = HEADING_PATTERNS if allow_body_list else HEADING_PATTERNS[:3]
    for pattern in patterns:
        match = pattern.match(clean)
        if not match:
            continue
        number = normalize_space(match.group("num"))
        title = clean_title(match.group("title"))
        return {"number": display_number(clean, number), "title": title, "level": level_from_number(number)}
    return None


def candidates_from_line(line: str) -> list[dict[str, str]]:
    text = normalize_space(strip_page_number(line))
    if not text:
        return []
    results: list[dict[str, str]] = []
    appendix = APPENDIX_PATTERN.match(text)
    if appendix:
        number = normalize_space(appendix.group("number"))
        title = clean_title(appendix.group("title"))
        if is_bid_appendix_number(number):
            kind = "appendix_group" if re.fullmatch(r"(?:技术\s*)?(?:附表|副表)\s*[A-Za-z一二三四五六七八九十百千万零〇两]+", number) else "appendix"
        else:
            kind = "reference_appendix"
        results.append({"kind": kind, "number": number, "title": f"{number} {title}".strip()})
        return results
    heading = parse_heading_line(text)
    if heading and heading["title"]:
        results.append({"kind": "heading", "number": heading["number"], "title": heading["title"]})
    for pattern in REQUIREMENT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        title = clean_requirement_title(match.group("title"))
        if usable_requirement_title(title):
            results.append({"kind": "requirement", "number": "", "title": title})
    return dedupe_raw_candidates(results)


def normalize_levels(entries: list[OutlineEntry]) -> list[OutlineEntry]:
    normalized: list[OutlineEntry] = []
    stack: list[int] = []
    for entry in entries:
        level = max(1, entry.level)
        if not stack and level > 1:
            level = 1
        elif stack and level > stack[-1] + 1:
            level = stack[-1] + 1
        while stack and stack[-1] >= level:
            stack.pop()
        stack.append(level)
        normalized.append(
            OutlineEntry(
                number=entry.number,
                title=entry.title,
                level=level,
                source_file=entry.source_file,
                paragraph_index=entry.paragraph_index,
                raw_text=entry.raw_text,
            )
        )
    return normalized


def toc_item_from_template(order: int, entry: OutlineEntry, annotation: str = "保留", source: str = "template") -> dict[str, Any]:
    return {
        "itemId": f"TOC-{order:04d}",
        "order": order,
        "number": entry.number,
        "title": entry.title,
        "level": entry.level,
        "annotation": annotation,
        "source": source,
        "reason": "来自投标模板目录骨架。",
        "source_refs": [
            {
                "type": "template",
                "role": "skeleton",
                "path": entry.source_file,
                "paragraphIndex": entry.paragraph_index,
                "raw_text": entry.raw_text,
                "rawText": entry.raw_text,
                "basisText": entry.raw_text,
            }
        ],
        "material_refs": [],
    }


def toc_item_from_candidate(order: int, candidate: Candidate) -> dict[str, Any]:
    return {
        "itemId": f"TOC-{order:04d}",
        "order": order,
        "number": candidate.number,
        "title": appendix_title_without_number(candidate),
        "level": 1,
        "annotation": "新增-副表",
        "source": "tender",
        "reason": "招标文件明确列出附表/副表目录。",
        "source_refs": [source_ref_from_candidate(candidate, relation="appendix_required", confidence=0.9)],
        "material_refs": [],
    }


def source_ref_from_candidate(candidate: Candidate, relation: str, confidence: float, reason: str = "") -> dict[str, Any]:
    basis_text = normalize_space(candidate.raw_text)
    return {
        "type": "tender",
        "role": "basis",
        "kind": "codex_semantic",
        "candidateKind": candidate.kind,
        "candidateId": candidate.id,
        "relation": relation,
        "confidence": round(float(confidence), 3),
        "reason": reason or relation_reason(relation),
        "fileId": candidate.file_id,
        "fileName": candidate.file_name,
        "path": candidate.source_file,
        "paragraphIndex": candidate.paragraph_index,
        "raw_text": candidate.raw_text,
        "rawText": candidate.raw_text,
        "basisText": basis_text,
        "searchText": basis_text,
        "title": candidate.title,
        "number": candidate.number,
        "contextTitle": candidate.context_title,
    }


def best_match(candidate: Candidate, template_index: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate_key = title_key(" ".join([candidate.title, candidate.context_title, candidate.raw_text]))
    candidate_tokens = title_tokens(candidate_key)
    best: dict[str, Any] | None = None
    for record in template_index:
        score = match_score(candidate_key, candidate_tokens, str(record.get("key") or ""), set(record.get("tokens") or set()))
        if best is None or score > best["score"]:
            best = {"item": record["item"], "score": score}
    if best is None or best["score"] < match_threshold(candidate):
        return None
    relation = "direct_requirement" if best["score"] >= 0.86 else "supporting_requirement"
    return {**best, "relation": relation}


def match_score(candidate_key: str, candidate_tokens: set[str], title_key_value: str, title_token_values: set[str]) -> float:
    if not candidate_key or not title_key_value:
        return 0.0
    if candidate_key in title_key_value or title_key_value in candidate_key:
        return 1.0
    if not candidate_tokens or not title_token_values:
        return 0.0
    overlap = candidate_tokens & title_token_values
    return len(overlap) / max(1, min(len(candidate_tokens), len(title_token_values)))


def match_threshold(candidate: Candidate) -> float:
    if candidate.kind == "heading":
        return 0.58
    return 0.66


def is_bid_appendix_number(number: str) -> bool:
    compact = re.sub(r"\s+", "", normalize_space(number))
    return compact.startswith(("技术附表", "附表", "副表"))


def relation_reason(relation: str) -> str:
    return {
        "direct_requirement": "目录项与招标要求直接对应。",
        "supporting_requirement": "目录项可承接该招标要求。",
        "appendix_required": "招标文件明确要求该附表/副表。",
    }.get(relation, "语义审核依据。")


def outline_evidence(entry: OutlineEntry) -> dict[str, Any]:
    return {
        "number": entry.number,
        "title": entry.title,
        "level": entry.level,
        "sourceFile": entry.source_file,
        "paragraphIndex": entry.paragraph_index,
        "rawText": entry.raw_text,
    }


def candidate_evidence(candidate: Candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "title": candidate.title,
        "kind": candidate.kind,
        "number": candidate.number,
        "fileId": candidate.file_id,
        "fileName": candidate.file_name,
        "sourceFile": candidate.source_file,
        "paragraphIndex": candidate.paragraph_index,
        "rawText": candidate.raw_text,
        "basisText": normalize_space(candidate.raw_text),
        "searchText": normalize_space(candidate.raw_text),
        "contextTitle": candidate.context_title,
    }


def appendix_title_without_number(candidate: Candidate) -> str:
    number = normalize_space(candidate.number)
    title = candidate.title
    if number and title.startswith(number):
        return clean_title(title[len(number) :])
    return normalize_space(title)


def title_key(value: str) -> str:
    text = clean_title(value).lower()
    text = TITLE_KEY_DROP.sub("", text)
    text = re.sub(r"[\s　,，.。:：;；、（）()\[\]【】《》<>\"'“”‘’\-_/\\]+", "", text)
    text = re.sub(r"(方案|计划|安排|要求|说明|响应|材料|文件|内容)$", "", text)
    return text


def title_tokens(value: str) -> set[str]:
    text = title_key(value)
    raw_tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+", text)
    tokens: set[str] = set()
    for token in raw_tokens:
        if token in NOISE_TOKENS:
            continue
        if len(token) <= 6:
            tokens.add(token)
        else:
            for size in (2, 3, 4):
                for index in range(0, len(token) - size + 1):
                    tokens.add(token[index : index + size])
    return tokens


def clean_title(value: str) -> str:
    text = normalize_space(value)
    text = re.sub(r"^[：:、,，.。;\-—~]+", "", text)
    text = re.sub(r"[。；;]+$", "", text)
    return text.strip()


def clean_requirement_title(value: str) -> str:
    text = clean_title(value)
    text = re.sub(r"^(?:提供|提交|编制|说明|承诺|响应)", "", text)
    return clean_title(text)


def strip_heading_number(value: str) -> str:
    parsed = parse_heading_line(value)
    if parsed:
        return parsed["title"]
    return clean_title(value)


def strip_page_number(value: str) -> str:
    """Strip a trailing TOC-style page number (e.g. ``1.1 项目概况 ......... 12``).

    Defensive against table-cell numeric values (e.g. ``216.9`` from a power
    curve appendix in the bid template). The rule is: only commit to the
    strip if the result still contains real heading content — at least one
    Chinese ideograph or Latin letter. Otherwise the input is itself a
    numeric value (``216.9``, ``2.75-3.25``, ``3.5``) and we must keep it
    intact, otherwise downstream identifies it as a noise TOC item.

    Without this guard, the previous regex would mangle ``216.9`` into
    ``216`` because the dot is in the separator class — bug surfaced when
    13 spurious GAP items appeared in S3 with titles like ``216``, ``367``."""

    text = normalize_space(value)
    stripped = re.sub(r"[\s　.．·•-]*(?:第\s*)?\d{1,4}\s*(?:页)?$", "", text).strip()
    if not re.search(r"[一-鿿A-Za-z]", stripped):
        return text
    return stripped


def level_from_number(number: str) -> int:
    value = normalize_space(number)
    if "." in value:
        return value.count(".") + 1
    return 1


def display_number(line: str, number: str) -> str:
    if line.startswith("第") and "章" in line:
        return f"第{number}章"
    return number


def usable_requirement_title(title: str) -> bool:
    key = title_key(title)
    if not key or key in NOISE_TOKENS:
        return False
    return len(key) >= 2


def dedupe_raw_candidates(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        key = item.get("kind", "") + "|" + title_key(item.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def existing_path(value: Any, label: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if not str(value or "").strip() or not path.exists():
        raise SystemExit(f"{label} not found: {value}")
    return path


def optional_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    return path if path.exists() else None


def tender_inputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in manifest.get("tenderFiles") or []:
        raw_path = item.get("path") if isinstance(item, dict) else item
        path = Path(str(raw_path or "")).expanduser()
        if path.exists() and path.suffix.lower() == ".docx":
            result.append(
                {
                    "id": str(item.get("id") or "") if isinstance(item, dict) else "",
                    "name": str(item.get("name") or path.name) if isinstance(item, dict) else path.name,
                    "path": str(path),
                    "originalPath": str(item.get("originalPath") or "") if isinstance(item, dict) else "",
                }
            )
    fallback = Path(str(manifest.get("tenderFile") or "")).expanduser()
    known = {str(item.get("path") or "") for item in result}
    if fallback.exists() and fallback.suffix.lower() == ".docx" and str(fallback) not in known:
        result.append({"id": "", "name": fallback.name, "path": str(fallback), "originalPath": ""})
    if not result:
        raise SystemExit("no docx tender files found in manifest")
    return result


def source_file_payload(item: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "path": str(item.get("path") or ""),
        "originalPath": str(item.get("originalPath") or ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
