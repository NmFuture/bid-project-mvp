from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CURRENT = Path(__file__).resolve()
SCRIPT_DIR = CURRENT.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from business_contract import SCHEMA_VERSION, SKILL_NAME, _clean
from business_workflow import build_business_workflow_result, normalize_ai_decision


DECISION_HELPER_BUCKETS = {"accepted", "rejected", "needsReview"}


def _summary(result: dict[str, Any], output_path: Path) -> dict[str, Any]:
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    scoring = structured.get("scoringCriteria") if isinstance(structured.get("scoringCriteria"), dict) else {}
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
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
            "scoringCounts": {
                key: len(scoring.get(key) or [])
                for key in ("business",)
            },
            "workflowStage": (structured.get("workflow") or {}).get("stage") or "",
            "projectDates": {
                "endDate": project_dates.get("endDate") or "",
            },
        },
    }


def _manifest_output_dir(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    output_path = Path(str(manifest.get("structuredResultPath") or manifest_path.with_name("s1_structured_result.json")))
    return output_path.parent


def _review_plan_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("reviewPlanPath") or "").strip()
    if value:
        return Path(value)
    return _manifest_output_dir(manifest_path, manifest) / "review_plan.json"


def _candidate_package_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = str(manifest.get("candidatePackagePath") or "").strip()
    if value:
        return Path(value)
    return _manifest_output_dir(manifest_path, manifest) / "candidate_package.json"


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise RuntimeError(f"manifest must be a JSON object: {manifest_path}")
    return manifest


