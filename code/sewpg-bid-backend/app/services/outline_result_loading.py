"""S2 目录结果加载与校验：技术标 compose 可信校验、商务标 outline.json 转换、TOC 项清洗。

从 outline_generation 拆出；对外仍经 app.services.outline_generation 门面 re-export。
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type
from app.services.outline_chapter_runner import (
    OUTLINE_SKILL_NAME,
    _load_technical_outline_runner,
)

PUBLIC_EVIDENCE_DECISION_LIMIT = 80
TECHNICAL_SUGGESTION_ACTIONS = {"必要", "建议增加", "建议删除", "待确认"}


def _is_business_bid(bid_type: Any) -> bool:
    return require_bid_type(
        bid_type,
        error_message="目录生成必须显式传入技术标或商务标。",
    ) == BUSINESS_BID_TYPE



def _load_outline_result(
    result: dict[str, Any],
    manifest_path: Path,
    *,
    expected_bid_type: Any | None = None,
    trusted_technical_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    resolved_bid_type = expected_bid_type if expected_bid_type is not None else manifest.get("bidType")
    is_business_bid = _is_business_bid(resolved_bid_type)
    trusted_output = (
        trusted_technical_input.get("outputFile")
        if isinstance(trusted_technical_input, dict) and not is_business_bid
        else None
    )
    output_file = Path(
        str(trusted_output or result.get("outputFile") or manifest.get("outputFile") or "")
    ).expanduser()
    if is_business_bid:
        evidence_file = Path(str(result.get("evidenceFile") or manifest.get("evidenceFile") or "")).expanduser()
        return _load_business_outline_result(result, manifest, output_file, evidence_file)

    if not output_file.exists():
        raise RuntimeError(f"S2 目录 Skill 未生成 outputFile：{output_file}")
    validated_outline: dict[str, Any] | None = None
    if expected_bid_type is not None:
        validated_outline = _validate_technical_compose_report(
            manifest_path.parent,
            output_file,
            trusted_input=trusted_technical_input,
        )

    outline = validated_outline or json.loads(output_file.read_text(encoding="utf-8"))
    if (
        not isinstance(outline, dict)
        or outline.get("schema_version") != "technical-outline.v1"
        or not isinstance(outline.get("nodes"), list)
        or not outline["nodes"]
    ):
        raise RuntimeError("S2 目录 Skill 输出不是有效 technical-outline.v1。")

    outline["outputFile"] = str(output_file)
    if isinstance(result.get("opencodeOutput"), dict):
        outline["opencodeOutput"] = result["opencodeOutput"]
    outline["ruleEvidence"] = _technical_rule_evidence(outline["nodes"])
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    outline["summary"] = summary or {
        "total_nodes": outline["ruleEvidence"]["nodeCount"],
        "action_counts": outline["ruleEvidence"]["actionCounts"],
    }
    return outline


def _validate_technical_compose_report(
    work_dir: Path,
    output_file: Path,
    *,
    trusted_input: dict[str, Any] | None,
) -> dict[str, Any]:
    report_path = work_dir / "outline_compose_report.json"
    if not report_path.exists():
        raise RuntimeError("技术标目录缺少 compose report，拒绝接收直接写入的 outputFile。")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("技术标目录 compose report 无法读取。") from exc
    if not isinstance(report, dict) or report.get("schema_version") != "technical-outline-compose-report.v1":
        raise RuntimeError("技术标目录 compose report Schema 无效。")
    required_fields = {
        "inputFingerprint",
        "decisionsDigest",
        "outputSha256",
        "outputFile",
    }
    if str((trusted_input or {}).get("tenderInputsDigest") or "").strip():
        required_fields.update(
            {"tenderInputsDigest", "headingsStateDigest", "decisionStateDigest"}
        )
    if any(not str(report.get(field) or "").strip() for field in required_fields):
        raise RuntimeError("技术标目录 compose report 字段不完整。")
    reported_output = Path(str(report.get("outputFile") or "")).expanduser()
    if reported_output.resolve() != output_file.resolve():
        raise RuntimeError("技术标目录 compose report 指向了不同的 outputFile。")
    try:
        output_bytes = output_file.read_bytes()
        actual_outline = json.loads(output_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("技术标目录 outputFile 无法读取。") from exc
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    if report.get("outputSha256") != output_sha256:
        raise RuntimeError("技术标目录 outputFile 在 compose 后被修改。")
    if not isinstance(trusted_input, dict):
        raise RuntimeError("技术标目录缺少后端可信模板快照。")

    template_file = Path(str(trusted_input.get("templateFile") or "")).expanduser()
    expected_template_sha256 = str(trusted_input.get("templateFileSha256") or "")
    trusted_structure = trusted_input.get("templateStructure")
    if not template_file.is_file() or not expected_template_sha256 or not isinstance(trusted_structure, dict):
        raise RuntimeError("技术标目录后端可信模板快照无效。")
    current_template_sha256 = hashlib.sha256(template_file.read_bytes()).hexdigest()
    if current_template_sha256 != expected_template_sha256:
        raise RuntimeError("技术标历史模板在 Opencode 执行期间被修改。")

    runner = _load_technical_outline_runner()
    composer = runner.outline_composer
    try:
        trusted_fingerprint = composer.template_fingerprint(
            composer.annotate_template_structure(trusted_structure)
        )
        structure_path = work_dir / "template_structure.json"
        current_structure = json.loads(structure_path.read_text(encoding="utf-8"))
        current_fingerprint = composer.template_fingerprint(
            composer.annotate_template_structure(current_structure)
        )
        decisions = composer.load_decisions(work_dir, trusted_structure, required=True)
        workflow_proof: dict[str, str] = {}
        trusted_tender_files = trusted_input.get("tenderFiles")
        trusted_tender_digest = str(trusted_input.get("tenderInputsDigest") or "")
        if trusted_tender_digest:
            if not isinstance(trusted_tender_files, list) or not trusted_tender_files:
                raise RuntimeError("技术标目录后端可信招标文件快照无效。")
            current_tender_digest = runner.review_workflow.tender_input_fingerprint(
                trusted_tender_files
            )
            if current_tender_digest != trusted_tender_digest:
                raise RuntimeError("技术标招标文件在 Opencode 执行期间被修改。")
            trusted_appendix_items = trusted_input.get("appendixItems")
            if not isinstance(trusted_appendix_items, list) or any(
                not isinstance(item, dict) for item in trusted_appendix_items
            ):
                raise RuntimeError("技术标目录后端可信附表清单快照无效。")
            workspace_appendix_items = (
                runner.review_workflow.decision_appendix_items(work_dir)
            )
            _, trusted_appendix_digest = (
                runner.decision_workflow._normalized_appendix_inventory(
                    trusted_appendix_items
                )
            )
            _, workspace_appendix_digest = (
                runner.decision_workflow._normalized_appendix_inventory(
                    workspace_appendix_items
                )
            )
            if workspace_appendix_digest != trusted_appendix_digest:
                raise RuntimeError("技术标目录工作区附表清单与后端可信快照不一致。")
            workflow_proof = runner.review_workflow.require_headings_complete(
                work_dir,
                trusted_tender_files,
            )
            workflow_proof.update(
                runner.decision_workflow.validate_finalized_decisions(
                    work_dir,
                    trusted_structure,
                    decisions,
                    workflow_binding=workflow_proof,
                    appendix_items=trusted_appendix_items,
                )
            )
            composer.validate_compose_report(
                work_dir=work_dir,
                output_file=output_file,
                structure=trusted_structure,
                decisions=decisions,
                workflow_proof=workflow_proof,
            )
        expected_outline, context = composer.build_composition(trusted_structure, decisions)
    except RuntimeError:
        raise
    except (OSError, json.JSONDecodeError, ValueError, SystemExit) as exc:
        raise RuntimeError(f"技术标目录 compose 可信校验失败：{exc}") from exc

    if current_fingerprint != trusted_fingerprint:
        raise RuntimeError("技术标模板结构与后端可信快照不一致。")
    if report.get("inputFingerprint") != trusted_fingerprint:
        raise RuntimeError("技术标目录 compose report 的模板指纹不可信。")
    if report.get("decisionsDigest") != context["decisionsDigest"]:
        raise RuntimeError("技术标目录 compose report 的 decisions 摘要不一致。")
    if actual_outline != expected_outline:
        raise RuntimeError("技术标目录输出无法由可信模板与 decisions 确定性重组。")
    return copy.deepcopy(expected_outline)


def _load_business_outline_result(
    result: dict[str, Any],
    manifest: dict[str, Any],
    output_file: Path,
    evidence_file: Path,
) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or output_file.parent)).expanduser()
    business_outline_file = Path(str(result.get("businessOutlineFile") or work_dir / "outline.json")).expanduser()
    business_outline = _load_business_outline_json(business_outline_file)
    _write_business_toc_from_outline_payload(manifest, business_outline, business_outline_file, output_file, evidence_file)
    toc = json.loads(output_file.read_text(encoding="utf-8"))
    if not isinstance(toc, dict) or not isinstance(toc.get("items"), list):
        raise RuntimeError("商务标 outline.json 未能转换为有效 bid-toc-json-v1。")
    toc["items"] = _clean_toc_items(toc["items"])
    _rewrite_toc_file(output_file, toc, evidence_file)
    toc["outputFile"] = str(output_file)
    toc["evidenceFile"] = str(evidence_file)
    toc["businessOutlineFile"] = str(business_outline_file)
    if isinstance(result.get("opencodeOutput"), dict):
        toc["opencodeOutput"] = result["opencodeOutput"]
    toc["ruleEvidence"] = _public_rule_evidence_from_file(evidence_file)
    return toc


def _load_business_outline_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"商务标目录 Skill 未生成最终 outline.json：{path}")
    business_outline = _load_json_dict(path)
    if business_outline.get("schema_version") != "business_bid_outline.v1":
        raise RuntimeError("商务标 outline.json schema_version 必须是 business_bid_outline.v1。")
    sections = business_outline.get("sections")
    if not isinstance(sections, list) or not sections:
        raise RuntimeError("商务标 outline.json 必须包含非空 sections[]。")
    _validate_business_outline_section_numbers(sections)
    return business_outline


def _validate_business_outline_section_numbers(sections: list[Any], path: str = "sections") -> None:
    for index, section in enumerate(sections):
        section_path = f"{path}[{index}]"
        if not isinstance(section, dict):
            continue
        if "number" not in section:
            raise RuntimeError(f"商务标 outline.json {section_path}.number 缺失。")
        _business_section_number(section.get("number"))
        children = section.get("children")
        if isinstance(children, list):
            _validate_business_outline_section_numbers(children, f"{section_path}.children")


def _write_business_toc_from_outline(
    manifest: dict[str, Any],
    result: dict[str, Any],
    output_file: Path,
    evidence_file: Path,
) -> None:
    work_dir = Path(str(manifest.get("workDir") or output_file.parent)).expanduser()
    business_outline_file = Path(str(result.get("businessOutlineFile") or work_dir / "outline.json")).expanduser()
    business_outline = _load_business_outline_json(business_outline_file)
    _write_business_toc_from_outline_payload(manifest, business_outline, business_outline_file, output_file, evidence_file)


def _write_business_toc_from_outline_payload(
    manifest: dict[str, Any],
    business_outline: dict[str, Any],
    business_outline_file: Path,
    output_file: Path,
    evidence_file: Path,
) -> None:
    work_dir = Path(str(manifest.get("workDir") or output_file.parent)).expanduser()
    sections = business_outline.get("sections") if isinstance(business_outline.get("sections"), list) else []
    if not sections:
        raise RuntimeError("商务标 outline.json 必须包含非空 sections[]。")

    items = _clean_toc_items(_business_toc_items_from_sections(sections))
    counts = Counter(str(item.get("annotation") or "") for item in items)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    source_files = {
        "tender": manifest.get("tenderFiles") if isinstance(manifest.get("tenderFiles"), list) else [],
        "template": str(manifest.get("templateFile") or ""),
        "output": str(output_file),
        "evidence": str(evidence_file),
        "businessOutline": str(business_outline_file),
        "tenderMapInputs": str(work_dir / "tender_map_inputs.json"),
        "historyBidOutlineInputs": str(work_dir / "history_bid_outline_inputs.json"),
    }
    toc = {
        "schema_version": "bid-toc-json-v1",
        "document_title": str(business_outline.get("document_name") or "商务标目录"),
        "project": {
            "projectId": str(manifest.get("projectId") or ""),
            "projectCode": str(manifest.get("projectCode") or ""),
            "projectName": str(manifest.get("projectName") or ""),
            "bidType": require_bid_type(
                manifest.get("bidType"),
                error_message="商务标目录生成必须显式传入商务标。",
            ),
        },
        "source_files": source_files,
        "summary": {
            "total_items": len(items),
            "annotation_counts": dict(counts),
        },
        "items": items,
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
        "businessOutlineFile": str(business_outline_file),
    }
    evidence = {
        "schema_version": "bid-toc-evidence-v1",
        "engine": "bid-business-outline-generator",
        "inputs": source_files,
        "businessOutlineFile": str(business_outline_file),
        "decisions": business_outline.get("review_items") if isinstance(business_outline.get("review_items"), list) else [],
    }
    output_file.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
    if not evidence_file.exists():
        evidence_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


def _business_toc_items_from_sections(sections: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def append_section(section: dict[str, Any], fallback_level: int) -> None:
        order = len(items) + 1
        required_status = _normalize_required_status(section.get("required_status") or section.get("requiredStatus"))
        source_text = str(section.get("source_text") or section.get("sourceText") or "").strip()
        source_refs = _business_source_refs_from_section(section, source_text)
        number = _business_section_number(section.get("number"))
        items.append(
            {
                "itemId": f"TOC-{order:04d}",
                "order": order,
                "number": number,
                "title": str(section.get("title") or section.get("name") or f"商务标目录项{order}").strip(),
                "level": _coerce_toc_level(section.get("level") or fallback_level),
                "annotation": _business_annotation_from_required_status(required_status),
                "required_status": required_status,
                "requiredStatus": required_status,
                "source_text": source_text,
                "sourceText": source_text,
                "source": "business_outline",
                "reason": str(section.get("reason") or "商务标目录项来自 futurecode 生成的 outline.json。").strip(),
                "source_refs": source_refs,
                "material_refs": [],
            }
        )
        children = section.get("children") if isinstance(section.get("children"), list) else []
        for child in children:
            if isinstance(child, dict):
                append_section(child, fallback_level + 1)

    for section in sections:
        if isinstance(section, dict):
            append_section(section, 1)
    return items


def _business_section_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    raise RuntimeError("商务标 outline.json sections[].number 必须是字符串或 null。")


def _normalize_required_status(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"必要", "可选", "待确认"}:
        return text
    if text in {"必选", "必须", "应提交", "须提交", "保留"}:
        return "必要"
    if text in {"选填", "按需", "如适用", "适用时提交"}:
        return "可选"
    return text or "待确认"


def _business_annotation_from_required_status(required_status: str) -> str:
    if required_status == "待确认":
        return "待确认"
    if required_status == "可选":
        return "可选"
    return "保留"


def _business_source_refs_from_section(section: dict[str, Any], source_text: str) -> list[dict[str, Any]]:
    raw_refs = section.get("source_refs") if isinstance(section.get("source_refs"), list) else []
    if not raw_refs and isinstance(section.get("sourceRefs"), list):
        raw_refs = section["sourceRefs"]
    if not raw_refs and isinstance(section.get("source_ref"), dict):
        raw_refs = [section["source_ref"]]
    refs = [_clean_source_ref(ref) for ref in raw_refs if isinstance(ref, dict)]
    if refs:
        return refs
    if not source_text:
        return []
    return [
        _clean_source_ref(
            {
                "type": "tender",
                "role": "basis",
                "kind": "business_outline_section",
                "sectionId": str(section.get("id") or ""),
                "title": str(section.get("title") or ""),
                "raw_text": source_text,
                "rawText": source_text,
                "basisText": source_text,
                "searchText": source_text,
                "reason": "商务标 outline.json 目录项依据",
            }
        )
    ]



def _apply_agent_decisions(
    toc: dict[str, Any],
    agent_decisions: list[Any],
    evidence_file: Path,
) -> dict[str, Any]:
    evidence = _load_json_dict(evidence_file)
    candidates = {
        str(item.get("id") or item.get("candidateId") or ""): item
        for item in evidence.get("tenderCandidates", [])
        if isinstance(item, dict)
    }
    items = _clean_toc_items(toc.get("items") if isinstance(toc.get("items"), list) else [])
    item_index = _item_lookup(items)
    for raw_decision in agent_decisions:
        if not isinstance(raw_decision, dict):
            continue
        decision = str(raw_decision.get("decision") or raw_decision.get("action") or "").strip()
        candidate_id = str(raw_decision.get("candidateId") or raw_decision.get("id") or "")
        candidate = candidates.get(candidate_id)
        if candidate is None:
            continue
        if decision in {"attach_evidence", "attach", "covered"}:
            target = _find_decision_target(raw_decision, item_index, items)
            if target is None:
                continue
            target.setdefault("source_refs", []).append(_source_ref_from_agent_candidate(candidate, raw_decision))
        elif decision in {"append_item", "add", "add_appendix"}:
            items.append(_toc_item_from_agent_candidate(len(items) + 1, candidate, raw_decision))
        elif decision in {"exclude", "candidate", "ignore"}:
            continue
    toc["items"] = _clean_toc_items(items)
    return toc


def _rewrite_toc_file(
    output_file: Path,
    toc: dict[str, Any],
    evidence_file: Path,
    *,
    agent_decisions: list[Any] | None = None,
) -> None:
    raw_items = toc.get("items") if isinstance(toc.get("items"), list) else []
    items = _clean_toc_items(raw_items)
    counts = Counter(str(item.get("annotation") or "") for item in items)
    toc["items"] = items
    summary = toc.get("summary") if isinstance(toc.get("summary"), dict) else {}
    summary.update(
        {
            "total_items": len(items),
            "annotation_counts": dict(counts),
        }
    )
    toc["summary"] = summary
    toc["outputFile"] = str(output_file)
    toc["evidenceFile"] = str(evidence_file)
    output_file.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
    if evidence_file.exists():
        evidence = _load_json_dict(evidence_file)
        if agent_decisions is not None:
            evidence["agentDecisions"] = [item for item in agent_decisions if isinstance(item, dict)]
        evidence_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

def _clean_toc_items(items: list[Any]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        source_refs = item.get("source_refs")
        if not isinstance(source_refs, list):
            source_refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
        annotation = str(item.get("annotation") or "").strip() or "保留"
        required_status = str(item.get("required_status") or item.get("requiredStatus") or "").strip()
        if not required_status:
            required_status = _required_status_from_annotation(annotation)
        source_text = _toc_item_source_text(item)
        cleaned.append(
            {
                "itemId": str(item.get("itemId") or f"TOC-{index:04d}"),
                "order": index,
                "number": str(item.get("number") or "").strip(),
                "title": str(item.get("title") or item.get("name") or f"未命名章节{index}").strip(),
                "level": _coerce_toc_level(item.get("level")),
                "annotation": annotation,
                "required_status": required_status,
                "requiredStatus": required_status,
                "source_text": source_text,
                "sourceText": source_text,
                "source": str(item.get("source") or "").strip() or "template",
                "reason": str(item.get("reason") or "").strip(),
                "source_refs": [_clean_source_ref(ref) for ref in source_refs if isinstance(ref, dict)],
                "material_refs": [],
            }
        )
    return cleaned


def _required_status_from_annotation(annotation: str) -> str:
    text = str(annotation or "").strip()
    if text in {"待确认", "可选"}:
        return text
    if text in {"保留", "必要"}:
        return "必要"
    return text


def _clean_source_ref(ref: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(ref)
    if "raw_text" in cleaned and "rawText" not in cleaned:
        cleaned["rawText"] = cleaned.get("raw_text")
    if "rawText" in cleaned and "raw_text" not in cleaned:
        cleaned["raw_text"] = cleaned.get("rawText")
    basis_text = str(cleaned.get("basisText") or cleaned.get("rawText") or cleaned.get("raw_text") or "")
    if basis_text and not cleaned.get("basisText"):
        cleaned["basisText"] = basis_text
    if basis_text and not cleaned.get("searchText"):
        cleaned["searchText"] = basis_text
    return cleaned


def _item_lookup(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        for key in (
            str(item.get("itemId") or ""),
            str(item.get("title") or ""),
            _title_key(str(item.get("title") or "")),
        ):
            if key:
                result[key] = item
    return result


def _find_decision_target(
    decision: dict[str, Any],
    item_index: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for key in (
        str(decision.get("targetItemId") or ""),
        str(decision.get("targetTitle") or ""),
        _title_key(str(decision.get("targetTitle") or "")),
    ):
        if key and key in item_index:
            return item_index[key]
    return items[-1] if items else None


def _source_ref_from_agent_candidate(candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    basis_text = str(candidate.get("searchText") or candidate.get("basisText") or candidate.get("rawText") or "")
    return {
        "type": "tender",
        "role": "basis",
        "kind": "codex_semantic",
        "candidateKind": str(candidate.get("kind") or ""),
        "candidateId": str(candidate.get("id") or decision.get("candidateId") or ""),
        "relation": str(decision.get("relation") or "semantic_match"),
        "confidence": _coerce_confidence(decision.get("confidence")),
        "reason": str(decision.get("reason") or ""),
        "fileId": str(candidate.get("fileId") or ""),
        "fileName": str(candidate.get("fileName") or ""),
        "path": str(candidate.get("sourceFile") or candidate.get("path") or ""),
        "paragraphIndex": candidate.get("paragraphIndex"),
        "raw_text": str(candidate.get("rawText") or ""),
        "rawText": str(candidate.get("rawText") or ""),
        "basisText": basis_text,
        "searchText": basis_text,
        "title": str(candidate.get("title") or ""),
        "number": str(candidate.get("number") or ""),
        "contextTitle": str(candidate.get("contextTitle") or ""),
    }


def _toc_item_from_agent_candidate(order: int, candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    number = str(decision.get("number") or candidate.get("number") or "").strip()
    title = str(decision.get("title") or candidate.get("title") or "").strip()
    if number and title.startswith(number):
        title = title[len(number) :].strip(" ：:、.-")
    return {
        "itemId": f"TOC-{order:04d}",
        "order": order,
        "number": number,
        "title": title or f"未命名附表{order}",
        "level": _coerce_toc_level(decision.get("level") or 1),
        "annotation": str(decision.get("annotation") or "新增-副表"),
        "source": "tender",
        "reason": str(decision.get("reason") or "Agent 判断招标文件要求追加该目录项。"),
        "source_refs": [_source_ref_from_agent_candidate(candidate, decision)],
        "material_refs": [],
    }


def _coerce_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _public_rule_evidence_from_file(path: Path) -> dict[str, Any]:
    evidence = _load_json_dict(path)
    decisions = evidence.get("decisions") if isinstance(evidence.get("decisions"), list) else []
    if evidence.get("schema_version") == "bid-toc-evidence-v2":
        action_counts = Counter(
            str(item.get("action") or "")
            for item in decisions
            if isinstance(item, dict) and str(item.get("action") or "")
        )
        return {
            "schemaVersion": "bid-toc-evidence-v2",
            "engine": str(evidence.get("engine") or ""),
            "ruleVersion": str(evidence.get("ruleVersion") or evidence.get("rule_version") or ""),
            "decisionCount": len(decisions),
            "reviewCount": sum(
                1
                for item in decisions
                if isinstance(item, dict) and bool(item.get("review_required") or item.get("reviewRequired"))
            ),
            "actionCounts": dict(action_counts),
        }
    candidates = evidence.get("tenderCandidates") if isinstance(evidence.get("tenderCandidates"), list) else []
    template_outline = evidence.get("templateOutline") if isinstance(evidence.get("templateOutline"), list) else []
    item_sources = evidence.get("itemSources") if isinstance(evidence.get("itemSources"), list) else []
    return {
        "schemaVersion": str(evidence.get("schema_version") or ""),
        "engine": str(evidence.get("engine") or ""),
        "ruleVersion": str(evidence.get("ruleVersion") or evidence.get("rule_version") or ""),
        "templateOutlineCount": len(template_outline),
        "tenderCandidateCount": len(candidates),
        "itemSources": [
            dict(item)
            for item in item_sources
            if isinstance(item, dict)
        ][:PUBLIC_EVIDENCE_DECISION_LIMIT],
        "itemSourceCount": len(item_sources),
        "decisions": [
            dict(item)
            for item in decisions
            if isinstance(item, dict)
        ][:PUBLIC_EVIDENCE_DECISION_LIMIT],
        "decisionCount": len(decisions),
        "agentDecisions": [
            dict(item)
            for item in (evidence.get("agentDecisions") if isinstance(evidence.get("agentDecisions"), list) else [])
            if isinstance(item, dict)
        ][:PUBLIC_EVIDENCE_DECISION_LIMIT],
    }


def _title_key(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").lower())
    text = re.sub(r"[，,。.:：;；、（）()\[\]【】《》<>\"'“”‘’\\/_-]+", "", text)
    return text


def _technical_rule_evidence(nodes: list[Any]) -> dict[str, Any]:
    action_counts: Counter[str] = Counter()
    node_count = 0

    def walk(items: list[Any]) -> None:
        nonlocal node_count
        for item in items:
            if not isinstance(item, dict):
                continue
            node_count += 1
            action = str(item.get("suggestion_action") or item.get("suggestionAction") or "待确认").strip()
            action_counts[action if action in TECHNICAL_SUGGESTION_ACTIONS else "待确认"] += 1
            children = item.get("children")
            if isinstance(children, list):
                walk(children)

    walk(nodes)
    return {
        "schemaVersion": "technical-outline.v1",
        "engine": OUTLINE_SKILL_NAME,
        "nodeCount": node_count,
        "actionCounts": dict(action_counts),
    }


def _toc_item_source_text(item: dict[str, Any]) -> str:
    explicit = str(item.get("source_text") or item.get("sourceText") or "").strip()
    if explicit:
        return explicit
    source_refs = item.get("source_refs")
    if not isinstance(source_refs, list):
        source_refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        text = str(
            ref.get("searchText")
            or ref.get("basisText")
            or ref.get("rawText")
            or ref.get("raw_text")
            or ""
        ).strip()
        if text:
            return text
    return ""


def _coerce_toc_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 1
    return max(1, level)
