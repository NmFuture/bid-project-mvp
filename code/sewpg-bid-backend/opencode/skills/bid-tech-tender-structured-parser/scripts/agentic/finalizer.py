from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .checklist import CHECKLIST_VERSION
from .delivery_contract import normalize_items, normalize_project_basics, technical_interpretation_payload
from .paths import document_map_path, nav_store_path, structured_result_path, submission_path, validation_report_path
from .submission_store import load as load_submissions
from .validator import validate


SCHEMA_VERSION = "bid-tender-structured-v1"
SKILL_NAME = "bid-tech-tender-structured-parser"


def _source_documents(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    docs = []
    for item in manifest.get("documents") or []:
        if isinstance(item, dict):
            docs.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "sourcePath": str(item.get("sourcePath") or ""),
                    "textPath": str(item.get("textPath") or ""),
                }
            )
    return docs


def finalize(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    validation = validate(manifest_path, manifest)
    submissions = load_submissions(manifest_path, manifest)
    targets = submissions.get("targets") if isinstance(submissions.get("targets"), dict) else {}
    items = normalize_items(
        targets.get("technicalInterpretation"),
        manifest_path=manifest_path,
        manifest=manifest,
    )
    interpretation = technical_interpretation_payload(items)
    project_basics = normalize_project_basics(targets.get("projectBasics"))
    field_groups = {"projectBasics": project_basics}
    workflow = {
        "mode": "opencode-agentic-navigation",
        "navStorePath": str(nav_store_path(manifest_path, manifest)),
        "documentMapPath": str(document_map_path(manifest_path, manifest)),
        "submissionPath": str(submission_path(manifest_path, manifest)),
        "validationReportPath": str(validation_report_path(manifest_path, manifest)),
        "stage": "finalized" if validation.get("status") == "passed" else "failed",
        "checklistVersion": CHECKLIST_VERSION,
        "checklistCount": interpretation["summary"]["total"],
        "evidenceCount": int(validation.get("evidenceCount") or 0),
        "submittedTargetCount": int(validation.get("submittedTargetCount") or 0),
        "missingTargets": list(validation.get("missingTargets") or []),
        "validationErrors": list(validation.get("validationErrors") or []),
    }
    structured = {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "mode": "opencode-skill",
        "sourceDocuments": _source_documents(manifest),
        "technicalInterpretation": interpretation,
        "fieldGroups": field_groups,
        "scoringCriteria": {"technical": [], "business": [], "price": [], "lcoe": [], "compliance": []},
        "requirementPresence": {},
        "coverage": [
            {
                "target": "projectBasics",
                "status": "covered" if any(row.get("value") for row in project_basics) else "missing",
                "summary": f"项目基础信息识别 {sum(1 for row in project_basics if row.get('value'))}/{len(project_basics)} 项。",
            },
            {
                "target": "technicalInterpretation",
                "status": workflow["stage"],
                "summary": f"技术解读清单 {interpretation['summary']['total']} 条，已找到 {interpretation['summary']['found']} 条，部分找到 {interpretation['summary']['partial']} 条。",
            }
        ],
        "projectFactFields": project_basics,
        "workflow": workflow,
    }
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "items": items,
        "structured": structured,
    }
    output_path = structured_result_path(manifest_path, manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def summary(result: dict[str, Any], output_path: Path) -> dict[str, Any]:
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    interpretation = structured.get("technicalInterpretation") if isinstance(structured.get("technicalInterpretation"), dict) else {}
    workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
    counts = interpretation.get("summary") if isinstance(interpretation.get("summary"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "outputFile": str(output_path),
        "summary": {
            "itemCount": len(result.get("items") or []),
            "checklistVersion": interpretation.get("checklistVersion") or CHECKLIST_VERSION,
            "checklistCount": counts.get("total") or 0,
            "statusCounts": {
                "found": counts.get("found") or 0,
                "partial": counts.get("partial") or 0,
                "missing": counts.get("missing") or 0,
                "needs_spec": counts.get("needs_spec") or 0,
            },
            "workflowStage": workflow.get("stage") or "",
        },
    }