def _load_review_plan(manifest_path: Path, manifest: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    review_plan_path = _review_plan_path(manifest_path, manifest)
    review_plan = json.loads(review_plan_path.read_text(encoding="utf-8"))
    if not isinstance(review_plan, dict):
        raise RuntimeError(f"review_plan must be a JSON object: {review_plan_path}")
    return review_plan_path, review_plan


def _task_refs(review_plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in review_plan.get("tasks") or [] if isinstance(item, dict)]


def _resolve_task_ref(review_plan: dict[str, Any], task_id: str) -> dict[str, Any]:
    normalized = str(task_id or "").strip()
    for task_ref in _task_refs(review_plan):
        if str(task_ref.get("taskId") or "").strip() == normalized:
            return task_ref
    raise RuntimeError(f"review_plan 中未找到 taskId: {normalized}")


def _path_from_ref(base_dir: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else base_dir / path


def _task_list_payload(review_plan_path: Path, review_plan: dict[str, Any]) -> dict[str, Any]:
    base_dir = review_plan_path.parent
    tasks = []
    present: list[str] = []
    missing: list[str] = []
    for task_ref in _task_refs(review_plan):
        task_id = str(task_ref.get("taskId") or "")
        decision_path = _path_from_ref(base_dir, task_ref.get("decisionPath"))
        is_present = decision_path.is_file()
        if is_present:
            present.append(task_id)
        elif task_ref.get("required", True):
            missing.append(task_id)
        tasks.append(
            {
                "taskId": task_id,
                "task": str(task_ref.get("task") or ""),
                "module": str(task_ref.get("module") or ""),
                "partIndex": int(task_ref.get("partIndex") or 0),
                "partCount": int(task_ref.get("partCount") or 0),
                "candidateCount": int(task_ref.get("candidateCount") or 0),
                "taskPath": str(task_ref.get("taskPath") or ""),
                "decisionPath": str(task_ref.get("decisionPath") or ""),
                "required": bool(task_ref.get("required", True)),
                "decisionPresent": is_present,
            }
        )
    return {
        "schemaVersion": "bid-business-task-list-v1",
        "targetSkill": SKILL_NAME,
        "reviewPlanPath": str(review_plan_path),
        "taskCount": len(tasks),
        "requiredTaskCount": sum(1 for task in tasks if task["required"]),
        "presentDecisionTaskCount": len(present),
        "missingDecisionTaskCount": len(missing),
        "tasks": tasks,
    }


def _review_status_payload(review_plan_path: Path, review_plan: dict[str, Any]) -> dict[str, Any]:
    listing = _task_list_payload(review_plan_path, review_plan)
    present = [task["taskId"] for task in listing["tasks"] if task["decisionPresent"]]
    missing = [task["taskId"] for task in listing["tasks"] if task["required"] and not task["decisionPresent"]]
    return {
        "schemaVersion": "bid-business-review-status-v1",
        "targetSkill": SKILL_NAME,
        "reviewPlanPath": str(review_plan_path),
        "requiredDecisionTaskCount": int(listing["requiredTaskCount"]),
        "presentDecisionTaskCount": len(present),
        "missingDecisionTaskCount": len(missing),
        "presentDecisionTasks": present,
        "missingDecisionTasks": missing,
    }


def _task_payload(review_plan_path: Path, review_plan: dict[str, Any], task_id: str) -> dict[str, Any]:
    task_ref = _resolve_task_ref(review_plan, task_id)
    task_path = _path_from_ref(review_plan_path.parent, task_ref.get("taskPath"))
    task_payload = json.loads(task_path.read_text(encoding="utf-8"))
    if not isinstance(task_payload, dict):
        raise RuntimeError(f"task payload must be a JSON object: {task_path}")
    return task_payload


def _validate_decision_payload(manifest_path: Path, manifest: dict[str, Any], review_plan_path: Path, review_plan: dict[str, Any], task_id: str) -> dict[str, Any]:
    task_ref = _resolve_task_ref(review_plan, task_id)
    task_name = str(task_ref.get("task") or task_id)
    decision_path = _path_from_ref(review_plan_path.parent, task_ref.get("decisionPath"))
    candidate_package_path = _candidate_package_path(manifest_path, manifest)
    candidate_package = json.loads(candidate_package_path.read_text(encoding="utf-8"))
    if not decision_path.is_file():
        return {
            "schemaVersion": "bid-business-decision-validation-v1",
            "targetSkill": SKILL_NAME,
            "taskId": task_id,
            "task": task_name,
            "decisionPath": str(decision_path),
            "status": "failed",
            "issueCount": 1,
            "issues": [
                {
                    "task": task_id,
                    "bucket": "",
                    "code": "missing_decision_file",
                    "candidateId": "",
                    "evidenceIds": [],
                    "message": "指定 task 的 decisionPath 尚未写入。",
                }
            ],
        }
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    normalized, issues = normalize_ai_decision(decision, task_name=task_name, candidate_package=candidate_package)
    normalized["taskId"] = str(normalized.get("taskId") or task_id)
    if not issues:
        decision_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "schemaVersion": "bid-business-decision-validation-v1",
        "targetSkill": SKILL_NAME,
        "taskId": task_id,
        "task": task_name,
        "decisionPath": str(decision_path),
        "status": "passed" if not issues else "failed",
        "issueCount": len(issues),
        "issues": issues,
    }


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("candidateId") or candidate.get("id") or "").strip()


def _candidate_evidence_ids(candidate: dict[str, Any]) -> list[str]:
    return [str(item) for item in candidate.get("evidenceIds") or [] if str(item)]


def _decision_item_from_candidate(candidate: dict[str, Any], bucket: str, field_type: str, reason: str) -> dict[str, Any]:
    return {
        "candidateId": _candidate_id(candidate),
        "decision": bucket,
        "fieldType": field_type or str(candidate.get("candidateType") or candidate.get("module") or "review_candidate"),
        "content": str(candidate.get("content") or ""),
        "applicableScope": str(candidate.get("applicableScope") or "all bid sections"),
        "sourceText": str(candidate.get("sourceText") or candidate.get("sectionPath") or candidate.get("sourceFile") or "task candidate"),
        "reason": reason or "opencode agent semantic decision",
        "evidenceIds": _candidate_evidence_ids(candidate),
    }


def _split_ids(value: str) -> set[str]:
    normalized = str(value or "").replace(";", ",").replace("|", ",")
    return {item.strip() for item in normalized.split(",") if item.strip()}


