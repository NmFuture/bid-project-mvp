from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


BOUNDARY_DECISIONS_SCHEMA_VERSION = "bid-business-template-extractor-boundary-decisions-v1"
WORKFLOW_SCHEMA_VERSION = "bid-business-template-extractor-btplbound-v1"
BATCH_SIZE = 8
BOUNDARY_REFERENCE_ROLES = {"template_start", "section_container", "boundary_only"}
HEADING_ROLES = BOUNDARY_REFERENCE_ROLES | {"reject"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_name(value: str, fallback: str) -> str:
    text = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in value).strip()
    return text or fallback


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    return manifest


def manifest_output_dir(manifest: dict[str, Any], manifest_path: Path) -> Path:
    return Path(str(manifest.get("outputDir") or manifest_path.parent / "business_template_extraction")).resolve()


def document_outputs(manifest: dict[str, Any], manifest_path: Path) -> list[dict[str, Any]]:
    output_dir = manifest_output_dir(manifest, manifest_path)
    result_path = output_dir / "business_template_extraction.json"
    payload_docs: list[dict[str, Any]] = []
    if result_path.is_file():
        try:
            payload = read_json(result_path)
            if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
                payload_docs = [item for item in payload["documents"] if isinstance(item, dict)]
        except Exception:
            payload_docs = []

    docs = manifest.get("documents") if isinstance(manifest.get("documents"), list) else []
    by_id = {str(item.get("id") or ""): item for item in docs if isinstance(item, dict)}
    outputs: list[dict[str, Any]] = []
    if payload_docs:
        for index, item in enumerate(payload_docs, 1):
            raw_output = str(item.get("outputDir") or "").strip()
            if not raw_output:
                continue
            document_id = str(item.get("id") or f"DOC-{index}")
            manifest_doc = by_id.get(document_id, {})
            outputs.append(
                {
                    "id": document_id,
                    "name": str(item.get("name") or manifest_doc.get("name") or ""),
                    "sourcePath": str(item.get("sourcePath") or manifest_doc.get("sourcePath") or ""),
                    "outputDir": str(Path(raw_output).resolve()),
                }
            )
        if outputs:
            return outputs

    for index, document in enumerate(docs, 1):
        if not isinstance(document, dict):
            continue
        source = Path(str(document.get("sourcePath") or ""))
        document_id = str(document.get("id") or "")
        output_name = safe_name(document_id or source.stem, f"document-{index}")
        outputs.append(
            {
                "id": document_id,
                "name": str(document.get("name") or source.name),
                "sourcePath": str(source),
                "outputDir": str((output_dir / output_name).resolve()),
            }
        )
    return outputs


def load_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = read_json(path)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def batch_dir(document_output: Path) -> Path:
    return document_output / "agent_decision_batches"


def phase_path(document_output: Path, phase: str, batch_no: int) -> Path:
    return batch_dir(document_output) / f"{phase}_decision_batch_{batch_no:04d}.json"


def audit_batch_path(document_output: Path, phase: str, batch_no: int) -> Path:
    return batch_dir(document_output) / f"{phase}_batch_{batch_no:04d}.json"


def compact_block(block: dict[str, Any]) -> dict[str, Any]:
    text = str(block.get("text") or "")
    item: dict[str, Any] = {
        "blockId": block.get("blockId"),
        "type": str(block.get("type") or ""),
        "text": text[:800],
    }
    if block.get("rows"):
        item["rows"] = block.get("rows")
    for key in ("styleName", "isCentered", "isLikelyHeading", "pageSegment", "positionInPageSegment", "isPageFirstNonEmpty"):
        if key in block:
            item[key] = block.get(key)
    return item


def read_document_artifacts(document: dict[str, Any]) -> dict[str, Any]:
    output = Path(str(document["outputDir"]))
    candidates = load_list(output / "candidate_templates.json")
    windows = load_list(output / "candidate_windows.json")
    blocks = load_list(output / "blocks.json")
    regions = load_list(output / "regions.json")
    windows_by_candidate = {str(item.get("candidateId") or ""): item for item in windows}
    blocks_by_id = {}
    for block in blocks:
        try:
            blocks_by_id[int(block["blockId"])] = block
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "document": document,
        "outputDir": output,
        "candidates": candidates,
        "windowsByCandidate": windows_by_candidate,
        "blocks": blocks,
        "blocksById": blocks_by_id,
        "regions": regions,
    }


