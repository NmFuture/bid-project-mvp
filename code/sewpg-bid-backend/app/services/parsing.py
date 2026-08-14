from __future__ import annotations

import json
import copy
import logging
import re
import shutil
# 模块符号保留：facade re-export（parsing-01 硬约束），既有测试经本模块 patch subprocess.run。
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.config import settings
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.business_section_tree import write_business_section_tree
from app.services.business_template_extractor import run_business_template_extractor
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
# 模块符号保留：实现已迁至 parse_extract，既有测试经本模块引用 nav_to_text。
from app.services.document_nav import nav_to_text
from app.services.docling_engine import DoclingParseEngine
# 模块符号保留：facade re-export（parsing-01 硬约束），外部调用方经本模块取 ocr_service。
from app.services.ocr_service import IMAGE_SUFFIXES, ocr_service
from app.services.agent_engine.concurrency import AGENT_CONCURRENCY_BUDGET
from app.services.agent_engine.factory import AgentEngineFactory
# 模块符号保留：既有测试经它 patch 类方法（默认引擎实际经 AgentEngineFactory 创建）。
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.agent_engine.orchestrator import AgentOrchestrator
# 拆分搬迁（parsing-01）：通用件与文本提取实现已移至 parse_common/parse_extract，
# 此处 re-export 保持 app.services.parsing.<符号> 可解析、可 patch。
from app.services.parse_common import (
    _normalize_text,
    _raise_if_parse_cancelled,
    _run_coroutine_blocking,
    _run_with_progress_heartbeat,
    parsed_appendix_path,
    parsed_project_dir,
)
from app.services.parse_extract import (
    WORD_NAMESPACE,
    _append_ocr_blocks_to_document_nav,
    _finalize_loaded_document_nav,
    _merge_document_nav_quality,
    _ocr_business_pdf_pages,
    _ocr_fallback_text,
    _parse_pdf_with_document_engine,
    extract_docx_text,
    extract_pdf_text,
)
# parsing-01 第 2 步搬迁：商务字段/资格/承诺/评分/契约总装实现已移至 parse_business_fields，门面 re-export。
from app.services.parse_business_fields import (
    BIDDER_INSTRUCTION_TABLE_TITLE,
    BID_DEADLINE_CONTEXT,
    BID_DEADLINE_DATE_PATTERN,
    BUSINESS_CORE_PROJECT_FIELDS,
    BUSINESS_PROJECT_FACT_FIELD_SPECS,
    BUSINESS_RESPONSE_FIELDS,
    CLAUSE_PATTERN,
    COMMERCIAL_REJECTION_KEYWORDS,
    COMMITMENT_DOC_KEYWORDS,
    COMMITMENT_GENERATION_HINTS,
    COMMITMENT_IGNORE_KEYWORDS,
    COMMITMENT_NON_REQUIREMENT_TITLE_HINTS,
    COMMITMENT_REQUIREMENT_CONTEXT_HINTS,
    COMMITMENT_REQUIREMENT_FIELDS,
    COMMITMENT_SEMANTIC_REVIEW_MAX_ITEMS,
    COMMITMENT_TOPIC_KEYWORDS,
    COMMITMENT_TOPIC_TITLE_KEYWORDS,
    FieldSpec,
    LABEL_VALUE_PATTERN,
    LEADING_NUMBER_PATTERN,
    MARKDOWN_TABLE_LINE_PATTERN,
    OPENING_TIME_CONTEXT,
    PROJECT_BASIC_FIELDS,
    QUALIFICATION_EXCLUDE_KEYWORDS,
    QUALIFICATION_REQUIRED_CUES,
    QUALIFICATION_SECTION_ANCHORS,
    QUALIFICATION_STOP_ANCHORS,
    QUALIFICATION_SUPPORT_FIELDS,
    SCOPE_PATTERN,
    SCORING_SCORE_PATTERN,
    TECHNICAL_COMMITMENT_KEYWORDS,
    _align_commitment_letters_with_existing_templates,
    _append_commitment_clue,
    _append_commitment_letter,
    _append_semantic_commitment_candidate,
    _block_number,
    _build_business_commitment_analysis,
    _build_business_coverage,
    _build_business_project_basics,
    _build_business_project_fact_fields,
    _build_business_requirement_presence,
    _build_business_response_fields,
    _build_commitment_requirement_fields,
    _build_commitment_semantic_review_prompt,
    _build_qualification_requirements,
    _build_qualification_support_fields,
    _business_core_field_score,
    _business_field_from_item,
    _business_presence_from_keywords,
    _business_project_name_from_structured,
    _business_project_value_usable,
    _business_tenderer_name_from_structured,
    _clean,
    _collect_markdown_table,
    _commitment_alignment_topics_for_template,
    _commitment_decision_action,
    _commitment_decision_for_item,
    _commitment_review_signature,
    _commitment_template_can_cover_letter,
    _commitment_template_match_score,
    _commitment_text,
    _contains_commitment_requirement_context,
    _copy_meta_fields,
    _document_text_lines,
    _docx_table_after_bidder_instruction_anchor,
    _empty_business_field,
    _extract_bidder_instruction_rows,
    _extract_commercial_rejection_clauses,
    _extract_commitment_trigger_phrase,
    _extract_docx_core_candidate_items,
    _extract_markdown_scoring,
    _extract_qualification_requirements_from_documents,
    _filter_business_scoring,
    _find_business_item,
    _find_commitment_items,
    _is_bid_deadline_relative_context,
    _is_bidder_instruction_title_anchor,
    _is_commitment_doc_required,
    _is_commitment_item_ignored,
    _is_docx_source,
    _is_markdown_separator_row,
    _is_normalized_bid_deadline,
    _is_qualification_anchor,
    _is_qualification_stop,
    _is_reference_only_value,
    _is_technical_commitment_item,
    _line_has_explicit_commitment_obligation,
    _looks_like_bare_commitment_title,
    _looks_like_qualification_intro_line,
    _looks_like_qualification_requirement,
    _looks_like_scope_heading,
    _looks_like_section_heading,
    _merge_business_scoring,
    _new_docx_candidate_item,
    _normalize_bid_deadline,
    _normalize_commitment_title_by_topic,
    _normalize_commitment_title_prefix,
    _normalize_commitment_topic,
    _normalize_core_field_value,
    _normalize_qualification_content,
    _normalize_qualification_scope,
    _normalized_business_match_text,
    _parse_bidder_instruction_rows,
    _parse_markdown_scoring_rows,
    _parse_markdown_table_row,
    _preferred_commitment_title,
    _qualification_heading_level,
    _qualification_source_text,
    _review_commitment_candidates_semantically,
    _scan_business_hint_items,
    _scoring_bucket_from_title,
    _split_label_value,
    _strip_bidder_instruction_title_prefix,
    _strip_core_party_contact_tail,
    _strip_leading_number,
    _transform_to_business_contract,
)
# parsing-01 第 3 步搬迁：附表提取/docx 写入切片物化/商务模板判定实现已移至 parse_appendix，门面 re-export。
from app.services.parse_appendix import (
    _build_appendix_slice_state,
    _extract_document_nav_appendices,
    _extract_docx_appendices,
    _extract_markdown_appendices,
    _extract_text_appendices,
    _extract_text_business_appendices,
    _prepare_appendix_outputs,
    _prepare_commitment_letter_outputs,
    _slice_appendix_from_source,
    _write_appendix_docx,
    materialize_appendix_docx,
    materialize_business_commitment_letter_docx,
    materialize_parse_appendix_docx_assets,
    materialize_parse_business_commitment_letter_docx_assets,
)
from app.services.parse_profiles import (
    BUSINESS_PARSE_PROFILE,
    TECHNICAL_PARSE_PROFILE,
    ParseProfile,
    resolve_parse_profile,
)
# parsing-01 第 4 步搬迁：S1 skill 会话链路（prompt/CLI/分片调度/finalize/prefill）已移至
# parse_s1_skill；import 期副作用（PARSER_CORE_DIR/sys.path/parser_core）单点在 parse_s1_skill，门面 re-export。
from app.services.parse_s1_skill import (
    _S1_SHARD_REQUEST_SLOTS,
    _ShardProgressAggregator,
    _build_tender_parse_prompt,
    _finalize_business_s1_result,
    _needs_business_s1_finalize_guard,
    _project_basics_bid_deadline,
    _project_basics_project_prefill,
    _run_parse_skill,
    _run_s1parse_cli,
    _run_technical_sharded_parse_skill,
    _technical_submitted_item_count,
    _technical_total_item_count,
    parse_structured_documents,
)
from app.services.system_settings import system_settings_service

