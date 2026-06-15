from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import nav_store
from .delivery_contract import (
    normalize_bidder_instructions,
    normalize_business_scoring,
    normalize_project_basics,
    normalize_project_fact_fields,
    normalize_qualification_requirements,
    normalize_rejection_clauses,
    project_dates as normalize_project_dates,
)
from .paths import document_map_path, nav_store_path, structured_result_path, submission_path, validation_report_path
from .submission_store import load as load_submissions
from .validator import validate


SCHEMA_VERSION = "bid-business-tender-structured-v1"
SKILL_NAME = "bid-business-tender-structured-parser"


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


def _coverage(field_groups: dict[str, Any], scoring: dict[str, Any], validation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"target": "projectBasics", "count": len(field_groups.get("projectBasics") or []), "status": "covered" if field_groups.get("projectBasics") else "missing"},
        {"target": "qualificationRequirements", "count": len(field_groups.get("qualificationRequirements") or []), "status": "covered" if field_groups.get("qualificationRequirements") else "missing"},
        {"target": "bidderInstructions", "count": len(field_groups.get("bidderInstructions") or []), "status": "covered" if field_groups.get("bidderInstructions") else "missing"},
        {"target": "commercialRejectionClauses", "count": len(field_groups.get("commercialRejectionClauses") or []), "status": "covered" if field_groups.get("commercialRejectionClauses") else "missing"},
        {"target": "businessScoringCriteria", "count": len(scoring.get("business") or []), "status": "covered" if scoring.get("business") else "missing"},
        {"target": "validation", "count": len(validation.get("validationErrors") or []), "status": validation.get("status") or "unknown"},
    ]


def finalize(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    validation = validate(manifest_path, manifest)
    submissions = load_submissions(manifest_path, manifest)
    targets = submissions.get("targets") if isinstance(submissions.get("targets"), dict) else {}
    project_dates = normalize_project_dates(targets.get("projectDates"))
    project_basics = normalize_project_basics(targets.get("projectBasics"), project_dates)
    if not project_dates.get("endDate"):
        for row in project_basics:
            if row.get("key") == "bidDeadline" and row.get("value"):
                project_dates["endDate"] = str(row.get("value") or "")
                break
    field_groups = {
        "projectBasics": project_basics,
        "qualificationRequirements": normalize_qualification_requirements(targets.get("qualificationRequirements")),
        "bidderInstructions": normalize_bidder_instructions(targets.get("bidderInstructions")),
        "commercialRejectionClauses": normalize_rejection_clauses(targets.get("commercialRejectionClauses")),
    }
    scoring = {
        "business": normalize_business_scoring(targets.get("businessScoringCriteria")),
    }
    project_fact_fields = normalize_project_fact_fields(targets.get("projectFactFields"), project_basics)
    workflow = {
        "mode": "opencode-agentic-navigation",
        "navStorePath": str(nav_store_path(manifest_path, manifest)),
        "documentMapPath": str(document_map_path(manifest_path, manifest)),
        "submissionPath": str(submission_path(manifest_path, manifest)),
        "validationReportPath": str(validation_report_path(manifest_path, manifest)),
        "stage": "finalized" if validation.get("status") == "passed" else "failed",
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
        "fieldGroups": field_groups,
        "scoringCriteria": scoring,
        "projectFactFields": project_fact_fields,
        "projectDates": project_dates,
        "coverage": _coverage(field_groups, scoring, validation),
        "workflow": workflow,
    }
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "items": project_fact_fields + field_groups["qualificationRequirements"] + field_groups["bidderInstructions"] + field_groups["commercialRejectionClauses"] + scoring["business"],
        "structured": structured,
    }
    output_path = structured_result_path(manifest_path, manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def summary(result: dict[str, Any], output_path: Path) -> dict[str, Any]:
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    scoring = structured.get("scoringCriteria") if isinstance(structured.get("scoringCriteria"), dict) else {}
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
    workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "outputFile": str(output_path),
        "summary": {
            "itemCount": len(result.get("items") or []),
            "targetCounts": {
                "projectBasics": len(field_groups.get("projectBasics") or []),
                "qualificationRequirements": len(field_groups.get("qualificationRequirements") or []),
                "bidderInstructions": len(field_groups.get("bidderInstructions") or []),
                "commercialRejectionClauses": len(field_groups.get("commercialRejectionClauses") or []),
                "businessScoringCriteria": len(scoring.get("business") or []),
            },
            "scoringCounts": {"business": len(scoring.get("business") or [])},
            "workflowStage": workflow.get("stage") or "",
            "projectDates": project_dates,
        },
    }
