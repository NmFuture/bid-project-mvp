from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REFERENCES_DIR = SKILL_DIR / "references"

SCHEMA_VERSION = "bid-business-gap-plan-v1"
MODULE_MAPPING_PATH = REFERENCES_DIR / "task_mapping_table.json"
COMMITMENT_RULES_PATH = REFERENCES_DIR / "commitment_rules.json"
CERTIFICATE_RULES_PATH = REFERENCES_DIR / "certificate_rules.json"
WIKI_MODULE_CODE_TO_MODULE_KEYS = {
    "BM-01": {"structured_response_tables", "qualification_compliance_certificates", "performance_cooperation_support"},
    "BM-02": {"base_documents_guarantees"},
    "BM-03": {"structured_response_tables"},
    "BM-04": {"structured_response_tables"},
    "BM-05": {"structured_response_tables"},
    "BM-06": {"base_documents_guarantees"},
    "BM-07": {"base_documents_guarantees"},
    "BM-08": {"qualification_compliance_certificates"},
    "BM-09": {"performance_cooperation_support"},
    "BM-10": {"structured_response_tables"},
    "BM-11": {"commitments_and_notes"},
    "BM-12": {"commitments_and_notes", "qualification_compliance_certificates"},
    "BM-13": {"performance_cooperation_support", "enterprise_finance_supply"},
}
TASK_SYNONYMS = {
    "投标函": ["投标书", "投标函格式", "投标文件函"],
    "授权": ["授权委托书", "授权书", "法定代表人授权", "单位负责人授权", "委托代理"],
    "廉洁": ["廉洁承诺", "廉洁自律", "廉洁协议", "廉洁声明"],
    "投标专用章": ["专用章效力", "印章效力", "投标印章"],
    "保证金": ["投标保证金", "保函", "保证金回单", "电汇回单", "担保"],
    "履约": ["履约保证", "履约保函", "履约保证函", "履约承诺"],
    "报价": ["投标价格", "价格表", "报价表", "分项报价", "开标价格", "唱标"],
    "规格": ["货物规格", "规格一览表", "供货范围", "配置表", "参数表"],
    "商务偏差": ["偏差表", "偏离表", "商务条款响应", "响应表"],
    "营业执照": ["营业证明", "统一社会信用代码", "企业法人营业执照"],
    "体系认证": ["ISO", "质量管理体系", "环境管理体系", "职业健康安全管理体系"],
    "信用": ["信用中国", "失信", "经营异常", "纳税信用", "资信证明"],
    "机型认证": ["整机认证", "型式认证", "风力发电机组型式认证", "机组认证"],
    "大部件": ["部件型式认证", "叶片", "齿轮箱", "发电机", "变流器", "主轴承"],
    "业绩": ["合同", "中标通知书", "240h", "试运行", "验收", "运行业绩"],
    "战略协议": ["框架协议", "合作协议", "示范应用", "评价信", "优秀供应商"],
    "承诺": ["承诺函", "承诺书", "声明", "说明", "附件9"],
}
NEGATIVE_MATCH_RULES = [
    {
        "taskModules": {"base_documents_guarantees", "structured_response_tables", "commitments_and_notes"},
        "materialHints": ["通用素材/03-业绩资产池", "共用业绩库", "共用业绩", "业绩证明", "performance_library", "中标通知书", "合同扫描件", "验收报告", "240h"],
        "penalty": 0.42,
        "reason": "业绩资产不适合作为当前响应件",
    },
    {
        "taskModules": {"performance_cooperation_support"},
        "materialHints": ["商务响应文件", "投标函", "授权", "保证金", "报价", "价格表", "偏差表"],
        "penalty": 0.38,
        "reason": "项目响应文件不适合作为业绩支撑",
    },
    {
        "taskTitleHints": ["银行", "资信"],
        "materialHints": ["纳税"],
        "penalty": 0.5,
        "reason": "纳税信用材料不适用于银行资信任务",
    },
    {
        "taskTypes": {"certificate"},
        "materialHints": ["投标函", "报价", "价格表", "偏差", "承诺", "授权"],
        "penalty": 0.5,
        "reason": "响应文书不适合作为证书",
    },
    {
        "taskModules": {"structured_response_tables"},
        "materialHints": ["营业执照", "体系认证", "机型认证", "资信证明", "审计报告"],
        "penalty": 0.35,
        "reason": "资质证书不适合作为结构化表格数据源",
    },
]

USAGE_MODE_TO_ASSEMBLY_MODE = {
    "attach_whole": "attach_whole_file",
    "attach_whole_file": "attach_whole_file",
    "whole_file": "attach_whole_file",
    "full_attachment": "attach_whole_file",
    "embed_scan": "embed_scan_or_image",
    "embed_scan_or_image": "embed_scan_or_image",
    "image_embed": "embed_scan_or_image",
    "pdf_pages_embed": "embed_scan_or_image",
    "extract_and_summarize": "extract_and_summarize",
    "summarize": "extract_and_summarize",
    "extract_summary": "extract_and_summarize",
    "extract_segment": "extract_segment",
    "excerpt": "extract_segment",
    "quote_segment": "extract_segment",
    "partial_extract": "extract_segment",
    "fill_template": "template_fill_docx",
    "template_fill": "template_fill_docx",
    "template_fill_docx": "template_fill_docx",
    "table_source": "table_fill_from_material",
    "fill_table": "table_fill_from_material",
    "table_fill_from_material": "table_fill_from_material",
}