TEXT_PREVIEW_LIMIT = 600

logger = logging.getLogger(__name__)


def _extract_structured_requirements(documents: list[dict[str, Any]], texts_by_id: dict[str, str]) -> dict[str, Any]:
    return parse_structured_documents(
        documents,
        texts_by_id,
        mode="local-structured-parser",
    )


def _business_local_contract_result(
    project_id: str,
    structured_result: dict[str, Any],
    *,
    profile: ParseProfile,
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
) -> dict[str, Any]:
    if profile.key != "business":
        return structured_result
    return _transform_to_business_contract(
        project_id,
        structured_result,
        profile=profile,
        documents=documents,
        texts_by_id=texts_by_id,
        run_semantic_review=True,
    )


def _business_template_extractor_allows_preview_fallback(warning: str) -> bool:
    text = str(warning or "")
    if not text:
        return False
    if any(
        token in text
        for token in (
            "Agent 裁决未完成",
            "agent 裁决未完成",
            "Agent 未完成",
            "agent 未完成",
            "缺少 Agent 裁决文件",
            "缺少 agent 裁决文件",
            "opencode incomplete/stalled",
            "futurecode 创建 session 失败",
            "getaddrinfo failed",
        )
    ):
        return False
    return any(
        token in text
        for token in (
            "未找到可用于商务模板提取 skill 的 DOCX 招标文件",
        )
    )


