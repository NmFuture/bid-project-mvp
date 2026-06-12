from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from scripts.anchor_detector import detect_candidate_anchors, write_candidate_windows
from scripts.boundary_planner import plan_boundaries
from scripts.boundary_validator import validate_boundaries
from scripts.docx_blocks import extract_blocks
from scripts.docx_slicer import slice_docx_by_boundaries
from scripts.header_cluster_detector import detect_header_clusters
from scripts.region_detector import detect_excluded_format_regions, detect_format_regions
from scripts.report_writer import write_review


BOUNDARY_DECISIONS_SCHEMA_VERSION = "bid-business-template-extractor-boundary-decisions-v1"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def _load_or_prepare_candidates(source_docx: Path, output_dir: Path, *, clean: bool) -> dict[str, Any]:
    source_docx = source_docx.resolve()
    output_dir = output_dir.resolve()
    if not source_docx.is_file():
        raise FileNotFoundError(f"找不到招标文件：{source_docx}")
    if clean:
        _clean_output_dir(output_dir)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    blocks = extract_blocks(source_docx)
    regions = detect_format_regions(blocks)
    excluded_regions = detect_excluded_format_regions(blocks)
    anchors = detect_candidate_anchors(blocks, regions)
    anchors = _merge_synthetic_structural_anchors(blocks, regions, anchors)
    candidate_templates = _candidate_templates(anchors)
    anchors = _anchors_with_candidate_ids(anchors, candidate_templates)
    windows = write_candidate_windows(blocks, regions, anchors)

    write_json(output_dir / "blocks.json", blocks)
    write_json(output_dir / "regions.json", regions)
    write_json(output_dir / "excluded_regions.json", excluded_regions)
    write_json(output_dir / "candidate_templates.json", candidate_templates)
    write_json(output_dir / "candidate_windows.json", windows)
    return {
        "source": str(source_docx),
        "outputDir": str(output_dir),
        "blocks": blocks,
        "regions": regions,
        "excludedRegions": excluded_regions,
        "anchors": anchors,
        "windows": windows,
    }


def _merge_synthetic_structural_anchors(blocks: list[dict], regions: list[dict], anchors: list[dict]) -> list[dict]:
    by_block_id: dict[int, dict] = {int(anchor["blockId"]): dict(anchor) for anchor in anchors}
    clusters_by_region = detect_header_clusters(blocks, regions, anchors)
    for clusters in clusters_by_region.values():
        for cluster in clusters:
            anchor = dict(cluster.get("anchor") or {})
            if not anchor:
                continue
            block_id = int(anchor["blockId"])
            if block_id in by_block_id:
                existing = by_block_id[block_id]
                existing_signals = existing.get("signals") if isinstance(existing.get("signals"), list) else []
                anchor_signals = anchor.get("signals") if isinstance(anchor.get("signals"), list) else []
                existing["signals"] = sorted(set(existing_signals + anchor_signals))
                continue
            by_block_id[block_id] = anchor
    merged = list(by_block_id.values())
    merged.sort(key=lambda item: int(item["blockId"]))
    for index, anchor in enumerate(merged, 1):
        prefix = "SYN" if str(anchor.get("source") or "") == "synthetic" else "ANC"
        anchor["id"] = anchor.get("id") or f"{prefix}-{index:04d}"
    return merged


