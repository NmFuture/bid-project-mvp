"""技术标项目事实表：状态归一化、主构建与派生事实（门面）。

解析文本事实提取与素材事实提取分别拆到
technical_fact_extract_parse / technical_fact_extract_materials，
与技术/商务两线共享的抽取辅助（fact_table_common）一并在本文件 re-export，
外部调用方与 patch 目标无需改动。
"""

from __future__ import annotations

import copy
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 模块符号保留：bid_type 单一事实来源（scope_state_rules 源码约束）+ 素材作用域 re-export。
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.identity import build_project_material_scope
from app.services.technical_fact_field_specs import (
    SPEC_LABEL_ALIASES,
    fillable_specs,
    spec_category,
)
from app.services.technical_fact_spec_global import resolve_fact_specs
from app.services.turbine_models import project_turbine_model, project_turbine_models
# 拆分搬迁：标签归一基元与两线共享抽取辅助已移至 fact_table_common，门面 re-export。
from app.services.fact_table_common import (
    COMMON_PROJECT_FACT_LABELS,
    FACT_MATERIAL_SOURCE_PRIORITIES,
    FACT_TABLE_HEADER_WORDS,
    add_performance_facts_from_parse_text,
    canonical_fact_label,
    fact_label_key,
    looks_like_project_name,
    looks_like_tender_no,
)
# 拆分搬迁：解析文本事实提取已移至 technical_fact_extract_parse，门面 re-export。
from app.services.technical_fact_extract_parse import (
    blank_source_docx_path,
    clean_table_cell_text,
    fillable_table_labels_from_blank_source,
    iter_parse_fact_fields,
    looks_like_party_name,
    looks_like_table_field_label,
    table_field_label_from_row,
    technical_fact_labels_from_task,
    trusted_parse_fact_fields,
)
# 拆分搬迁：素材事实提取已移至 technical_fact_extract_materials，门面 re-export。
from app.services.technical_fact_extract_materials import (
    FACT_MATERIAL_USAGE_BUILD,
    FACT_MATERIAL_USAGE_CURATE,
    FILL_TEMPLATE_NAME_PREFIX,
    clean_fact_text,
    clean_fact_unit,
    clean_fact_value,
    facts_from_docx_material,
    facts_from_free_text,
    facts_from_guarantee_table,
    facts_from_material_name,
    facts_from_table_cells,
    facts_from_xlsx_material,
    material_fact,
    material_fact_from_label_value,
    material_is_fact_relevant,
    material_is_fill_template,
    prepare_project_fact_materials,
    project_fact_material_index,
    project_fact_material_work_dir,
    project_material_fact_fields,
    run_async_material_files,
    xlsx_model_column,
)

logger = logging.getLogger(__name__)


PROJECT_FACT_TABLE_SCHEMA_VERSION = "bid-project-fact-table-v2"

# 字段状态模型（三态，产品裁决 2026-08-10）：
# unextracted 待填写（没有取值，人工在页面上补）
# confirmed 可用（有取值即可用，不论来自规则抽取、AI 复核还是人工录入）
# not_applicable 不适用（人工裁定本项目不需要此字段，notes 注明原因）
#
# 取消「人工逐条确认」这道闸门：抽出什么就是什么，不对由人直接改。原七态里的
# extracted / pending_confirmation / conflict 都只是「有值但没人看过」的不同说法，
# missing_source 与 unextracted 都是「没值」，对下游没有行为差异，一并收敛。
# 多来源冲突不再占状态位：按来源优先级取值，其余候选留在 alternatives 并置
# hasConflict 标记供页面提示，见 add_candidate。
FACT_STATUS_UNEXTRACTED = "unextracted"
FACT_STATUS_CONFIRMED = "confirmed"
FACT_STATUS_NOT_APPLICABLE = "not_applicable"

FACT_FIELD_STATUSES = {
    FACT_STATUS_UNEXTRACTED,
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_NOT_APPLICABLE,
}


def normalize_fact_status(status: Any, *, has_value: bool) -> str:
    """归一字段状态：不适用是人工裁定、与取值无关；其余一律按有无取值判定。

    历史状态（v1 四态 candidate/missing，v2 七态 extracted/pending_confirmation/
    conflict/missing_source）无需逐个映射：它们的区别只在「谁写的值」，而那个信息
    在 sourceRefs 里，不在 status 里。旧数据读进来即被这里收敛，不需要迁移脚本。
    """
    if str(status or "").strip() == FACT_STATUS_NOT_APPLICABLE:
        return FACT_STATUS_NOT_APPLICABLE
    return FACT_STATUS_CONFIRMED if has_value else FACT_STATUS_UNEXTRACTED


# 来源优先级（数值越大越优先），口径见 docs/20260723-项目事实表填写任务梳理.md §5：
# 招标文件原文 > 项目创建信息 > 项目定制素材 > 客户定制素材 > 标准素材。
# 人工值不在这里排序——它靠 sourceRefs 的人工标记直接锁定，任何来源都覆盖不了。
FACT_SOURCE_PRIORITY_TENDER = 340
FACT_SOURCE_PRIORITY_PROJECT = 320
# 机型、台数、基础形式是人在「完善项目信息」里逐行选定的，不是平台侧初值，
# 招标文件抽取覆盖不了（产品裁决 2026-08-10）。同来源的单机容量/叶轮直径/轮毂高度
# 是机型参数表带出来的，不属于人填，仍按 FACT_SOURCE_PRIORITY_PROJECT。
FACT_SOURCE_PRIORITY_PROJECT_TURBINE = 350


# 人工来源标记：manualFact 是人工新增的字段行，manualEdit 是人在页面上改过的格子。
# 重建时只有带这些标记（或人工确认/标不适用）的值跨轮保留，见 is_human_authored_fact_field。
FACT_MANUAL_SOURCE_TYPES = {"manualFact", "manualEdit"}