def _merge_business_local_artifacts(
    structured_result: dict[str, Any],
    local_business_result: dict[str, Any],
    *,
    profile: ParseProfile,
) -> dict[str, Any]:
    if profile.key != "business":
        return structured_result
    structured = structured_result.get("structured") if isinstance(structured_result.get("structured"), dict) else {}
    local_structured = local_business_result.get("structured") if isinstance(local_business_result.get("structured"), dict) else {}
    if not isinstance(structured, dict) or not isinstance(local_structured, dict):
        return structured_result

    field_groups = structured.setdefault("fieldGroups", {})
    local_field_groups = local_structured.get("fieldGroups") if isinstance(local_structured.get("fieldGroups"), dict) else {}
    if isinstance(field_groups, dict):
        for key in ("businessResponse", "qualificationSupport", "commitmentRequirements"):
            if key not in field_groups and isinstance(local_field_groups.get(key), list):
                field_groups[key] = copy.deepcopy(local_field_groups.get(key) or [])

    scoring = structured.setdefault("scoringCriteria", {})
    if isinstance(scoring, dict):
        for key in ("price", "compliance"):
            scoring.setdefault(key, [])

    for key in ("appendices", "commitmentLetters", "commitmentClues", "commitmentTemplateAlignments", "businessFormatRegions"):
        local_value = local_structured.get(key)
        if isinstance(local_value, list) and (local_value or not isinstance(structured.get(key), list)):
            if not structured.get(key):
                structured[key] = copy.deepcopy(local_value)

    local_presence = local_structured.get("requirementPresence")
    if isinstance(local_presence, dict):
        current_presence = structured.get("requirementPresence")
        if not isinstance(current_presence, dict) or not current_presence:
            structured["requirementPresence"] = copy.deepcopy(local_presence)

    category_counts = structured.setdefault("categoryCounts", {})
    local_category_counts = local_structured.get("categoryCounts") if isinstance(local_structured.get("categoryCounts"), dict) else {}
    if isinstance(category_counts, dict):
        for key, value in local_category_counts.items():
            category_counts.setdefault(key, value)

    return structured_result


