from __future__ import annotations

import asyncio
import copy
import json
import re
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.core.config import BASE_DIR
from app.services.minio_client import minio_client
from app.services.ocr_service import ocr_service
from app.services.opencode_client import OpencodeClient
from app.services.peripheral import PeripheralError
from app.services.technical_gap_domain import (
    summarize_technical_gap_plan,
    technical_gap_artifact_onlyoffice_payload,
)
from app.services.technical_fact_spec_versions import resolve_project_specs
from app.services.technical_gap_state import legacy_technical_gap_items_from_plan
from app.services.technical_material_store import technical_material_store
from app.services.turbine_models import project_turbine_model
from app.services.workspace_artifacts import technical_workspace_dir


TABLE_FILL_SCHEMA_VERSION = "bid-tech-table-fill-v1"
WORD_FILL_SCHEMA_VERSION = "bid-tech-word-placeholder-fill-v1"
TECHNICAL_TABLE_FILL_SKILL_NAME = "bid-tech-table-filler"
TECHNICAL_WORD_FILL_SKILL_NAME = "bid-tech-word-placeholder-filler"
TABLE_FILL_RUNNER = BASE_DIR / "opencode" / "skills" / TECHNICAL_TABLE_FILL_SKILL_NAME / "scripts" / "run_from_manifest.py"
WORD_FILL_RUNNER = BASE_DIR / "opencode" / "skills" / TECHNICAL_WORD_FILL_SKILL_NAME / "scripts" / "run_from_manifest.py"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _project_dir(project: dict[str, Any]) -> Path:
    project_id = str(project.get("id") or "")
    project_dir = technical_workspace_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _run_async(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    loop_thread_id = getattr(loop, "_thread_id", None)
    if loop_thread_id is not None and threading.get_ident() == loop_thread_id:
        raise RuntimeError(
            "_run_async was called from the running event loop's own thread. "
            "Wrap the calling sync code with asyncio.to_thread or run it in a worker thread."
        )

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - re-raised in caller
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


def _object_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _material_key(material: dict[str, Any]) -> str:
    return str(material.get("id") or material.get("materialId") or material.get("path") or material.get("docx") or "").strip()


def _material_summary(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(material.get("id") or material.get("materialId") or ""),
        "name": str(material.get("name") or material.get("title") or material.get("fileName") or ""),
        "path": str(material.get("path") or material.get("docx") or ""),
        "folderPath": str(material.get("folderPath") or ""),
        "materialTier": str(material.get("materialTier") or material.get("materialScope") or ""),
        "usage": str(material.get("usage") or ""),
        "source": str(material.get("source") or ""),
        "hasCleanedWord": bool(material.get("hasCleanedWord")),
        "cleanedFileName": str(material.get("cleanedFileName") or ""),
        "turbineModelLabel": str(material.get("turbineModelLabel") or ""),
        "matchReason": str(material.get("matchReason") or ""),
        "turbineFit": str(material.get("turbineFit") or ""),
    }


def _dedupe_material_summaries(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for material in materials:
        key = _material_key(material)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(_material_summary(material))
    return result


def _is_material_word_fill_task(item: dict[str, Any], task: dict[str, Any]) -> bool:
    blank = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
    source_type = str(blank.get("sourceType") or "")
    usage = str(item.get("usage") or "")
    try:
        placeholder_count = int(blank.get("placeholderCount") or 0)
    except (TypeError, ValueError):
        placeholder_count = 0
    material_id = str(blank.get("materialId") or blank.get("id") or "")
    return (
        source_type == "material_fill_template"
        or (
            usage in {"section_fill", "chapter_fill"}
            and placeholder_count > 0
            and material_id.startswith("RAW-")
        )
    )


def normalize_technical_gap_plan_fill_task_skills(plan: dict[str, Any]) -> int:
    repaired = 0
    for item in _object_items(plan.get("items")):
        for task in _object_items(item.get("fillTasks")):
            current = str(task.get("skill") or "")
            expected = TECHNICAL_WORD_FILL_SKILL_NAME if _is_material_word_fill_task(item, task) else ""
            if not expected or current == expected:
                continue
            task["skill"] = expected
            repaired += 1
    if repaired:
        plan["summary"] = summarize_technical_gap_plan(plan)
    return repaired


def enrich_fact_table_with_spec_columns(
    fact_table: dict[str, Any],
    gap_state: dict[str, Any],
) -> dict[str, Any]:
    """给事实表字段补上清单第 2/3 列（待填写文件 / 原占位符位置）。

    这两列是随「按清单定位」一起加的，改动前生成并存进 gap_state 的事实表没有它们，
    正文填写会误判成「清单未下发」而回退到旧的模糊匹配链路（起 agent + 跑 OCR，单条
    几十秒）。这里按 specKey 从项目当前生效清单现补，只补元数据不碰任何取值，
    也就不需要用户重建事实表——重建会重跑规则抽取，动到已确认的值。
    """
    fields = fact_table.get("fields")
    if not isinstance(fields, list) or not fields:
        return fact_table
    specs, _meta = resolve_project_specs(gap_state)
    specs_by_key = {str(spec.get("key") or ""): spec for spec in specs if isinstance(spec, dict) and spec.get("key")}
    if not specs_by_key:
        return fact_table
    enriched = copy.deepcopy(fact_table)
    for field in enriched.get("fields") or []:
        if not isinstance(field, dict):
            continue
        if str(field.get("placeholder") or "").strip() or str(field.get("targetFile") or "").strip():
            continue
        spec = specs_by_key.get(str(field.get("specKey") or ""))
        if not spec:
            continue
        field["placeholder"] = str(spec.get("placeholder") or "")
        field["targetFile"] = str(spec.get("targetFile") or "")
    return enriched


def fact_table_spec_coverage(fact_table: dict[str, Any]) -> tuple[int, int]:
    """事实表字段总数，以及其中带清单第 2/3 列（待填写文件 / 原占位符位置）的字段数。"""
    fields = _object_items(fact_table.get("fields"))
    covered = sum(
        1
        for field in fields
        if str(field.get("placeholder") or "").strip() or str(field.get("targetFile") or "").strip()
    )
    return len(fields), covered


def fact_table_drives_placeholders(fact_table: dict[str, Any]) -> bool:
    """事实表字段是否带清单第 2/3 列（待填写文件 / 原占位符位置）。

    带了就说明正文填写能按占位符精确查表定位字段，不再需要参考素材做模糊匹配。
    """
    return fact_table_spec_coverage(fact_table)[1] > 0


def require_spec_driven_fact_table(fact_table: dict[str, Any]) -> None:
    """正文填写前置校验：事实表必须能驱动占位符定位，否则直接失败。

    以前清单元数据缺失会静默回退到旧的模糊匹配链路（上下文规则 + 全库相似度 + 从素材
    抽事实 + 起 agent + 跑 OCR），单条几十秒且是错值的主要来源，而界面上只表现为「慢」，
    用户无从知道自己走错了路。这里改成显式报错并给出修复动作。

    只判零覆盖：部分字段缺列时，缺列的那些会在填写报告里记成 not_in_spec 并标黄，
    可见且不会填错值，不需要在入口拦截。
    """
    total, covered = fact_table_spec_coverage(fact_table)
    if not total:
        raise RuntimeError("正文填写需要项目事实表，当前项目还没有可用的事实表字段，请先抽取并确认事实表。")
    if not covered:
        raise RuntimeError(
            f"事实表 {total} 个字段都缺少清单的「待填写文件」「原占位符位置」两列，"
            "正文填写无法定位字段，请重新上传项目事实表清单后再填写。"
        )


def _appendix_task_for_fill(item: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    blank_source = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
    blank_id = str(blank_source.get("id") or "").strip()
    appendix_tasks = _object_items(item.get("appendixTasks"))
    for appendix_task in appendix_tasks:
        if blank_id and str(appendix_task.get("id") or "") == blank_id:
            return dict(appendix_task)
    return dict(appendix_tasks[0]) if appendix_tasks else {}


def _project_tender_documents_for_fill(
    project: dict[str, Any],
    appendix_task: dict[str, Any],
) -> list[dict[str, Any]]:
    routing = appendix_task.get("sourceRouting") if isinstance(appendix_task.get("sourceRouting"), dict) else {}
    if not routing.get("useTenderParseFields"):
        return []
    # 完整文档记录（含 sourcePath/textPath）由解析链路写入 project.parse_storage.documents；
    # project.parse_result 里只有摘要（sourceFiles），旧数据可能带 documents，均作兜底。
    parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
    documents = parse_storage.get("documents")
    if not isinstance(documents, list):
        parse_result = project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}
        documents = parse_result.get("documents")
        if not isinstance(documents, list):
            documents = parse_result.get("sourceFiles")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in _object_items(documents):
        if document.get("status") == "failed":
            continue
        source_path = Path(str(document.get("sourcePath") or ""))
        text_path = Path(str(document.get("textPath") or ""))
        supported_source = source_path.suffix.lower() in {".docx", ".pdf", ".xlsx", ".xlsm", ".txt", ".md"}
        readable_source = (
            source_path
            if supported_source and source_path.is_file()
            else text_path
            if text_path.is_file()
            else None
        )
        if readable_source is None:
            continue
        document_id = str(document.get("id") or "").strip()
        key = document_id or str(readable_source.resolve())
        if key in seen:
            continue
        seen.add(key)
        nav_path = Path(str(document.get("documentNavPath") or ""))
        result.append(
            {
                "id": document_id or f"TENDER-{len(result) + 1}",
                "name": str(document.get("name") or document.get("fileName") or source_path.name or readable_source.name),
                "sourcePath": str(readable_source),
                "originalSourcePath": str(source_path) if source_path.is_file() else "",
                "textPath": str(text_path) if text_path.is_file() else "",
                "ocrTextPath": str(text_path) if text_path.is_file() else "",
                "documentNavPath": str(nav_path) if nav_path.is_file() else "",
                "pageCount": document.get("pageCount") or 0,
                "sourceType": "project_tender_document",
                "parsedTextFallback": readable_source == text_path and readable_source != source_path,
            }
        )
    return result


def _selected_reference_material_ids(
    item: dict[str, Any],
    appendix_task: dict[str, Any],
    data: dict[str, Any],
) -> list[str]:
    if "referenceMaterialIds" in data:
        return _string_items(data.get("referenceMaterialIds"))

    has_source_routing = (
        isinstance(appendix_task.get("sourceRouting"), dict)
        and appendix_task["sourceRouting"].get("source") == "appendix_source_matrix"
    ) or (
        isinstance(item.get("sourceRouting"), dict)
        and item["sourceRouting"].get("source") == "appendix_source_matrix"
    )
    if has_source_routing:
        routed = _string_items([
            _material_key(material)
            for material in (
                _object_items(appendix_task.get("recommendedMaterials"))
                + _object_items(item.get("sourceRoutedMaterials"))
            )
        ])
        if routed:
            return routed

    matched = [_material_key(material) for material in _object_items(item.get("matchedMaterials"))]
    matched = [item for item in matched if item]
    if matched:
        return matched

    recommended = _string_items([
        _material_key(material)
        for material in _object_items(appendix_task.get("recommendedMaterials"))
    ])
    return recommended


def _reference_materials_for_fill(
    item: dict[str, Any],
    appendix_task: dict[str, Any],
    data: dict[str, Any],
    selected_ids: list[str],
) -> list[dict[str, Any]]:
    context = _dedupe_material_summaries(
        _object_items(data.get("referenceMaterials"))
        + _object_items(item.get("matchedMaterials"))
        + _object_items(item.get("candidateMaterials"))
        + _object_items(item.get("sourceRoutedMaterials"))
        + _object_items(appendix_task.get("recommendedMaterials"))
        + [
            material
            for task in _object_items(item.get("appendixTasks"))
            for material in _object_items(task.get("recommendedMaterials"))
        ]
    )
    by_id = {
        str(material.get("id") or "").strip(): material
        for material in context
        if str(material.get("id") or "").strip()
    }
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for material_id in selected_ids:
        if material_id in seen:
            continue
        seen.add(material_id)
        result.append(by_id.get(material_id) or {"id": material_id, "name": material_id})
    return result


def _allowed_technical_material_index(material_scope: dict[str, Any], turbine_model: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope in material_scope.get("readableScopes") or []:
        if not isinstance(scope, dict):
            continue
        folder_path = str(scope.get("path") or "").strip()
        if not folder_path:
            continue
        payload = _run_async(
            technical_material_store.raw_files(
                folder_path=folder_path,
                material_tier=str(scope.get("materialTier") or ""),
                turbine_model=turbine_model,
                recursive=True,
                page=1,
                page_size=1000,
            )
        )
        for raw in payload.get("items") or []:
            if not isinstance(raw, dict):
                continue
            material_id = str(raw.get("id") or "")
            if not material_id or material_id in seen:
                continue
            seen.add(material_id)
            items.append(
                {
                    "id": material_id,
                    "name": str(raw.get("name") or ""),
                    "folderPath": str(raw.get("folderPath") or ""),
                    "materialTier": str(raw.get("materialTier") or scope.get("materialTier") or ""),
                    "hasCleanedWord": bool(raw.get("hasCleanedWord")),
                    "cleanedFileName": str(raw.get("cleanedFileName") or ""),
                    "cleanStatus": str(raw.get("cleanStatus") or ""),
                    "turbineModelLabel": str(raw.get("turbineModelLabel") or ""),
                    "updatedAt": str(raw.get("updatedAt") or ""),
                }
            )
    return items


def _material_index_for_fill(
    project: dict[str, Any],
    plan: dict[str, Any],
    item: dict[str, Any],
    selected_ids: list[str],
    reference_materials: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    _ = project
    context = _dedupe_material_summaries(
        reference_materials
        + _object_items(item.get("sourceRoutedMaterials"))
        + _object_items(plan.get("materialIndex"))
        + _object_items(item.get("candidateMaterials"))
        + _object_items(item.get("matchedMaterials"))
        + [
            material
            for task in _object_items(item.get("appendixTasks"))
            for material in _object_items(task.get("recommendedMaterials"))
        ]
    )
    by_id = {
        _material_key(material): material
        for material in context
        if _material_key(material)
    }
    return _dedupe_material_summaries([
        by_id.get(material_id) or {"id": material_id, "name": material_id}
        for material_id in selected_ids
    ])


async def _downloadable_technical_fill_source_payload(material_id: str) -> tuple[dict[str, Any], str]:
    try:
        payload = await technical_material_store.raw_download_cleaned_content(material_id)
        return payload, "cleaned"
    except Exception:
        payload = await technical_material_store.raw_download_content(material_id)
    mime_type = str(payload.get("mimeType") or "")
    file_name = str(payload.get("fileName") or "").lower()
    allowed_ext = file_name.endswith((".docx", ".xlsx", ".xlsm", ".pdf"))
    allowed_mime = (
        "wordprocessingml" in mime_type
        or "spreadsheetml" in mime_type
        or "ms-excel" in mime_type
        or mime_type == "application/pdf"
    )
    if not allowed_ext and not allowed_mime:
        raise ValueError(f"素材 {material_id} 不是填写 Skill 可读取的 Word/Excel/PDF。")
    return payload, "raw"


async def _downloadable_technical_word_payload(material_id: str) -> tuple[dict[str, Any], str]:
    try:
        payload = await technical_material_store.raw_download_cleaned_content(material_id)
        return payload, "cleaned"
    except Exception:
        payload = await technical_material_store.raw_download_content(material_id)
    mime_type = str(payload.get("mimeType") or "")
    file_name = str(payload.get("fileName") or "")
    if "wordprocessingml" not in mime_type and not file_name.lower().endswith(".docx"):
        raise ValueError(f"素材 {material_id} 没有可用于拼接的 Word 文件或清洗稿。")
    return payload, "raw"


def _ensure_pdf_ocr_sidecar(pdf_path: Path) -> tuple[str, str]:
    """为证书类 PDF 素材生成 OCR 文本 sidecar（{stem}.ocr.txt，与 PDF 同目录缓存复用）。

    返回 (sidecar 路径, 状态)。OCR 未配置/失败时不抛出，仅返回空路径与原因，
    由 manifest 透出，填表侧对无 sidecar 的 PDF 显式报错。
    """
    sidecar_path = pdf_path.with_suffix(".ocr.txt")
    if sidecar_path.exists() and sidecar_path.stat().st_size > 0:
        return str(sidecar_path), "cached"
    try:
        text, _meta = _run_async(
            ocr_service.recognize_text_for_parse(
                file_name=pdf_path.name,
                content=pdf_path.read_bytes(),
                mime_type="application/pdf",
            )
        )
    except PeripheralError as exc:
        if exc.code == "OCR_CONFIG_REQUIRED":
            return "", "skipped: OCR 模型未启用或未配置"
        return "", f"failed: {exc.detail}"
    except Exception as exc:
        return "", f"failed: {exc}"
    if not str(text or "").strip():
        return "", "failed: OCR 识别结果为空"
    sidecar_path.write_text(str(text), encoding="utf-8")
    return str(sidecar_path), "generated"


def _ensure_pdf_ocr_sidecars_batch(pending: list[tuple[dict[str, Any], Path]]) -> int:
    """对本轮收集的待 OCR PDF 批量提交、统一等待并回填 sidecar 状态。

    与 _ensure_pdf_ocr_sidecar 的单份状态语义一致（generated / skipped / failed），
    区别在于全部任务一次性提交给 OCR worker 池并发执行，而不是逐份串行同步等待
    （R09-B07-01）。OCR 未配置/失败不抛出，仅写入各 item 的 ocrStatus。
    返回本轮新生成的 sidecar 数。
    """
    if not pending:
        return 0

    def _mark_all(status: str) -> int:
        for item, _pdf_path in pending:
            item["ocrStatus"] = status
        return 0

    try:
        results = _run_async(
            ocr_service.recognize_texts_for_parse_batch(
                files=[(pdf_path.name, pdf_path.read_bytes(), "application/pdf") for _, pdf_path in pending]
            )
        )
    except PeripheralError as exc:
        if exc.code == "OCR_CONFIG_REQUIRED":
            return _mark_all("skipped: OCR 模型未启用或未配置")
        return _mark_all(f"failed: {exc.detail}")
    except Exception as exc:
        return _mark_all(f"failed: {exc}")

    generated = 0
    for (item, pdf_path), result in zip(pending, results, strict=True):
        if isinstance(result, BaseException):
            if isinstance(result, PeripheralError) and result.code == "OCR_CONFIG_REQUIRED":
                item["ocrStatus"] = "skipped: OCR 模型未启用或未配置"
            elif isinstance(result, PeripheralError):
                item["ocrStatus"] = f"failed: {result.detail}"
            else:
                item["ocrStatus"] = f"failed: {result}"
            continue
        text, _meta = result
        if not str(text or "").strip():
            item["ocrStatus"] = "failed: OCR 识别结果为空"
            continue
        sidecar_path = pdf_path.with_suffix(".ocr.txt")
        # 批量等待期间其他任务可能已补齐同一 sidecar，缓存优先不覆写
        if not (sidecar_path.exists() and sidecar_path.stat().st_size > 0):
            sidecar_path.write_text(str(text), encoding="utf-8")
        item["ocrTextPath"] = str(sidecar_path)
        item["ocrStatus"] = "generated"
        generated += 1
    return generated


def _prepare_material_index_files(
    material_index: list[dict[str, Any]],
    work_dir: Path,
    *,
    cache_dir: Path | None = None,
    limit: int = 240,
    ocr_pdf: bool = False,
    ocr_budget: int = 12,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    cache_dir = cache_dir or (work_dir / "material_index")
    # 两阶段：先逐份串行下载落地（缓存命中秒过），收集本轮需 OCR 的 PDF；
    # 再对收集列表批量提交、统一等待回填，避免逐份同步阻塞 OCR worker 池。
    pending_ocr: list[tuple[dict[str, Any], Path]] = []
    for material in material_index[:limit]:
        item = dict(material)
        material_id = str(item.get("id") or item.get("materialId") or "").strip()
        if not material_id:
            prepared.append(item)
            continue
        awaitable = _downloadable_technical_fill_source_payload(material_id)
        try:
            payload, source_kind = _run_async(awaitable)
        except Exception:
            if hasattr(awaitable, "close"):
                awaitable.close()
            prepared.append(item)
            continue
        file_name = _safe_filename(
            str(item.get("cleanedFileName") or payload.get("fileName") or item.get("name") or f"{material_id}.docx"),
            f"{material_id}.docx",
        )
        target_path = cache_dir / f"{material_id}-{file_name}"
        if not target_path.exists():
            minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
        item.update(
            {
                "path": str(target_path),
                "sourceKind": source_kind,
                "fileName": target_path.name,
            }
        )
        if ocr_pdf and target_path.suffix.lower() == ".pdf":
            has_cache = target_path.with_suffix(".ocr.txt").exists()
            if has_cache:
                sidecar_path, ocr_status = _ensure_pdf_ocr_sidecar(target_path)
                if sidecar_path:
                    item["ocrTextPath"] = sidecar_path
                item["ocrStatus"] = ocr_status
            elif len(pending_ocr) < ocr_budget:
                pending_ocr.append((item, target_path))
            else:
                item["ocrStatus"] = _OCR_BUDGET_SKIPPED_STATUS
        prepared.append(item)
    _ensure_pdf_ocr_sidecars_batch(pending_ocr)
    return prepared


# 单轮 OCR 配额跳过的状态文案。填表任务内部按轮循环补齐（见
# _prepare_fill_materials_with_ocr），一轮内仍受 ocr_budget 约束。
_OCR_BUDGET_SKIPPED_STATUS = "skipped: 本次运行 OCR 配额已用完，缓存后续运行补齐"
# 补齐循环兜底轮数：一轮三路最多各新 OCR ocr_budget 份，正常项目 2-3 轮内收敛。
_AI_FILL_OCR_PREP_MAX_ROUNDS = 10


def _prepare_fill_materials_with_ocr(
    material_index: list[dict[str, Any]],
    reference_materials: list[dict[str, Any]],
    recommended_materials: list[dict[str, Any]],
    work_dir: Path,
    *,
    cache_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """在本次填表任务内部循环补齐 PDF OCR sidecar，使一次点击即可用全量素材。

    单轮准备仍受 ocr_budget 约束（排队与并发由 OcrTask worker 保证，配额只是
    单轮时间封顶）；sidecar 落共享缓存跨轮/跨缺口复用，已就绪的素材秒过。
    循环到没有"配额跳过"的 PDF 为止，之后填表只跑一次。
    防死循环：限轮数，且某轮就绪数零增长即停止（OCR 失败为 failed 状态，
    不计入跳过，不会导致空转）。
    """
    prev_ready = -1
    for _round in range(_AI_FILL_OCR_PREP_MAX_ROUNDS):
        material_index = _prepare_material_index_files(
            material_index,
            work_dir,
            cache_dir=cache_dir,
            ocr_pdf=True,
        )
        reference_materials = _prepare_material_index_files(
            reference_materials,
            work_dir,
            cache_dir=cache_dir,
            ocr_pdf=True,
        )
        recommended_materials = _prepare_material_index_files(
            recommended_materials,
            work_dir,
            cache_dir=cache_dir,
            ocr_pdf=True,
        )
        prepared_lists = (material_index, reference_materials, recommended_materials)
        deferred = sum(
            1
            for prepared in prepared_lists
            for item in prepared
            if str(item.get("ocrStatus") or "") == _OCR_BUDGET_SKIPPED_STATUS
        )
        ready = sum(
            1
            for prepared in prepared_lists
            for item in prepared
            if str(item.get("ocrTextPath") or "").strip()
        )
        if deferred == 0 or ready <= prev_ready:
            break
        prev_ready = ready
    return material_index, reference_materials, recommended_materials


def _prepare_word_blank_source(blank_source: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    source = dict(blank_source)
    for key in ("docxPath", "path", "workspacePath"):
        candidate = Path(str(source.get(key) or ""))
        if candidate.exists() and candidate.suffix.lower() == ".docx":
            source["docxPath"] = str(candidate)
            return source

    material_id = str(source.get("materialId") or source.get("id") or "").strip()
    if not material_id:
        raise ValueError("待填写 Word 缺少 materialId/docxPath，无法准备模板。")
    payload, source_kind = _run_async(_downloadable_technical_word_payload(material_id))
    file_name = _safe_filename(
        str(source.get("cleanedFileName") or payload.get("fileName") or source.get("title") or f"{material_id}.docx"),
        f"{material_id}.docx",
    )
    if not file_name.lower().endswith(".docx"):
        file_name = f"{Path(file_name).stem}.docx"
    target_path = work_dir / "blank_source" / f"{material_id}-{file_name}"
    if not target_path.exists():
        minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
    source.update(
        {
            "docxPath": str(target_path),
            "path": str(target_path),
            "sourceKind": source_kind,
            "fileName": target_path.name,
        }
    )
    return source


def _field_key(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("key") or field.get("label") or field.get("title") or "").strip()


def _field_summary(field: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(field.get("id") or field.get("key") or field.get("label") or ""),
        "label": str(field.get("label") or field.get("title") or field.get("keyEntity") or field.get("id") or ""),
        "value": str(field.get("value") or field.get("keyValue") or ""),
        "sourceFile": str(field.get("sourceFile") or ""),
        "evidence": str(field.get("evidence") or ""),
        "evidenceLocation": str(field.get("evidenceLocation") or ""),
    }


def _parse_fields_for_fill(appendix_task: dict[str, Any], task: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = _object_items(appendix_task.get("availableParseFields")) + _object_items(appendix_task.get("fields"))
    requested = _string_items(data.get("parseFieldIds"))
    blank_source = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
    blank_id = str(blank_source.get("id") or "").strip()
    requested_field_ids = [item for item in requested if item != blank_id]
    if not requested_field_ids:
        return [_field_summary(field) for field in candidates]

    by_key: dict[str, dict[str, Any]] = {}
    for field in candidates:
        key = _field_key(field)
        if key:
            by_key[key] = field
    result: list[dict[str, Any]] = []
    for field_id in requested_field_ids:
        result.append(_field_summary(by_key.get(field_id) or {"id": field_id, "label": field_id}))
    return result


def _run_local_skill_runner(runner: Path, manifest_path: Path, schema_version: str) -> dict[str, Any]:
    if not runner.exists():
        raise RuntimeError(f"Skill runner 不存在：{runner}")
    result = subprocess.run(
        [sys.executable, str(runner), "--manifest", str(manifest_path), "--response", "summary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
        raise RuntimeError(f"Skill runner 执行失败（{result.returncode}）：{detail}")
    payload = json.loads(result.stdout or "{}")
    payload.setdefault("schema_version", schema_version)
    payload.setdefault(
        "opencodeOutput",
        {
            "status": "received",
            "sessionId": str(manifest_path),
            "providerId": "local-skill",
            "modelId": runner.parent.parent.name,
            "receivedAt": _now_iso(),
            "parts": [{"type": "text", "text": result.stdout.strip()}],
        },
    )
    return payload


def _build_table_filler_prompt(manifest_path: Path) -> str:
    return f"""
Use the {TECHNICAL_TABLE_FILL_SKILL_NAME} skill.

你现在在做技术标缺口项 AI 填写。后端已经准备好 manifest，其中包含待填写空表/Word、人工指定的参考素材、解析字段和输出路径。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径：

s4fill {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def run_technical_table_filler_skill(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    prompt = _build_table_filler_prompt(manifest_path)
    try:
        return OpencodeClient().run_bid_tech_table_filler_with_trace(
            prompt,
            stream_callback=(
                (lambda details: progress_callback("table_filler_delta", details))
                if progress_callback
                else None
            ),
            early_tool_command="s4fill",
        )
    except Exception:
        return _run_local_skill_runner(TABLE_FILL_RUNNER, manifest_path, TABLE_FILL_SCHEMA_VERSION)


def run_technical_word_placeholder_filler_skill(manifest_path: Path) -> dict[str, Any]:
    """正文填写：直接跑本地脚本。

    脚本是纯确定性查表（占位符原文 → 事实表字段），agent 在这条链路上只做一件事——
    转发一条 shell 命令，起会话的开销远大于执行本身。
    """
    return _run_local_skill_runner(WORD_FILL_RUNNER, manifest_path, WORD_FILL_SCHEMA_VERSION)


def _numeric_report_value(report: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = report.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        if isinstance(value, str) and value.strip().isdigit():
            return max(0, int(value.strip()))
    return 0


def _merge_fill_sidecar_report(result: dict[str, Any], output_file: Path) -> dict[str, Any]:
    sidecar = output_file.with_suffix(".fill_report.json")
    if not sidecar.exists():
        return result
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return result
    if not isinstance(data, dict):
        return result
    merged = dict(result)
    for key in ("evidenceRefs", "filledFieldDetails", "unfilledFieldDetails", "unfilledFields"):
        sidecar_value = data.get(key)
        current_value = merged.get(key)
        if isinstance(sidecar_value, list) and (
            not isinstance(current_value, list) or len(sidecar_value) > len(current_value)
        ):
            merged[key] = sidecar_value
    sidecar_report = data.get("fillReport")
    if isinstance(sidecar_report, dict):
        current_report = merged.get("fillReport") if isinstance(merged.get("fillReport"), dict) else {}
        merged["fillReport"] = {**current_report, **sidecar_report}
    return merged


def _build_fill_quality_report(result: dict[str, Any], *, output_exists: bool) -> dict[str, Any]:
    report = result.get("fillReport") if isinstance(result.get("fillReport"), dict) else {}
    unfilled_fields = result.get("unfilledFields") if isinstance(result.get("unfilledFields"), list) else []
    evidence_refs = result.get("evidenceRefs") if isinstance(result.get("evidenceRefs"), list) else []
    failed_target_count = _numeric_report_value(report, "failedTargetCount")
    filled_count = _numeric_report_value(
        report,
        "filledFieldCount",
        "filledPlaceholderCount",
        "filledCellCount",
    )
    unfilled_count = max(
        _numeric_report_value(
            report,
            "unfilledFieldCount",
            "unfilledPlaceholderCount",
            "unfilledCellCount",
            "residualPlaceholderCount",
        ),
        len(unfilled_fields),
    )
    expected_count = _numeric_report_value(
        report,
        "targetFieldCount",
        "targetPlaceholderCount",
        "fieldCount",
        "placeholderCount",
        "totalFieldCount",
    )
    if expected_count <= 0:
        expected_count = filled_count + unfilled_count
    coverage_rate = filled_count / expected_count if expected_count else 0.0
    evidence_chain_rate = min(1.0, len(evidence_refs) / filled_count) if filled_count else 0.0
    semantic_check_count = _numeric_report_value(report, "semanticCheckCount")
    semantic_failed_count = _numeric_report_value(report, "semanticFailedCount")
    semantic_rate_value = report.get("semanticValidationRate")
    try:
        semantic_validation_rate = float(semantic_rate_value) if semantic_rate_value is not None else None
    except (TypeError, ValueError):
        semantic_validation_rate = None
    correctness_rate = (
        min(evidence_chain_rate, semantic_validation_rate)
        if semantic_check_count > 0 and semantic_validation_rate is not None
        else evidence_chain_rate
    )
    completeness_rate = 1.0 if output_exists and unfilled_count == 0 and coverage_rate >= 0.85 else min(coverage_rate, 1.0 if output_exists else 0.0)
    thresholds = {
        "coverageRate": 0.85,
        "correctnessRate": 0.85,
        "completenessRate": 0.85,
    }
    status = "passed" if (
        coverage_rate >= thresholds["coverageRate"]
        and correctness_rate >= thresholds["correctnessRate"]
        and completeness_rate >= thresholds["completenessRate"]
        and unfilled_count == 0
        and semantic_failed_count == 0
        and failed_target_count == 0
        and output_exists
    ) else "needs_review"
    return {
        "schemaVersion": "bid-fill-quality-report-v1",
        "status": status,
        "coverageRate": round(coverage_rate, 4),
        "correctnessRate": round(correctness_rate, 4),
        "completenessRate": round(completeness_rate, 4),
        "evidenceChainRate": round(evidence_chain_rate, 4),
        "expectedFieldCount": expected_count,
        "filledFieldCount": filled_count,
        "unfilledFieldCount": unfilled_count,
        "evidenceRefCount": len(evidence_refs),
        "residualPlaceholderCount": unfilled_count,
        "semanticCheckCount": semantic_check_count,
        "semanticFailedCount": semantic_failed_count,
        "semanticValidationRate": round(semantic_validation_rate, 4) if semantic_validation_rate is not None else None,
        "failedTargetCount": failed_target_count,
        "thresholds": thresholds,
    }


def _path_from_result(value: Any, *, base_dir: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _fill_output_files(result: dict[str, Any], resolved_output: Path) -> list[Path]:
    raw_files = result.get("outputFiles")
    paths: list[Path] = []
    if isinstance(raw_files, list):
        for item in raw_files:
            text = str(item or "").strip()
            if not text:
                continue
            path = _path_from_result(text, base_dir=resolved_output.parent)
            if path.suffix.lower() == ".docx":
                paths.append(path)
    if not paths and resolved_output.suffix.lower() == ".docx":
        paths.append(resolved_output)

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _target_result_for_output(result: dict[str, Any], output_file: Path, index: int) -> dict[str, Any]:
    target_results = _object_items(result.get("targetResults"))
    output_key = str(output_file)
    for target in target_results:
        target_output = str(target.get("outputFile") or "").strip()
        if target_output and str(_path_from_result(target_output, base_dir=output_file.parent)) == output_key:
            return dict(target)
    if 0 <= index - 1 < len(target_results):
        return dict(target_results[index - 1])
    return {
        "schema_version": result.get("schema_version") or result.get("schemaVersion") or TABLE_FILL_SCHEMA_VERSION,
        "outputFile": str(output_file),
        "unfilledFields": list(result.get("unfilledFields") or []),
        "evidenceRefs": list(result.get("evidenceRefs") or []),
        "fillReport": dict(result.get("fillReport") or {}),
        "filledAt": result.get("filledAt") or _now_iso(),
    }


def _build_ai_fill_artifacts(
    *,
    project_id: str,
    base_artifact_id: str,
    gap_id: str,
    task_id: str,
    item_title: str,
    skill_name: str,
    result: dict[str, Any],
    output_files: list[Path],
    batch_report_path: Path,
    created_at: str,
    operator: str,
    reference_materials: list[dict[str, Any]],
    recommended_materials: list[dict[str, Any]],
    parse_fields: list[dict[str, Any]],
    tender_documents: list[dict[str, Any]],
    manifest_path: Path,
    s7_ready: bool,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> list[dict[str, Any]]:
    batch_count = len(output_files)
    artifacts: list[dict[str, Any]] = []
    for index, output_file in enumerate(output_files, start=1):
        target_result = _target_result_for_output(result, output_file, index)
        target_result = _merge_fill_sidecar_report(target_result, output_file)
        target_report = target_result.get("fillReport") if isinstance(target_result.get("fillReport"), dict) else {}
        artifact_id = base_artifact_id if batch_count == 1 else f"{base_artifact_id}-{index:03d}"
        title = str(target_report.get("title") or item_title or output_file.stem)
        quality_report = _build_fill_quality_report(target_result, output_exists=output_file.exists())
        artifact_s7_ready = s7_ready and quality_report["status"] == "passed"
        artifacts.append(
            {
                "id": artifact_id,
                "source": "ai_fill",
                "skill": skill_name,
                "gapId": gap_id,
                "fillTaskId": task_id,
                "title": title,
                "fileName": output_file.name,
                "path": str(output_file),
                "createdAt": created_at,
                "operator": operator,
                "unfilledFields": list(target_result.get("unfilledFields") or []),
                "evidenceRefs": list(target_result.get("evidenceRefs") or []),
                "fillReport": target_report,
                "qualityReport": quality_report,
                "referenceMaterialIds": [
                    _material_key(material)
                    for material in reference_materials
                    if _material_key(material)
                ],
                "referenceMaterials": reference_materials,
                "recommendedMaterials": recommended_materials,
                "parseFields": parse_fields,
                "tenderDocuments": [
                    {
                        "id": str(document.get("id") or ""),
                        "name": str(document.get("name") or ""),
                        "sourceType": str(document.get("sourceType") or "project_tender_document"),
                    }
                    for document in tender_documents
                ],
                "manifestPath": str(manifest_path),
                "batchReportPath": str(batch_report_path) if batch_count > 1 else "",
                "batchTargetIndex": index if batch_count > 1 else 0,
                "batchTargetCount": batch_count if batch_count > 1 else 0,
                "opencodeOutput": result.get("opencodeOutput") or {},
                "onlyoffice": technical_gap_artifact_onlyoffice_payload(
                    project_id=project_id,
                    artifact_id=artifact_id,
                    file_name=output_file.name,
                    browser_base_url=browser_base_url,
                    onlyoffice_base_url=onlyoffice_base_url,
                ),
                "s7Ready": artifact_s7_ready,
                "qualityGate": "auto_passed" if artifact_s7_ready else "needs_review",
                "confirmed": artifact_s7_ready,
            }
        )
    return artifacts


def _compact_resolved_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    reference_materials = [
        {
            "id": _material_key(material),
            "name": str(material.get("name") or material.get("title") or material.get("fileName") or ""),
            "folderPath": str(material.get("folderPath") or ""),
            "materialTier": str(material.get("materialTier") or ""),
        }
        for material in _object_items(artifact.get("referenceMaterials"))
        if _material_key(material)
    ]
    return {
        "id": artifact.get("id"),
        "source": artifact.get("source"),
        "skill": artifact.get("skill"),
        "gapId": artifact.get("gapId"),
        "fillTaskId": artifact.get("fillTaskId"),
        "title": artifact.get("title"),
        "fileName": artifact.get("fileName"),
        "path": artifact.get("path"),
        "createdAt": artifact.get("createdAt"),
        "operator": artifact.get("operator"),
        "unfilledFields": list(artifact.get("unfilledFields") or []),
        "evidenceRefs": list(artifact.get("evidenceRefs") or []),
        "fillReport": artifact.get("fillReport") or {},
        "qualityReport": artifact.get("qualityReport") or {},
        "referenceMaterialIds": _string_items(
            artifact.get("referenceMaterialIds")
            or [_material_key(material) for material in reference_materials]
        ),
        "referenceMaterials": reference_materials,
        "tenderDocuments": _object_items(artifact.get("tenderDocuments")),
        "manifestPath": artifact.get("manifestPath"),
        "batchReportPath": artifact.get("batchReportPath") or "",
        "batchTargetIndex": artifact.get("batchTargetIndex") or 0,
        "batchTargetCount": artifact.get("batchTargetCount") or 0,
        "onlyoffice": artifact.get("onlyoffice") or {},
        "s7Ready": artifact.get("s7Ready", True),
        "qualityGate": str(artifact.get("qualityGate") or ""),
        "confirmed": bool(artifact.get("confirmed")),
        "confirmedAt": str(artifact.get("confirmedAt") or ""),
        "confirmedBy": str(artifact.get("confirmedBy") or ""),
        "referenceMaterialCount": len(artifact.get("referenceMaterials") or []),
        "tenderDocumentCount": len(artifact.get("tenderDocuments") or []),
        "recommendedMaterialCount": len(artifact.get("recommendedMaterials") or []),
    }


def _replace_resolved_artifacts(
    current: Any,
    artifacts: list[dict[str, Any]],
    *,
    fill_task_id: str,
    skill_name: str,
) -> list[dict[str, Any]]:
    compact_artifacts = [_compact_resolved_artifact(artifact) for artifact in artifacts]
    compact_ids = {str(artifact.get("id") or "").strip() for artifact in compact_artifacts}
    compact_names = {str(artifact.get("fileName") or "").strip() for artifact in compact_artifacts}
    kept: list[dict[str, Any]] = []
    for item in _object_items(current):
        item_id = str(item.get("id") or "").strip()
        item_task_id = str(item.get("fillTaskId") or "").strip()
        item_skill = str(item.get("skill") or "").strip()
        item_file_name = str(item.get("fileName") or "").strip()
        if item_id and item_id in compact_ids:
            continue
        if fill_task_id and item_task_id == fill_task_id:
            continue
        if not item_task_id and item_skill == skill_name and item_file_name in compact_names:
            continue
        kept.append(_compact_resolved_artifact(item))
    kept.extend(compact_artifacts)
    return kept[-24:]


def run_technical_ai_fill_for_gap(
    project: dict[str, Any],
    gap_id: str,
    data: dict[str, Any],
    *,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> dict[str, Any]:
    gap_state = project.get("gap_state") or {}
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    project_fact_table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
    project_fact_table = enrich_fact_table_with_spec_columns(project_fact_table, gap_state)
    normalize_technical_gap_plan_fill_task_skills(plan)
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    item = next((entry for entry in items if str(entry.get("id") or "") == gap_id), None)
    if item is None:
        raise KeyError(gap_id)

    fill_tasks = item.get("fillTasks") if isinstance(item.get("fillTasks"), list) else []
    requested_task_id = str(data.get("fillTaskId") or "")
    task = next(
        (
            entry
            for entry in fill_tasks
            if not requested_task_id or str(entry.get("id") or "") == requested_task_id
        ),
        None,
    )
    if task is None:
        raise ValueError("当前缺口没有可执行的 AI 填写任务。")

    skill_name = str(task.get("skill") or TECHNICAL_TABLE_FILL_SKILL_NAME)
    appendix_task = _appendix_task_for_fill(item, task)
    blank_source = dict(task.get("blankSource") or {}) if isinstance(task.get("blankSource"), dict) else {}
    # 正文填写只走清单定位（占位符原文 → 事实表字段），素材既不参与定位也不提供取值，
    # 因此不备素材、不跑 OCR、不起 agent；附表填写仍按原路准备素材。
    is_word_fill = skill_name == TECHNICAL_WORD_FILL_SKILL_NAME
    if is_word_fill:
        require_spec_driven_fact_table(project_fact_table)
    selected_reference_ids = [] if is_word_fill else _selected_reference_material_ids(item, appendix_task, data)
    reference_materials = (
        [] if is_word_fill else _reference_materials_for_fill(item, appendix_task, data, selected_reference_ids)
    )
    blank_source_id = str(blank_source.get("id") or blank_source.get("materialId") or "").strip()
    reference_materials = [
        material
        for material in reference_materials
        if str(material.get("id") or material.get("materialId") or "").strip() != blank_source_id
    ]
    recommended_materials = list(reference_materials)
    material_index = (
        []
        if is_word_fill
        else _material_index_for_fill(
            project,
            plan,
            item,
            selected_reference_ids,
            reference_materials,
        )
    )
    parse_fields = _parse_fields_for_fill(appendix_task, task, data)
    tender_documents = _project_tender_documents_for_fill(project, appendix_task)
    source_routing = appendix_task.get("sourceRouting") if isinstance(appendix_task.get("sourceRouting"), dict) else {}
    if source_routing.get("useTenderParseFields") and not tender_documents:
        raise RuntimeError("附表填写规则要求读取招标文件，但项目当前没有可读取的原始文件或全文解析结果，请重新解析招标文件。")
    work_dir = _project_dir(project) / "s4_gap_workdir" / "ai_fill" / gap_id
    work_dir.mkdir(parents=True, exist_ok=True)
    shared_material_cache_dir = _project_dir(project) / "s4_gap_workdir" / "ai_fill" / "_material_index_cache"
    # PDF 素材（认证证书等）三路都做 OCR sidecar：证书 PDF 通常只经 materialIndex
    # 关键词选源进入填表。sidecar 落在共享缓存跨缺口复用。
    # referenceMaterials/recommendedMaterials 只带素材库虚拟目录路径（如
    # "技术标/通用素材/.../证书.pdf"），不是本地可读路径；只下载过 material_index，
    # 这两路（尤其是路由命中的认证证书 PDF）从未落地过，table-filler 拿到手时
    # material_path() 解析不出真实文件，会静默丢弃——即使上游路由完全正确。
    # 单轮准备有 OCR 配额上限，这里在任务内部循环补齐，保证一次点击用全量素材。
    if not is_word_fill:
        material_index, reference_materials, recommended_materials = _prepare_fill_materials_with_ocr(
            material_index,
            reference_materials,
            recommended_materials,
            work_dir,
            cache_dir=shared_material_cache_dir,
        )
    artifact_task_id = _safe_filename(str(task.get("id") or "task"), "task")
    artifact_id = f"ART-{gap_id}-{artifact_task_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    output_stem = _safe_filename(str(item.get("title") or gap_id), gap_id)
    if len(fill_tasks) > 1:
        output_suffix = _safe_filename(str(task.get("id") or blank_source_id or "task"), "task")
        output_file = work_dir / f"{output_stem}_{output_suffix}_AI填写.docx"
    else:
        output_file = work_dir / f"{output_stem}_AI填写.docx"
    manifest_path = work_dir / ("word_fill_input.json" if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME else "table_fill_input.json")
    if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME:
        blank_source = _prepare_word_blank_source(blank_source, work_dir)
    manifest = {
        "schemaVersion": WORD_FILL_SCHEMA_VERSION if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME else TABLE_FILL_SCHEMA_VERSION,
        "projectId": str(project.get("id") or ""),
        "projectName": str(project.get("name") or ""),
        "projectIdentity": project.get("identity") or {},
        "customerName": str(project.get("customerName") or ""),
        "projectTurbineModel": project_turbine_model(project),
        "gapId": gap_id,
        "fillTaskId": str(task.get("id") or ""),
        "title": str(item.get("title") or ""),
        "gapItem": {
            "id": gap_id,
            "number": str(item.get("number") or item.get("section") or ""),
            "title": str(item.get("title") or ""),
            "decision": str(item.get("decision") or ""),
            "usage": str(item.get("usage") or ""),
            "gapReason": str(item.get("gapReason") or item.get("reason") or ""),
            "materialScope": item.get("materialScope") or {},
            "turbineCheck": item.get("turbineCheck") or {},
        },
        "appendixTask": {
            "id": str(appendix_task.get("id") or ""),
            "title": str(appendix_task.get("title") or ""),
            "sourceFile": str(appendix_task.get("sourceFile") or ""),
            "docxPath": str(appendix_task.get("docxPath") or ""),
            "workspacePath": str(appendix_task.get("workspacePath") or ""),
            "rowCount": appendix_task.get("rowCount") or 0,
            "sourceRouting": appendix_task.get("sourceRouting") if isinstance(appendix_task.get("sourceRouting"), dict) else {},
            "availableParseFields": parse_fields,
            "tenderDocuments": tender_documents,
        },
        "blankSource": blank_source,
        "referenceMaterialIds": selected_reference_ids,
        "referenceMaterials": reference_materials,
        "projectFactTable": project_fact_table,
        "materialIndex": material_index,
        "recommendedMaterials": recommended_materials,
        "parseFieldIds": _string_items(data.get("parseFieldIds")),
        "parseFields": parse_fields,
        "tenderDocuments": tender_documents,
        "constraints": str(data.get("constraints") or ""),
        "operator": str(data.get("operator") or "当前用户"),
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if skill_name == TECHNICAL_WORD_FILL_SKILL_NAME:
        result = run_technical_word_placeholder_filler_skill(manifest_path)
    else:
        result = run_technical_table_filler_skill(manifest_path)
    resolved_output = Path(str(result.get("outputFile") or output_file))
    if not resolved_output.exists():
        raise RuntimeError(f"AI 填写未生成输出文件：{resolved_output}")
    output_files = _fill_output_files(result, resolved_output)
    if not output_files:
        raise RuntimeError("AI 填写未生成可预览 Word 输出文件。")
    missing_outputs = [path for path in output_files if not path.exists()]
    if missing_outputs:
        raise RuntimeError(f"AI 填写输出文件不存在：{missing_outputs[0]}")

    if len(output_files) == 1:
        result = _merge_fill_sidecar_report(result, output_files[0])
    quality_report = _build_fill_quality_report(
        result,
        output_exists=bool(output_files) and all(path.exists() for path in output_files),
    )
    created_at = _now_iso()
    operator = str(data.get("operator") or "当前用户")
    artifacts = _build_ai_fill_artifacts(
        project_id=str(project.get("id") or ""),
        base_artifact_id=artifact_id,
        gap_id=gap_id,
        task_id=str(task.get("id") or ""),
        item_title=str(item.get("title") or resolved_output.stem),
        skill_name=skill_name,
        result=result,
        output_files=output_files,
        batch_report_path=resolved_output,
        created_at=created_at,
        operator=operator,
        reference_materials=reference_materials,
        recommended_materials=recommended_materials,
        parse_fields=parse_fields,
        tender_documents=tender_documents,
        manifest_path=manifest_path,
        s7_ready=quality_report["status"] == "passed",
        browser_base_url=browser_base_url,
        onlyoffice_base_url=onlyoffice_base_url,
    )
    artifact = artifacts[0]

    task["status"] = "completed"
    task["outputArtifactId"] = artifact["id"]
    task["outputArtifactIds"] = [entry["id"] for entry in artifacts]
    task["completedAt"] = created_at
    item["status"] = "resolved" if quality_report["status"] == "passed" else "needs_input"
    item["qualityStatus"] = quality_report["status"]
    item["qualityReport"] = quality_report
    item["resolvedArtifacts"] = _replace_resolved_artifacts(
        item.get("resolvedArtifacts"),
        artifacts,
        fill_task_id=str(task.get("id") or ""),
        skill_name=skill_name,
    )
    item["resolvedAt"] = created_at
    item["resolvedSource"] = artifact["fileName"] if len(artifacts) == 1 else f"{len(artifacts)} 份AI填写产物"
    item["reviewNotes"] = list(item.get("reviewNotes") or [])
    unfilled_count = len(result.get("unfilledFields") or [])
    if unfilled_count:
        item["reviewNotes"].append(f"AI 填写仍有未填字段：{unfilled_count} 项")
    if quality_report["status"] != "passed":
        item["reviewNotes"].append("AI 填写质量验收未达标，请人工复核或补充事实表后重填。")

    plan["updatedAt"] = created_at
    plan["summary"] = summarize_technical_gap_plan(plan)
    gap_state["plan"] = plan
    gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
    gap_state["submittedForReview"] = False
    gap_state["reviewConfirmed"] = False
    gap_state["reviewedAt"] = ""
    return {"item": item, "artifact": artifact, "artifacts": artifacts, "gapPlan": plan}