ASSEMBLY_MODE_TO_USAGE = {
    "template_fill_docx": "fill_template",
    "table_fill_from_material": "fill_table",
    "attach_whole_file": "attach_whole",
    "embed_scan_or_image": "embed_scan",
    "extract_and_summarize": "extract_and_summarize",
    "extract_segment": "extract_segment",
    "ai_draft": "generate_draft",
    "manual_upload": "manual_upload",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate business bid gap plan from backend manifest.")
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--manifest", dest="manifest_option")
    parser.add_argument("--response", choices=("summary", "plan"), default="summary")
    args = parser.parse_args()

    manifest_path = Path(str(args.manifest_option or args.manifest or "")).expanduser()
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = load_json(manifest_path)
    plan = build_business_gap_plan(manifest, manifest_path)
    output_file = Path(str(manifest.get("outputFile") or manifest_path.with_name("business_gap_plan.json"))).expanduser()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "outputFile": str(output_file),
        "tocRefCount": len(plan.get("tocRefs") or []),
        "taskCount": len(plan.get("tasks") or []),
        "coverageStatus": str((plan.get("summary") or {}).get("coverageStatus") or "complete"),
        "summary": plan.get("summary") or {},
    }
    response = plan if args.response == "plan" else summary
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def build_business_gap_plan(manifest: dict[str, Any], manifest_path: Path | None = None) -> dict[str, Any]:
    validate_manifest(manifest)
    now = now_iso()
    mapping = load_json(MODULE_MAPPING_PATH)
    commitment_rules = load_json(COMMITMENT_RULES_PATH)
    certificate_rules = load_json(CERTIFICATE_RULES_PATH)

    toc = load_json(Path(str(manifest.get("tocJsonPath") or "")).expanduser())
    parse_result = load_json(Path(str(manifest.get("parseResultPath") or "")).expanduser())
    toc_items = normalize_toc_items(toc)
    leaf_ids = leaf_node_ids(toc_items)

    module_groups = module_groups_from_mapping(mapping)
    tasks: list[dict[str, Any]] = []
    toc_refs: list[dict[str, Any]] = []
    task_by_fingerprint: dict[str, dict[str, Any]] = {}

    for item in toc_items:
        node_id = str(item["nodeId"])
        is_leaf = node_id in leaf_ids
        toc_ref = {
            "nodeId": node_id,
            "number": str(item.get("number") or ""),
            "title": str(item.get("title") or ""),
            "level": int(item.get("level") or 1),
            "taskIds": [],
            "status": "empty",
            "source": str(item.get("source") or ""),
            "requiredStatus": str(item.get("requiredStatus") or item.get("required_status") or ""),
        }
        if is_leaf:
            task = task_from_toc_item(item, mapping, now)
            task_by_fingerprint[task["fingerprint"]] = task
            tasks.append(task)
            toc_ref["taskIds"].append(task["id"])
        toc_refs.append(toc_ref)

    attach_parse_artifacts(
        tasks=tasks,
        toc_refs=toc_refs,
        parse_result=parse_result,
        commitment_rules=commitment_rules,
        now=now,
    )
    ensure_special_certificate_tasks(
        tasks=tasks,
        toc_refs=toc_refs,
        toc_items=toc_items,
        mapping=mapping,
        certificate_rules=certificate_rules,
        now=now,
    )
    add_candidate_materials(tasks, manifest)
    recompute_task_states(tasks, manifest)
    merge_state(tasks, manifest)
    annotate_fact_readiness(tasks, manifest)
    update_toc_ref_statuses(toc_refs, tasks)

    summary = summarize_plan(toc_refs, tasks)
    coverage_expected = len(toc_items)
    if len(toc_refs) != coverage_expected:
        raise SystemExit(
            f"toc coverage failed: expected {coverage_expected}, got {len(toc_refs)}"
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "projectId": str(manifest.get("projectId") or ""),
        "projectName": str(manifest.get("projectName") or ""),
        "bidType": "商务标",
        "generatedAt": now,
        "views": {"default": "toc", "available": ["toc", "module"]},
        "summary": summary,
        "moduleGroups": module_groups,
        "tocRefs": toc_refs,
        "tasks": tasks,
        "materialScope": manifest.get("materialScope") if isinstance(manifest.get("materialScope"), dict) else {},
        "selectedBusinessTurbineModel": manifest.get("selectedBusinessTurbineModel") if isinstance(manifest.get("selectedBusinessTurbineModel"), dict) else {},
        "businessWikiIndexSummary": (manifest.get("businessWikiIndex") or {}).get("summary") if isinstance(manifest.get("businessWikiIndex"), dict) else {},
        "manifestPath": str(manifest_path or ""),
        "planFile": str(manifest.get("outputFile") or ""),
    }


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = [
        "projectId",
        "projectName",
        "bidType",
        "workDir",
        "tocJsonPath",
        "parseResultPath",
        "materialScope",
        "materialIndex",
        "selectedBusinessTurbineModel",
        "outputFile",
    ]
    missing = [key for key in required if key not in manifest]
    if missing:
        raise SystemExit(f"manifest missing required keys: {', '.join(missing)}")
    if "商务" not in str(manifest.get("bidType") or ""):
        raise SystemExit("bid-business-gap-planner only accepts bidType=商务标")
    for key in ("tocJsonPath", "parseResultPath"):
        path = Path(str(manifest.get(key) or "")).expanduser()
        if not path.exists():
            raise SystemExit(f"{key} not found: {path}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"failed to read json {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"json must be object: {path}")
    return data


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_toc_items(toc: dict[str, Any]) -> list[dict[str, Any]]:
    items = toc.get("items") if isinstance(toc.get("items"), list) else []
    result: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    counters: list[int] = []
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            continue
        level = coerce_int(raw.get("level"), 1)
        level = max(1, min(level, 8))
        while stack and stack[-1][0] >= level:
            stack.pop()
        counters = counters[:level]
        if len(counters) < level:
            counters.extend([0] * (level - len(counters)))
        counters[level - 1] += 1
        generated_node_id = "TOC-" + "-".join(str(part) for part in counters[:level] if part)
        node_id = str(raw.get("nodeId") or raw.get("itemId") or raw.get("id") or generated_node_id).strip()
        parent_id = stack[-1][1] if stack else ""
        item = {
            **raw,
            "nodeId": node_id,
            "parentNodeId": str(raw.get("parentNodeId") or raw.get("parentId") or parent_id),
            "number": str(raw.get("number") or raw.get("tocNumber") or ""),
            "title": str(raw.get("title") or raw.get("name") or f"商务目录项{index}").strip(),
            "level": level,
            "order": coerce_int(raw.get("order"), index),
        }
        result.append(item)
        stack.append((level, node_id))
    return result


def leaf_node_ids(items: list[dict[str, Any]]) -> set[str]:
    parent_ids = {str(item.get("parentNodeId") or "") for item in items if str(item.get("parentNodeId") or "")}
    return {str(item.get("nodeId") or "") for item in items if str(item.get("nodeId") or "") not in parent_ids}


def module_groups_from_mapping(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    sub_by_module: dict[str, list[dict[str, Any]]] = {}
    for sub in mapping.get("subModuleGroups") or []:
        if not isinstance(sub, dict):
            continue
        module_key = str(sub.get("moduleKey") or "")
        if not module_key:
            continue
        sub_by_module.setdefault(module_key, []).append(
            {"key": str(sub.get("key") or ""), "label": str(sub.get("label") or "")}
        )
    groups: list[dict[str, Any]] = []
    for raw in mapping.get("moduleGroups") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "")
        groups.append(
            {
                "key": key,
                "label": str(raw.get("label") or key),
                "order": coerce_int(raw.get("order"), len(groups) + 1),
                "subModules": sub_by_module.get(key, []),
            }
        )
    return groups


def task_from_toc_item(item: dict[str, Any], mapping: dict[str, Any], now: str) -> dict[str, Any]:
    title = str(item.get("title") or "").strip()
    rule = best_mapping_rule(title, mapping)
    task_key_base = str(rule.get("key") or mapping.get("fallback", {}).get("key") or "manual_mapping_required")
    module_key = str(rule.get("moduleKey") or mapping.get("fallback", {}).get("moduleKey") or "commitments_and_notes")
    task_type = str(rule.get("taskType") or mapping.get("fallback", {}).get("taskType") or "document")
    decision = str(rule.get("decision") or mapping.get("fallback", {}).get("decision") or "review_required")
    sub_module = str(rule.get("subModuleKey") or "")
    display_order = coerce_int(item.get("order"), 1) * 10
    task_key = stable_key(task_key_base, title, str(item.get("number") or item.get("nodeId") or ""))
    risks = []
    source_type = "toc_fixed" if rule else "manual"
    if not rule:
        risks.append("manual_placement_required")
    if task_type == "certificate":
        risks.append("expiry_check_required")
        if task_key_base in {"turbine_model_certificate", "component_type_certificate"}:
            risks.append("model_fit_review_required")
    if decision == "material_required":
        risks.append("missing_material")

    task = {
        "id": f"BTASK-{display_order:04d}",
        "taskKey": task_key,
        "title": title,
        "titleAlias": [],
        "moduleKey": module_key,
        "taskType": task_type,
        "decision": decision,
        "status": status_from_decision(decision),
        "sourceType": source_type,
        "sourceRequirement": source_requirement_from_toc(item, source_type),
        "sourceEvidenceRefs": source_refs_from_toc(item),
        "tocTarget": toc_target_from_item(item),
        "candidateMaterials": [],
        "selectedMaterialRefs": [],
        "resolvedArtifacts": [],
        "assemblyMode": default_assembly_mode(module_key, task_type, decision, title),
        "materialUsage": "",
        "fillPlan": build_fill_plan(task_type, decision, title, module_key),
        "selectedEvidenceSegments": [],
        "riskFlags": dedupe(risks),
        "requirementLevel": "required",
        "assigneeMode": assignee_mode(task_type, decision),
        "displayOrder": display_order,
        "fingerprint": fingerprint([module_key, task_type, title, str(item.get("nodeId") or "")]),
        "updatedAt": now,
    }
    if sub_module:
        task["subModuleKey"] = sub_module
    topic_group = topic_group_for_title(title, module_key)
    if topic_group:
        task.update(topic_group)
    return task


def best_mapping_rule(title: str, mapping: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_text(title)
    best: tuple[int, dict[str, Any]] = (0, {})
    for rule in mapping.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        score = 0
        for keyword in rule.get("keywords") or []:
            key = normalize_text(keyword)
            if key and key in normalized:
                score += len(key)
        if score > best[0]:
            best = (score, rule)
    return best[1]


def attach_parse_artifacts(
    *,
    tasks: list[dict[str, Any]],
    toc_refs: list[dict[str, Any]],
    parse_result: dict[str, Any],
    commitment_rules: dict[str, Any],
    now: str,
) -> None:
    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    letters = structured.get("commitmentLetters") if isinstance(structured.get("commitmentLetters"), list) else []
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    scoring = structured.get("businessScoringAsset") if isinstance(structured.get("businessScoringAsset"), dict) else {}
    if not scoring:
        scoring = structured.get("scoringAsset") if isinstance(structured.get("scoringAsset"), dict) else {}

    for appendix in appendices:
        if isinstance(appendix, dict):
            attach_appendix_to_task(tasks, appendix, now)
    if scoring:
        attach_scoring_to_task(tasks, scoring, now)
    for letter in letters:
        if isinstance(letter, dict):
            attach_commitment_letter(tasks, toc_refs, letter, commitment_rules, now)


def attach_appendix_to_task(tasks: list[dict[str, Any]], appendix: dict[str, Any], now: str) -> None:
    title = str(appendix.get("title") or appendix.get("name") or "商务附件模板").strip()
    if not title:
        return
    task = best_task_for_title(tasks, title) or best_task_for_title(tasks, "附件 模板")
    if not task:
        return
    artifact = artifact_from_parse_item(
        appendix,
        artifact_type="parse_appendix_template",
        source_mode="parsed_from_tender_attachment_template",
        default_name=f"{title}.docx",
    )
    append_unique_artifact(task, artifact)
    task["updatedAt"] = now
    add_unique(task, "riskFlags", "parser_generated_unconfirmed")
    if str(appendix.get("assetReviewStatus") or "") == "approved":
        set_task_ready_if_artifact_confirmed(task)


def attach_scoring_to_task(tasks: list[dict[str, Any]], scoring: dict[str, Any], now: str) -> None:
    task = (
        best_task_for_title(tasks, "商务评分索引表")
        or best_task_for_title(tasks, "商务评分标准")
        or best_task_for_title(tasks, "评分标准")
        or best_business_scoring_task(tasks)
    )
    if not task:
        return
    path = str(scoring.get("docxPath") or scoring.get("path") or "")
    if not path:
        return
    artifact = {
        "artifactId": str(scoring.get("id") or "ART-SCORING"),
        "artifactType": "parse_business_scoring",
        "fileName": str(scoring.get("fileName") or Path(path).name or "商务评分标准.docx"),
        "filePath": path,
        "sourceMode": "parsed_business_scoring",
        "version": 1,
        "previewable": True,
        "confirmed": str(scoring.get("reviewStatus") or scoring.get("status") or "") == "approved",
        "reviewStatus": str(scoring.get("reviewStatus") or scoring.get("status") or "pending_review"),
    }
    append_unique_artifact(task, artifact)
    task["updatedAt"] = now
    task["assemblyMode"] = "attach_whole_file"
    task["materialUsage"] = "attach_whole"
    task["fillPlan"] = merge_fill_plan_with_task(task)
    if artifact["confirmed"]:
        set_task_ready_if_artifact_confirmed(task)
    else:
        task["decision"] = "review_required"
        task["status"] = "review_required"
        add_unique(task, "riskFlags", "parser_generated_unconfirmed")


def best_business_scoring_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for task in tasks:
        title = str(task.get("title") or "")
        task_key = str(task.get("taskKey") or "")
        score = 0
        if "商务评分" in title or "评分索引" in title or "评分标准" in title:
            score += 10
        if "business_scoring" in task_key:
            score += 8
        if str(task.get("moduleKey") or "") == "structured_response_tables":
            score += 2
        if score:
            candidates.append((score, task))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def attach_commitment_letter(
    tasks: list[dict[str, Any]],
    toc_refs: list[dict[str, Any]],
    letter: dict[str, Any],
    commitment_rules: dict[str, Any],
    now: str,
) -> None:
    title = str(letter.get("title") or letter.get("name") or "承诺函").strip()
    if not title:
        return
    if is_technical_boundary(title, commitment_rules):
        return
    task = best_task_for_title(tasks, title)
    if not task:
        task = best_commitment_task(tasks) or create_parser_commitment_task(tasks, toc_refs, letter, now)
        if task not in tasks:
            tasks.append(task)
            append_task_to_toc_ref(toc_refs, task)
    artifact = artifact_from_parse_item(
        letter,
        artifact_type="parse_commitment_letter",
        source_mode="generated_by_s1_business_parser",
        default_name=f"{title}.docx",
    )
    append_unique_artifact(task, artifact)
    task["sourceType"] = "parser_explicit"
    task["sourceRequirement"] = source_requirement_from_letter(letter)
    add_unique(task, "sourceEvidenceRefs", source_evidence_from_letter(letter), key_field="id")
    add_unique(task, "riskFlags", "parser_generated_unconfirmed")
    task["decision"] = "review_required"
    task["status"] = "review_required"
    task["updatedAt"] = now
    if str(letter.get("assetReviewStatus") or "") == "approved":
        artifact["confirmed"] = True
        set_task_ready_if_artifact_confirmed(task)


def ensure_special_certificate_tasks(
    *,
    tasks: list[dict[str, Any]],
    toc_refs: list[dict[str, Any]],
    toc_items: list[dict[str, Any]],
    mapping: dict[str, Any],
    certificate_rules: dict[str, Any],
    now: str,
) -> None:
    combined_titles = " ".join(str(item.get("title") or "") for item in toc_items)
    extras = [
        ("机型认证证书", "turbine_model_certificate"),
        ("大部件型式认证证书", "component_type_certificate"),
    ]
    for title, rule_key in extras:
        if any(rule_key in str(task.get("taskKey") or "") for task in tasks):
            continue
        if normalize_text(title) not in normalize_text(combined_titles) and "认证" not in normalize_text(combined_titles):
            # 商务标专题证书高频关键材料：即便目录未单列，也进入待复核任务。
            pass
        target_item = best_toc_for_special_certificate(toc_items) or (toc_items[-1] if toc_items else {})
        synthetic = {
            **target_item,
            "title": title,
            "order": coerce_int(target_item.get("order"), len(tasks) + 1) + len(tasks),
            "nodeId": str(target_item.get("nodeId") or "TOC-MANUAL"),
        }
        rule = next((r for r in mapping.get("rules") or [] if isinstance(r, dict) and str(r.get("key") or "") == rule_key), {})
        task = task_from_toc_item(synthetic, {**mapping, "rules": [rule]}, now)
        task["sourceType"] = "parser_semantic"
        task["decision"] = "material_required"
        task["status"] = "needs_input"
        add_unique(task, "riskFlags", "manual_placement_required")
        tasks.append(task)
        append_task_to_toc_ref(toc_refs, task)


def add_candidate_materials(tasks: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    material_index = manifest.get("materialIndex") if isinstance(manifest.get("materialIndex"), list) else []
    template_index = manifest.get("templateIndex") if isinstance(manifest.get("templateIndex"), list) else []
    selected_model = manifest.get("selectedBusinessTurbineModel") if isinstance(manifest.get("selectedBusinessTurbineModel"), dict) else {}
    wiki_index = manifest.get("businessWikiIndex") if isinstance(manifest.get("businessWikiIndex"), dict) else {}
    material_by_id = {
        str(material.get("id") or material.get("materialId") or ""): material
        for material in material_index
        if isinstance(material, dict) and str(material.get("id") or material.get("materialId") or "")
    }
    for task in tasks:
        template_candidates = template_candidates_for_task(task, template_index)
        if template_candidates:
            task["templateCandidates"] = template_candidates[:6]
        candidates_by_key: dict[str, dict[str, Any]] = {}
        for material in material_index:
            if not isinstance(material, dict):
                continue
            score, reason, risk_flags = material_match_score(task, material, selected_model)
            if score <= 0:
                continue
            candidate = {
                "materialId": str(material.get("id") or material.get("materialId") or ""),
                "materialName": str(material.get("name") or material.get("fileName") or ""),
                "libraryScope": str(material.get("materialTier") or material.get("libraryScope") or ""),
                "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
                "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
                "sourceType": str(material.get("sourceType") or "material_library"),
                "candidateType": str(material.get("candidateType") or "raw_material"),
                "cleanStatus": str(material.get("cleanStatus") or ""),
                "cleanedFileName": str(material.get("cleanedFileName") or ""),
                "score": round(score, 4),
                "reason": reason,
                "path": str(material.get("path") or material.get("folderPath") or ""),
                "fileType": file_type(material),
                "previewable": True,
                "folderPath": str(material.get("folderPath") or ""),
                "reviewStatus": str(material.get("reviewStatus") or ""),
                "tags": [str(item) for item in material.get("tags") or [] if str(item).strip()][:16],
                "keywords": [str(item) for item in material.get("keywords") or [] if str(item).strip()][:24],
                "summary": str(material.get("summary") or ""),
            }
            merge_candidate_material(candidates_by_key, candidate)
            for flag in risk_flags:
                add_unique(task, "riskFlags", flag)
        for wiki_candidate in wiki_material_candidates(task, wiki_index, material_index, material_by_id, selected_model):
            merge_candidate_material(candidates_by_key, wiki_candidate)
            for flag in wiki_candidate.get("riskFlags") or []:
                add_unique(task, "riskFlags", flag)
        for feedback_candidate in feedback_material_candidates(task, manifest, material_by_id):
            merge_candidate_material(candidates_by_key, feedback_candidate)
            add_unique(task, "riskFlags", "manual_feedback_candidate")
        candidates = list(candidates_by_key.values())
        candidates.sort(key=candidate_sort_key, reverse=True)
        task["candidateMaterials"] = dedupe_materials(candidates[:8])
        apply_assembly_intent(task)


def template_candidates_for_task(task: dict[str, Any], template_index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not should_use_template_candidates(task):
        return []
    candidates: list[dict[str, Any]] = []
    for template in template_index:
        if not isinstance(template, dict):
            continue
        score, reason = template_match_score(task, template)
        if score <= 0:
            continue
        candidates.append(
            {
                "templateId": str(template.get("templateId") or ""),
                "templateName": str(template.get("templateName") or template.get("fileName") or ""),
                "fileName": str(template.get("fileName") or ""),
                "filePath": str(template.get("filePath") or ""),
                "originalPath": str(template.get("originalPath") or ""),
                "sourceMode": str(template.get("sourceMode") or ""),
                "sourceLabel": str(template.get("sourceLabel") or ""),
                "templateScope": str(template.get("templateScope") or ""),
                "assemblyMode": "template_fill_docx",
                "materialUsage": "fill_template",
                "mimeType": str(template.get("mimeType") or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                "score": round(score, 4),
                "reason": reason,
                "previewable": True,
                "confirmed": False,
                "reviewStatus": "candidate",
                "candidateType": "bid_template",
            }
        )
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


def should_use_template_candidates(task: dict[str, Any]) -> bool:
    mode = str(task.get("assemblyMode") or "")
    usage = str(task.get("materialUsage") or "")
    decision = str(task.get("decision") or "")
    title = str(task.get("title") or "")
    return (
        mode == "template_fill_docx"
        or usage == "fill_template"
        or decision == "fill_required"
        or any(token in title for token in ["投标函", "授权", "廉洁", "承诺", "声明", "说明", "履约", "专用章"])
    )


def template_match_score(task: dict[str, Any], template: dict[str, Any]) -> tuple[float, str]:
    title = normalize_text(str(task.get("title") or ""))
    template_text = normalize_text(" ".join([
        str(template.get("templateName") or ""),
        str(template.get("fileName") or ""),
        str(template.get("sourceLabel") or ""),
        str(template.get("sourceMode") or ""),
    ]))
    if not template_text:
        return 0.0, ""
    score = float(template.get("score") or 0.7)
    reasons = [str(template.get("reason") or "投标模板候选")]
    if str(template.get("templateScope") or "") == "project":
        score += 0.12
        reasons.append("项目上传模板优先")
    if title and title in template_text:
        score += 0.14
        reasons.append("模板名命中任务标题")
    for token in business_template_tokens(title):
        if token in template_text:
            score += 0.05
            reasons.append(f"命中{token}")
            break
    return min(score, 0.99), " + ".join(dedupe(reasons))


def business_template_tokens(value: str) -> list[str]:
    text = normalize_text(value)
    tokens = ["投标函", "授权", "廉洁", "承诺", "声明", "说明", "履约", "专用章", "附件", "格式", "模板"]
    return [token for token in tokens if token in text]


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, int, int, int]:
    return (
        float(candidate.get("score") or 0),
        1 if candidate.get("feedbackKey") else 0,
        1 if candidate.get("evidenceSegmentId") else 0,
        1 if candidate.get("wikiCardId") else 0,
    )


def apply_assembly_intent(task: dict[str, Any]) -> None:
    candidates = [item for item in task.get("candidateMaterials") or [] if isinstance(item, dict)]
    template_candidates = [item for item in task.get("templateCandidates") or [] if isinstance(item, dict)]
    best = candidates[0] if candidates else {}
    inferred = "template_fill_docx" if template_candidates else assembly_mode_from_candidate(task, best) if best else ""
    if inferred:
        task["assemblyMode"] = inferred
    else:
        task["assemblyMode"] = str(task.get("assemblyMode") or default_assembly_mode(
            str(task.get("moduleKey") or ""),
            str(task.get("taskType") or ""),
            str(task.get("decision") or ""),
            str(task.get("title") or ""),
        ))
    task["materialUsage"] = str(
        ("fill_template" if template_candidates else "")
        or (best.get("wikiUsageMode") if best else "")
        or ASSEMBLY_MODE_TO_USAGE.get(str(task.get("assemblyMode") or ""), "")
    )
    task["fillPlan"] = merge_fill_plan_with_task(task)
    task["selectedEvidenceSegments"] = evidence_segments_from_candidates(candidates)
    if str(task.get("assemblyMode") or "") == "extract_segment" and not task["selectedEvidenceSegments"]:
        add_unique(task, "riskFlags", "segment_location_required")


def assembly_mode_from_candidate(task: dict[str, Any], candidate: dict[str, Any]) -> str:
    usage = normalize_usage_mode(str(candidate.get("wikiUsageMode") or ""))
    if usage:
        return usage
    artifact_mode = normalize_usage_mode(str(candidate.get("assemblyMode") or ""))
    if artifact_mode:
        return artifact_mode
    file_type_value = str(candidate.get("fileType") or "").lower()
    path = str(candidate.get("path") or candidate.get("materialName") or "").lower()
    task_type = str(task.get("taskType") or "")
    if task_type in {"certificate", "attachment"}:
        if file_type_value in {"pdf", "image"} or path.endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
            return "embed_scan_or_image"
        return "attach_whole_file"
    if task_type == "table":
        return "table_fill_from_material"
    if task_type == "bundle":
        return "extract_and_summarize" if candidate.get("materialId") else "attach_whole_file"
    return ""


def normalize_usage_mode(value: str) -> str:
    key = str(value or "").strip().lower().replace("-", "_")
    return USAGE_MODE_TO_ASSEMBLY_MODE.get(key, "")


def merge_fill_plan_with_task(task: dict[str, Any]) -> dict[str, Any]:
    base = build_fill_plan(
        str(task.get("taskType") or ""),
        str(task.get("decision") or ""),
        str(task.get("title") or ""),
        str(task.get("moduleKey") or ""),
    )
    base["mode"] = str(task.get("assemblyMode") or base["mode"])
    base["materialUsage"] = str(task.get("materialUsage") or ASSEMBLY_MODE_TO_USAGE.get(base["mode"], ""))
    if task.get("selectedEvidenceSegments"):
        base["evidenceSegmentCount"] = len(task.get("selectedEvidenceSegments") or [])
    return base


def evidence_segments_from_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        segment_id = str(candidate.get("evidenceSegmentId") or "").strip()
        if not segment_id or segment_id in seen:
            continue
        seen.add(segment_id)
        evidence = candidate.get("wikiEvidence") if isinstance(candidate.get("wikiEvidence"), dict) else {}
        segments.append(
            {
                "segmentId": segment_id,
                "title": str(candidate.get("evidenceSegmentTitle") or evidence.get("segmentTitle") or ""),
                "materialId": str(candidate.get("materialId") or ""),
                "materialName": str(candidate.get("materialName") or ""),
                "wikiCardId": str(candidate.get("wikiCardId") or evidence.get("cardId") or ""),
                "sourcePages": str(candidate.get("evidenceSourcePages") or evidence.get("sourcePages") or ""),
                "summary": str(candidate.get("evidenceSummary") or evidence.get("summary") or ""),
                "usageMode": str(candidate.get("wikiUsageMode") or evidence.get("usageMode") or ""),
            }
        )
    return segments[:8]


def feedback_material_candidates(
    task: dict[str, Any],
    manifest: dict[str, Any],
    material_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    feedback = manifest.get("materialFeedback") if isinstance(manifest.get("materialFeedback"), dict) else {}
    items = [item for item in feedback.get("items") or [] if isinstance(item, dict)]
    candidates: list[dict[str, Any]] = []
    for item in items:
        relevance = feedback_relevance(task, item)
        if relevance <= 0:
            continue
        material_id = str(item.get("materialId") or "").strip()
        material = material_by_id.get(material_id, {})
        material_name = str(material.get("name") or material.get("fileName") or item.get("materialName") or material_id)
        folder_path = str(material.get("folderPath") or item.get("folderPath") or "")
        score = min(0.995, 0.86 + relevance * 0.14)
        candidates.append(
            {
                "materialId": material_id,
                "materialName": material_name,
                "libraryScope": str(material.get("materialTier") or item.get("materialTier") or ""),
                "businessMaterialKind": str(material.get("businessMaterialKind") or item.get("businessMaterialKind") or ""),
                "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or item.get("businessMaterialKindLabel") or ""),
                "cleanStatus": str(material.get("cleanStatus") or item.get("cleanStatus") or ""),
                "cleanedFileName": str(material.get("cleanedFileName") or item.get("cleanedFileName") or ""),
                "score": round(score, 4),
                "reason": "人工纠偏反馈命中 + 同项目历史选择优先",
                "path": folder_path,
                "fileType": file_type(material) if material else file_type({"name": material_name}),
                "previewable": True,
                "folderPath": folder_path,
                "wikiCardId": str(item.get("wikiCardId") or ""),
                "wikiUsageMode": str(item.get("materialUsage") or ""),
                "evidenceSegmentId": str(item.get("evidenceSegmentId") or ""),
                "evidenceSegmentTitle": str(item.get("evidenceSegmentTitle") or ""),
                "evidenceSummary": str(item.get("evidenceSummary") or ""),
                "wikiEvidence": {
                    "cardId": str(item.get("wikiCardId") or ""),
                    "segmentId": str(item.get("evidenceSegmentId") or ""),
                    "segmentTitle": str(item.get("evidenceSegmentTitle") or ""),
                    "summary": str(item.get("evidenceSummary") or ""),
                    "usageMode": str(item.get("materialUsage") or ""),
                    "mappingModule": str(item.get("moduleKey") or ""),
                    "feedbackKey": str(item.get("feedbackKey") or ""),
                },
                "feedbackKey": str(item.get("feedbackKey") or ""),
                "feedbackSource": str(item.get("source") or "business_s3_manual_selection"),
                "riskFlags": ["manual_feedback_candidate"],
            }
        )
    return candidates


def feedback_relevance(task: dict[str, Any], feedback: dict[str, Any]) -> float:
    score = 0.0
    if str(task.get("moduleKey") or "") and str(task.get("moduleKey") or "") == str(feedback.get("moduleKey") or ""):
        score += 0.35
    if str(task.get("taskType") or "") and str(task.get("taskType") or "") == str(feedback.get("taskType") or ""):
        score += 0.18
    if str(task.get("assemblyMode") or "") and str(task.get("assemblyMode") or "") == str(feedback.get("assemblyMode") or ""):
        score += 0.1
    task_title = normalize_text(task.get("title") or "")
    feedback_text = normalize_text(
        " ".join(
            [
                str(feedback.get("taskTitle") or ""),
                str(feedback.get("tocTitle") or ""),
                str(feedback.get("materialName") or ""),
                str(feedback.get("folderPath") or ""),
                str(feedback.get("evidenceSegmentTitle") or ""),
                str(feedback.get("evidenceSummary") or ""),
            ]
        )
    )
    title_score = similarity_score(task_title, feedback_text)
    if title_score >= 0.16:
        score += min(0.35, title_score)
    if task_title and task_title in feedback_text:
        score += 0.2
    return min(score, 0.95) if score >= 0.35 else 0.0


def merge_candidate_material(candidates_by_key: dict[str, dict[str, Any]], candidate: dict[str, Any]) -> None:
    key = candidate_key(candidate)
    if not key:
        return
    segment = candidate_evidence_segment(candidate)
    existing = candidates_by_key.get(key)
    if existing is None:
        stored = {name: value for name, value in candidate.items() if name != "riskFlags"}
        if segment:
            stored["evidenceSegments"] = [segment]
        candidates_by_key[key] = stored
        return
    if float(candidate.get("score") or 0) > float(existing.get("score") or 0):
        existing["score"] = candidate.get("score")
    for reason in str(candidate.get("reason") or "").split(" + "):
        if reason and reason not in str(existing.get("reason") or ""):
            existing["reason"] = " + ".join(filter(None, [str(existing.get("reason") or ""), reason]))
    for key_name, value in candidate.items():
        if key_name in {"score", "reason", "riskFlags"}:
            continue
        if value not in (None, "", [], {}) and not existing.get(key_name):
            existing[key_name] = value
    if candidate.get("wikiEvidence"):
        existing["wikiEvidence"] = candidate["wikiEvidence"]
    if candidate.get("wikiCardId"):
        existing["wikiCardId"] = candidate["wikiCardId"]
    if segment:
        existing_segments = existing.setdefault("evidenceSegments", [])
        if isinstance(existing_segments, list):
            existing_ids = {str(item.get("evidenceSegmentId") or item.get("segmentId") or "") for item in existing_segments if isinstance(item, dict)}
            segment_id = str(segment.get("evidenceSegmentId") or segment.get("segmentId") or "")
            if segment_id and segment_id not in existing_ids:
                existing_segments.append(segment)
    existing["score"] = round(min(float(existing.get("score") or 0), 0.99), 4)


def candidate_key(candidate: dict[str, Any]) -> str:
    return str(candidate.get("materialId") or candidate.get("path") or candidate.get("materialName") or "")


def candidate_evidence_segment(candidate: dict[str, Any]) -> dict[str, Any]:
    segment_id = str(candidate.get("evidenceSegmentId") or "").strip()
    if not segment_id:
        return {}
    return {
        "segmentId": segment_id,
        "evidenceSegmentId": segment_id,
        "evidenceSegmentTitle": str(candidate.get("evidenceSegmentTitle") or ""),
        "title": str(candidate.get("evidenceSegmentTitle") or ""),
        "evidenceSegmentType": str(candidate.get("evidenceSegmentType") or ""),
        "evidenceSourcePages": str(candidate.get("evidenceSourcePages") or ""),
        "sourcePages": str(candidate.get("evidenceSourcePages") or ""),
        "evidenceSummary": str(candidate.get("evidenceSummary") or ""),
        "summary": str(candidate.get("evidenceSummary") or ""),
        "wikiCardId": str(candidate.get("wikiCardId") or ""),
        "wikiUsageMode": str(candidate.get("wikiUsageMode") or ""),
        "materialId": str(candidate.get("materialId") or ""),
        "materialName": str(candidate.get("materialName") or ""),
        "folderPath": str(candidate.get("folderPath") or candidate.get("path") or ""),
        "businessMaterialKind": str(candidate.get("businessMaterialKind") or ""),
        "businessMaterialKindLabel": str(candidate.get("businessMaterialKindLabel") or ""),
        "wikiEvidence": dict(candidate.get("wikiEvidence") or {}) if isinstance(candidate.get("wikiEvidence"), dict) else {},
    }


def wiki_material_candidates(
    task: dict[str, Any],
    wiki_index: dict[str, Any],
    material_index: list[dict[str, Any]],
    material_by_id: dict[str, dict[str, Any]],
    selected_model: dict[str, Any],
) -> list[dict[str, Any]]:
    if not wiki_index:
        return []
    rows = [row for row in wiki_index.get("mappingRows") or [] if isinstance(row, dict)]
    cards = [card for card in wiki_index.get("evidenceCards") or [] if isinstance(card, dict)]
    segments = [segment for segment in wiki_index.get("evidenceSegments") or [] if isinstance(segment, dict)]
    cards_by_id = {
        str(card.get("card_id") or ""): card
        for card in cards
        if str(card.get("card_id") or "")
    }
    segments_by_card_id: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        card_id = str(segment.get("card_id") or "")
        if card_id:
            segments_by_card_id.setdefault(card_id, []).append(segment)
    candidates: list[dict[str, Any]] = []
    seen_cards: set[str] = set()
    seen_segments: set[str] = set()

    for row in rows:
        relevance = wiki_mapping_relevance(task, row)
        if relevance <= 0:
            continue
        for card_id in split_wiki_list(row.get("candidate_card_ids")):
            card = cards_by_id.get(card_id)
            if not card:
                continue
            seen_cards.add(card_id)
            card_segments = segments_by_card_id.get(card_id) or []
            segment_candidates = wiki_segment_candidates_for_card(
                task,
                card,
                card_segments,
                row,
                material_index,
                material_by_id,
                selected_model,
                relevance,
            )
            if segment_candidates:
                candidates.extend(segment_candidates)
                seen_segments.update(str(item.get("evidenceSegment", {}).get("segmentId") or "") for item in segment_candidates)
            else:
                candidate = wiki_candidate_from_card(task, card, row, material_index, material_by_id, selected_model, relevance)
                if candidate:
                    candidates.append(candidate)

    for card in cards:
        card_id = str(card.get("card_id") or "")
        if card_id in seen_cards:
            continue
        relevance = wiki_card_relevance(task, card)
        if relevance <= 0:
            continue
        candidate = wiki_candidate_from_card(task, card, {}, material_index, material_by_id, selected_model, relevance)
        if candidate:
            candidates.append(candidate)
    for segment in segments:
        segment_id = str(segment.get("segment_id") or "")
        if segment_id and segment_id in seen_segments:
            continue
        relevance = wiki_segment_relevance(task, segment)
        if relevance <= 0:
            continue
        card = cards_by_id.get(str(segment.get("card_id") or "")) or segment
        candidate = wiki_candidate_from_segment(
            task,
            segment,
            card,
            {},
            material_index,
            material_by_id,
            selected_model,
            relevance,
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def wiki_mapping_relevance(task: dict[str, Any], row: dict[str, Any]) -> float:
    task_title = normalize_text(task.get("title") or "")
    module_key = str(task.get("moduleKey") or "")
    module_code = str(row.get("module_code") or "").strip()
    module_name = normalize_text(row.get("module_name") or "")
    category = normalize_text(row.get("business_category") or "")
    score = 0.0
    if module_key in WIKI_MODULE_CODE_TO_MODULE_KEYS.get(module_code, set()):
        score += 0.45
    if task_title and module_name and similarity_score(task_title, module_name) >= 0.26:
        score += 0.35
    for token in tokenize_zh(task_title):
        if len(token) >= 2 and token in module_name + category:
            score += 0.04
            if score >= 0.8:
                break
    return min(score, 0.9) if score >= 0.35 else 0.0


def wiki_card_relevance(task: dict[str, Any], card: dict[str, Any]) -> float:
    task_title = normalize_text(task.get("title") or "")
    card_text = normalize_text(
        " ".join(
            [
                str(card.get("title") or ""),
                str(card.get("path") or ""),
                str(card.get("business_category") or ""),
                str(card.get("evidence_topic") or ""),
                str(card.get("document_type") or ""),
                " ".join(str(item) for item in card.get("keywords") or []),
                " ".join(str(item) for item in card.get("applicable_modules") or []),
                " ".join(str(item) for item in card.get("applicable_chapters") or []),
                " ".join(str(item) for item in card.get("chapter_keywords") or []),
            ]
        )
    )
    if not task_title or not card_text:
        return 0.0
    if task_title in card_text:
        return 0.72
    score = similarity_score(task_title, card_text)
    if score >= 0.18:
        return min(0.62, score + 0.2)
    module_keywords = module_material_keywords(str(task.get("moduleKey") or ""), str(task.get("taskType") or ""), str(task.get("subModuleKey") or ""))
    hits = sum(1 for keyword in module_keywords if normalize_text(keyword) and normalize_text(keyword) in card_text)
    if hits >= 2:
        return 0.45
    return 0.0


def wiki_segment_candidates_for_card(
    task: dict[str, Any],
    card: dict[str, Any],
    segments: list[dict[str, Any]],
    mapping_row: dict[str, Any],
    material_index: list[dict[str, Any]],
    material_by_id: dict[str, dict[str, Any]],
    selected_model: dict[str, Any],
    base_relevance: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for segment in segments:
        relevance = max(base_relevance, wiki_segment_relevance(task, segment))
        if relevance <= 0:
            continue
        candidate = wiki_candidate_from_segment(
            task,
            segment,
            card,
            mapping_row,
            material_index,
            material_by_id,
            selected_model,
            relevance,
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def wiki_segment_relevance(task: dict[str, Any], segment: dict[str, Any]) -> float:
    task_title = normalize_text(task.get("title") or "")
    segment_text = normalize_text(
        " ".join(
            [
                str(segment.get("title") or ""),
                str(segment.get("path") or ""),
                str(segment.get("business_category") or ""),
                str(segment.get("evidence_topic") or ""),
                str(segment.get("document_type") or ""),
                str(segment.get("summary") or ""),
                " ".join(str(item) for item in segment.get("keywords") or []),
                " ".join(str(item) for item in segment.get("key_fields") or []),
                " ".join(str(item) for item in segment.get("applicable_chapters") or []),
                " ".join(str(item) for item in segment.get("chapter_keywords") or []),
            ]
        )
    )
    if not task_title or not segment_text:
        return 0.0
    if task_title in segment_text:
        return 0.78
    synonym_hits = synonym_hit_count(task, segment_text)
    if synonym_hits >= 2:
        return min(0.76, 0.48 + synonym_hits * 0.08)
    score = similarity_score(task_title, segment_text)
    if score >= 0.18:
        return min(0.68, score + 0.25)
    module_keywords = module_material_keywords(str(task.get("moduleKey") or ""), str(task.get("taskType") or ""), str(task.get("subModuleKey") or ""))
    hits = sum(1 for keyword in module_keywords if normalize_text(keyword) and normalize_text(keyword) in segment_text)
    if hits >= 2:
        return 0.52
    return 0.0


def wiki_candidate_from_segment(
    task: dict[str, Any],
    segment: dict[str, Any],
    card: dict[str, Any],
    mapping_row: dict[str, Any],
    material_index: list[dict[str, Any]],
    material_by_id: dict[str, dict[str, Any]],
    selected_model: dict[str, Any],
    relevance: float,
) -> dict[str, Any] | None:
    material = material_for_wiki_card(segment if segment.get("material_id") else card, material_index, material_by_id)
    if not material:
        material = material_for_wiki_card(card, material_index, material_by_id)
    if not material:
        return None
    risk_flags = wiki_risk_flags({**card, **segment})
    reasons = ["Wiki证据片段命中"]
    if mapping_row:
        reasons.append(str(mapping_row.get("module_name") or "模板模块映射表"))
    if str(segment.get("source_pages") or ""):
        reasons.append("包含页码/位置线索")
    model_score = 0.0
    if str(segment.get("validity_status") or card.get("validity_status") or "") in {"valid", "有效"}:
        reasons.append("有效期状态可用")
        model_score += 0.03
    if str(task.get("taskType") or "") == "certificate":
        model_score += wiki_model_score({**card, **segment}, selected_model, risk_flags, reasons)
    score = 0.62 + relevance * 0.3 + model_score
    penalty, penalty_reasons = negative_match_penalty(task, segment)
    if penalty:
        score -= penalty
        risk_flags.append("semantic_match_only")
        reasons.extend(penalty_reasons)
    try:
        priority = float(str(segment.get("priority_score") or card.get("priority_score") or "0"))
        score += min(priority / 1000, 0.08)
    except ValueError:
        pass
    if score <= 0.34:
        return None
    usage_mode = str(segment.get("usage_mode") or card.get("usage_mode") or mapping_row.get("usage_mode") or "")
    card_id = str(segment.get("card_id") or card.get("card_id") or "")
    segment_id = str(segment.get("segment_id") or "")
    return {
        "materialId": str(material.get("id") or material.get("materialId") or segment.get("material_id") or card.get("material_id") or ""),
        "materialName": str(material.get("name") or material.get("fileName") or card.get("title") or segment.get("title") or ""),
        "libraryScope": str(material.get("materialTier") or material.get("libraryScope") or segment.get("material_tier") or card.get("material_tier") or ""),
        "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
        "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
        "cleanStatus": str(material.get("cleanStatus") or ""),
        "cleanedFileName": str(material.get("cleanedFileName") or ""),
        "score": round(min(score, 0.99), 4),
        "reason": " + ".join(dedupe(reasons)),
        "path": str(segment.get("path") or card.get("path") or material.get("path") or material.get("folderPath") or ""),
        "fileType": file_type(material) or file_type({"name": card.get("title") or segment.get("title") or ""}),
        "previewable": True,
        "folderPath": str(material.get("folderPath") or ""),
        "wikiCardId": card_id,
        "wikiUsageMode": usage_mode,
        "validityStatus": str(segment.get("validity_status") or card.get("validity_status") or ""),
        "expiryDate": str(segment.get("expiry_date") or card.get("expiry_date") or ""),
        "evidenceSegmentId": segment_id,
        "evidenceSegmentTitle": str(segment.get("title") or ""),
        "evidenceSegmentType": str(segment.get("segment_type") or ""),
        "evidenceSourcePages": str(segment.get("source_pages") or ""),
        "evidenceSummary": str(segment.get("summary") or ""),
        "wikiEvidence": {
            "cardId": card_id,
            "segmentId": segment_id,
            "segmentTitle": str(segment.get("title") or ""),
            "segmentType": str(segment.get("segment_type") or ""),
            "sourcePages": str(segment.get("source_pages") or ""),
            "summary": str(segment.get("summary") or ""),
            "usageMode": usage_mode,
            "evidenceTopic": str(segment.get("evidence_topic") or card.get("evidence_topic") or ""),
            "applicableChapters": [str(item) for item in (segment.get("applicable_chapters") or card.get("applicable_chapters") or []) if str(item).strip()],
            "chapterKeywords": [str(item) for item in (segment.get("chapter_keywords") or card.get("chapter_keywords") or []) if str(item).strip()],
            "validityStatus": str(segment.get("validity_status") or card.get("validity_status") or ""),
            "expiryDate": str(segment.get("expiry_date") or card.get("expiry_date") or ""),
            "riskNotes": str(segment.get("risk_notes") or card.get("risk_notes") or ""),
            "ocrStatus": str(segment.get("ocr_status") or card.get("ocr_status") or ""),
            "ocrConfidence": str(segment.get("ocr_confidence") or card.get("ocr_confidence") or ""),
            "needsHumanConfirm": str(segment.get("needs_human_confirm") or card.get("needs_human_confirm") or ""),
            "mappingModule": str(mapping_row.get("module_name") or ""),
        },
        "riskFlags": risk_flags,
    }


def wiki_candidate_from_card(
    task: dict[str, Any],
    card: dict[str, Any],
    mapping_row: dict[str, Any],
    material_index: list[dict[str, Any]],
    material_by_id: dict[str, dict[str, Any]],
    selected_model: dict[str, Any],
    relevance: float,
) -> dict[str, Any] | None:
    material = material_for_wiki_card(card, material_index, material_by_id)
    if not material:
        return None
    model_score = 0.0
    risk_flags = wiki_risk_flags(card)
    reasons = ["Wiki映射/证据卡片命中"]
    if mapping_row:
        reasons.append(str(mapping_row.get("module_name") or "模板模块映射表"))
    if str(card.get("validity_status") or "") in {"valid", "有效"}:
        reasons.append("有效期状态可用")
        model_score += 0.03
    if str(task.get("taskType") or "") == "certificate":
        model_score += wiki_model_score(card, selected_model, risk_flags, reasons)
    score = 0.58 + relevance * 0.28 + model_score
    try:
        priority = float(str(card.get("priority_score") or "0"))
        score += min(priority / 1000, 0.08)
    except ValueError:
        pass
    return {
        "materialId": str(material.get("id") or material.get("materialId") or card.get("material_id") or ""),
        "materialName": str(material.get("name") or material.get("fileName") or card.get("title") or ""),
        "libraryScope": str(material.get("materialTier") or material.get("libraryScope") or card.get("material_tier") or ""),
        "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
        "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
        "cleanStatus": str(material.get("cleanStatus") or ""),
        "cleanedFileName": str(material.get("cleanedFileName") or ""),
        "score": round(min(score, 0.99), 4),
        "reason": " + ".join(dedupe(reasons)),
        "path": str(card.get("path") or material.get("path") or material.get("folderPath") or ""),
        "fileType": file_type(material) or file_type({"name": card.get("title") or ""}),
        "previewable": True,
        "folderPath": str(material.get("folderPath") or ""),
        "wikiCardId": str(card.get("card_id") or ""),
        "wikiUsageMode": str(card.get("usage_mode") or mapping_row.get("usage_mode") or ""),
        "validityStatus": str(card.get("validity_status") or ""),
        "expiryDate": str(card.get("expiry_date") or ""),
        "wikiEvidence": {
            "cardId": str(card.get("card_id") or ""),
            "usageMode": str(card.get("usage_mode") or mapping_row.get("usage_mode") or ""),
            "evidenceTopic": str(card.get("evidence_topic") or ""),
            "applicableChapters": [str(item) for item in (card.get("applicable_chapters") or []) if str(item).strip()],
            "chapterKeywords": [str(item) for item in (card.get("chapter_keywords") or []) if str(item).strip()],
            "validityStatus": str(card.get("validity_status") or ""),
            "expiryDate": str(card.get("expiry_date") or ""),
            "riskNotes": str(card.get("risk_notes") or ""),
            "ocrStatus": str(card.get("ocr_status") or ""),
            "ocrConfidence": str(card.get("ocr_confidence") or ""),
            "needsHumanConfirm": str(card.get("needs_human_confirm") or ""),
            "mappingModule": str(mapping_row.get("module_name") or ""),
        },
        "riskFlags": risk_flags,
    }


def material_for_wiki_card(
    card: dict[str, Any],
    material_index: list[dict[str, Any]],
    material_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    material_id = str(card.get("material_id") or card.get("materialId") or "").strip()
    if material_id and material_id in material_by_id:
        return material_by_id[material_id]
    card_path = normalize_text(card.get("path") or "")
    card_title = normalize_text(card.get("title") or "")
    for material in material_index:
        haystack = normalize_text(
            " ".join(
                str(material.get(key) or "")
                for key in ("id", "materialId", "name", "fileName", "folderPath", "cleanedFileName")
            )
        )
        if material_id and material_id.replace("RAW-", "") and normalize_text(material_id) in haystack:
            return material
        if card_title and card_title in haystack:
            return material
        if card_path and haystack and (card_path in haystack or haystack in card_path):
            return material
    return None


def wiki_risk_flags(card: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    status = str(card.get("validity_status") or "").strip().lower()
    if status in {"expired", "过期"}:
        flags.append("wiki_validity_expired")
    elif status in {"expiring_soon", "即将过期"}:
        flags.append("wiki_validity_expiring_soon")
    elif status in {"unknown", "pending_verify", "待核验", "待识别"}:
        flags.append("wiki_validity_pending_verify")
    if str(card.get("needs_human_confirm") or "").strip().lower() in {"yes", "true", "1"}:
        flags.append("wiki_human_confirm_required")
    confidence = str(card.get("ocr_confidence") or "").strip()
    try:
        if confidence not in {"", "n/a", "待OCR"} and float(confidence) < 0.75:
            flags.append("wiki_ocr_low_confidence")
    except ValueError:
        if confidence == "待OCR":
            flags.append("wiki_ocr_pending")
    if str(card.get("risk_notes") or "").strip() and str(card.get("risk_notes") or "").strip() != "无":
        flags.append("wiki_risk_note")
    return dedupe(flags)


def wiki_model_score(card: dict[str, Any], selected_model: dict[str, Any], risks: list[str], reasons: list[str]) -> float:
    model = normalize_text(selected_model.get("model") or selected_model.get("label") or selected_model.get("name") or "")
    if not model:
        risks.append("manual_model_input")
        return 0.0
    models = [normalize_text(item) for item in card.get("turbine_models") or [] if normalize_text(item)]
    if not models:
        return 0.0
    if any(item in model or model in item for item in models):
        reasons.append("Wiki机型字段匹配")
        return 0.14
    risks.append("model_fit_review_required")
    return 0.0


def split_wiki_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.split(r"[、,，;；]+", str(value or ""))
    return [str(item).strip(" `") for item in raw_values if str(item).strip(" `") and str(item).strip(" `") not in {"-", "[]"}]


def task_synonym_terms(task: dict[str, Any]) -> list[str]:
    title = str(task.get("title") or "")
    module_terms = module_material_keywords(
        str(task.get("moduleKey") or ""),
        str(task.get("taskType") or ""),
        str(task.get("subModuleKey") or ""),
    )
    terms = [title, *module_terms]
    normalized_title = normalize_text(title)
    for key, synonyms in TASK_SYNONYMS.items():
        normalized_key = normalize_text(key)
        if normalized_key and (normalized_key in normalized_title or any(normalize_text(term) and normalize_text(term) in normalized_title for term in synonyms)):
            terms.extend([key, *synonyms])
    return dedupe([term for term in terms if str(term).strip()])


def synonym_hit_count(task: dict[str, Any], haystack: str) -> int:
    normalized_haystack = normalize_text(haystack)
    if not normalized_haystack:
        return 0
    hits = 0
    for term in task_synonym_terms(task):
        key = normalize_text(term)
        if len(key) >= 2 and key in normalized_haystack:
            hits += 1
            if hits >= 4:
                break
    return hits


CAPACITY_THRESHOLD_RE = re.compile(r"(\d{1,2}(?:\.\d{1,2})?)\s*mw及以上")
MODEL_POWER_RE = re.compile(r"(?:ew)?(\d{1,2}(?:\.\d{1,2})?)[-—](\d{2,3})")


def _capacity_text(value: Any) -> str:
    # 容量/机型解析不能用 normalize_text（它会剥掉小数点和连字符）
    return re.sub(r"\s+", "", str(value or "").lower())


def task_capacity_threshold_mw(title: str) -> float:
    match = CAPACITY_THRESHOLD_RE.search(_capacity_text(title))
    return float(match.group(1)) if match else 0.0


def material_max_power_mw(material: dict[str, Any]) -> float:
    text = _capacity_text(
        " ".join(
            [
                str(material.get("turbineModelLabel") or ""),
                str(material.get("name") or ""),
                *[str(keyword) for keyword in material.get("keywords") or []],
            ]
        )
    )
    best = 0.0
    for match in MODEL_POWER_RE.finditer(text):
        power = float(match.group(1))
        if 1.0 <= power <= 30.0:
            best = max(best, power)
    return best


def negative_match_penalty(task: dict[str, Any], material: dict[str, Any]) -> tuple[float, list[str]]:
    haystack = normalize_text(
        " ".join(
            str(material.get(key) or "")
            for key in (
                "name",
                "fileName",
                "materialName",
                "folderPath",
                "path",
                "cleanedFileName",
                "title",
                "business_category",
                "document_type",
                "summary",
                "segment_type",
            )
        )
    )
    if not haystack:
        return 0.0, []
    module_key = str(task.get("moduleKey") or "")
    task_type = str(task.get("taskType") or "")
    total = 0.0
    reasons: list[str] = []
    for rule in NEGATIVE_MATCH_RULES:
        modules = rule.get("taskModules") or set()
        types = rule.get("taskTypes") or set()
        title_hints = rule.get("taskTitleHints") or []
        module_ok = not modules or module_key in modules
        type_ok = not types or task_type in types
        title_norm = normalize_text(task.get("title"))
        title_ok = not title_hints or any(normalize_text(hint) in title_norm for hint in title_hints)
        if not module_ok or not type_ok or not title_ok:
            continue
        if any(normalize_text(hint) and normalize_text(hint) in haystack for hint in rule.get("materialHints") or []):
            total += float(rule.get("penalty") or 0)
            reasons.append(str(rule.get("reason") or "负面规则降权"))
    return min(total, 0.75), dedupe(reasons)


def material_match_score(task: dict[str, Any], material: dict[str, Any], selected_model: dict[str, Any]) -> tuple[float, str, list[str]]:
    haystack = normalize_text(
        " ".join(
            [
                *[str(material.get(key) or "") for key in (
                    "name",
                    "fileName",
                    "folderPath",
                    "path",
                    "cleanedFileName",
                    "turbineModelLabel",
                    "businessMaterialKind",
                    "businessMaterialKindLabel",
                    "sourceType",
                    "candidateType",
                    "businessCategory",
                    "documentType",
                    "summary",
                    "customerName",
                    "projectType",
                    "scale",
                    "location",
                    "amount",
                    "turbineModel",
                )],
                " ".join(str(item) for item in material.get("tags") or []),
                " ".join(str(item) for item in material.get("keywords") or []),
            ]
        )
    )
    task_title = normalize_text(str(task.get("title") or ""))
    module_key = str(task.get("moduleKey") or "")
    task_type = str(task.get("taskType") or "")
    risks: list[str] = []
    score = 0.0
    hard_cap = 0.99
    reasons: list[str] = []

    if task_title and task_title in haystack:
        score += 0.65
        reasons.append("文件名/路径命中任务标题")
    synonym_hits = synonym_hit_count(task, haystack)
    if synonym_hits:
        score += min(0.22, synonym_hits * 0.08)
        reasons.append("命中任务同义词")
    for token in tokenize_zh(task_title):
        if len(token) >= 2 and token in haystack:
            score += min(0.2, len(token) / 20)
    module_keywords = module_material_keywords(module_key, task_type, str(task.get("subModuleKey") or ""))
    for keyword in module_keywords:
        key = normalize_text(keyword)
        if key and key in haystack:
            score += 0.18
            reasons.append(f"命中{keyword}")
            break
    if str(material.get("materialTier") or "") == "project":
        score += 0.08
        reasons.append("项目素材优先")
    elif str(material.get("materialTier") or "") == "customer":
        score += 0.05
        reasons.append("客户素材")
    if str(material.get("sourceType") or "") in {"performance_library", "performance_package"}:
        if module_key == "performance_cooperation_support":
            threshold = task_capacity_threshold_mw(str(task.get("title") or ""))
            if threshold:
                power = material_max_power_mw(material)
                if power and power < threshold:
                    # 机型容量低于任务门槛（如 6.25MW 条目进 10MW 任务），直接排除
                    return 0.0, "", []
                if not power:
                    risks.append("capacity_unverified")
            title_norm = normalize_text(str(task.get("title") or ""))
            if ("240" in title_norm or "试运行" in title_norm) and not any(
                token in haystack for token in ("240", "试运行")
            ):
                score -= 0.25
                risks.append("trial_run_evidence_unverified")
                reasons.append("缺试运行证据待人工确认")
            score += 0.18
            reasons.append("共用业绩库候选")
        else:
            # 跨模块时业绩资产硬性封顶，避免同义词饱和把分数顶满
            hard_cap = min(hard_cap, 0.3)
            reasons.append("业绩资产跨模块降权")

    if task_type == "certificate":
        score += certificate_model_score(material, selected_model, risks, reasons)
    penalty, penalty_reasons = negative_match_penalty(task, material)
    if penalty:
        score -= penalty
        risks.append("semantic_match_only")
        reasons.extend(penalty_reasons)
    if score <= 0.24:
        return 0.0, "", []
    return min(score, hard_cap), " + ".join(dedupe(reasons)) or "素材语义候选", risks


def certificate_model_score(material: dict[str, Any], selected_model: dict[str, Any], risks: list[str], reasons: list[str]) -> float:
    model = normalize_text(selected_model.get("model") or selected_model.get("label") or selected_model.get("name") or "")
    material_model = normalize_text(material.get("turbineModelLabel") or material.get("model") or "")
    if not model:
        risks.append("manual_model_input")
        return 0.0
    if material_model and material_model in model or model and model in material_model:
        reasons.append("机型标签匹配")
        return 0.25
    if material_model:
        risks.append("model_fit_review_required")
        return 0.05
    risks.append("model_fit_review_required")
    return 0.0


def project_fact_overview(manifest: dict[str, Any]) -> dict[str, Any]:
    table = manifest.get("projectFactTable") if isinstance(manifest.get("projectFactTable"), dict) else {}
    fields = [field for field in table.get("fields") or [] if isinstance(field, dict)]
    missing = [
        str(field.get("label") or "")
        for field in fields
        if bool(field.get("required", True)) and not str(field.get("value") or "").strip()
    ]
    ready_count = sum(1 for field in fields if str(field.get("value") or "").strip())
    return {
        "available": bool(fields),
        "missingFacts": [label for label in missing if label],
        "readyFactCount": ready_count,
        "totalFactCount": len(fields),
    }


def annotate_fact_readiness(tasks: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    overview = project_fact_overview(manifest)
    for task in tasks:
        fill_plan = task.get("fillPlan") if isinstance(task.get("fillPlan"), dict) else {}
        artifacts = [item for item in task.get("resolvedArtifacts") or [] if isinstance(item, dict)]
        if (
            any(str(item.get("assemblyMode") or "") == "template_fill_docx" for item in artifacts)
            and str(task.get("assemblyMode") or "") != "template_fill_docx"
        ):
            # 任务装配方式以解析附件模板工件为准，避免 fillPlan 与工件自相矛盾
            task["assemblyMode"] = "template_fill_docx"
            task["materialUsage"] = "fill_template"
            fill_plan["mode"] = "template_fill_docx"
            fill_plan["requiresProjectFacts"] = True
            fill_plan["requiresMaterialEvidence"] = False
            fill_plan["outputArtifactType"] = "filled_docx"
            task["fillPlan"] = fill_plan
        if not overview["available"] or not fill_plan.get("requiresProjectFacts"):
            continue
        fill_plan["missingFacts"] = list(overview["missingFacts"])
        fill_plan["readyFactCount"] = overview["readyFactCount"]
        fill_plan["totalFactCount"] = overview["totalFactCount"]
        task["fillPlan"] = fill_plan
        if overview["missingFacts"]:
            add_unique(task, "riskFlags", "missing_project_facts")
            if str(task.get("status") or "") == "ready":
                # 必填事实缺失时不允许 ready，防止带空白占位直接进装配
                task["status"] = "review_required"
                task["decision"] = "review_required"
        else:
            remove_value(task, "riskFlags", "missing_project_facts")


def recompute_task_states(tasks: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    for task in tasks:
        artifacts = [item for item in task.get("resolvedArtifacts") or [] if isinstance(item, dict)]
        confirmed_artifacts = [item for item in artifacts if bool(item.get("confirmed"))]
        candidates = [item for item in task.get("candidateMaterials") or [] if isinstance(item, dict)]
        template_candidates = [item for item in task.get("templateCandidates") or [] if isinstance(item, dict)]
        if confirmed_artifacts:
            task["decision"] = "ready"
            task["status"] = "ready"
            remove_value(task, "riskFlags", "missing_material")
            remove_value(task, "riskFlags", "parser_generated_unconfirmed")
            continue
        if artifacts:
            task["decision"] = "review_required"
            task["status"] = "review_required"
            continue
        if template_candidates:
            task["decision"] = "review_required"
            task["status"] = "review_required"
            remove_value(task, "riskFlags", "missing_material")
            add_unique(task, "riskFlags", "candidate_template_unconfirmed")
            continue
        if candidates:
            task["decision"] = "review_required"
            task["status"] = "review_required"
            remove_value(task, "riskFlags", "missing_material")
            continue
        if str(task.get("decision") or "") == "ready":
            task["status"] = "ready"
        elif str(task.get("decision") or "") == "fill_required":
            task["status"] = "needs_input"
        elif str(task.get("decision") or "") == "material_required":
            task["status"] = "needs_input"
            add_unique(task, "riskFlags", "missing_material")
        else:
            task["decision"] = "review_required"
            task["status"] = "review_required"


def merge_state(tasks: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    state_path = Path(str(manifest.get("statePath") or "")).expanduser()
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return
    state_tasks = state.get("tasks") if isinstance(state, dict) and isinstance(state.get("tasks"), dict) else {}
    for task in tasks:
        task_id = str(task.get("id") or "")
        task_key = str(task.get("taskKey") or "")
        saved = state_tasks.get(task_id) or state_tasks.get(task_key)
        if not isinstance(saved, dict):
            continue
        for key in (
            "status",
            "decision",
            "selectedMaterialRefs",
            "notes",
            "confirmed",
            "assemblyMode",
            "materialUsage",
            "fillPlan",
            "selectedEvidenceSegments",
        ):
            if key in saved:
                task[key] = saved[key]
        if isinstance(saved.get("resolvedArtifacts"), list):
            for artifact in saved["resolvedArtifacts"]:
                if isinstance(artifact, dict):
                    append_saved_artifact(task, artifact)


def append_saved_artifact(task: dict[str, Any], artifact: dict[str, Any]) -> None:
    artifacts = task.setdefault("resolvedArtifacts", [])
    key = str(artifact.get("artifactId") or artifact.get("filePath") or artifact.get("fileName") or "")
    parse_generated = str(artifact.get("artifactType") or "").startswith("parse_") or str(
        artifact.get("sourceMode") or ""
    ).startswith("parsed_")
    for existing in artifacts:
        if not isinstance(existing, dict):
            continue
        existing_key = str(existing.get("artifactId") or existing.get("filePath") or existing.get("fileName") or "")
        if existing_key and existing_key == key:
            if parse_generated:
                # 解析类工件的路径以本次解析为准，历史状态只保留人工审核结论
                review_keys = ("confirmed", "reviewStatus", "notes")
                existing.update({k: artifact[k] for k in review_keys if k in artifact and artifact[k] not in (None, "")})
            else:
                existing.update({k: v for k, v in artifact.items() if v not in (None, "")})
            return
    artifacts.append(artifact)


def update_toc_ref_statuses(toc_refs: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> None:
    task_by_id = {str(task.get("id") or ""): task for task in tasks}
    for ref in toc_refs:
        ids = [str(item) for item in ref.get("taskIds") or []]
        bound = [task_by_id[task_id] for task_id in ids if task_id in task_by_id]
        if not bound:
            ref["status"] = "empty"
        elif all(str(task.get("status") or "") in {"ready", "resolved", "ignored"} for task in bound):
            ref["status"] = "ready"
        elif any(str(task.get("status") or "") == "review_required" for task in bound):
            ref["status"] = "review_required"
        else:
            ref["status"] = "partial"


def summarize_plan(toc_refs: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    decisions: dict[str, int] = {}
    statuses: dict[str, int] = {}
    modules: dict[str, int] = {}
    for task in tasks:
        decisions[str(task.get("decision") or "")] = decisions.get(str(task.get("decision") or ""), 0) + 1
        statuses[str(task.get("status") or "")] = statuses.get(str(task.get("status") or ""), 0) + 1
        modules[str(task.get("moduleKey") or "")] = modules.get(str(task.get("moduleKey") or ""), 0) + 1
    blocking = sum(1 for task in tasks if str(task.get("status") or "") in {"needs_input", "filling", "review_required"})
    return {
        "tocRefCount": len(toc_refs),
        "taskCount": len(tasks),
        "coverageStatus": "complete",
        "readyCount": statuses.get("ready", 0) + statuses.get("resolved", 0),
        "needsInputCount": statuses.get("needs_input", 0),
        "reviewRequiredCount": statuses.get("review_required", 0),
        "blockingCount": blocking,
        "decisionCounts": {key: value for key, value in decisions.items() if key},
        "statusCounts": {key: value for key, value in statuses.items() if key},
        "moduleCounts": {key: value for key, value in modules.items() if key},
    }


def status_from_decision(decision: str) -> str:
    if decision == "ready":
        return "ready"
    if decision in {"fill_required", "material_required", "ai_draft_required"}:
        return "needs_input"
    return "review_required"


def assignee_mode(task_type: str, decision: str) -> str:
    if task_type in {"attachment", "certificate", "bundle"}:
        return "manual_upload"
    if decision == "fill_required":
        return "generate_or_fill"
    if decision == "ai_draft_required":
        return "ai_draft"
    return "manual_review"


def default_assembly_mode(module_key: str, task_type: str, decision: str, title: str) -> str:
    normalized = normalize_text(title)
    if decision == "ai_draft_required":
        return "ai_draft"
    if task_type == "table":
        return "table_fill_from_material"
    if task_type == "certificate":
        return "embed_scan_or_image"
    if task_type == "attachment":
        if any(token in normalized for token in ["扫描", "回单", "保函", "证书", "图片", "pdf"]):
            return "embed_scan_or_image"
        return "attach_whole_file"
    if task_type == "bundle":
        if module_key in {"enterprise_finance_supply", "performance_cooperation_support"}:
            return "extract_and_summarize"
        return "attach_whole_file"
    if decision == "fill_required":
        return "template_fill_docx"
    if any(token in normalized for token in ["投标函", "授权", "廉洁", "承诺", "声明", "说明", "履约"]):
        return "template_fill_docx"
    return "extract_and_summarize"


def build_fill_plan(task_type: str, decision: str, title: str, module_key: str) -> dict[str, Any]:
    mode = default_assembly_mode(module_key, task_type, decision, title)
    plan: dict[str, Any] = {
        "mode": mode,
        "requiresProjectFacts": mode in {"template_fill_docx", "table_fill_from_material", "extract_and_summarize", "ai_draft"},
        "requiresMaterialEvidence": mode in {"table_fill_from_material", "extract_and_summarize", "extract_segment", "attach_whole_file", "embed_scan_or_image"},
        "requiresHumanReview": True,
        "expectedInputs": [],
        "outputArtifactType": "",
    }
    if mode == "template_fill_docx":
        plan["expectedInputs"] = ["项目事实表", "素材库模板底稿或解析附件模板"]
        plan["outputArtifactType"] = "filled_docx"
    elif mode == "table_fill_from_material":
        plan["expectedInputs"] = ["空表模板", "项目事实表", "素材库证据片段"]
        plan["outputArtifactType"] = "filled_table_docx"
    elif mode == "extract_segment":
        plan["expectedInputs"] = ["已确认素材证据片段"]
        plan["outputArtifactType"] = "extracted_segment_docx"
    elif mode == "extract_and_summarize":
        plan["expectedInputs"] = ["素材清洗稿或原件", "证据片段定位", "项目事实表"]
        plan["outputArtifactType"] = "extracted_summary_docx"
    elif mode == "embed_scan_or_image":
        plan["expectedInputs"] = ["证书/回单/PDF/图片原件"]
        plan["outputArtifactType"] = "embedded_scan"
    elif mode == "attach_whole_file":
        plan["expectedInputs"] = ["完整附件原件"]
        plan["outputArtifactType"] = "whole_file_attachment"
    elif mode == "ai_draft":
        plan["expectedInputs"] = ["项目事实表", "招标要求上下文"]
        plan["outputArtifactType"] = "ai_draft_docx"
    else:
        plan["expectedInputs"] = ["人工补充材料"]
        plan["outputArtifactType"] = "manual_artifact"
    return plan


def source_requirement_from_toc(item: dict[str, Any], source_type: str) -> dict[str, Any]:
    text = str(item.get("sourceText") or item.get("source_text") or item.get("reason") or item.get("title") or "")
    return {
        "triggerText": text,
        "triggerContext": str(item.get("reason") or ""),
        "normalizedTopic": normalize_topic(str(item.get("title") or "")),
        "fromSection": str(item.get("number") or ""),
        "extractionMethod": source_type,
    }


def source_requirement_from_letter(letter: dict[str, Any]) -> dict[str, Any]:
    return {
        "triggerText": str(letter.get("triggerText") or letter.get("evidence") or letter.get("title") or ""),
        "triggerContext": str(letter.get("triggerContext") or letter.get("content") or ""),
        "normalizedTopic": normalize_topic(str(letter.get("normalizedTopic") or letter.get("title") or "")),
        "fromSection": str(letter.get("section") or letter.get("placementHint") or ""),
        "extractionMethod": "parser_explicit",
    }


def source_refs_from_toc(item: dict[str, Any]) -> list[dict[str, Any]]:
    refs = item.get("source_refs") if isinstance(item.get("source_refs"), list) else item.get("sourceRefs")
    result: list[dict[str, Any]] = []
    if isinstance(refs, list):
        for index, ref in enumerate(refs, start=1):
            if isinstance(ref, dict):
                result.append({"id": str(ref.get("id") or f"TOC-SRC-{index}"), **ref})
    source_text = str(item.get("sourceText") or item.get("source_text") or "")
    if source_text and not result:
        result.append({"id": f"TOC-SRC-{item.get('nodeId')}", "type": "toc", "text": source_text})
    return result


def source_evidence_from_letter(letter: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(letter.get("id") or fingerprint([letter.get("title"), letter.get("docxPath")])),
        "type": "parse_commitment_letter",
        "title": str(letter.get("title") or ""),
        "text": str(letter.get("triggerText") or letter.get("evidence") or ""),
        "filePath": str(letter.get("docxPath") or ""),
    }


def toc_target_from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodeId": str(item.get("nodeId") or ""),
        "number": str(item.get("number") or ""),
        "title": str(item.get("title") or ""),
        "required": str(item.get("requiredStatus") or item.get("required_status") or "").strip() not in {"可选", "optional"},
    }


def artifact_from_parse_item(item: dict[str, Any], *, artifact_type: str, source_mode: str, default_name: str) -> dict[str, Any]:
    path = str(item.get("docxPath") or item.get("filePath") or item.get("path") or "")
    assembly_mode = "template_fill_docx" if artifact_type == "parse_appendix_template" else "attach_whole_file"
    if artifact_type == "parse_commitment_letter":
        assembly_mode = "attach_whole_file"
    return {
        "artifactId": str(item.get("id") or fingerprint([artifact_type, path, item.get("title")])) or fingerprint([default_name]),
        "artifactType": artifact_type,
        "fileName": str(item.get("fileName") or (Path(path).name if path else default_name)),
        "filePath": path,
        "sourceMode": source_mode,
        "assemblyMode": assembly_mode,
        "materialUsage": ASSEMBLY_MODE_TO_USAGE.get(assembly_mode, ""),
        "version": coerce_int(item.get("version"), 1),
        "previewable": bool(path),
        "confirmed": str(item.get("assetReviewStatus") or item.get("reviewStatus") or "") == "approved",
        "reviewStatus": str(item.get("assetReviewStatus") or item.get("reviewStatus") or "pending_review"),
    }


def append_unique_artifact(task: dict[str, Any], artifact: dict[str, Any]) -> None:
    artifacts = task.setdefault("resolvedArtifacts", [])
    key = str(artifact.get("artifactId") or artifact.get("filePath") or artifact.get("fileName") or "")
    for existing in artifacts:
        if not isinstance(existing, dict):
            continue
        existing_key = str(existing.get("artifactId") or existing.get("filePath") or existing.get("fileName") or "")
        if existing_key and existing_key == key:
            existing.update({k: v for k, v in artifact.items() if v not in (None, "")})
            return
    artifacts.append(artifact)


def set_task_ready_if_artifact_confirmed(task: dict[str, Any]) -> None:
    task["decision"] = "ready"
    task["status"] = "ready"
    remove_value(task, "riskFlags", "missing_material")
    remove_value(task, "riskFlags", "parser_generated_unconfirmed")


def best_task_for_title(tasks: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    normalized = normalize_text(title)
    if not normalized:
        return None
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for task in tasks:
        task_title = normalize_text(task.get("title") or "")
        if not task_title:
            continue
        score = similarity_score(normalized, task_title)
        if score > best[0]:
            best = (score, task)
    return best[1] if best[0] >= 0.42 else None


def best_commitment_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    commitment_tasks = [task for task in tasks if str(task.get("moduleKey") or "") == "commitments_and_notes"]
    if not commitment_tasks:
        return None
    def score(task: dict[str, Any]) -> int:
        title = str(task.get("title") or "")
        if "投标人需要说明" in title or "其他内容" in title:
            return 3
        if "承诺" in title or "声明" in title:
            return 2
        return 1
    return sorted(commitment_tasks, key=score, reverse=True)[0]


def create_parser_commitment_task(tasks: list[dict[str, Any]], toc_refs: list[dict[str, Any]], letter: dict[str, Any], now: str) -> dict[str, Any]:
    target_ref = best_commitment_toc_ref(toc_refs) or (toc_refs[-1] if toc_refs else {})
    index = len(tasks) + 1
    title = str(letter.get("title") or "承诺函")
    task = {
        "id": f"BTASK-PARSER-{index:04d}",
        "taskKey": stable_key("parser_commitment", title, str(letter.get("id") or index)),
        "title": title,
        "titleAlias": [],
        "moduleKey": "commitments_and_notes",
        "taskType": "document",
        "decision": "review_required",
        "status": "review_required",
        "sourceType": "parser_explicit",
        "sourceRequirement": source_requirement_from_letter(letter),
        "sourceEvidenceRefs": [source_evidence_from_letter(letter)],
        "tocTarget": {
            "nodeId": str(target_ref.get("nodeId") or ""),
            "number": str(target_ref.get("number") or ""),
            "title": str(target_ref.get("title") or "投标人需要说明的其他内容"),
            "required": True,
        },
        "candidateMaterials": [],
        "selectedMaterialRefs": [],
        "resolvedArtifacts": [],
        "assemblyMode": "template_fill_docx",
        "materialUsage": "fill_template",
        "fillPlan": build_fill_plan("document", "review_required", title, "commitments_and_notes"),
        "selectedEvidenceSegments": [],
        "riskFlags": ["parser_generated_unconfirmed", "manual_placement_required"],
        "requirementLevel": "required",
        "assigneeMode": "manual_review",
        "displayOrder": 6000 + index,
        "fingerprint": fingerprint(["parser_commitment", title, letter.get("id")]),
        "updatedAt": now,
    }
    topic_group = topic_group_for_title(title, "commitments_and_notes")
    if topic_group:
        task.update(topic_group)
    return task


def append_task_to_toc_ref(toc_refs: list[dict[str, Any]], task: dict[str, Any]) -> None:
    target = task.get("tocTarget") if isinstance(task.get("tocTarget"), dict) else {}
    node_id = str(target.get("nodeId") or "")
    for ref in toc_refs:
        if str(ref.get("nodeId") or "") == node_id:
            ids = ref.setdefault("taskIds", [])
            if task["id"] not in ids:
                ids.append(task["id"])
            return


def best_commitment_toc_ref(toc_refs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ref in toc_refs:
        title = str(ref.get("title") or "")
        if "投标人需要说明" in title or "其他内容" in title:
            return ref
    for ref in toc_refs:
        title = str(ref.get("title") or "")
        if "承诺" in title or "说明" in title or "声明" in title:
            return ref
    return None


def best_toc_for_special_certificate(toc_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in toc_items:
        title = str(item.get("title") or "")
        if any(keyword in title for keyword in ("证书", "认证", "资格", "证明")):
            return item
    return toc_items[-1] if toc_items else None


def is_technical_boundary(title: str, rules: dict[str, Any]) -> bool:
    normalized = normalize_text(title)
    for topic in rules.get("technicalBoundaryTopics") or []:
        if normalize_text(topic) in normalized:
            return True
    return False


def topic_group_for_title(title: str, module_key: str) -> dict[str, str]:
    if module_key != "commitments_and_notes":
        return {}
    text = normalize_text(title)
    if "保密" in text:
        return {"topicGroupKey": "confidentiality_commitments", "topicGroupLabel": "保密类承诺"}
    if any(word in text for word in ("不得存在", "资格", "禁止投标", "处罚")):
        return {"topicGroupKey": "bid_eligibility_commitments", "topicGroupLabel": "投标资格类承诺"}
    if any(word in text for word in ("行贿", "廉洁")):
        return {"topicGroupKey": "integrity_commitments", "topicGroupLabel": "廉洁合规类承诺"}
    return {"topicGroupKey": "other_commitments", "topicGroupLabel": "其他承诺与说明"}


def module_material_keywords(module_key: str, task_type: str, sub_module_key: str = "") -> list[str]:
    if module_key == "base_documents_guarantees":
        return ["投标函", "授权", "廉洁", "保证金", "保函", "专用章", "响应文件"]
    if module_key == "structured_response_tables":
        return ["价格", "报价", "开标", "规格", "偏差", "供货范围", "评分", "附件", "模板"]
    if module_key == "qualification_compliance_certificates":
        if sub_module_key == "special_certificates":
            return ["机型认证", "大部件", "型式认证", "证书", "认证"]
        return ["营业执照", "资质", "体系", "信用", "失信", "开户", "股权", "证书"]
    if module_key == "enterprise_finance_supply":
        return ["公司简介", "工厂", "生产能力", "服务能力", "质量", "供货", "财务", "审计", "资信", "纳税"]
    if module_key == "performance_cooperation_support":
        return ["业绩", "合同", "中标", "240h", "试运行", "验收", "战略", "框架", "供应链", "评价"]
    if module_key == "commitments_and_notes":
        return ["承诺", "声明", "说明", "其他内容", "保密", "不存在"]
    return [task_type]


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|]+", "", text)
    return text


def normalize_topic(value: str) -> str:
    text = str(value or "")
    for suffix in ("承诺函", "承诺书", "声明函", "声明", "格式", "附件"):
        text = text.replace(suffix, "")
    return text.strip() or str(value or "").strip()


def tokenize_zh(value: str) -> list[str]:
    text = normalize_text(value)
    tokens: list[str] = []
    for length in (6, 5, 4, 3, 2):
        for start in range(0, max(0, len(text) - length + 1)):
            tokens.append(text[start : start + length])
    return dedupe(tokens)


def similarity_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b)) + 0.25
    a_tokens = set(tokenize_zh(a))
    b_tokens = set(tokenize_zh(b))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / max(len(a_tokens | b_tokens), 1)


def stable_key(*parts: Any) -> str:
    raw = "_".join(normalize_text(part) for part in parts if normalize_text(part))
    if not raw:
        raw = "business_task"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    prefix = re.sub(r"[^a-zA-Z0-9_]+", "_", str(parts[0] or "task").lower()).strip("_") or "task"
    return f"{prefix}_{digest}"


def fingerprint(parts: list[Any]) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return "sha1:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def coerce_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def add_unique(target: dict[str, Any], key: str, value: Any, *, key_field: str = "") -> None:
    items = target.setdefault(key, [])
    if not isinstance(items, list):
        target[key] = items = []
    if isinstance(value, dict) and key_field:
        new_key = str(value.get(key_field) or "")
        for index, item in enumerate(items):
            if isinstance(item, dict) and str(item.get(key_field) or "") == new_key:
                items[index] = {**item, **value}
                return
    elif value in items:
        return
    items.append(value)


def remove_value(target: dict[str, Any], key: str, value: Any) -> None:
    items = target.get(key)
    if isinstance(items, list):
        target[key] = [item for item in items if item != value]


def file_type(material: dict[str, Any]) -> str:
    if str(material.get("sourceType") or "") in {"performance_library", "performance_package"} and str(material.get("cleanStatus") or "") == "metadata_only":
        return "record"
    name = str(material.get("name") or material.get("fileName") or material.get("cleanedFileName") or "").lower()
    suffix = Path(name).suffix.lower().strip(".")
    return suffix or "file"


def dedupe_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for material in materials:
        key = candidate_key(material)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(material)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