def _write_decision_payload(
    manifest_path: Path,
    manifest: dict[str, Any],
    review_plan_path: Path,
    review_plan: dict[str, Any],
    task_id: str,
    *,
    bucket_by_candidate_id: dict[str, str],
    default_bucket: str,
    field_type: str,
    reason: str,
) -> dict[str, Any]:
    if default_bucket not in DECISION_HELPER_BUCKETS:
        raise RuntimeError("decision helper bucket must be accepted, rejected, or needsReview")
    invalid_buckets = sorted({bucket for bucket in bucket_by_candidate_id.values() if bucket not in DECISION_HELPER_BUCKETS})
    if invalid_buckets:
        raise RuntimeError("decision helper bucket must be accepted, rejected, or needsReview: " + ", ".join(invalid_buckets))

    task_ref = _resolve_task_ref(review_plan, task_id)
    task_name = str(task_ref.get("task") or task_id)
    if task_name == "qualification_review":
        decision_path = _path_from_ref(review_plan_path.parent, task_ref.get("decisionPath"))
        return {
            "schemaVersion": "bid-business-decision-write-v1",
            "targetSkill": SKILL_NAME,
            "taskId": task_id,
            "task": task_name,
            "decisionPath": str(decision_path),
            "status": "failed",
            "issueCount": 1,
            "issues": [
                {
                    "task": task_id,
                    "bucket": "qualificationItems",
                    "code": "qualification_requires_raw_ai_items",
                    "candidateId": "",
                    "evidenceIds": [],
                    "message": "资格要求任务必须由 AI 直接输出 qualificationItems；decision-all/decision-set 不得自动拆分资格条款。",
                }
            ],
        }
    task_payload = _task_payload(review_plan_path, review_plan, task_id)
    decision_path = _path_from_ref(review_plan_path.parent, task_ref.get("decisionPath"))
    decision: dict[str, Any] = {
        "schemaVersion": "bid-business-ai-decision-v1",
        "task": task_name,
        "taskId": task_id,
        "adapter": "opencode-agent",
        "accepted": [],
        "rejected": [],
        "needsReview": [],
        "reason": reason or "opencode agent semantic decision",
        "evidenceIds": [],
    }
    task_candidate_ids: set[str] = set()
    evidence_ids: set[str] = set()
    for candidate in task_payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        candidate_id = _candidate_id(candidate)
        if not candidate_id:
            continue
        task_candidate_ids.add(candidate_id)
        bucket = bucket_by_candidate_id.get(candidate_id, default_bucket)
        item = _decision_item_from_candidate(candidate, bucket, field_type, reason)
        decision[bucket].append(item)
        evidence_ids.update(item["evidenceIds"])
    unknown_candidate_ids = sorted(set(bucket_by_candidate_id) - task_candidate_ids)
    if unknown_candidate_ids:
        return {
            "schemaVersion": "bid-business-decision-write-v1",
            "targetSkill": SKILL_NAME,
            "taskId": task_id,
            "task": task_name,
            "decisionPath": str(decision_path),
            "status": "failed",
            "issueCount": 1,
            "issues": [
                {
                    "task": task_id,
                    "bucket": "",
                    "code": "unknown_candidate_id",
                    "candidateId": ",".join(unknown_candidate_ids),
                    "evidenceIds": [],
                    "message": "decision helper referenced candidateId values that are not in this task.",
                }
            ],
        }
    decision["evidenceIds"] = sorted(evidence_ids)
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    validation = _validate_decision_payload(manifest_path, manifest, review_plan_path, review_plan, task_id)
    return {
        "schemaVersion": "bid-business-decision-write-v1",
        "targetSkill": SKILL_NAME,
        **validation,
    }


