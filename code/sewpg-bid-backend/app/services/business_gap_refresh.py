from __future__ import annotations

import copy
from typing import Any

from app.services.business_gap_domain import (
    default_task_assembly_mode,
    material_usage_for_assembly_mode,
    recompute_task_after_artifact_change,
    task_fill_plan,
)
from app.services.business_gap_planning import _business_template_index, build_business_gap_material_picker_index
from app.services.workspace_artifacts import business_workspace_dir


def refresh_template_candidates(project: dict[str, Any], business_gap_state: dict[str, Any]) -> bool:
    plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
    tasks = [task for task in plan.get("tasks") or [] if isinstance(task, dict)]
    if not tasks:
        return False

    project_id = str(project.get("id") or "")
    work_dir = business_workspace_dir(project_id) / "gaps"
    template_index = _business_template_index(project, work_dir)
    project_template_ids = {
        str(candidate.get("templateId") or candidate.get("filePath") or candidate.get("originalPath") or "")
        for candidate in template_index
        if isinstance(candidate, dict) and str(candidate.get("sourceMode") or "") == "project_uploaded_bid_template"
    }
    active_template_keys = {
        str(candidate.get("templateId") or candidate.get("filePath") or candidate.get("originalPath") or "")
        for candidate in template_index
        if isinstance(candidate, dict)
    }
    changed = False
    has_project_template = bool(project_template_ids)
    for task in tasks:
        if not task_wants_template_candidates(task):
            continue
        existing = [item for item in task.get("templateCandidates") or [] if isinstance(item, dict)]
        task_changed = False
        if active_template_keys:
            kept_existing: list[dict[str, Any]] = []
            for item in existing:
                item_key = str(item.get("templateId") or item.get("filePath") or item.get("originalPath") or "")
                source_mode = str(item.get("sourceMode") or "")
                if item_key not in active_template_keys:
                    continue
                if has_project_template and source_mode == "system_default_bid_template":
                    continue
                kept_existing.append(item)
            if len(kept_existing) != len(existing):
                existing = kept_existing
                task_changed = True
                changed = True
        elif existing:
            existing = []
            task_changed = True
            changed = True
        existing_keys = {
            str(item.get("templateId") or item.get("filePath") or item.get("originalPath") or "")
            for item in existing
            if str(item.get("templateId") or item.get("filePath") or item.get("originalPath") or "")
        }
        merged = [copy.deepcopy(item) for item in existing]
        for candidate in template_index:
            candidate_key = str(
                candidate.get("templateId")
                or candidate.get("filePath")
                or candidate.get("originalPath")
                or ""
            )
            if not candidate_key or candidate_key in existing_keys:
                continue
            merged.append(copy.deepcopy(candidate))
            existing_keys.add(candidate_key)
            task_changed = True
            changed = True
        if not task_changed:
            continue
        task["templateCandidates"] = sorted(
            merged,
            key=lambda item: 0 if str(item.get("sourceMode") or "") == "project_uploaded_bid_template" else 1,
        )[:8]
        if task["templateCandidates"]:
            if str(task.get("assemblyMode") or "") != "template_fill_docx":
                task["assemblyMode"] = "template_fill_docx"
            task["materialUsage"] = material_usage_for_assembly_mode("template_fill_docx")
            task["fillPlan"] = task_fill_plan(task)
        recompute_task_after_artifact_change(task)

    return changed


def refresh_material_kind_labels(project: dict[str, Any], business_gap_state: dict[str, Any]) -> bool:
    plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    if not tasks:
        return False
    picker = build_business_gap_material_picker_index(project)
    material_by_id = {
        str(item.get("id") or item.get("materialId") or ""): item
        for item in picker.get("materialIndex") or []
        if isinstance(item, dict) and str(item.get("id") or item.get("materialId") or "")
    }
    changed = False

    def apply_kind(target: dict[str, Any], material_id: str) -> None:
        nonlocal changed
        current = material_by_id.get(str(material_id or ""))
        if not current:
            return
        for field in ("businessMaterialKind", "businessMaterialKindLabel"):
            next_value = str(current.get(field) or "")
            if next_value and str(target.get(field) or "") != next_value:
                target[field] = next_value
                changed = True

    for task in tasks:
        if not isinstance(task, dict):
            continue
        for candidate in task.get("candidateMaterials") or []:
            if isinstance(candidate, dict):
                apply_kind(candidate, str(candidate.get("materialId") or candidate.get("id") or ""))
        for ref in task.get("selectedMaterialRefs") or []:
            if isinstance(ref, dict):
                apply_kind(ref, str(ref.get("materialId") or ref.get("id") or ""))
        for artifact in task.get("resolvedArtifacts") or []:
            if isinstance(artifact, dict):
                apply_kind(artifact, str(artifact.get("materialId") or ""))
        artifacts = task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else []
        if str(task.get("handlingMode") or "") == "manual_select":
            has_fixed_artifact = any(
                str(item.get("businessMaterialKind") or "") == "fixed"
                for item in artifacts
                if isinstance(item, dict)
            )
            task["handlingMode"] = "fixed_material" if has_fixed_artifact else "manual_upload"
            changed = True
    return changed


def task_wants_template_candidates(task: dict[str, Any]) -> bool:
    mode = str(task.get("assemblyMode") or "")
    decision = str(task.get("decision") or "")
    title = str(task.get("title") or "")
    if mode == "template_fill_docx":
        return True
    if decision == "fill_required":
        return True
    return default_task_assembly_mode(
        str(task.get("moduleKey") or ""),
        str(task.get("taskType") or ""),
        decision,
        title,
    ) == "template_fill_docx"