def _candidate_templates(anchors: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for index, anchor in enumerate(anchors, 1):
        candidates.append(
            {
                "candidateId": f"CAND-{index:04d}",
                "candidateBlockId": anchor.get("blockId"),
                "text": anchor.get("text") or "",
                "regionId": anchor.get("regionId") or "",
                "regionTitle": anchor.get("regionTitle") or "",
                "score": anchor.get("score"),
                "signals": anchor.get("signals") or [],
                "anchorId": anchor.get("id") or "",
            }
        )
    return candidates


def _anchors_with_candidate_ids(anchors: list[dict], candidates: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for anchor, candidate in zip(anchors, candidates):
        item = dict(anchor)
        item["candidateId"] = candidate["candidateId"]
        item["candidateBlockId"] = candidate["candidateBlockId"]
        enriched.append(item)
    return enriched


def _empty_quality(prepared: dict[str, Any]) -> dict[str, Any]:
    return {
        "formatRegionCount": len(prepared["regions"]),
        "excludedRegionCount": len(prepared["excludedRegions"]),
        "candidateAnchorCount": len(prepared["anchors"]),
        "candidateTemplateCount": len(prepared["anchors"]),
        "draftTemplateCount": 0,
        "validatedTemplateCount": 0,
        "catalogRejectedCount": 0,
        "outsideFormatRegionRejectedCount": 0,
        "lowConfidenceCount": 0,
        "needsReviewCount": 0,
        "agentDecisionCount": 0,
        "agentRejectedCount": 0,
        "headingDecisionCount": 0,
        "acceptedTemplateCount": 0,
        "boundaryReferenceCount": 0,
        "sectionContainerCount": 0,
        "boundaryOnlyCount": 0,
        "rejectedCount": 0,
        "scriptFallbackUsed": False,
    }


def _summary(prepared: dict[str, Any], template_count: int) -> dict[str, Any]:
    return {
        "blockCount": len(prepared["blocks"]),
        "regionCount": len(prepared["regions"]),
        "anchorCount": len(prepared["anchors"]),
        "templateCount": template_count,
    }


def _base_result(prepared: dict[str, Any], *, stage: str, template_count: int = 0) -> dict[str, Any]:
    return {
        "source": prepared["source"],
        "outputDir": prepared["outputDir"],
        "stage": stage,
        "formatRegions": prepared["regions"],
        "excludedRegions": prepared["excludedRegions"],
        "rejectedCandidates": [],
        "warnings": [],
        "quality": _empty_quality(prepared),
        "summary": _summary(prepared, template_count),
    }


def _region_for_block(regions: list[dict], block_id: int) -> dict | None:
    for region in regions:
        if int(region["startBlockId"]) <= block_id <= int(region["endBlockId"]):
            return region
    return None


def _decision_to_template(decision: dict, index: int, regions: list[dict]) -> dict | None:
    if not bool(decision.get("isTemplateStart")):
        return None
    start = int(decision.get("startBlockId") or decision.get("candidateBlockId") or 0)
    end = int(decision.get("endBlockId") or 0)
    region = _region_for_block(regions, start)
    title = str(decision.get("templateTitle") or "").strip()
    return {
        "id": f"TPL-{index:04d}",
        "candidateId": decision.get("candidateId"),
        "candidateBlockId": decision.get("candidateBlockId"),
        "title": title,
        "templateType": str(decision.get("templateType") or "business_template"),
        "regionId": region.get("id") if region else "",
        "regionTitle": region.get("title") if region else "",
        "startBlockId": start,
        "endBlockId": end,
        "anchorBlockId": decision.get("candidateBlockId"),
        "headerBlockIds": [start],
        "confidence": float(decision.get("confidence") or 0),
        "decisionSource": str(decision.get("decider") or "executing_agent"),
        "reason": str(decision.get("reason") or ""),
        "needsReview": bool(decision.get("needsReview")),
        "rejectReason": str(decision.get("rejectReason") or ""),
        "signals": ["agent_decision"],
    }


def _validate_decision_contract(decision: dict) -> None:
    required = [
        "candidateId",
        "candidateBlockId",
        "isTemplateStart",
        "rejectReason",
        "templateTitle",
        "templateType",
        "startBlockId",
        "endBlockId",
        "confidence",
        "reason",
        "needsReview",
    ]
    missing = [field for field in required if field not in decision]
    if missing:
        raise ValueError(f"llm_boundary_decisions.json decision 缺少字段：{', '.join(missing)}。")


def _agent_boundaries_from_decisions(path: Path, regions: list[dict]) -> tuple[dict[str, Any], list[dict], dict[str, int]]:
    payload = read_json(path)
    if payload.get("schemaVersion") != BOUNDARY_DECISIONS_SCHEMA_VERSION:
        raise ValueError(f"llm_boundary_decisions.json schemaVersion 必须为 {BOUNDARY_DECISIONS_SCHEMA_VERSION}。")
    if payload.get("decider") != "executing_agent":
        raise ValueError('llm_boundary_decisions.json decider 必须为 "executing_agent"。')
    if not isinstance(payload.get("decisions"), list):
        raise ValueError("llm_boundary_decisions.json 必须包含 decisions[]。")
    decisions = payload["decisions"]
    templates: list[dict] = []
    rejected: list[dict] = []
    boundary_reference_count = 0
    section_container_count = 0
    boundary_only_count = 0
    agent_rejected_count = 0
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        _validate_decision_contract(decision)
        heading_role = str(decision.get("headingRole") or ("template_start" if decision.get("isTemplateStart") else "reject"))
        is_boundary_reference = heading_role in {"template_start", "section_container", "boundary_only"}
        if is_boundary_reference:
            boundary_reference_count += 1
        if heading_role == "section_container":
            section_container_count += 1
        elif heading_role == "boundary_only":
            boundary_only_count += 1
        elif heading_role == "reject":
            agent_rejected_count += 1
        if not bool(decision.get("isTemplateStart")):
            reject_reason = str(decision.get("rejectReason") or ("agent 裁决为边界参考，不输出模板。" if is_boundary_reference else "agent 裁决为非模板起点。"))
            if heading_role == "section_container":
                reject_code = "section_container"
            elif heading_role == "boundary_only":
                reject_code = "boundary_only"
            else:
                reject_code = "catalog_contamination" if ("目录" in reject_reason or "catalog" in reject_reason.lower()) else "agent_rejected"
            rejected.append(
                {
                    "candidateId": decision.get("candidateId"),
                    "candidateBlockId": decision.get("candidateBlockId"),
                    "templateTitle": decision.get("templateTitle"),
                    "headingRole": heading_role,
                    "isBoundaryReference": is_boundary_reference,
                    "rejectCode": reject_code,
                    "rejectReason": reject_reason,
                    "decisionSource": "executing_agent",
                }
            )
            continue
        template = _decision_to_template(decision, len(templates) + 1, regions)
        if template is not None:
            templates.append(template)
    metrics = {
        "agentDecisionCount": len(decisions),
        "agentRejectedCount": agent_rejected_count,
        "headingDecisionCount": len(decisions),
        "acceptedTemplateCount": len(templates),
        "boundaryReferenceCount": boundary_reference_count,
        "sectionContainerCount": section_container_count,
        "boundaryOnlyCount": boundary_only_count,
        "rejectedCount": agent_rejected_count,
    }
    return {"templates": templates}, rejected, metrics


def _count_rejections(rejected: list[dict], code: str) -> int:
    return sum(1 for item in rejected if item.get("rejectCode") == code)


def _finalize_with_boundaries(
    source_docx: Path,
    output_dir: Path,
    prepared: dict[str, Any],
    draft_boundaries: dict[str, Any],
    *,
    fallback_used: bool,
    initial_rejections: list[dict] | None = None,
    agent_metrics: dict[str, int] | None = None,
) -> dict[str, Any]:
    templates_dir = output_dir / "templates"
    if templates_dir.exists():
        shutil.rmtree(templates_dir)
    validation = validate_boundaries(
        prepared["blocks"],
        prepared["regions"],
        draft_boundaries,
        reject_low_confidence=True,
        strict=False,
        raise_on_empty=False,
    )
    validated_templates = validation.get("templates") or []
    rejected = list(initial_rejections or []) + list(validation.get("rejectedTemplates") or [])
    boundaries = {"templates": validated_templates, "rejectedTemplates": rejected}
    if validated_templates:
        sliced_boundaries = slice_docx_by_boundaries(source_docx, prepared["blocks"], boundaries, output_dir)
        boundaries = {"templates": sliced_boundaries["templates"], "rejectedTemplates": rejected}
    write_json(output_dir / "boundaries.json", boundaries)
    write_review(output_dir, source_docx, prepared["regions"], boundaries)

    result = _base_result(prepared, stage="finalize", template_count=len(boundaries["templates"]))
    result["rejectedCandidates"] = rejected
    result["quality"]["draftTemplateCount"] = len(draft_boundaries.get("templates") or [])
    result["quality"]["validatedTemplateCount"] = len(boundaries["templates"])
    result["quality"]["acceptedTemplateCount"] = len(boundaries["templates"])
    result["quality"]["catalogRejectedCount"] = _count_rejections(rejected, "catalog_contamination")
    result["quality"]["outsideFormatRegionRejectedCount"] = _count_rejections(rejected, "outside_format_region")
    result["quality"]["lowConfidenceCount"] = _count_rejections(rejected, "low_confidence")
    result["quality"]["needsReviewCount"] = _count_rejections(rejected, "needs_review")
    result["quality"]["scriptFallbackUsed"] = fallback_used
    for key, value in (agent_metrics or {}).items():
        result["quality"][key] = value
    result["summary"] = _summary(prepared, len(boundaries["templates"]))
    for key in (
        "headingDecisionCount",
        "acceptedTemplateCount",
        "boundaryReferenceCount",
        "sectionContainerCount",
        "boundaryOnlyCount",
        "rejectedCount",
    ):
        if key in result["quality"]:
            result["summary"][key] = result["quality"][key]
    return result


def run_pipeline(source_docx: Path, output_dir: Path, *, stage: str = "finalize", fallback_mode: str = "") -> dict:
    source_docx = source_docx.resolve()
    output_dir = output_dir.resolve()
    normalized_stage = (stage or "finalize").lower()
    if normalized_stage not in {"prepare", "finalize"}:
        raise ValueError(f"未知模板提取阶段：{stage}")

    prepared = _load_or_prepare_candidates(source_docx, output_dir, clean=normalized_stage == "prepare")
    if normalized_stage == "prepare":
        write_review(output_dir, source_docx, prepared["regions"], {"templates": [], "rejectedTemplates": []})
        return _base_result(prepared, stage="prepare")

    decisions_path = output_dir / "llm_boundary_decisions.json"
    if decisions_path.is_file():
        try:
            draft_boundaries, agent_rejected, agent_metrics = _agent_boundaries_from_decisions(decisions_path, prepared["regions"])
        except ValueError as exc:
            result = _base_result(prepared, stage="finalize")
            result["warnings"].append(
                {
                    "code": "invalid_agent_decisions",
                    "message": str(exc),
                }
            )
            write_review(output_dir, source_docx, prepared["regions"], {"templates": [], "rejectedTemplates": []})
            return result
        write_json(output_dir / "boundaries.agent.json", draft_boundaries)
        return _finalize_with_boundaries(
            source_docx,
            output_dir,
            prepared,
            draft_boundaries,
            fallback_used=False,
            initial_rejections=agent_rejected,
            agent_metrics=agent_metrics,
        )

    if fallback_mode == "script":
        draft_boundaries = plan_boundaries(prepared["blocks"], prepared["regions"], prepared["anchors"])
        write_json(output_dir / "boundaries.draft.json", draft_boundaries)
        return _finalize_with_boundaries(
            source_docx,
            output_dir,
            prepared,
            draft_boundaries,
            fallback_used=True,
        )

    result = _base_result(prepared, stage="finalize")
    result["warnings"].append(
        {
            "code": "missing_agent_decisions",
            "message": "缺少 agent 裁决文件 llm_boundary_decisions.json，默认不执行模板切片。",
        }
    )
    write_review(output_dir, source_docx, prepared["regions"], {"templates": [], "rejectedTemplates": []})
    return result