def _write_qualification_item_payload(
    manifest_path: Path,
    manifest: dict[str, Any],
    review_plan_path: Path,
    review_plan: dict[str, Any],
    task_id: str,
    *,
    content: str,
    applicable_scope: str,
    evidence_ids: str,
    source_text: str,
    reason: str,
) -> dict[str, Any]:
    task_ref = _resolve_task_ref(review_plan, task_id)
    task_name = str(task_ref.get("task") or task_id)
    decision_path = _path_from_ref(review_plan_path.parent, task_ref.get("decisionPath"))
    if task_name != "qualification_review":
        return {
            "schemaVersion": "bid-business-decision-write-v1",
            "targetSkill": SKILL_NAME,
            "taskId": task_id,
            "task": task_name,
            "decisionPath": str(decision_path),
            "status": "failed",
            "issueCount": 1,
            "issues": [
                {
                    "task": task_id,
                    "bucket": "qualificationItems",
                    "code": "qualification_item_task_required",
                    "candidateId": "",
                    "evidenceIds": [],
                    "message": "qualification-item 只能用于 qualification_review 任务。",
                }
            ],
        }
    item_evidence_ids = sorted(_split_ids(evidence_ids))
    existing: dict[str, Any] = {}
    if decision_path.is_file():
        existing = json.loads(decision_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    decision = {
        "schemaVersion": "bid-business-ai-decision-v1",
        "task": task_name,
        "taskId": task_id,
        "adapter": str(existing.get("adapter") or "opencode-agent"),
        "qualificationItems": list(existing.get("qualificationItems") or []),
        "rejectedEvidenceIds": list(existing.get("rejectedEvidenceIds") or []),
        "reason": reason or str(existing.get("reason") or "opencode agent raw qualification split"),
        "evidenceIds": [],
        "accepted": [],
        "rejected": [],
        "needsReview": [],
    }
    decision["qualificationItems"].append(
        {
            "content": _clean(content),
            "applicableScope": _clean(applicable_scope) or "全部标段",
            "sourceText": _clean(source_text) or "投标人资格要求",
            "evidenceIds": item_evidence_ids,
        }
    )
    decision["evidenceIds"] = sorted(
        {
            str(value)
            for item in decision["qualificationItems"]
            for value in item.get("evidenceIds") or []
            if str(value).strip()
        }
        | {str(value) for value in decision["rejectedEvidenceIds"] if str(value).strip()}
    )
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    validation = _validate_decision_payload(manifest_path, manifest, review_plan_path, review_plan, task_id)
    return {
        "schemaVersion": "bid-business-decision-write-v1",
        "targetSkill": SKILL_NAME,
        **validation,
    }


def _decision_all_payload(
    manifest_path: Path,
    manifest: dict[str, Any],
    review_plan_path: Path,
    review_plan: dict[str, Any],
    task_id: str,
    bucket: str,
    field_type: str,
    reason: str,
) -> dict[str, Any]:
    return _write_decision_payload(
        manifest_path,
        manifest,
        review_plan_path,
        review_plan,
        task_id,
        bucket_by_candidate_id={},
        default_bucket=bucket,
        field_type=field_type,
        reason=reason,
    )


def _decision_set_payload(
    manifest_path: Path,
    manifest: dict[str, Any],
    review_plan_path: Path,
    review_plan: dict[str, Any],
    task_id: str,
    accepted_ids: str,
    rejected_ids: str,
    needs_review_ids: str,
    default_bucket: str,
    field_type: str,
    reason: str,
) -> dict[str, Any]:
    bucket_by_candidate_id: dict[str, str] = {}
    for bucket, raw_ids in (
        ("accepted", accepted_ids),
        ("rejected", rejected_ids),
        ("needsReview", needs_review_ids),
    ):
        for candidate_id in _split_ids(raw_ids):
            bucket_by_candidate_id[candidate_id] = bucket
    return _write_decision_payload(
        manifest_path,
        manifest,
        review_plan_path,
        review_plan,
        task_id,
        bucket_by_candidate_id=bucket_by_candidate_id,
        default_bucket=default_bucket,
        field_type=field_type,
        reason=reason,
    )


def _print_json(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> int:
    if len(sys.argv) not in {2, 3, 4, 7, 9, 10}:
        print("usage: s1parse [prepare|finalize|offline-fallback|tasks|status|task|validate-decision|decision-all|decision-set|qualification-item] <manifest> [taskId] [...]", file=sys.stderr)
        return 64

    if len(sys.argv) == 2:
        workflow_stage = "prepare"
        manifest_path = Path(sys.argv[1])
    else:
        workflow_stage = str(sys.argv[1]).strip().lower()
        manifest_path = Path(sys.argv[2])
    if workflow_stage not in {"prepare", "finalize", "offline-fallback", "tasks", "status", "task", "validate-decision", "decision-all", "decision-set", "qualification-item"}:
        print("usage: s1parse [prepare|finalize|offline-fallback|tasks|status|task|validate-decision|decision-all|decision-set|qualification-item] <manifest> [taskId] [...]", file=sys.stderr)
        return 64
    if workflow_stage in {"task", "validate-decision"} and len(sys.argv) != 4:
        print("usage: s1parse [task|validate-decision] <manifest> <taskId>", file=sys.stderr)
        return 64
    if workflow_stage == "decision-all" and len(sys.argv) != 7:
        print("usage: s1parse decision-all <manifest> <taskId> <accepted|rejected|needsReview> <fieldType> <reason>", file=sys.stderr)
        return 64
    if workflow_stage == "decision-set" and len(sys.argv) != 10:
        print("usage: s1parse decision-set <manifest> <taskId> <acceptedIdsCsv> <rejectedIdsCsv> <needsReviewIdsCsv> <defaultDecision> <fieldType> <reason>", file=sys.stderr)
        return 64
    if workflow_stage == "qualification-item" and len(sys.argv) != 9:
        print("usage: s1parse qualification-item <manifest> <taskId> <content> <applicableScope> <evidenceIdsCsv> <sourceText> <reason>", file=sys.stderr)
        return 64

    manifest = _load_manifest(manifest_path)
    if workflow_stage in {"tasks", "status", "task", "validate-decision", "decision-all", "decision-set", "qualification-item"}:
        review_plan_path, review_plan = _load_review_plan(manifest_path, manifest)
        if workflow_stage == "tasks":
            return _print_json(_task_list_payload(review_plan_path, review_plan))
        if workflow_stage == "status":
            return _print_json(_review_status_payload(review_plan_path, review_plan))
        if workflow_stage == "task":
            return _print_json(_task_payload(review_plan_path, review_plan, sys.argv[3]))
        if workflow_stage == "decision-all":
            return _print_json(
                _decision_all_payload(
                    manifest_path,
                    manifest,
                    review_plan_path,
                    review_plan,
                    sys.argv[3],
                    sys.argv[4],
                    sys.argv[5],
                    sys.argv[6],
                )
            )
        if workflow_stage == "decision-set":
            return _print_json(
                _decision_set_payload(
                    manifest_path,
                    manifest,
                    review_plan_path,
                    review_plan,
                    sys.argv[3],
                    sys.argv[4],
                    sys.argv[5],
                    sys.argv[6],
                    sys.argv[7],
                    sys.argv[8],
                    sys.argv[9],
                )
            )
        if workflow_stage == "qualification-item":
            return _print_json(
                _write_qualification_item_payload(
                    manifest_path,
                    manifest,
                    review_plan_path,
                    review_plan,
                    sys.argv[3],
                    content=sys.argv[4],
                    applicable_scope=sys.argv[5],
                    evidence_ids=sys.argv[6],
                    source_text=sys.argv[7],
                    reason=sys.argv[8],
                )
            )
        return _print_json(
            _validate_decision_payload(manifest_path, manifest, review_plan_path, review_plan, sys.argv[3])
        )

    output_path = Path(str(manifest.get("structuredResultPath") or manifest_path.with_name("s1_structured_result.json")))
    manifest = {**manifest, "structuredResultPath": str(output_path)}
    result = build_business_workflow_result(
        manifest,
        manifest_path=manifest_path,
        mode="opencode-skill",
        workflow_stage=workflow_stage,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_summary(result, output_path), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