def empty_fact_summary() -> dict[str, int]:
    return {
        "totalCount": 0,
        "requiredCount": 0,
        "confirmedCount": 0,
        "unextractedCount": 0,
        "notApplicableCount": 0,
        # 多来源分歧不再是状态，值已按优先级取定；这里只统计带 hasConflict 标记的行，
        # 供页面提示「这几个字段有别的来源给了不同值，翻 alternatives 复核」
        "conflictCount": 0,
        "specTotal": 0,
        "specBuiltTotal": 0,
        # deprecated：旧口径"有值的 spec 行数"，保留兼容，前端展示改用下方两段进度
        "specMatched": 0,
        # 清单进度：specConfirmedCount（有值可用）+ specUnfilledCount（待人工填）
        # + 不适用行 == specBuiltTotal。进度分母用 specBuiltTotal 减去不适用行，
        # 否则人工标了「不适用」的字段会让进度永远差那几条。
        "specConfirmedCount": 0,
        "specUnfilledCount": 0,
    }


def empty_project_fact_table(project_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "empty",
        "builtAt": "",
        "updatedAt": "",
        "confirmedAt": "",
        "confirmedBy": "",
        "fields": [],
        "summary": empty_fact_summary(),
    }


def summarize_project_fact_fields(fields: list[dict[str, Any]], spec_total: int | None = None) -> dict[str, int]:
    # 按归一后的状态统计：旧项目的 gap_state 里还留着七态，重建前也要数对
    def status_of(field: dict[str, Any]) -> str:
        return normalize_fact_status(field.get("status"), has_value=bool(str(field.get("value") or "").strip()))

    def count(status: str) -> int:
        return sum(1 for field in fields if status_of(field) == status)

    # 两段进度只统计规则骨架行；specSeq=0 也是合法序号，不能按真值过滤。
    spec_rows = [field for field in fields if field.get("specSeq") is not None]
    spec_confirmed = sum(1 for field in spec_rows if status_of(field) == FACT_STATUS_CONFIRMED)
    summary = empty_fact_summary()
    summary.update(
        {
            "totalCount": len(fields),
            "requiredCount": sum(1 for field in fields if field.get("required", True)),
            "confirmedCount": count(FACT_STATUS_CONFIRMED),
            "unextractedCount": count(FACT_STATUS_UNEXTRACTED),
            "notApplicableCount": count(FACT_STATUS_NOT_APPLICABLE),
            "conflictCount": sum(1 for field in fields if field.get("hasConflict")),
            # Dev 口径保持不变：已绑定规则条数是稳定分母，不能随当前建表结果波动。
            "specTotal": len(spec_rows) if spec_total is None else max(0, int(spec_total)),
            "specBuiltTotal": len(spec_rows),
            "specMatched": sum(1 for field in spec_rows if str(field.get("value") or "").strip()),
            "specConfirmedCount": spec_confirmed,
            # 不适用行没有值也不需要人补，归到「已了结」一侧，否则进度永远差这几条
            "specUnfilledCount": len(spec_rows)
            - spec_confirmed
            - sum(1 for field in spec_rows if status_of(field) == FACT_STATUS_NOT_APPLICABLE),
        }
    )
    return summary


def fact_source_ref_priority(ref: dict[str, Any]) -> int:
    source_type = str(ref.get("type") or "").strip()
    # 招标文件原文优先于项目创建信息：招标方写死的参数是投标必须对齐的口径，
    # 项目创建时填的机型/台数只是平台侧的初值（产品裁决 2026-08-10）
    if source_type == "parseField":
        return FACT_SOURCE_PRIORITY_TENDER
    if source_type in {"project", "projectIdentity", "projectTurbineModel", "derived"}:
        return FACT_SOURCE_PRIORITY_PROJECT
    if source_type in {"materialFact", "derivedMaterialFact"}:
        tier = str(ref.get("materialTier") or "").strip() or "standard"
        return FACT_MATERIAL_SOURCE_PRIORITIES.get(tier, 50)
    return 0


def normalize_fact_source_refs(refs: Any) -> list[dict[str, Any]]:
    normalized: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for index, ref in enumerate(refs if isinstance(refs, list) else []):
        if not isinstance(ref, dict):
            continue
        item = copy.deepcopy(ref)
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        normalized.append((fact_source_ref_priority(item), index, item))
    normalized.sort(key=lambda item: (-item[0], item[1]))
    return [item for _, _, item in normalized]


def normalize_project_fact_field(
    field: dict[str, Any],
    *,
    index: int,
    confirm: bool,
    operator: str,
    saved_at: str,
) -> dict[str, Any]:
    value = str(field.get("value") or "").strip()
    status = normalize_fact_status(field.get("status"), has_value=bool(value))
    incoming_refs = field.get("sourceRefs") if isinstance(field.get("sourceRefs"), list) else []
    if confirm and not any(
        isinstance(ref, dict) and str(ref.get("type") or "") in FACT_MANUAL_SOURCE_TYPES for ref in incoming_refs
    ):
        # 人在页面上保存过这一格 → 打人工标记。重建时靠它保留人工结论，
        # 不能再用 status==confirmed 代替：规则抽出来的值现在也是 confirmed。
        incoming_refs = [
            {"type": "manualEdit", "title": "人工填写", "field": str(field.get("label") or "")},
            *incoming_refs,
        ]
    source_refs = normalize_fact_source_refs(incoming_refs)
    source_priority = int(field.get("sourcePriority") or 0)
    if source_refs:
        source_priority = max(source_priority, fact_source_ref_priority(source_refs[0]))
    normalized = {
        "id": str(field.get("id") or f"FACT-{index:04d}"),
        "key": str(field.get("key") or fact_label_key(field.get("label")) or f"fact-{index}"),
        "label": str(field.get("label") or ""),
        "category": str(field.get("category") or "项目事实"),
        "value": value,
        "unit": str(field.get("unit") or ""),
        "required": bool(field.get("required", True)),
        "status": status,
        "confidence": float(field.get("confidence") or 0),
        "sourcePriority": source_priority,
        "sourceRefs": source_refs,
        "alternatives": copy.deepcopy(field.get("alternatives") if isinstance(field.get("alternatives"), list) else []),
        "notes": str(field.get("notes") or ""),
        "updatedAt": saved_at,
        "updatedBy": operator,
    }
    # 清单 spec 元数据（有则保留，供前端展示"待确认"标记与复核口径）；
    # turbineGroup/turbineModelLabel 是机型分组标记，页面保存后要跟着回写，否则分组丢失
    for meta_key in ("specSeq", "specKey", "reviewLabel", "needsConfirmation", "sourceKind", "sourceHint", "placeholder", "targetFile", "turbineGroup", "turbineModelLabel"):
        if field.get(meta_key) is not None:
            normalized[meta_key] = copy.deepcopy(field.get(meta_key))
    if field.get("outOfSpec"):
        normalized["outOfSpec"] = True
    if normalized["status"] == FACT_STATUS_CONFIRMED:
        normalized["confirmedAt"] = saved_at
        normalized["confirmedBy"] = operator
    else:
        normalized["confirmedAt"] = str(field.get("confirmedAt") or "")
        normalized["confirmedBy"] = str(field.get("confirmedBy") or "")
    return normalized