def all_document_artifacts(manifest: dict[str, Any], manifest_path: Path) -> list[dict[str, Any]]:
    return [read_document_artifacts(document) for document in document_outputs(manifest, manifest_path)]


def chunked(items: list[dict[str, Any]], size: int = BATCH_SIZE) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def candidate_batches(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    batch_no = 1
    for artifact in artifacts:
        for candidates in chunked(artifact["candidates"]):
            batches.append({"batchNo": batch_no, "artifact": artifact, "candidates": candidates})
            batch_no += 1
    return batches


def decision_ids(payload: dict[str, Any]) -> list[str]:
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
    return [str(item.get("candidateId") or "") for item in decisions if isinstance(item, dict)]


def read_saved_decision(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def normalize_candidate_for_batch(candidate: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidateId") or "")
    window = artifact["windowsByCandidate"].get(candidate_id, {})
    evidence_blocks = []
    for block in window.get("blocks") or []:
        if isinstance(block, dict):
            evidence_blocks.append(compact_block(block))
    return {
        "candidateId": candidate_id,
        "candidateBlockId": candidate.get("candidateBlockId"),
        "text": str(candidate.get("text") or candidate.get("title") or ""),
        "regionId": str(candidate.get("regionId") or ""),
        "regionTitle": str(candidate.get("regionTitle") or ""),
        "score": candidate.get("score"),
        "signals": candidate.get("signals") if isinstance(candidate.get("signals"), list) else [],
        "candidateTemplatesPath": str(artifact["outputDir"] / "candidate_templates.json"),
        "evidenceWindowPath": str(artifact["outputDir"] / "candidate_windows.json"),
        "evidenceBlocks": evidence_blocks,
    }


def build_candidate_batch(batch: dict[str, Any], batch_count: int) -> dict[str, Any]:
    artifact = batch["artifact"]
    payload = {
        "schemaVersion": WORKFLOW_SCHEMA_VERSION,
        "phase": "candidate",
        "batchNo": batch["batchNo"],
        "batchCount": batch_count,
        "batchSize": BATCH_SIZE,
        "documentId": artifact["document"].get("id"),
        "documentName": artifact["document"].get("name"),
        "documentOutputDir": str(artifact["outputDir"]),
        "decisionSaveCommand": (
            f"btplbound candidate-decision <manifest> {batch['batchNo']} <decision-json>"
        ),
        "candidates": [normalize_candidate_for_batch(candidate, artifact) for candidate in batch["candidates"]],
    }
    write_json(audit_batch_path(artifact["outputDir"], "candidate", int(batch["batchNo"])), payload)
    return payload


def validate_exact_batch_ids(actual_ids: list[str], expected_ids: list[str]) -> None:
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("decision file contains duplicate candidateId values")
    missing = [candidate_id for candidate_id in expected_ids if candidate_id not in actual_ids]
    extra = [candidate_id for candidate_id in actual_ids if candidate_id not in expected_ids]
    if missing or extra:
        raise ValueError(f"decision candidateId set mismatch; missing={missing}, extra={extra}")


def coerce_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be boolean")


def coerce_optional_bool(value: Any, field: str, default: bool) -> bool:
    if value is None:
        return default
    return coerce_bool(value, field)


def coerce_confidence(value: Any) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number between 0 and 1")
    confidence = float(value)
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be a number between 0 and 1")
    return confidence


def normalize_heading_role(raw: dict[str, Any], *, is_template_start: bool) -> str:
    role = str(raw.get("headingRole") or "").strip()
    if not role:
        return "template_start" if is_template_start else "reject"
    if role not in HEADING_ROLES:
        raise ValueError(f"headingRole must be one of {sorted(HEADING_ROLES)}")
    if is_template_start and role != "template_start":
        raise ValueError("isTemplateStart=true requires headingRole=template_start")
    if role == "template_start" and not is_template_start:
        raise ValueError("headingRole=template_start requires isTemplateStart=true")
    return role


def decision_heading_role(decision: dict[str, Any]) -> str:
    role = str(decision.get("headingRole") or "").strip()
    if role:
        return role
    return "template_start" if bool(decision.get("isTemplateStart")) else "reject"


def normalize_candidate_decisions(batch: dict[str, Any], decision_file: Path) -> dict[str, Any]:
    payload = read_json(decision_file)
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        raise ValueError("candidate decision file must contain decisions[]")
    candidate_by_id = {str(item.get("candidateId") or ""): item for item in batch["candidates"]}
    expected_ids = list(candidate_by_id)
    raw_decisions = [item for item in payload["decisions"] if isinstance(item, dict)]
    actual_ids = [str(item.get("candidateId") or "") for item in raw_decisions]
    validate_exact_batch_ids(actual_ids, expected_ids)

    normalized: list[dict[str, Any]] = []
    for raw in raw_decisions:
        candidate_id = str(raw.get("candidateId") or "")
        candidate = candidate_by_id[candidate_id]
        explicit_role = str(raw.get("headingRole") or "").strip()
        default_start = explicit_role == "template_start" if explicit_role else False
        is_template_start = coerce_optional_bool(raw.get("isTemplateStart"), "isTemplateStart", default_start)
        heading_role = normalize_heading_role(raw, is_template_start=is_template_start)
        confidence = coerce_confidence(raw.get("confidence"))
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise ValueError(f"{candidate_id} reason is required")
        template_title = str(raw.get("templateTitle") or candidate.get("text") or "").strip()
        template_type = str(raw.get("templateType") or "").strip()
        reject_reason = str(raw.get("rejectReason") or "").strip()
        if is_template_start and not template_title:
            raise ValueError(f"{candidate_id} templateTitle is required for accepted templates")
        if heading_role == "reject" and not reject_reason:
            raise ValueError(f"{candidate_id} rejectReason is required for rejected candidates")
        normalized.append(
            {
                "candidateId": candidate_id,
                "candidateBlockId": candidate.get("candidateBlockId"),
                "isTemplateStart": is_template_start,
                "headingRole": heading_role,
                "isBoundaryReference": heading_role in BOUNDARY_REFERENCE_ROLES,
                "rejectReason": "" if heading_role in BOUNDARY_REFERENCE_ROLES else reject_reason,
                "templateTitle": template_title,
                "templateType": template_type or ("business_template" if is_template_start else ""),
                "confidence": confidence,
                "reason": reason,
                "needsReview": coerce_bool(raw.get("needsReview"), "needsReview"),
                "documentOutputDir": str(batch["artifact"]["outputDir"]),
                "documentId": batch["artifact"]["document"].get("id"),
            }
        )
    return {
        "schemaVersion": WORKFLOW_SCHEMA_VERSION,
        "phase": "candidate",
        "batchNo": batch["batchNo"],
        "documentOutputDir": str(batch["artifact"]["outputDir"]),
        "decisions": normalized,
    }


def candidate_decision_map(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for batch in candidate_batches(artifacts):
        saved = read_saved_decision(phase_path(batch["artifact"]["outputDir"], "candidate", int(batch["batchNo"])))
        if not saved:
            continue
        for decision in saved.get("decisions") or []:
            if isinstance(decision, dict):
                decisions[str(decision.get("candidateId") or "")] = decision
    return decisions


def ensure_all_candidate_batches_decided(artifacts: list[dict[str, Any]]) -> None:
    missing = [
        batch["batchNo"]
        for batch in candidate_batches(artifacts)
        if not phase_path(batch["artifact"]["outputDir"], "candidate", int(batch["batchNo"])).is_file()
    ]
    if missing:
        raise ValueError(f"candidate decisions are incomplete; missing batches: {missing}")


def accepted_candidates(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decision_map = candidate_decision_map(artifacts)
    accepted: list[dict[str, Any]] = []
    for artifact in artifacts:
        candidates_by_id = {str(item.get("candidateId") or ""): item for item in artifact["candidates"]}
        for candidate_id, decision in decision_map.items():
            if str(decision.get("documentOutputDir") or "") != str(artifact["outputDir"]):
                continue
            if not bool(decision.get("isTemplateStart")):
                continue
            candidate = candidates_by_id.get(candidate_id)
            if not candidate:
                continue
            accepted.append({"artifact": artifact, "candidate": candidate, "candidateDecision": decision})
    accepted.sort(key=lambda item: (str(item["artifact"]["outputDir"]), int(item["candidate"].get("candidateBlockId") or 0)))
    return accepted


def boundary_reference_candidates(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decision_map = candidate_decision_map(artifacts)
    references: list[dict[str, Any]] = []
    for artifact in artifacts:
        candidates_by_id = {str(item.get("candidateId") or ""): item for item in artifact["candidates"]}
        for candidate_id, decision in decision_map.items():
            if str(decision.get("documentOutputDir") or "") != str(artifact["outputDir"]):
                continue
            if decision_heading_role(decision) not in BOUNDARY_REFERENCE_ROLES:
                continue
            candidate = candidates_by_id.get(candidate_id)
            if not candidate:
                continue
            references.append({"artifact": artifact, "candidate": candidate, "candidateDecision": decision})
    references.sort(key=lambda item: (str(item["artifact"]["outputDir"]), int(item["candidate"].get("candidateBlockId") or 0)))
    return references


def boundary_batches(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    batch_no = 1
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in accepted_candidates(artifacts):
        grouped.setdefault(str(item["artifact"]["outputDir"]), []).append(item)
    for items in grouped.values():
        for templates in chunked(items):
            batches.append({"batchNo": batch_no, "artifact": templates[0]["artifact"], "templates": templates})
            batch_no += 1
    return batches


def region_for_candidate(artifact: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
    candidate_region = str(candidate.get("regionId") or "")
    for region in artifact["regions"]:
        if candidate_region and str(region.get("id") or "") == candidate_region:
            return region
    try:
        block_id = int(candidate.get("candidateBlockId") or 0)
    except (TypeError, ValueError):
        return None
    for region in artifact["regions"]:
        try:
            if int(region["startBlockId"]) <= block_id <= int(region["endBlockId"]):
                return region
        except (KeyError, TypeError, ValueError):
            continue
    return None


def boundary_limits(item: dict[str, Any], all_items: list[dict[str, Any]]) -> tuple[int, int]:
    start, max_end, _next_reference = boundary_limits_with_reference(item, all_items)
    return start, max_end


def boundary_limits_with_reference(item: dict[str, Any], all_items: list[dict[str, Any]]) -> tuple[int, int, dict[str, Any] | None]:
    artifact = item["artifact"]
    candidate = item["candidate"]
    start = int(candidate.get("candidateBlockId") or 0)
    region = region_for_candidate(artifact, candidate)
    max_end = int(region.get("endBlockId")) if region else max(artifact["blocksById"] or {start: {}})
    same_doc = [
        other
        for other in all_items
        if str(other["artifact"]["outputDir"]) == str(artifact["outputDir"])
        and int(other["candidate"].get("candidateBlockId") or 0) > start
    ]
    next_reference = same_doc[0] if same_doc else None
    if same_doc:
        max_end = min(max_end, int(same_doc[0]["candidate"].get("candidateBlockId") or 0) - 1)
    return start, max_end, next_reference


def compact_range_blocks(artifact: dict[str, Any], start: int, end: int) -> list[dict[str, Any]]:
    block_ids = [block_id for block_id in range(start, end + 1) if block_id in artifact["blocksById"]]
    if len(block_ids) > 80:
        block_ids = block_ids[:45] + block_ids[-30:]
    return [compact_block(artifact["blocksById"][block_id]) for block_id in block_ids]


def compact_reference(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    candidate = item["candidate"]
    decision = item["candidateDecision"]
    return {
        "candidateId": candidate.get("candidateId"),
        "candidateBlockId": candidate.get("candidateBlockId"),
        "text": str(candidate.get("text") or candidate.get("title") or ""),
        "headingRole": decision.get("headingRole"),
        "isTemplateStart": bool(decision.get("isTemplateStart")),
        "reason": str(decision.get("reason") or ""),
    }


def build_boundary_batch(batch: dict[str, Any], batch_count: int, all_references: list[dict[str, Any]]) -> dict[str, Any]:
    templates = []
    for item in batch["templates"]:
        artifact = item["artifact"]
        candidate = item["candidate"]
        start, max_end, next_reference = boundary_limits_with_reference(item, all_references)
        templates.append(
            {
                "candidateId": candidate.get("candidateId"),
                "candidateBlockId": candidate.get("candidateBlockId"),
                "templateTitle": item["candidateDecision"].get("templateTitle"),
                "templateType": item["candidateDecision"].get("templateType"),
                "regionId": candidate.get("regionId"),
                "regionTitle": candidate.get("regionTitle"),
                "suggestedStartBlockId": start,
                "maxEndBlockId": max_end,
                "nextTrueTemplateRule": "endBlockId must be before the next boundary reference heading in this document",
                "nextBoundaryReference": compact_reference(next_reference),
                "candidateDecision": item["candidateDecision"],
                "boundaryEvidenceBlocks": compact_range_blocks(artifact, start, max_end),
            }
        )
    payload = {
        "schemaVersion": WORKFLOW_SCHEMA_VERSION,
        "phase": "boundary",
        "batchNo": batch["batchNo"],
        "batchCount": batch_count,
        "batchSize": BATCH_SIZE,
        "documentId": batch["artifact"]["document"].get("id"),
        "documentName": batch["artifact"]["document"].get("name"),
        "documentOutputDir": str(batch["artifact"]["outputDir"]),
        "decisionSaveCommand": (
            f"btplbound boundary-decision <manifest> {batch['batchNo']} <decision-json>"
        ),
        "templates": templates,
    }
    write_json(audit_batch_path(batch["artifact"]["outputDir"], "boundary", int(batch["batchNo"])), payload)
    return payload


def coerce_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def normalize_boundary_decisions(
    batch: dict[str, Any],
    decision_file: Path,
    all_references: list[dict[str, Any]],
    all_accepted: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = read_json(decision_file)
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        raise ValueError("boundary decision file must contain decisions[]")
    template_by_id = {str(item["candidate"].get("candidateId") or ""): item for item in batch["templates"]}
    expected_ids = list(template_by_id)
    raw_decisions = [item for item in payload["decisions"] if isinstance(item, dict)]
    actual_ids = [str(item.get("candidateId") or "") for item in raw_decisions]
    validate_exact_batch_ids(actual_ids, expected_ids)

    normalized: list[dict[str, Any]] = []
    for raw in raw_decisions:
        candidate_id = str(raw.get("candidateId") or "")
        item = template_by_id[candidate_id]
        artifact = item["artifact"]
        candidate = item["candidate"]
        start = coerce_int(raw.get("startBlockId"), "startBlockId")
        end = coerce_int(raw.get("endBlockId"), "endBlockId")
        if end < start:
            raise ValueError(f"{candidate_id} endBlockId must not be before startBlockId")
        if start not in artifact["blocksById"] or end not in artifact["blocksById"]:
            raise ValueError(f"{candidate_id} startBlockId/endBlockId must exist in blocks.json")
        min_start, max_end = boundary_limits(item, all_references)
        if start < min_start:
            raise ValueError(f"{candidate_id} startBlockId must not be before candidateBlockId")
        if end > max_end:
            raise ValueError(f"{candidate_id} endBlockId must not cross the next boundary reference heading")
        region = region_for_candidate(artifact, candidate)
        if region:
            region_start = int(region["startBlockId"])
            region_end = int(region["endBlockId"])
            if not (region_start <= start <= end <= region_end):
                raise ValueError(f"{candidate_id} startBlockId/endBlockId must stay inside the format region")
        confidence = coerce_confidence(raw.get("confidence"))
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise ValueError(f"{candidate_id} reason is required")
        normalized.append(
            {
                "candidateId": candidate_id,
                "candidateBlockId": candidate.get("candidateBlockId"),
                "startBlockId": start,
                "endBlockId": end,
                "confidence": confidence,
                "reason": reason,
                "needsReview": coerce_bool(raw.get("needsReview"), "needsReview"),
                "documentOutputDir": str(artifact["outputDir"]),
                "documentId": artifact["document"].get("id"),
            }
        )
    validate_no_boundary_overlap(normalized, batch, all_accepted)
    return {
        "schemaVersion": WORKFLOW_SCHEMA_VERSION,
        "phase": "boundary",
        "batchNo": batch["batchNo"],
        "documentOutputDir": str(batch["artifact"]["outputDir"]),
        "decisions": normalized,
    }


def validate_no_boundary_overlap(current: list[dict[str, Any]], batch: dict[str, Any], all_accepted: list[dict[str, Any]]) -> None:
    all_decisions: list[dict[str, Any]] = []
    for boundary_batch in boundary_batches_for_items(all_accepted):
        path = phase_path(boundary_batch["artifact"]["outputDir"], "boundary", int(boundary_batch["batchNo"]))
        if boundary_batch["batchNo"] == batch["batchNo"] and str(boundary_batch["artifact"]["outputDir"]) == str(batch["artifact"]["outputDir"]):
            continue
        saved = read_saved_decision(path)
        if saved:
            all_decisions.extend([item for item in saved.get("decisions") or [] if isinstance(item, dict)])
    all_decisions.extend(current)
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for decision in all_decisions:
        by_doc.setdefault(str(decision.get("documentOutputDir") or ""), []).append(decision)
    for decisions in by_doc.values():
        ordered = sorted(decisions, key=lambda item: int(item.get("startBlockId") or 0))
        previous_end = -1
        for decision in ordered:
            start = int(decision["startBlockId"])
            end = int(decision["endBlockId"])
            if start <= previous_end:
                raise ValueError("boundary decisions contain duplicate or overlapping ranges")
            previous_end = end


def boundary_batches_for_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    batch_no = 1
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item["artifact"]["outputDir"]), []).append(item)
    for templates in grouped.values():
        for chunk in chunked(templates):
            batches.append({"batchNo": batch_no, "artifact": chunk[0]["artifact"], "templates": chunk})
            batch_no += 1
    return batches


def all_boundary_decisions(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for batch in boundary_batches(artifacts):
        saved = read_saved_decision(phase_path(batch["artifact"]["outputDir"], "boundary", int(batch["batchNo"])))
        if not saved:
            continue
        for decision in saved.get("decisions") or []:
            if isinstance(decision, dict):
                decisions[str(decision.get("candidateId") or "")] = decision
    return decisions


def ensure_all_boundary_batches_decided(artifacts: list[dict[str, Any]]) -> None:
    missing = [
        batch["batchNo"]
        for batch in boundary_batches(artifacts)
        if not phase_path(batch["artifact"]["outputDir"], "boundary", int(batch["batchNo"])).is_file()
    ]
    if missing:
        raise ValueError(f"boundary decisions are incomplete; missing batches: {missing}")


def status_payload(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    artifacts = all_document_artifacts(manifest, manifest_path)
    candidates_total = sum(len(artifact["candidates"]) for artifact in artifacts)
    candidate_batch_items = candidate_batches(artifacts)
    candidate_decided = 0
    decided_candidate_batches = 0
    for batch in candidate_batch_items:
        saved = read_saved_decision(phase_path(batch["artifact"]["outputDir"], "candidate", int(batch["batchNo"])))
        if not saved:
            continue
        decided_candidate_batches += 1
        candidate_decided += len(saved.get("decisions") or [])
    candidate_complete = decided_candidate_batches == len(candidate_batch_items)

    boundary_batch_items = boundary_batches(artifacts) if candidate_complete else []
    boundary_decided = 0
    decided_boundary_batches = 0
    for batch in boundary_batch_items:
        saved = read_saved_decision(phase_path(batch["artifact"]["outputDir"], "boundary", int(batch["batchNo"])))
        if not saved:
            continue
        decided_boundary_batches += 1
        boundary_decided += len(saved.get("decisions") or [])
    return {
        "schemaVersion": WORKFLOW_SCHEMA_VERSION,
        "status": "ready" if candidate_complete and decided_boundary_batches == len(boundary_batch_items) else "waiting",
        "manifestPath": str(manifest_path),
        "documentCount": len(artifacts),
        "candidate": {
            "total": candidates_total,
            "decided": candidate_decided,
            "batchCount": len(candidate_batch_items),
            "decidedBatchCount": decided_candidate_batches,
            "pendingBatchCount": len(candidate_batch_items) - decided_candidate_batches,
        },
        "boundary": {
            "total": len(accepted_candidates(artifacts)) if candidate_complete else 0,
            "decided": boundary_decided,
            "batchCount": len(boundary_batch_items),
            "decidedBatchCount": decided_boundary_batches,
            "pendingBatchCount": len(boundary_batch_items) - decided_boundary_batches,
        },
    }


def final_decisions_for_document(artifact: dict[str, Any], candidate_map: dict[str, dict[str, Any]], boundary_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for candidate in artifact["candidates"]:
        candidate_id = str(candidate.get("candidateId") or "")
        candidate_decision = candidate_map.get(candidate_id)
        if not candidate_decision:
            continue
        heading_role = decision_heading_role(candidate_decision)
        if not bool(candidate_decision.get("isTemplateStart")):
            decisions.append(
                {
                    "candidateId": candidate_id,
                    "candidateBlockId": candidate.get("candidateBlockId"),
                    "isTemplateStart": False,
                    "headingRole": heading_role,
                    "isBoundaryReference": heading_role in BOUNDARY_REFERENCE_ROLES,
                    "rejectReason": str(candidate_decision.get("rejectReason") or ("agent boundary reference" if heading_role in BOUNDARY_REFERENCE_ROLES else "agent rejected")),
                    "templateTitle": str(candidate_decision.get("templateTitle") or candidate.get("text") or ""),
                    "templateType": str(candidate_decision.get("templateType") or ""),
                    "startBlockId": None,
                    "endBlockId": None,
                    "confidence": float(candidate_decision.get("confidence") or 0),
                    "reason": str(candidate_decision.get("reason") or ""),
                    "needsReview": bool(candidate_decision.get("needsReview")),
                }
            )
            continue
        boundary_decision = boundary_map.get(candidate_id)
        if not boundary_decision:
            raise ValueError(f"accepted candidate {candidate_id} has no boundary decision")
        confidence = min(float(candidate_decision.get("confidence") or 0), float(boundary_decision.get("confidence") or 0))
        decisions.append(
            {
                "candidateId": candidate_id,
                "candidateBlockId": candidate.get("candidateBlockId"),
                "isTemplateStart": True,
                "headingRole": "template_start",
                "isBoundaryReference": True,
                "rejectReason": "",
                "templateTitle": str(candidate_decision.get("templateTitle") or candidate.get("text") or ""),
                "templateType": str(candidate_decision.get("templateType") or "business_template"),
                "startBlockId": int(boundary_decision["startBlockId"]),
                "endBlockId": int(boundary_decision["endBlockId"]),
                "confidence": confidence,
                "reason": (
                    f"候选裁决：{candidate_decision.get('reason') or ''}\n"
                    f"边界裁决：{boundary_decision.get('reason') or ''}"
                ).strip(),
                "needsReview": bool(candidate_decision.get("needsReview")) or bool(boundary_decision.get("needsReview")),
            }
        )
    return decisions


def finalize(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    artifacts = all_document_artifacts(manifest, manifest_path)
    ensure_all_candidate_batches_decided(artifacts)
    ensure_all_boundary_batches_decided(artifacts)
    candidate_map = candidate_decision_map(artifacts)
    boundary_map = all_boundary_decisions(artifacts)
    role_counts = {
        "headingDecisionCount": len(candidate_map),
        "acceptedTemplateCount": 0,
        "boundaryReferenceCount": sum(
            1 for decision in candidate_map.values() if decision_heading_role(decision) in BOUNDARY_REFERENCE_ROLES
        ),
        "sectionContainerCount": sum(1 for decision in candidate_map.values() if decision.get("headingRole") == "section_container"),
        "boundaryOnlyCount": sum(1 for decision in candidate_map.values() if decision.get("headingRole") == "boundary_only"),
        "rejectedCount": sum(
            1 for decision in candidate_map.values() if decision_heading_role(decision) == "reject"
        ),
    }
    decision_files: list[str] = []
    decision_count = 0
    accepted_count = 0
    rejected_count = 0
    for artifact in artifacts:
        decisions = final_decisions_for_document(artifact, candidate_map, boundary_map)
        payload = {
            "schemaVersion": BOUNDARY_DECISIONS_SCHEMA_VERSION,
            "decider": "executing_agent",
            "decisions": decisions,
        }
        decision_path = artifact["outputDir"] / "llm_boundary_decisions.json"
        write_json(decision_path, payload)
        decision_files.append(str(decision_path))
        decision_count += len(decisions)
        accepted_count += sum(1 for item in decisions if item.get("isTemplateStart"))
        rejected_count += sum(1 for item in decisions if not item.get("isTemplateStart"))
    role_counts["acceptedTemplateCount"] = accepted_count
    return {
        "schemaVersion": BOUNDARY_DECISIONS_SCHEMA_VERSION,
        "decisionFiles": decision_files,
        "summary": {
            "documentCount": len(artifacts),
            "candidateCount": sum(len(artifact["candidates"]) for artifact in artifacts),
            "decisionCount": decision_count,
            **role_counts,
            "scriptFallbackUsed": False,
        },
    }


def command_status(args: list[str]) -> dict[str, Any]:
    if len(args) != 1:
        raise ValueError("usage: btplbound status <manifest>")
    manifest_path = Path(args[0]).resolve()
    return status_payload(load_manifest(manifest_path), manifest_path)


def command_candidate_batch(args: list[str]) -> dict[str, Any]:
    if len(args) != 2 or args[1] != "next":
        raise ValueError("usage: btplbound candidate-batch <manifest> next")
    manifest_path = Path(args[0]).resolve()
    artifacts = all_document_artifacts(load_manifest(manifest_path), manifest_path)
    batches = candidate_batches(artifacts)
    for batch in batches:
        if not phase_path(batch["artifact"]["outputDir"], "candidate", int(batch["batchNo"])).is_file():
            return build_candidate_batch(batch, len(batches))
    return {"schemaVersion": WORKFLOW_SCHEMA_VERSION, "phase": "candidate", "status": "complete", "batchCount": len(batches)}


def command_candidate_decision(args: list[str]) -> dict[str, Any]:
    if len(args) != 3:
        raise ValueError("usage: btplbound candidate-decision <manifest> <batchNo> <decision-json>")
    manifest_path = Path(args[0]).resolve()
    batch_no = coerce_int(args[1], "batchNo")
    decision_file = Path(args[2]).resolve()
    artifacts = all_document_artifacts(load_manifest(manifest_path), manifest_path)
    batches = {int(batch["batchNo"]): batch for batch in candidate_batches(artifacts)}
    if batch_no not in batches:
        raise ValueError(f"unknown candidate batchNo: {batch_no}")
    normalized = normalize_candidate_decisions(batches[batch_no], decision_file)
    write_json(phase_path(batches[batch_no]["artifact"]["outputDir"], "candidate", batch_no), normalized)
    accepted_count = sum(1 for item in normalized["decisions"] if item["isTemplateStart"])
    boundary_reference_count = sum(1 for item in normalized["decisions"] if item.get("isBoundaryReference"))
    return {
        "schemaVersion": WORKFLOW_SCHEMA_VERSION,
        "phase": "candidate",
        "batchNo": batch_no,
        "savedPath": str(phase_path(batches[batch_no]["artifact"]["outputDir"], "candidate", batch_no)),
        "decisionCount": len(normalized["decisions"]),
        "acceptedCount": accepted_count,
        "boundaryReferenceCount": boundary_reference_count,
        "rejectedCount": len(normalized["decisions"]) - accepted_count,
    }


def command_boundary_batch(args: list[str]) -> dict[str, Any]:
    if len(args) != 2 or args[1] != "next":
        raise ValueError("usage: btplbound boundary-batch <manifest> next")
    manifest_path = Path(args[0]).resolve()
    artifacts = all_document_artifacts(load_manifest(manifest_path), manifest_path)
    ensure_all_candidate_batches_decided(artifacts)
    accepted = accepted_candidates(artifacts)
    references = boundary_reference_candidates(artifacts)
    batches = boundary_batches_for_items(accepted)
    for batch in batches:
        if not phase_path(batch["artifact"]["outputDir"], "boundary", int(batch["batchNo"])).is_file():
            return build_boundary_batch(batch, len(batches), references)
    return {"schemaVersion": WORKFLOW_SCHEMA_VERSION, "phase": "boundary", "status": "complete", "batchCount": len(batches)}


def command_boundary_decision(args: list[str]) -> dict[str, Any]:
    if len(args) != 3:
        raise ValueError("usage: btplbound boundary-decision <manifest> <batchNo> <decision-json>")
    manifest_path = Path(args[0]).resolve()
    batch_no = coerce_int(args[1], "batchNo")
    decision_file = Path(args[2]).resolve()
    artifacts = all_document_artifacts(load_manifest(manifest_path), manifest_path)
    ensure_all_candidate_batches_decided(artifacts)
    accepted = accepted_candidates(artifacts)
    references = boundary_reference_candidates(artifacts)
    batches = {int(batch["batchNo"]): batch for batch in boundary_batches_for_items(accepted)}
    if batch_no not in batches:
        raise ValueError(f"unknown boundary batchNo: {batch_no}")
    normalized = normalize_boundary_decisions(batches[batch_no], decision_file, references, accepted)
    write_json(phase_path(batches[batch_no]["artifact"]["outputDir"], "boundary", batch_no), normalized)
    return {
        "schemaVersion": WORKFLOW_SCHEMA_VERSION,
        "phase": "boundary",
        "batchNo": batch_no,
        "savedPath": str(phase_path(batches[batch_no]["artifact"]["outputDir"], "boundary", batch_no)),
        "decisionCount": len(normalized["decisions"]),
        "acceptedCount": len(normalized["decisions"]),
    }


def command_finalize(args: list[str]) -> dict[str, Any]:
    if len(args) != 1:
        raise ValueError("usage: btplbound finalize <manifest>")
    manifest_path = Path(args[0]).resolve()
    return finalize(load_manifest(manifest_path), manifest_path)


COMMANDS = {
    "status": command_status,
    "candidate-batch": command_candidate_batch,
    "candidate-decision": command_candidate_decision,
    "boundary-batch": command_boundary_batch,
    "boundary-decision": command_boundary_decision,
    "finalize": command_finalize,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print(
            "usage: btplbound [status|candidate-batch|candidate-decision|boundary-batch|boundary-decision|finalize] ...",
            file=sys.stderr,
        )
        return 2
    try:
        payload = COMMANDS[args[0]](args[1:])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