def parse_tender_documents(
    project_id: str,
    tender_files: list[dict[str, Any]],
    *,
    bid_type: str,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    require_preparsed_pdf: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _raise_if_parse_cancelled(cancel_check)
    profile = resolve_parse_profile(bid_type)
    project_dir = parsed_project_dir(project_id)
    appendix_temp_dir = project_dir / "s1_appendices"
    if appendix_temp_dir.exists():
        shutil.rmtree(appendix_temp_dir)
    primary_extension = ".pdf" if any(Path(str(file_record.get("path") or "")).suffix.lower() == ".pdf" for file_record in tender_files) else (
        Path(str(tender_files[0].get("path") or "")).suffix.lower() if tender_files else ""
    )
    documents: list[dict[str, Any]] = []
    combined_parts: list[str] = []
    texts_by_id: dict[str, str] = {}
    warnings: list[str] = []
    # 单文件失败隔离：解析异常的文件记到这里，整批继续，结果与进度中显式可见。
    failed_documents: list[dict[str, Any]] = []
    if progress_callback:
        progress_callback("extract_started", {"fileCount": len(tender_files), "fileExtension": primary_extension})

    for file_index, file_record in enumerate(tender_files, start=1):
        _raise_if_parse_cancelled(cancel_check)
        file_path = Path(str(file_record["path"]))
        extension = file_path.suffix.lower()
        page_count: int | str = "-"
        file_warnings: list[str] = []
        ocr_meta: dict[str, Any] | None = None
        parse_metadata: dict[str, Any] = {}
        if progress_callback:
            progress_callback(
                "extracting_file",
                {
                    "fileName": file_record.get("name") or file_path.name,
                    "current": file_index,
                    "total": len(tender_files),
                    "fileCount": len(tender_files),
                    "fileExtension": extension,
                },
            )

        try:
            if extension == ".docx":
                def report_docx_text_progress(progress: int, text_length: int) -> None:
                    if progress_callback:
                        progress_callback(
                            "extracting_file_progress",
                            {
                                "fileName": file_record.get("name") or file_path.name,
                                "current": file_index,
                                "total": len(tender_files),
                                "fileCount": len(tender_files),
                                "progress": progress,
                                "textLength": text_length,
                                "fileExtension": extension,
                            },
                        )

                text = extract_docx_text(file_path, progress_callback=report_docx_text_progress)
            elif extension == ".md":
                text = file_path.read_text(encoding="utf-8", errors="replace")
            elif extension == ".txt":
                text = file_path.read_text(encoding="utf-8", errors="replace")
            elif extension == ".pdf":
                pdf_text_fallback_enabled = True
                if (
                    profile.key in {"business", "technical"}
                    and settings.business_pdf_parse_engine == "docling"
                ):
                    def report_pdf_extract_progress(metadata: dict[str, Any] | None = None) -> None:
                        if progress_callback:
                            payload = {
                                "fileName": file_record.get("name") or file_path.name,
                                "current": file_index,
                                "total": len(tender_files),
                                "fileCount": len(tender_files),
                                "fileExtension": extension,
                            }
                            payload.update(metadata or {})
                            progress_callback("pdf_extracting_progress", payload)

                    text, parse_metadata, engine_warnings = _run_with_progress_heartbeat(
                        lambda: _parse_pdf_with_document_engine(
                            project_id=project_id,
                            document={
                                "id": file_record["id"],
                                "name": file_record.get("name") or file_path.name,
                                "path": str(file_path),
                                "sourcePath": str(file_path),
                                "sha256": str(file_record.get("sha256") or ""),
                                "runId": str(file_record.get("runId") or ""),
                            },
                            file_path=file_path,
                            project_dir=project_dir,
                            engine_fallback="none" if profile.key == "technical" else None,
                            require_preparsed=require_preparsed_pdf,
                            technical_document_nav=profile.key == "technical",
                        ),
                        heartbeat=report_pdf_extract_progress,
                        cancel_check=cancel_check,
                    )
                    page_count = parse_metadata.get("pageCount") or page_count
                    file_warnings.extend(engine_warnings)
                    pdf_meta = {"pageCount": page_count, "warnings": [], "requiresOcr": False}
                    pdf_text_fallback_enabled = (
                        profile.key == "business" and settings.business_pdf_engine_fallback == "lightweight"
                    )
                else:
                    text = ""
                    pdf_meta = {"pageCount": page_count, "warnings": [], "requiresOcr": False}
                if not text and pdf_text_fallback_enabled:
                    text, pdf_meta = extract_pdf_text(file_path)
                page_count = pdf_meta["pageCount"]
                file_warnings.extend(pdf_meta["warnings"])
                if pdf_meta.get("requiresOcr") and (
                    profile.key != "business" or settings.business_pdf_ocr_fallback_enabled
                ):
                    ocr_text, ocr_meta = _ocr_fallback_text(project_id, file_record, file_path)
                    if ocr_text:
                        text = ocr_text
                        page_count = ocr_meta.get("pageCount") or page_count
                        file_warnings.append("扫描型 PDF 已通过 OCR/视觉模型转为可解析文本。")
                    else:
                        file_warnings.append(
                            f"OCR 兜底识别未完成：{ocr_meta.get('message') if ocr_meta else '未知错误'}"
                        )
            elif extension in IMAGE_SUFFIXES:
                ocr_text, ocr_meta = _ocr_fallback_text(project_id, file_record, file_path)
                if ocr_text:
                    text = ocr_text
                    page_count = ocr_meta.get("pageCount") or 1
                    file_warnings.append("图片文件已通过 OCR/视觉模型转为可解析文本。")
                else:
                    text = ""
                    page_count = 1
                    file_warnings.append(
                        f"图片文件需要 OCR 识别，但兜底识别未完成：{ocr_meta.get('message') if ocr_meta else '未知错误'}"
                    )
            else:
                text = ""
                file_warnings.append(f"当前 MVP 暂不解析 {extension or '未知'} 类型文件。")

            _raise_if_parse_cancelled(cancel_check)
            text = _normalize_text(text)
            text_length = len(text)
            text_path = project_dir / f"{file_record['id']}.txt"
            text_path.write_text(text, encoding="utf-8")

            metadata = {
                "id": file_record["id"],
                "name": file_record["name"],
                "sourcePath": str(file_path),
                "textPath": str(text_path),
                "textLength": text_length,
                "pageCount": page_count,
                "warnings": file_warnings,
                "status": "completed",
            }
            if ocr_meta:
                metadata["ocr"] = ocr_meta
            if parse_metadata:
                metadata.update(parse_metadata)
            documents.append(metadata)
            texts_by_id[str(file_record["id"])] = text
            warnings.extend(file_warnings)

            if text:
                combined_parts.append(f"# 文件：{file_record['name']}\n\n{text}")
            if progress_callback:
                progress_callback(
                    "file_extracted",
                    {
                        "fileName": file_record.get("name") or file_path.name,
                        "textLength": text_length,
                        "warnings": file_warnings,
                        "current": file_index,
                        "total": len(tender_files),
                        "fileCount": len(tender_files),
                        "fileExtension": extension,
                    },
                )
            _raise_if_parse_cancelled(cancel_check)
        except ParseCancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单文件失败隔离：记为失败条目，整批继续
            logger.warning("S1 单文件解析失败，跳过继续整批：%s", file_path, exc_info=True)
            error_text = str(exc)
            file_warnings = [f"文件解析失败：{error_text}"]
            warnings.extend(file_warnings)
            failed_documents.append(
                {
                    "id": str(file_record.get("id") or ""),
                    "name": str(file_record.get("name") or file_path.name),
                    "error": error_text,
                }
            )
            documents.append(
                {
                    "id": file_record["id"],
                    "name": file_record["name"],
                    "sourcePath": str(file_path),
                    "textPath": "",
                    "textLength": 0,
                    "pageCount": "-",
                    "warnings": file_warnings,
                    "status": "failed",
                    "parseError": error_text,
                }
            )
            texts_by_id[str(file_record["id"])] = ""
            if progress_callback:
                progress_callback(
                    "file_extracted",
                    {
                        "fileName": file_record.get("name") or file_path.name,
                        "textLength": 0,
                        "warnings": file_warnings,
                        "failed": True,
                        "error": error_text,
                        "current": file_index,
                        "total": len(tender_files),
                        "fileCount": len(tender_files),
                        "fileExtension": extension,
                    },
                )
            _raise_if_parse_cancelled(cancel_check)
            continue

    combined_text = _normalize_text("\n\n".join(combined_parts))
    combined_text_path = project_dir / "combined.txt"
    combined_text_path.write_text(combined_text, encoding="utf-8")

    # 单文件失败隔离：提取失败的文件只保留在结果清单（documents/summary）中可见，
    # 不进入下游二次解析——结构化抽取、附表/章节树扫描都会按 sourcePath 重开源文件。
    parseable_documents = [document for document in documents if document.get("status") != "failed"]

    if progress_callback:
        progress_callback("local_structure_started", {"documentCount": len(parseable_documents), "fileExtension": primary_extension})
    structured_result = _extract_structured_requirements(parseable_documents, texts_by_id)
    if progress_callback:
        local_items = structured_result.get("items") if isinstance(structured_result.get("items"), list) else []
        progress_callback("local_structure_finished", {"itemCount": len(local_items), "fileExtension": primary_extension})
    template_extraction_payload: dict[str, Any] | None = None
    template_extraction_warning = ""
    template_extraction_path = project_dir / "business_template_extraction" / "business_template_extraction.json"
    business_section_tree_path = ""
    business_section_tree_summary: dict[str, Any] = {}

    # 技术标且真的会跑 opencode 时，附表提取与结构化解析并行；其余情况保持原来的串行顺序。
    appendix_runs_with_skill = profile.key != "business" and settings.s1_parse_opencode_enabled
    appendices: list[dict[str, Any]] = []
    appendices_future: Future[list[dict[str, Any]]] | None = None
    appendix_pool: ThreadPoolExecutor | None = None

    if profile.key == "business":
        _raise_if_parse_cancelled(cancel_check)
        section_tree_path, section_tree_payload = write_business_section_tree(parseable_documents, project_dir)
        business_section_tree_path = str(section_tree_path)
        business_section_tree_summary = (
            section_tree_payload.get("summary")
            if isinstance(section_tree_payload, dict) and isinstance(section_tree_payload.get("summary"), dict)
            else {}
        )
        if progress_callback:
            progress_callback(
                "business_template_extraction_started",
                {"documentCount": len(parseable_documents), "fileExtension": primary_extension},
            )
        appendices, template_extraction_payload, template_extraction_warning = run_business_template_extractor(
            project_id=project_id,
            documents=parseable_documents,
            project_dir=project_dir,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        _raise_if_parse_cancelled(cancel_check)
        if progress_callback:
            progress_callback(
                "business_template_extraction_finished",
                {
                    "appendixCount": len(appendices),
                    "warningCount": len(template_extraction_payload.get("warnings") or [])
                    if isinstance(template_extraction_payload, dict)
                    else 0,
                },
            )
        if not appendices and _business_template_extractor_allows_preview_fallback(template_extraction_warning):
            if progress_callback:
                progress_callback("appendices_started", {"documentCount": len(parseable_documents), "fileExtension": primary_extension})
            appendices = _extract_markdown_appendices(project_id, parseable_documents, texts_by_id, profile=profile)
            appendices.extend(
                _extract_docx_appendices(
                    project_id,
                    parseable_documents,
                    start_index=len(appendices),
                    profile=profile,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            )
            appendices.extend(
                _extract_text_business_appendices(
                    project_id,
                    parseable_documents,
                    texts_by_id,
                    start_index=len(appendices),
                    profile=profile,
                )
            )
    else:

        def extract_appendices(
            appendix_progress: Callable[[str, dict[str, Any] | None], None] | None,
        ) -> list[dict[str, Any]]:
            _raise_if_parse_cancelled(cancel_check)
            if appendix_progress:
                appendix_progress(
                    "appendices_started",
                    {"documentCount": len(parseable_documents), "fileExtension": primary_extension},
                )
            collected = _extract_markdown_appendices(project_id, parseable_documents, texts_by_id, profile=profile)
            collected.extend(
                _extract_docx_appendices(
                    project_id,
                    parseable_documents,
                    start_index=len(collected),
                    profile=profile,
                    progress_callback=appendix_progress,
                    cancel_check=cancel_check,
                )
            )
            document_nav_appendices = _extract_document_nav_appendices(
                project_id,
                parseable_documents,
                start_index=len(collected),
                profile=profile,
            )
            collected.extend(document_nav_appendices)
            document_nav_document_ids = {
                str(item.get("sourceDocumentId") or "")
                for item in document_nav_appendices
                if str(item.get("sourceDocumentId") or "")
            }
            collected.extend(
                _extract_text_appendices(
                    project_id,
                    parseable_documents,
                    texts_by_id,
                    start_index=len(collected),
                    profile=profile,
                    skip_document_ids=document_nav_document_ids,
                )
            )
            return collected

        if appendix_runs_with_skill:
            # 附表提取与 opencode 会话之间没有依赖：导航索引只读 manifest.documents，
            # finalize 重写结构化结果时也不含 appendices，附表是 finalize 之后才从内存合并回去的。
            # 所以放到后台线程与 prepare + 分片会话同时跑，把这段本地耗时藏进会话等待里。
            # 重叠期间不上报附表阶段进度：两个阶段同时写进度会让阶段标签来回跳。
            appendix_pool = ThreadPoolExecutor(
                max_workers=settings.s1_appendix_workers, thread_name_prefix="s1-appendix"
            )
            appendices_future = appendix_pool.submit(extract_appendices, None)
        else:
            appendices = extract_appendices(progress_callback)
    if appendices_future is None:
        appendices = _prepare_appendix_outputs(project_id, appendices, renumber=True, profile=profile)
        structured_result["structured"]["appendices"] = appendices
    if profile.key == "business" and not settings.s1_parse_opencode_enabled:
        local_business_result = _business_local_contract_result(
            project_id,
            structured_result,
            profile=profile,
            documents=parseable_documents,
            texts_by_id=texts_by_id,
        )
        structured_result = local_business_result
    else:
        local_business_result = structured_result
    if progress_callback and appendices_future is None:
        progress_callback(
            "appendices_extracted",
            {
                "appendixCount": len(appendices),
                "generatedCount": sum(1 for item in appendices if item.get("status") == "generated"),
                "fileExtension": primary_extension,
            },
        )
    structured_path = project_dir / "s1_structured_result.json"
    structured_path.write_text(json.dumps(structured_result, ensure_ascii=False, indent=2), encoding="utf-8")
    skill_manifest_path = project_dir / "s1_parse_manifest.json"
    skill_manifest = {
        "projectId": project_id,
        "bidType": profile.bid_type,
        "parseProfile": profile.key,
        "targetSkill": profile.skill_name,
        "combinedTextPath": str(combined_text_path),
        "structuredResultPath": str(structured_path),
        "businessTemplateExtractionPath": str(template_extraction_path) if profile.key == "business" and template_extraction_path.is_file() else "",
        "businessTemplateExtractionSummary": (
            template_extraction_payload.get("summary")
            if profile.key == "business" and isinstance(template_extraction_payload, dict)
            else {}
        ),
        "businessSectionTreePath": business_section_tree_path,
        "businessSectionTreeSummary": business_section_tree_summary,
        "documents": parseable_documents,
        "targets": list(profile.targets),
    }
    skill_manifest_path.write_text(json.dumps(skill_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback("skill_manifest_ready", {"manifestPath": str(skill_manifest_path), "fileExtension": primary_extension})
    _raise_if_parse_cancelled(cancel_check)
    try:
        structured_result, skill_warning = _run_parse_skill(
            skill_manifest_path,
            local_result=structured_result,
            profile=profile,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        _raise_if_parse_cancelled(cancel_check)
        if progress_callback and settings.s1_parse_opencode_enabled:
            progress_callback("opencode_finished", {})
        if _needs_business_s1_finalize_guard(
            profile=profile,
            structured_result=structured_result,
            skill_manifest_path=skill_manifest_path,
        ):
            structured_result, finalize_warning = _finalize_business_s1_result(
                skill_manifest_path,
                structured_result,
                profile,
            )
            if finalize_warning:
                skill_warning = f"{skill_warning}；{finalize_warning}" if skill_warning else finalize_warning
    except BaseException:
        # 主链路已经失败，这里只负责回收附表线程，避免解析结束后还有线程在往项目目录写文件。
        # 附表自身的异常只记日志，不能盖掉原始失败原因。
        if appendices_future is not None:
            try:
                appendices_future.result()
            except BaseException:
                logger.warning("解析失败后回收附表提取线程时报错。", exc_info=True)
            if appendix_pool is not None:
                appendix_pool.shutdown(wait=True)
        raise
    if appendices_future is not None:
        # 附表分支的异常必须在这里显式抛出，不能因为会话成功就当作附表也成功。
        # 结果由下面既有的合并块写回 structured；这里不再补发附表阶段事件，
        # 否则结构化解析已经结束后阶段标签会倒回“提取附表中”。
        try:
            appendices = appendices_future.result()
        finally:
            if appendix_pool is not None:
                appendix_pool.shutdown(wait=True)
    if template_extraction_warning:
        warnings.append(template_extraction_warning)
    structured_result = _merge_business_local_artifacts(
        structured_result,
        local_business_result,
        profile=profile,
    )
    resolved_structured = structured_result.setdefault("structured", {})
    if profile.key == "business" and not resolved_structured.get("appendices") and appendices:
        resolved_structured["appendices"] = appendices
    elif profile.key != "business" and not resolved_structured.get("appendices"):
        resolved_structured["appendices"] = appendices
    if isinstance(resolved_structured.get("appendices"), list):
        resolved_structured["appendices"] = _prepare_appendix_outputs(
            project_id,
            resolved_structured["appendices"],
            renumber=True,
            profile=profile,
        )
    if profile.key == "business" and isinstance(resolved_structured.get("commitmentLetters"), list):
        resolved_structured["commitmentLetters"] = _prepare_commitment_letter_outputs(
            project_id,
            resolved_structured.get("commitmentLetters") or [],
            renumber=True,
            profile=profile,
            project_name=_business_project_name_from_structured(resolved_structured),
            tenderer_name=_business_tenderer_name_from_structured(resolved_structured),
        )
    if skill_warning:
        warnings.append(skill_warning)
    structured_path.write_text(json.dumps(structured_result, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = project_dir / "manifest.json"
    manifest = {
        "projectId": project_id,
        "combinedTextPath": str(combined_text_path),
        "documents": documents,
        "structuredResultPath": str(structured_path),
        "skillManifestPath": str(skill_manifest_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    items = structured_result.get("items") if isinstance(structured_result.get("items"), list) else []
    structured = structured_result.get("structured") if isinstance(structured_result.get("structured"), dict) else {}
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
    project_deadline = _project_basics_bid_deadline(structured)
    project_prefill = _project_basics_project_prefill(structured)

    summary = {
        "fileCount": len(tender_files),
        "failedFileCount": len(failed_documents),
        "failedDocuments": failed_documents,
        "extractedCount": len(items),
        "textLength": len(combined_text),
        "textPreview": combined_text[:TEXT_PREVIEW_LIMIT],
        "warnings": warnings,
        "targetSkill": profile.skill_name,
        "categoryCounts": structured.get("categoryCounts") or {},
        "appendixCount": len(structured.get("appendices") or []),
    }
    if profile.key == "business" or project_dates:
        summary["projectDates"] = {
            "startDate": project_dates.get("startDate") or "",
            "endDate": project_dates.get("endDate") or "",
        }
    if profile.key == "business":
        summary["commitmentLetterCount"] = len(structured.get("commitmentLetters") or [])

    if progress_callback:
        progress_callback(
            "complete",
            {
                "extractedCount": len(items),
                "appendixCount": len(structured.get("appendices") or []),
                "failedFileCount": len(failed_documents),
                "failedDocuments": failed_documents,
            },
        )
    _raise_if_parse_cancelled(cancel_check)

    project_update_start = project_dates.get("startDate") or ""
    project_update_end = project_deadline or project_dates.get("endDate") or ""
    project_updates = {}
    if project_update_start:
        project_updates["startDate"] = project_update_start
    if project_update_end:
        project_updates["endDate"] = project_update_end
        project_updates["deadline"] = project_update_end

    return summary, {
        "projectDir": str(project_dir),
        "combinedTextPath": str(combined_text_path),
        "manifestPath": str(manifest_path),
        "structuredResultPath": str(structured_path),
        "skillManifestPath": str(skill_manifest_path),
        "bidType": profile.bid_type,
        "parseProfile": profile.key,
        "documents": documents,
        "items": items,
        "structured": structured,
        "projectUpdates": project_updates,
        "projectPrefill": project_prefill,
    }