def fact_table_value_map(fact_table: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fact_table.get("fields") or []:
        if not isinstance(field, dict):
            continue
        label = canonical_fact_label(str(field.get("label") or field.get("title") or ""))
        value = str(field.get("value") or "").strip()
        if label and value:
            values[label] = value
            values[fact_label_key(label)] = value
    return values


def _spec_match_keys(spec: dict[str, Any]) -> list[str]:
    """spec 的候选匹配键：label、reviewLabel、手工别名，统一走 canonical 归一。"""
    keys: list[str] = []
    for label in [spec.get("label"), spec.get("reviewLabel"), *SPEC_LABEL_ALIASES.get(str(spec.get("label") or ""), [])]:
        key = fact_label_key(label)
        if key and key not in keys:
            keys.append(key)
    return keys


def reconcile_fact_fields_with_specs(
    fields_by_key: dict[str, dict[str, Any]],
    existing_by_key: dict[str, dict[str, Any]] | None = None,
    specs: list[dict[str, Any]] | None = None,
) -> None:
    """以填值 spec 为骨架对齐抽取结果。

    - 匹配到的字段打上 spec 元数据；needsConfirmation 且已自动提取的转"待人工确认"。
    - 未匹配到的 spec 生成"未提取"骨架字段，保证清单字段在事实表中齐全。
    - 一个启发式字段只归属一个 spec（按清单序号顺序先到先得）。
    - 上一轮已有人工值/人工状态的 spec 字段在重建时保留（人工确认结果不丢）。
    - specs 为 None 时回退 fillable_specs()（全局清单）；构建链路显式传已解析的 specs。
    """
    existing_by_key = existing_by_key or {}
    matched_field_keys: set[str] = set()
    for spec in (specs if specs is not None else fillable_specs()):
        match_keys = _spec_match_keys(spec)
        field: dict[str, Any] | None = None
        for key in match_keys:
            candidate = fields_by_key.get(key)
            if candidate is not None and key not in matched_field_keys:
                field = candidate
                matched_field_keys.add(key)
                break
        if field is not None:
            field.pop("outOfSpec", None)
            field["specSeq"] = int(spec.get("seq") or 0)
            field["specKey"] = str(spec.get("key") or "")
            field["reviewLabel"] = str(spec.get("reviewLabel") or "")
            field["needsConfirmation"] = bool(spec.get("needsConfirmation"))
            field["sourceKind"] = str(spec.get("sourceKind") or "")
            # 正文填写按「待填写文件 + 占位符原文」定位字段，两列随字段下发到 manifest
            field["placeholder"] = str(spec.get("placeholder") or "")
            field["targetFile"] = str(spec.get("targetFile") or "")
            # needsConfirmation 只作为「这条清单要求人工复核口径」的展示标记随字段下发，
            # 不再改状态：有值就可用，口径对不对由人在页面上看着标记自行核。
            continue
        key = fact_label_key(spec.get("label")) or f"spec-{int(spec.get('seq') or 0):03d}"
        if key in fields_by_key:
            key = f"spec-{int(spec.get('seq') or 0):03d}"
        skeleton = {
            "id": "",
            "key": key,
            "label": str(spec.get("label") or ""),
            "category": spec_category(spec),
            "value": "",
            "unit": "",
            "required": True,
            "status": FACT_STATUS_UNEXTRACTED,
            "confidence": 0.0,
            "sourcePriority": 0,
            "sourceRefs": [],
            "alternatives": [],
            "notes": str(spec.get("note") or ""),
            "updatedAt": "",
            "updatedBy": "",
            "confirmedAt": "",
            "confirmedBy": "",
            "specSeq": int(spec.get("seq") or 0),
            "specKey": str(spec.get("key") or ""),
            "reviewLabel": str(spec.get("reviewLabel") or ""),
            "needsConfirmation": bool(spec.get("needsConfirmation")),
            "sourceKind": str(spec.get("sourceKind") or ""),
            "sourceHint": str(spec.get("referenceFile") or ""),
            "placeholder": str(spec.get("placeholder") or ""),
            "targetFile": str(spec.get("targetFile") or ""),
        }
        # 上一轮的人工结果随重建保留；AI 与规则抽取的值一律不继承，本轮重新取
        previous = next(
            (existing_by_key[k] for k in [key, *match_keys, f"spec-{int(spec.get('seq') or 0):03d}"] if k in existing_by_key),
            None,
        )
        if previous is not None:
            prev_value = str(previous.get("value") or "").strip()
            prev_status = normalize_fact_status(previous.get("status"), has_value=bool(prev_value))
            if is_human_authored_fact_field(previous):
                skeleton["value"] = prev_value
                skeleton["unit"] = str(previous.get("unit") or "")
                skeleton["status"] = prev_status
                skeleton["sourceRefs"] = copy.deepcopy(
                    previous.get("sourceRefs") if isinstance(previous.get("sourceRefs"), list) else []
                )
                skeleton["confirmedAt"] = str(previous.get("confirmedAt") or "")
                skeleton["confirmedBy"] = str(previous.get("confirmedBy") or "")
        fields_by_key[key] = skeleton
        # 骨架键同样占位，避免后续 spec 把别人的骨架当成匹配字段
        matched_field_keys.add(key)


def is_manual_fact_field(field: dict[str, Any]) -> bool:
    """人工新增字段：sourceRefs 含 manualFact 来源。无 specSeq，不计入清单统计。"""
    refs = field.get("sourceRefs") if isinstance(field.get("sourceRefs"), list) else []
    return any(isinstance(ref, dict) and str(ref.get("type") or "") == "manualFact" for ref in refs)


def is_human_authored_fact_field(field: dict[str, Any]) -> bool:
    """人工产出的值：重建时只有这些跨轮保留，AI 与规则抽取的值一律重来。

    只认两种人工动作：sourceRefs 里的人工标记（新增字段 manualFact / 页面上保存过
    manualEdit），以及人工裁定的「不适用」。

    不能再拿 status==confirmed 当依据：三态收敛后规则抽取和 AI 复核的值也是
    confirmed，那样判会让整张表都被当成人工结论保留下来，重建等于不重建——
    规则改进、清单换版、素材更新全都进不来。
    """
    refs = field.get("sourceRefs") if isinstance(field.get("sourceRefs"), list) else []
    if any(
        isinstance(ref, dict) and str(ref.get("type") or "") in FACT_MANUAL_SOURCE_TYPES for ref in refs
    ):
        return True
    return str(field.get("status") or "") == FACT_STATUS_NOT_APPLICABLE


def preserve_compatible_existing_fields(
    existing_by_key: dict[str, dict[str, Any]],
    fields_by_key: dict[str, dict[str, Any]],
) -> None:
    """保留人工产出的字段（新增/改值/确认/不适用），避免重建时丢失人工结论。

    已确认字段先移除旧 spec 元数据，再参与当前规则对齐；若没有命中当前规则，
    则以 outOfSpec 标记留在表尾，且不计入当前规则版本的进度。
    """
    for existing in existing_by_key.values():
        if not isinstance(existing, dict):
            continue
        label_text = canonical_fact_label(existing.get("label"))
        key = fact_label_key(label_text)
        if not key:
            continue
        source_refs = [
            ref
            for ref in (existing.get("sourceRefs") if isinstance(existing.get("sourceRefs"), list) else [])
            if isinstance(ref, dict)
        ]
        if not is_human_authored_fact_field(existing):
            continue
        is_manual = any(str(ref.get("type") or "") == "manualFact" for ref in source_refs)
        has_value = bool(str(existing.get("value") or "").strip())
        field = copy.deepcopy(existing)
        for meta_key in ("specSeq", "specKey", "reviewLabel", "needsConfirmation", "sourceKind", "sourceHint", "placeholder", "targetFile"):
            field.pop(meta_key, None)
        field["label"] = label_text
        field["key"] = key
        field["category"] = str(field.get("category") or ("人工补充事实" if is_manual else "清单外历史事实"))
        field["status"] = normalize_fact_status(field.get("status"), has_value=has_value)
        field["sourceRefs"] = source_refs or (
            [{"type": "manualFact", "title": "人工新增", "field": label_text}] if is_manual else []
        )
        # 人工改过值的清单字段没命中当前规则版本时留在表尾且不计进度；
        # 人工新增字段本来就在清单外，不标；标了不适用的没有值，也不标。
        if field["status"] == FACT_STATUS_CONFIRMED and not is_manual:
            field["outOfSpec"] = True
        fields_by_key[key] = field


def build_project_fact_table(project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
    built_at = _now_iso()
    existing_table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    existing_by_key = {
        fact_label_key(field.get("label")): field
        for field in (existing_table.get("fields") if isinstance(existing_table.get("fields"), list) else [])
        if isinstance(field, dict) and fact_label_key(field.get("label"))
    }
    fields_by_key: dict[str, dict[str, Any]] = {}
    # 人在「完善项目信息」里逐行选定的机型参数：归一键 → (机型序号, 组内序号)，
    # 用于把这些行按机型分组置顶，并让它们绕过清单骨架过滤（多机型行不在清单里）。
    turbine_group_by_key: dict[str, tuple[int, int]] = {}
    turbine_label_by_key: dict[str, str] = {}
    # 清单全局唯一（规则页上传），所有项目同一份；这里把生效版本固化进产物做审计
    project_specs, fact_specs_meta = resolve_fact_specs()
    # 换了新 Excel（规则版本变更）视作从头来：连人工值一起丢弃。清单换掉后字段本就
    # 可能对不上号，继承旧值只会让上一版的结论混进新清单。同一份 Excel 刷新不受影响。
    existing_rule_id = str(
        (existing_table.get("factSpecsRef") or {}).get("ruleId") or ""
        if isinstance(existing_table.get("factSpecsRef"), dict)
        else ""
    )
    if existing_rule_id != str(fact_specs_meta.get("ruleId") or ""):
        existing_by_key = {}

    def is_material_fact_ref(ref: dict[str, Any]) -> bool:
        return str(ref.get("type") or "") in {"materialFact", "derivedMaterialFact"}

    def blank_source_paths() -> set[str]:
        paths: set[str] = set()
        plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
        for item in plan.get("items") or []:
            if not isinstance(item, dict):
                continue
            for task in item.get("fillTasks") or []:
                if not isinstance(task, dict):
                    continue
                blank = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
                for key in ("docxPath", "path", "workspacePath"):
                    value = str(blank.get(key) or "").strip()
                    if value:
                        paths.add(str(Path(value).resolve()))
        return paths

    def add_candidate(
        label: str,
        value: Any,
        *,
        category: str,
        source_ref: dict[str, Any],
        confidence: float = 0.8,
        required: bool = True,
        unit: str = "",
        source_priority: int = 0,
    ) -> None:
        label_text = canonical_fact_label(label)
        if not label_text:
            return
        key = fact_label_key(label_text)
        value_text = str(value or "").strip()
        existing = existing_by_key.get(key)
        preserve_existing = bool(
            existing
            and is_human_authored_fact_field(existing)
            and str(existing.get("value") or "").strip()
        )
        if preserve_existing:
            value_text = str(existing.get("value") or "").strip()
        field = fields_by_key.get(key)
        incoming_priority = int(source_priority or 0)
        if not field:
            field = {
                "id": str((existing or {}).get("id") or f"FACT-{len(fields_by_key) + 1:04d}"),
                "key": key,
                "label": label_text,
                "category": category,
                "value": value_text,
                "unit": str(((existing or {}).get("unit") if preserve_existing else unit) or ""),
                "required": bool((existing or {}).get("required", required)),
                "status": normalize_fact_status(
                    (existing or {}).get("status") if preserve_existing else None,
                    has_value=bool(value_text),
                ),
                "confidence": float(((existing or {}).get("confidence") if preserve_existing else None) or (confidence if value_text else 0) or 0),
                "sourcePriority": int((existing or {}).get("sourcePriority") if preserve_existing else (incoming_priority if value_text else 0)),
                # 保留旧 sourceRefs：人工标记（manualEdit/manualFact）存在这里，
                # 清空会让下一轮重建认不出这是人工值而误当 AI 值冲掉
                "sourceRefs": copy.deepcopy((existing or {}).get("sourceRefs"))
                if preserve_existing and isinstance((existing or {}).get("sourceRefs"), list)
                else [],
                "alternatives": copy.deepcopy(
                    (existing or {}).get("alternatives")
                    if preserve_existing and isinstance((existing or {}).get("alternatives"), list)
                    else []
                ),
                "notes": str((existing or {}).get("notes") if preserve_existing else ""),
                "updatedAt": str((existing or {}).get("updatedAt") if preserve_existing else built_at),
                "updatedBy": str((existing or {}).get("updatedBy") if preserve_existing else ""),
                "confirmedAt": str((existing or {}).get("confirmedAt") if preserve_existing else ""),
                "confirmedBy": str((existing or {}).get("confirmedBy") if preserve_existing else ""),
            }
            fields_by_key[key] = field
        elif value_text and field.get("value") and value_text != field["value"]:
            alternatives = field.setdefault("alternatives", [])
            # 谁能覆盖谁只看「是不是人工写的」，不再看 status——三态收敛后规则抽取的值
            # 也是 confirmed，拿 status 当锁会让本轮第一个到场的来源锁死后面更高优先级的。
            locked = is_human_authored_fact_field(field)
            existing_rank = (int(field.get("sourcePriority") or 0), float(field.get("confidence") or 0))
            incoming_rank = (incoming_priority, float(confidence or 0))
            if incoming_rank > existing_rank and not locked:
                old_value = str(field.get("value") or "")
                if old_value and old_value not in [str(item.get("value") or "") for item in alternatives if isinstance(item, dict)]:
                    alternatives.append({"value": old_value, "source": (field.get("sourceRefs") or [{}])[0]})
                field["value"] = value_text
                field["unit"] = str(unit or field.get("unit") or "")
                field["category"] = category
                field["status"] = FACT_STATUS_CONFIRMED
                field["confidence"] = float(confidence or 0)
                field["sourcePriority"] = incoming_priority
                if source_ref:
                    field["sourceRefs"] = [source_ref] + list(field.get("sourceRefs") or [])
                    source_ref = {}
            elif incoming_rank == existing_rank and not locked:
                existing_material = any(
                    is_material_fact_ref(ref)
                    for ref in (field.get("sourceRefs") if isinstance(field.get("sourceRefs"), list) else [])
                    if isinstance(ref, dict)
                )
                # 同优先级不同值：值保持先到的那个，只挂标记 + 留候选，不再拦成待人工裁决
                if not (existing_material and is_material_fact_ref(source_ref)):
                    field["hasConflict"] = True
                if value_text not in [str(item.get("value") or "") for item in alternatives if isinstance(item, dict)]:
                    alternatives.append({"value": value_text, "source": source_ref})
            elif value_text not in [str(item.get("value") or "") for item in alternatives if isinstance(item, dict)]:
                alternatives.append({"value": value_text, "source": source_ref})
        elif value_text and field.get("value") and value_text == field.get("value"):
            existing_rank = (int(field.get("sourcePriority") or 0), float(field.get("confidence") or 0))
            incoming_rank = (incoming_priority, float(confidence or 0))
            if incoming_rank > existing_rank and not is_human_authored_fact_field(field):
                field["unit"] = str(unit or field.get("unit") or "")
                field["category"] = category
                field["confidence"] = float(confidence or 0)
                field["sourcePriority"] = incoming_priority
                if source_ref:
                    field["sourceRefs"] = [source_ref] + list(field.get("sourceRefs") or [])
                    source_ref = {}
        elif value_text and not field.get("value"):
            field["value"] = value_text
            field["status"] = FACT_STATUS_CONFIRMED
            field["unit"] = str(unit or field.get("unit") or "")
            field["confidence"] = max(float(field.get("confidence") or 0), float(confidence or 0))
            field["sourcePriority"] = incoming_priority
            field["category"] = category
            if source_ref:
                field["sourceRefs"] = [source_ref] + list(field.get("sourceRefs") or [])
                source_ref = {}
        if source_ref:
            field.setdefault("sourceRefs", []).append(source_ref)
        if preserve_existing and value_text:
            field["status"] = normalize_fact_status(existing.get("status"), has_value=True)


    trusted_parse_facts = trusted_parse_fact_fields(project.get("parse_result"))
    first_parse_value = {
        fact_label_key(fact.get("label")): fact.get("value")
        for fact in trusted_parse_facts
        if fact.get("value")
    }
    identity = project.get("identity") if isinstance(project.get("identity"), dict) else {}
    owner = identity.get("owner") or identity.get("customerCanonicalName") or identity.get("customerName") or project.get("owner") or project.get("customerName")
    project_name = first_parse_value.get(fact_label_key("项目名称")) or project.get("name")
    add_candidate("项目名称", project_name, category="项目基础信息", source_ref={"type": "project", "field": "name", "title": "项目名称"}, confidence=0.86, source_priority=FACT_SOURCE_PRIORITY_PROJECT)
    add_candidate("招标方", owner, category="项目基础信息", source_ref={"type": "projectIdentity", "field": "owner", "title": "招标方"}, confidence=0.92, source_priority=FACT_SOURCE_PRIORITY_PROJECT)
    add_candidate("招标人", owner, category="项目基础信息", source_ref={"type": "projectIdentity", "field": "owner", "title": "招标人"}, confidence=0.92, source_priority=FACT_SOURCE_PRIORITY_PROJECT)
    add_candidate("客户名称", project.get("customerName"), category="项目基础信息", source_ref={"type": "project", "field": "customerName", "title": "客户名称"}, confidence=0.9, source_priority=FACT_SOURCE_PRIORITY_PROJECT)
    add_candidate("日期", datetime.now(UTC).strftime("%Y年%m月%d日"), category="系统字段", source_ref={"type": "system", "field": "currentDate", "title": "当前日期"}, confidence=0.62)

    turbine_models = project_turbine_models(project)
    turbine = turbine_models[0] if turbine_models else {}
    multi_turbine = len(turbine_models) > 1
    model = turbine.get("model") or turbine.get("turbineModel")
    hub_height = turbine.get("hubHeightM")
    for index, row in enumerate(turbine_models, start=1):
        # 单机型退化成不带序号的字段名，与清单第 11/80/81/83/84 行是同一个归一键；
        # 多机型每行独立成组，不带序号的那几行留给下面的全场口径。
        prefix = f"机型{index}" if multi_turbine else ""
        row_model = row.get("model") or row.get("turbineModel")
        row_rated_kw = row.get("ratedPowerKw")
        row_rated_mw = f"{row_rated_kw / 1000:g}" if isinstance(row_rated_kw, (int, float)) else ""
        for order, (label, value, field_name, unit, confidence, priority) in enumerate(
            (
                (f"投标机型{index}" if multi_turbine else "投标机型", row_model, "model", "", 0.98, FACT_SOURCE_PRIORITY_PROJECT_TURBINE),
                (f"{prefix}台数" if multi_turbine else "机组台数", row.get("turbineCount"), "turbineCount", "台", 0.95, FACT_SOURCE_PRIORITY_PROJECT_TURBINE),
                (f"{prefix}基础形式", row.get("foundationType"), "foundationType", "", 0.95, FACT_SOURCE_PRIORITY_PROJECT_TURBINE),
                (f"{prefix}单机容量", row_rated_mw or row_rated_kw, "ratedPowerKw", "MW" if row_rated_mw else "", 0.9, FACT_SOURCE_PRIORITY_PROJECT),
                (f"{prefix}叶轮直径", row.get("rotorDiameterM"), "rotorDiameterM", "m", 0.9, FACT_SOURCE_PRIORITY_PROJECT),
                (f"{prefix}轮毂高度", row.get("hubHeightM"), "hubHeightM", "m", 0.86, FACT_SOURCE_PRIORITY_PROJECT),
            ),
            start=1,
        ):
            key = fact_label_key(label)
            if not key:
                continue
            turbine_group_by_key[key] = (index, order)
            turbine_label_by_key[key] = str(row_model or "")
            add_candidate(
                label,
                value,
                category="机型参数",
                source_ref={
                    "type": "projectTurbineModel",
                    "field": field_name,
                    "title": label,
                    "turbineModel": str(row_model or ""),
                },
                confidence=confidence,
                unit=unit,
                source_priority=priority,
            )
    if multi_turbine:
        # 清单第 11/80/81/83/84 行带 targetFile 和占位符，正文填写靠它们取值，多机型时
        # 不能空着：机型给全部机型的合并串，台数给各行之和，其余单机参数按第一个机型给，
        # 来源里标明是哪个机型（各机型取值口径待正文填写支持按机型铺开后再收口）。
        add_candidate(
            "投标机型",
            "、".join(str(row.get("model") or "").strip() for row in turbine_models if str(row.get("model") or "").strip()),
            category="机型参数",
            source_ref={"type": "projectTurbineModel", "field": "model", "title": "投标机型（全部机型）"},
            confidence=0.98,
            source_priority=FACT_SOURCE_PRIORITY_PROJECT_TURBINE,
        )
        rated_kw = turbine.get("ratedPowerKw")
        rated_mw = f"{rated_kw / 1000:g}" if isinstance(rated_kw, (int, float)) else ""
        for label, value, field_name, unit, confidence in (
            ("单机容量", rated_mw or rated_kw, "ratedPowerKw", "MW" if rated_mw else "", 0.9),
            ("叶轮直径", turbine.get("rotorDiameterM"), "rotorDiameterM", "m", 0.9),
            ("轮毂高度", hub_height, "hubHeightM", "m", 0.86),
        ):
            add_candidate(
                label,
                value,
                category="机型参数",
                source_ref={
                    "type": "projectTurbineModel",
                    "field": field_name,
                    "title": f"{label}（机型1 {model or ''}）",
                    "turbineModel": str(model or ""),
                },
                confidence=confidence,
                unit=unit,
                source_priority=FACT_SOURCE_PRIORITY_PROJECT,
            )
    # 机组台数取各机型台数之和：弹窗强制每行填正整数，任一行填不出数就不给值，
    # 回落到招标文件与素材抽取。单机型时这个和就是那一行本身。
    turbine_counts = [str(row.get("turbineCount") or "").strip() for row in turbine_models]
    if multi_turbine and turbine_counts and all(count.isdigit() and int(count) > 0 for count in turbine_counts):
        add_candidate(
            "机组台数",
            str(sum(int(count) for count in turbine_counts)),
            category="机型参数",
            source_ref={"type": "projectTurbineModel", "field": "turbineCount", "title": "机组台数（各机型之和）"},
            confidence=0.95,
            unit="台",
            source_priority=FACT_SOURCE_PRIORITY_PROJECT_TURBINE,
        )
    if model and hub_height:
        add_candidate("投标方案", f"{model}-{hub_height}m", category="方案口径", source_ref={"type": "derived", "field": "modelHubHeight", "title": "投标方案"}, confidence=0.78, source_priority=FACT_SOURCE_PRIORITY_PROJECT)
        add_candidate("方案", f"{model}-{hub_height}m", category="方案口径", source_ref={"type": "derived", "field": "modelHubHeight", "title": "方案"}, confidence=0.78, source_priority=FACT_SOURCE_PRIORITY_PROJECT)
    elif model:
        add_candidate("投标方案", model, category="方案口径", source_ref={"type": "derived", "field": "model", "title": "投标方案"}, confidence=0.64, source_priority=80)

    for fact in trusted_parse_facts:
        add_candidate(
            str(fact.get("label") or ""),
            fact.get("value"),
            category=str(fact.get("category") or "招标解析字段"),
            source_ref=copy.deepcopy(fact.get("sourceRef") or {}),
            confidence=float(fact.get("confidence") or 0.82),
            required=bool(fact.get("required", False)),
            unit=str(fact.get("unit") or ""),
            source_priority=FACT_SOURCE_PRIORITY_TENDER,
        )

    for fact in project_material_fact_fields(
        project, gap_state, excluded_paths=blank_source_paths(), specs=project_specs
    ):
        if fact.get("internal"):
            continue
        add_candidate(
            str(fact.get("label") or ""),
            fact.get("value"),
            category=str(fact.get("category") or "素材库事实"),
            source_ref=copy.deepcopy(fact.get("sourceRef") or {}),
            confidence=float(fact.get("confidence") or 0.78),
            required=bool(fact.get("required", False)),
            unit=str(fact.get("unit") or ""),
            source_priority=int(fact.get("sourcePriority") or 0),
        )

    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    for item in plan.get("items") or []:
        if not isinstance(item, dict):
            continue
        for task in item.get("fillTasks") or []:
            if not isinstance(task, dict):
                continue
            blank = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
            for label in blank.get("placeholderLabels") or []:
                add_candidate(
                    str(label),
                    "",
                    category="待填写Word字段",
                    source_ref={
                        "type": "gapPlaceholder",
                        "gapId": str(item.get("id") or ""),
                        "title": str(item.get("title") or ""),
                        "field": str(label),
                    },
                    confidence=0.0,
                )
            for label in fillable_table_labels_from_blank_source(blank):
                add_candidate(
                    label,
                    "",
                    category="待填写表格字段",
                    source_ref={
                        "type": "gapTableField",
                        "gapId": str(item.get("id") or ""),
                        "title": str(item.get("title") or ""),
                        "field": label,
                        "blankSourceId": str(blank.get("id") or ""),
                    },
                    confidence=0.0,
                )

    for task in plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for label in technical_fact_labels_from_task(task):
            add_candidate(
                label,
                "",
                category="技术待填写字段",
                source_ref={
                    "type": "technicalGapTask",
                    "taskId": str(task.get("id") or ""),
                    "title": str(task.get("title") or ""),
                    "field": label,
                },
                confidence=0.0,
            )

    preserve_compatible_existing_fields(existing_by_key, fields_by_key)
    # 字段骨架来自任务启动时固化的规则快照（项目绑定版本，无绑定回落系统默认清单）
    spec_mode = bool(project_specs)
    if not spec_mode:
        logger.warning("项目 %s 无可用事实表字段规则，按来源并集构建", project.get("id"))
    reconcile_fact_fields_with_specs(fields_by_key, existing_by_key, project_specs)

    fields = list(fields_by_key.values())
    # 分组标记在 preserve_compatible_existing_fields 之后按归一键补：那一步会用人工值
    # 整个换掉 field dict，构建时打的标记会丢。
    for field in fields:
        group = turbine_group_by_key.get(str(field.get("key") or ""))
        if group:
            field["turbineGroup"] = group[0]
            field["turbineModelLabel"] = turbine_label_by_key.get(str(field.get("key") or ""), "")
    if spec_mode:
        # 以清单为唯一字段骨架：匹配不到 spec 的来源字段不再单独成行，
        # 只保留 spec 行、人工新增字段、旧规则下已经人工确认的兼容字段，
        # 以及按项目选定机型展开的机型参数行（多机型时这些行不在清单里）。
        fields = [
            field
            for field in fields
            if field.get("specSeq") is not None
            or is_manual_fact_field(field)
            or bool(field.get("outOfSpec"))
            or field.get("turbineGroup")
        ]
    for field in fields:
        source_refs = normalize_fact_source_refs(field.get("sourceRefs"))
        field["sourceRefs"] = source_refs
        if source_refs:
            field["sourcePriority"] = max(
                int(field.get("sourcePriority") or 0),
                fact_source_ref_priority(source_refs[0]),
            )
    category_order = {
        "项目基础信息": 0,
        "机型参数": 1,
        "方案口径": 2,
        "系统字段": 3,
        "招标解析字段": 4,
        "素材库事实": 5,
        "性能保证": 6,
        "待填写Word字段": 7,
        "待填写表格字段": 8,
        "技术待填写字段": 9,
        "清单-招标文件": 10,
        "清单-项目定制材料": 11,
        "清单-认证证书": 12,
        "清单-平台输入": 13,
        "清单-自动生成": 14,
    }
    fields.sort(
        key=lambda field: (
            # 人选的机型参数按机型分组置顶：多机型时页面据此分段显示，
            # 单机型时只有一组、组内顺序与现在的机型参数段一致。
            0 if field.get("turbineGroup") else 1,
            int(field.get("turbineGroup") or 0),
            turbine_group_by_key.get(str(field.get("key") or ""), (0, 0))[1],
            # 清单模式下，人工新增和清单外历史字段追加在当前规则骨架之后。
            1 if spec_mode and field.get("specSeq") is None else 0,
            category_order.get(str(field.get("category") or ""), 9),
            0 if field.get("required") else 1,
            int(field.get("specSeq")) if field.get("specSeq") is not None else 9999,
            field.get("label") or "",
        )
    )
    # 补 id 时避开已有 id：骨架行按排序序号补 FACT-XXXX，可能与清单外候选自带的
    # FACT-XXXX 撞号（清单模式下杂行被过滤后序号前移），撞号则顺延到未占用的序号
    used_ids: set[str] = set()
    for index, field in enumerate(fields, start=1):
        field_id = str(field.get("id") or "")
        if not field_id or field_id in used_ids:
            serial = index
            field_id = f"FACT-{serial:04d}"
            while field_id in used_ids:
                serial += 1
                field_id = f"FACT-{serial:04d}"
        field["id"] = field_id
        used_ids.add(field_id)
    return {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": str(project.get("id") or ""),
        "status": "draft",
        "builtAt": built_at,
        "updatedAt": built_at,
        "confirmedAt": "",
        "confirmedBy": "",
        "fields": fields,
        "summary": summarize_project_fact_fields(fields, spec_total=len(project_specs)),
        # 本次构建实际使用的规则版本快照（审计：正式标书用了哪版规则）
        "factSpecsRef": fact_specs_meta,
    }


def derived_material_fact_fields(project: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_label: dict[str, dict[str, Any]] = {}
    guarantee_matrix_rows: list[dict[str, Any]] = []
    for fact in facts:
        if fact.get("label") == "__guaranteeMatrixRow":
            guarantee_matrix_rows.append(fact)
            continue
        label = canonical_fact_label(fact.get("label"))
        if not label or not fact.get("value"):
            continue
        current = by_label.get(label)
        rank = (int(fact.get("sourcePriority") or 0), float(fact.get("confidence") or 0))
        if current is None or rank > (int(current.get("sourcePriority") or 0), float(current.get("confidence") or 0)):
            by_label[label] = fact
    rated_kw = project_turbine_model(project).get("ratedPowerKw")
    rated_mw = float(rated_kw) / 1000 if isinstance(rated_kw, (int, float)) and rated_kw else 0
    result: list[dict[str, Any]] = []
    total = number_from_fact(by_label.get("总装机容量"))
    count = number_from_fact(by_label.get("机组台数"))
    source = by_label.get("总装机容量") or by_label.get("机组台数") or {}
    material_ref = copy.deepcopy(source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {})
    if total and rated_mw and not count:
        derived_count = total / rated_mw
        rounded = round(derived_count)
        if abs(derived_count - rounded) < 0.01:
            result.append(
                {
                    "label": "机组台数",
                    "value": str(rounded),
                    "category": "素材库事实",
                    "unit": "台",
                    "confidence": 0.86,
                    "sourcePriority": int(source.get("sourcePriority") or 0),
                    "sourceRef": {**material_ref, "type": "derivedMaterialFact", "field": "总装机容量/单机容量"},
                }
            )
    if count and rated_mw and not total:
        result.append(
            {
                "label": "总装机容量",
                "value": f"{count * rated_mw:g}MW",
                "category": "素材库事实",
                "unit": "MW",
                "confidence": 0.82,
                "sourcePriority": int(source.get("sourcePriority") or 0),
                "sourceRef": {**material_ref, "type": "derivedMaterialFact", "field": "机组台数/单机容量"},
            }
        )
    year_avg = number_from_fact(by_label.get("年平均风速"))
    if year_avg and guarantee_matrix_rows:
        def matrix_distance(row: dict[str, Any]) -> float:
            value = row.get("value") if isinstance(row.get("value"), dict) else {}
            wind = number_from_fact({"value": value.get("windSpeed")})
            return abs(float(wind or 0) - year_avg) if wind else 9999

        selected = min(guarantee_matrix_rows, key=matrix_distance)
        if matrix_distance(selected) <= 0.08:
            selected_value = selected.get("value") if isinstance(selected.get("value"), dict) else {}
            selected_ref = copy.deepcopy(selected.get("sourceRef") if isinstance(selected.get("sourceRef"), dict) else {})
            wind_speed = str(selected_value.get("windSpeed") or "")
            if selected_value.get("energyMwh"):
                result.append(
                    {
                        "label": "保证发电量",
                        "value": str(selected_value.get("energyMwh")),
                        "category": "性能保证",
                        "unit": "MWh",
                        "confidence": 0.86,
                        "sourcePriority": int(selected.get("sourcePriority") or 0),
                        "sourceRef": {**selected_ref, "type": "derivedMaterialFact", "field": f"发电量保证矩阵/{wind_speed}m/s"},
                    }
                )
            if selected_value.get("hours"):
                result.append(
                    {
                        "label": "保证有效小时数",
                        "value": str(selected_value.get("hours")),
                        "category": "性能保证",
                        "unit": "h",
                        "confidence": 0.86,
                        "sourcePriority": int(selected.get("sourcePriority") or 0),
                        "sourceRef": {**selected_ref, "type": "derivedMaterialFact", "field": f"发电量保证矩阵/{wind_speed}m/s"},
                    }
                )
    return result


def number_from_fact(fact: dict[str, Any] | None) -> float | None:
    if not isinstance(fact, dict):
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(fact.get("value") or ""))
    return float(match.group(1)) if match else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
