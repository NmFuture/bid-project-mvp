"""S2 目录生成编排门面：skill 运行、prompt 构建与节点清洗。

并行章节执行器、结果加载校验、TOC 工作区发布分别拆到
outline_chapter_runner / outline_result_loading / outline_toc_publish，
本文件 re-export 全部原符号，外部调用方与 patch 目标无需改动。
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.services.bid_outline_state import save_generated_outline_state
from app.services.bid_project_state import project_parse_input_records
from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.file_utils import run_awaitable_sync
from app.services.bid_runtime_state import build_directory_opencode_output, now_iso
from app.services.workspace_project_access import (
    get_any_workspace_project_runtime_state,
    persist_workspace_project_state,
    require_any_workspace_project_for_update,
)
# 拆分搬迁：并行章节执行器已移至 outline_chapter_runner，此处 re-export
# 保持 app.services.outline_generation.<符号> 可解析、可 patch。
from app.services.outline_chapter_runner import (
    OUTLINE_SKILL_NAME,
    TECH_OUTLINE_CHAPTER_WORKERS,
    TECH_OUTLINE_FINALIZE_COMMAND,
    TECH_OUTLINE_FINALIZE_EARLY_COMMAND,
    TECH_OUTLINE_HANDOFF_DECISION_UNITS,
    TECH_OUTLINE_TOTAL_WORKERS,
    _TECH_OUTLINE_REQUEST_SLOTS,
    _ChapterDecisionAggregator,
    _ChapterParallelUnsupported,
    _build_outline_appendix_predecision_prompt,
    _build_outline_appendix_prompt,
    _build_outline_chapter_prompt,
    _build_outline_finalize_prompt,
    _build_outline_handoff_prompt,
    _capture_trusted_technical_outline_input,
    _close_technical_outline_without_llm,
    _finalize_current_technical_outline,
    _load_technical_outline_runner,
    _outline_chapter_base_urls,
    _prepare_outline_appendix_workspace,
    _prepare_outline_chapter_workspaces,
    _run_outline_appendix_session,
    _run_parallel_outline_chapters,
    _technical_outline_handoff_state,
)
# 拆分搬迁：结果加载与校验已移至 outline_result_loading，门面 re-export。
from app.services.outline_result_loading import (
    PUBLIC_EVIDENCE_DECISION_LIMIT,
    TECHNICAL_SUGGESTION_ACTIONS,
    _apply_agent_decisions,
    _business_annotation_from_required_status,
    _business_section_number,
    _business_source_refs_from_section,
    _business_toc_items_from_sections,
    _clean_source_ref,
    _clean_toc_items,
    _coerce_confidence,
    _coerce_toc_level,
    _find_decision_target,
    _is_business_bid,
    _item_lookup,
    _load_business_outline_json,
    _load_business_outline_result,
    _load_json_dict,
    _load_outline_result,
    _normalize_required_status,
    _public_rule_evidence_from_file,
    _required_status_from_annotation,
    _rewrite_toc_file,
    _source_ref_from_agent_candidate,
    _technical_rule_evidence,
    _title_key,
    _toc_item_from_agent_candidate,
    _toc_item_source_text,
    _validate_business_outline_section_numbers,
    _validate_technical_compose_report,
    _write_business_toc_from_outline,
    _write_business_toc_from_outline_payload,
)
# 拆分搬迁：TOC 工作区发布/路径重映射与输入拷贝已移至 outline_toc_publish，门面 re-export。
from app.services.outline_toc_publish import (
    MANIFEST_FACT_VALUE_STATUSES,
    _archive_workspace_if_exists,
    _copy_single_template,
    _copy_template_inputs,
    _copy_tender_inputs,
    _copy_visual_template_input,
    _heading_style_for_line,
    _looks_like_attachment_template,
    _outline_bid_type,
    _prepare_toc_skill_workspace,
    _publish_toc_skill_workspace,
    _remap_json_file,
    _remap_workspace_paths,
    _remove_manifest_alias,
    _unique_path,
    _write_text_docx,
    project_facts_for_manifest,
)

BUSINESS_OUTLINE_SKILL_NAME = "bid-business-outline-generator"
BUSINESS_OUTLINE_SKILL_COMMAND = "business-outline"

logger = logging.getLogger(__name__)


def _outline_skill_name(bid_type: Any) -> str:
    return BUSINESS_OUTLINE_SKILL_NAME if _is_business_bid(bid_type) else OUTLINE_SKILL_NAME


def generate_outline_for_project(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return generate_outline_for_project_with_progress(project_id, data)


def generate_outline_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    project = get_any_workspace_project_runtime_state(project_id, not_found_error=KeyError)
    parse_storage = copy.deepcopy(project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {})
    tender_file_records, template_file_records = project_parse_input_records(project_id, project)
    combined_text_path = Path(str(parse_storage.get("combinedTextPath") or ""))
    if not combined_text_path.exists():
        raise ValueError("S1 解析结果不存在，请先完成解析。")

    combined_text = combined_text_path.read_text(encoding="utf-8").strip()
    if not combined_text:
        raise ValueError("S1 解析文本为空，暂时无法生成目录。")

    skill_workspace = _prepare_toc_skill_workspace(
        project_id=project_id,
        project=project,
        parse_storage=parse_storage,
        tender_file_records=tender_file_records,
        template_file_records=template_file_records,
    )
    if progress_callback:
        progress_callback(
            "inputs_ready",
            {
                "tenderFileCount": skill_workspace["tenderFileCount"],
                "templateFileCount": skill_workspace["templateFileCount"],
                "workDir": skill_workspace["workDir"],
                "bidType": skill_workspace["bidType"],
            },
        )

    toc_result = _run_outline_skill(
        Path(str(skill_workspace["canonicalManifestPath"])),
        bid_type=skill_workspace["bidType"],
        progress_callback=progress_callback,
    )
    publish_info = _publish_toc_skill_workspace(skill_workspace, toc_result)
    toc_result = publish_info["result"]
    nodes = _nodes_from_generation_result(
        toc_result,
        compact_technical=not _is_business_bid(skill_workspace["bidType"]),
    )
    summary = _summary_from_generation_result(toc_result)
    opencode_output = toc_result.get("opencodeOutput") if isinstance(toc_result.get("opencodeOutput"), dict) else {}
    if not opencode_output:
        opencode_output = build_directory_opencode_output(status="received")
    skill_name = _outline_skill_name(skill_workspace["bidType"])
    opencode_output.update(
        {
            "engine": skill_name,
            "skill": skill_name,
            "workDir": publish_info["workDir"],
            "manifestPath": publish_info["manifestPath"],
            "canonicalManifestPath": publish_info["canonicalManifestPath"],
            "stagingWorkDir": publish_info["stagingWorkDir"],
            "archiveRoot": publish_info["archiveRoot"],
            "tocJsonPath": str(toc_result.get("outputFile") or publish_info["outputFile"]),
        }
    )
    evidence_path = str(toc_result.get("evidenceFile") or publish_info.get("evidenceFile") or "").strip()
    if evidence_path:
        opencode_output["evidencePath"] = evidence_path
    if progress_callback:
        progress_callback(
            "normalizing_result",
            {
                "chapterCount": len(nodes),
            },
        )

    generated_at = now_iso()
    project_for_update = require_any_workspace_project_for_update(project_id, not_found_error=KeyError)
    payload = save_generated_outline_state(
        project_for_update,
        nodes=nodes,
        generated_at=generated_at,
        summary=summary,
        opencode_output=opencode_output,
        rule_evidence=toc_result.get("ruleEvidence") if isinstance(toc_result.get("ruleEvidence"), dict) else {},
        invalidate_technical_downstream=bool((data or {}).get("regenerateOutline")),
    )
    persist_workspace_project_state(project_for_update)
    return payload


def _run_outline_skill(
    manifest_path: Path,
    *,
    bid_type: Any,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    if _is_business_bid(bid_type):
        return _run_business_outline_skill(manifest_path, progress_callback=progress_callback)

    try:
        trusted_input = _capture_trusted_technical_outline_input(manifest_path)
        chapter_session_ids: list[str] = []
        parallel_appendix_result: dict[str, Any] | None = None
        appendix_predecided = False
        handoff_kwargs: dict[str, Any] = {}
        parallel_completed = False
        finalizing_reported = False

        def emit_finalizing_result() -> None:
            nonlocal finalizing_reported
            if progress_callback and not finalizing_reported:
                progress_callback("finalizing_result", {})
                finalizing_reported = True

        try:
            parallel_result = _run_parallel_outline_chapters(
                manifest_path,
                trusted_input["templateStructure"],
                progress_callback=progress_callback,
            )
            if isinstance(parallel_result, dict):
                chapter_session_ids = list(
                    parallel_result.get("chapterSessionIds") or []
                )
                raw_appendix_result = parallel_result.get("appendixResult")
                if isinstance(raw_appendix_result, dict):
                    parallel_appendix_result = raw_appendix_result
                appendix_predecided = bool(
                    parallel_result.get("appendixPredecided")
                )
            else:
                # 兼容测试和历史调用方的章节会话列表。
                chapter_session_ids = list(parallel_result or [])
            parallel_completed = True
        except _ChapterParallelUnsupported:
            previous_decided_count = [-1]

            def handoff_state(handoff_index: int) -> dict[str, Any]:
                del handoff_index
                state = _technical_outline_handoff_state(
                    manifest_path,
                    previous_decided_count=previous_decided_count[0],
                )
                previous_decided_count[0] = int(state["decidedCount"])
                if progress_callback:
                    decided = int(state["decidedCount"])
                    progress_callback(
                        "decision_progress",
                        {
                            "phase": "serial",
                            "decided": decided,
                            "total": decided + int(state.get("remainingCount") or 0),
                        },
                    )
                return state

            handoff_kwargs = {
                "handoff_prompt_factory": lambda index: _build_outline_handoff_prompt(
                    manifest_path,
                    index,
                ),
                "handoff_state_callback": handoff_state,
            }

        if chapter_session_ids and not settings.tech_outline_llm_finalize:
            # 附表预判成功时已在章节合并后受控物化；失败才串行降级。
            appendix_result = parallel_appendix_result
            if not appendix_predecided:
                appendix_result = _run_outline_appendix_session(
                    manifest_path,
                    progress_callback=progress_callback,
                )
            emit_finalizing_result()
            generated = {
                **_close_technical_outline_without_llm(manifest_path),
                "opencodeOutput": (
                    appendix_result.get("opencodeOutput")
                    if isinstance(appendix_result, dict)
                    else {}
                )
                or {},
            }
        else:
            if parallel_completed:
                emit_finalizing_result()

            def session_ready(details: dict[str, Any]) -> None:
                if not progress_callback:
                    return
                callback_details = (
                    {**details, "suppressStage": True}
                    if finalizing_reported
                    else details
                )
                progress_callback("outline_session_ready", callback_details)
                if str(details.get("sessionPhase") or "") == "finalize":
                    emit_finalizing_result()

            def stream_delta(details: dict[str, Any]) -> None:
                if not progress_callback:
                    return
                callback_details = (
                    {**details, "suppressStage": True}
                    if finalizing_reported
                    else details
                )
                progress_callback("outline_delta", callback_details)

            # 保留直建：显式传 opencode 专有 timeout_ms（覆盖 DB timeoutMs 默认），非「只要默认引擎」。
            generated = run_awaitable_sync(OpencodeEngine(
                timeout_ms=int(settings.opencode_timeout_sec * 1000)
            ).generate_outline_with_trace(
                    _build_outline_finalize_prompt(manifest_path),
                    session_ready_callback=session_ready if progress_callback else None,
                    stream_callback=stream_delta if progress_callback else None,
                    early_tool_command=TECH_OUTLINE_FINALIZE_EARLY_COMMAND,
                    terminal_validator=lambda: _finalize_current_technical_outline(manifest_path),
                    **handoff_kwargs,
                ))
        loaded = _load_outline_result(
            generated,
            manifest_path,
            expected_bid_type=bid_type,
            trusted_technical_input=trusted_input,
        )
        if chapter_session_ids:
            output_trace = loaded.setdefault("opencodeOutput", {})
            final_session_id = str(output_trace.get("sessionId") or "")
            output_trace["sessionIds"] = [
                *chapter_session_ids,
                *([final_session_id] if final_session_id else []),
            ]
            output_trace["chapterSessionCount"] = len(chapter_session_ids)
            output_trace["parallelChapterWorkers"] = min(
                TECH_OUTLINE_CHAPTER_WORKERS,
                len(chapter_session_ids),
            )
            output_trace["parallelAppendixSessionCount"] = int(
                bool(parallel_appendix_result)
            )
            output_trace["parallelDecisionWorkers"] = min(
                TECH_OUTLINE_TOTAL_WORKERS,
                len(chapter_session_ids) + int(bool(parallel_appendix_result)),
            )
        return loaded
    except Exception as exc:
        if progress_callback:
            progress_callback(
                "outline_failed",
                {"error": str(exc), "manifestPath": str(manifest_path)},
            )
        raise RuntimeError(
            "技术标目录生成失败：目录生成需要 opencode 自主决策，"
            f"futurecode/opencode 执行失败：{exc}。"
        ) from exc


def _run_business_outline_skill(
    manifest_path: Path,
    *,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    prompt = _build_business_outline_prompt(manifest_path)
    try:
        # 保留直建：显式传 opencode 专有 timeout_ms（覆盖 DB timeoutMs 默认），非「只要默认引擎」。
        result = run_awaitable_sync(OpencodeEngine(timeout_ms=int(settings.opencode_timeout_sec * 1000)).generate_outline_with_trace(
            prompt,
            session_ready_callback=(
                (lambda details: progress_callback("outline_session_ready", details))
                if progress_callback
                else None
            ),
            stream_callback=(
                (lambda details: progress_callback("outline_delta", details))
                if progress_callback
                else None
            ),
            early_tool_command="",
        ))
    except Exception as exc:
        if progress_callback:
            progress_callback(
                "outline_fallback",
                {"error": str(exc), "manifestPath": str(manifest_path)},
            )
        raise RuntimeError(
            "商务标目录生成失败："
            f"futurecode 执行失败：{exc}。"
            "本地 bid-business-outline-generator 只负责准备候选材料，不能兜底生成最终 outline.json。"
        ) from exc
    return _load_outline_result(result, manifest_path, expected_bid_type=BUSINESS_BID_TYPE)


def _build_outline_prompt(manifest_path: Path, bid_type: Any) -> str:
    bid_type_text = require_bid_type(
        bid_type,
        error_message="目录生成必须显式传入技术标或商务标。",
    )
    if _is_business_bid(bid_type_text):
        return _build_business_outline_prompt(manifest_path)
    skill_name = _outline_skill_name(bid_type_text)
    return f"""
Use the {skill_name} skill.

生成 S2 {bid_type_text}目录。目录学习、招标新增项和适用性建议由 Opencode 按 Skill 自主判断，不得把未判断节点自动当成必要。

manifest：{manifest_path}

历史投标模板提供目录经验，当前招标文件提供本项目要求。完整学习模板一至三级目录，模板已有第三级目录统一进入结果供用户确认，但不预设任何模板节点必须保留。每个模板节点由 Opencode 自主选择保留或建议删除，并自主判断建议增加项；建议删除的节点仍保留供用户确认。最终目录最多三级，第四级及更深层级只作为对应第三级节点的内容参考，不把参数、条款或表格字段机械扩成目录，再结合招标文件逐项判断。

严格按 Skill 执行受控流程。`prepare` 只执行一次；完成后不要再执行同功能的 `s2outline template`，不要直接读取 `template_structure.json`，模板节点只通过 `decision-next` 按章获取。招标目录必须按 `next_cursor` 分页读到 `complete=true`；每章自主使用 `s2outline section` 阅读相关章节或小节，使用 `s2outline search` 跨章节查漏并继续详读原文。每个决策单元一次提交保留、建议增加、建议删除，不做章节复核。完成全部章节后用 `s2outline appendix-next {manifest_path} --max-items 40` 判断附表，再只做一次全局复核；发现遗漏或误判必须用 `review-corrections` 写入目录决策，不能只记在总结或留给后续阶段。确认无问题后执行 `review-complete`、`decisions` 和 `compose`。不得编写临时脚本批量拼装判断，不得自行写入 manifest.outputFile 或决策状态文件，也不得读取决策状态文件。最后执行：

首次执行 `s2outline prepare {manifest_path}` 时，Bash 必须显式设置 `timeout=300000`。若仍超时，只增大 timeout 后重试同一命令；不要检查脚本或包装器，不要绕过 `s2outline`。

{TECH_OUTLINE_FINALIZE_COMMAND} {manifest_path}

finalize 只校验结果，也是后端的完成信号。最后原样返回 finalize 的严格 JSON，不要 Markdown 或解释文字。
""".strip()


def _build_business_outline_prompt(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    business_outline_file = str(work_dir / "outline.json")
    decisions_file = str(work_dir / "outline_authoring_decisions.json")
    history_file = str(work_dir / "history_bid_outline_inputs.json")
    tender_file = str(work_dir / "tender_map_inputs.json")
    document_structure_index_file = str(work_dir / "document_structure_index.json")
    source_text_candidates_file = str(work_dir / "source_text_candidates.json")
    return f"""
Use the {BUSINESS_OUTLINE_SKILL_NAME} skill.

你现在在做 S2 商务标目录生成。必须完整执行 bid-business-outline-generator Skill，并严格遵循原有 Skill 的产物边界：准备脚本只生成输入材料，opencode 只输出语义选择、状态判断和保留/延后理由，最终 outline.json 必须通过固定的 outline_authoring_helper.py 机械写回。

manifest：{manifest_path}

集成准备动作：直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径：

{BUSINESS_OUTLINE_SKILL_COMMAND} {manifest_path}

强制工具顺序：加载 skill 之后，第一条非 skill 工具调用必须是 Bash，且 Bash command 必须完全等于上面这一行。禁止在这条 Bash 命令完成前调用 read、glob、list、ls、cat、head、tail、grep 或任何读取 manifest/JSON 的工具。不要读取 manifest 内容来“理解输入”；准备命令会读取 manifest 并产出后续判断所需材料。

Mandatory tool order: after the skill tool is loaded, your first non-skill tool call MUST be the Bash tool with exactly the `business-outline {manifest_path}` command above. Do not call read, glob, list, ls, cat, head, tail, grep, or any manifest/JSON inspection tool before that Bash command completes. Do not inspect the manifest first.

该命令只负责根据 manifest.templateFile 和 manifest.tenderFiles 生成：
- {history_file}
- {tender_file}
- {document_structure_index_file}
- {source_text_candidates_file}

该命令不得被视为最终目录生成；不得把它的 stdout、summary 或任何候选信息当作最终 outline.json。

AI 判断动作：命令完成后，继续按 bid-business-outline-generator Skill 的步骤 2-6 做 AI 判断：学习历史商务标目录结构，分析当前招标文件，读取并消费 document_structure_index.json 与 source_text_candidates.json，匹配每个目录项的 source_text，判断 required_status，补强必须提交材料，并把每个保留目录项的语义决策写入 outline_authoring_decisions.json。不得现场编写临时 Python 写回脚本。

必须使用后端 manifest.templateFile 作为历史商务标/商务模板来源，不扫描当前工作目录，不使用 user_confirmed_inputs.json。

后续判断只基于原始 Skill 输入产物：
- 历史商务标输入：{history_file}
- 招标文件输入：{tender_file}
- 文档结构索引：{document_structure_index_file}
- source_text 候选：{source_text_candidates_file}

source_text 选择必须先消费 source_text_candidates.json 的首选候选：若某目录项已有 candidates[0]，且候选不是目录页/目次页，也不是合计、总计、小计等汇总行，最终 section.source_text 应优先逐字采用该候选，并把候选的 scope、evidence_strength、evidence_category、match_reason 写入 section.evidence_scope、section.evidence_strength、section.evidence_category、section.reason。不要用同一章节内的表格汇总行替换强标题候选或强段落候选；若首选候选是目录项标题本身或明确提交材料名称，最终 source_text 必须保留该候选，不得改用“合计 | 100”这类汇总行。

历史继承策略：章节级、材料级目录应保留；具体项目业绩清单、具体证书扫描件、协议明细、过程材料明细、逐页附件、图片说明、合同逐项列表等细碎内容，应由 opencode 判断为“素材库组装项/正文素材”，在 outline_authoring_decisions.json 中显式写 action: "defer" 并说明理由，不能因为只有历史原文就默认以 history_fallback 全部保留进目录。

禁止调用 read 工具；不要使用 cat/head/tail/grep 直接打印 JSON 大文件。需要访问文件内容或写回结果时，只能调用 Bash 工具执行 python3 脚本读取上述原始产物、按 bid-business-outline-generator Skill 逻辑分析和写回。Python 脚本可以完整读取 JSON 文件到内存，但每次 stdout 只输出当前判断所需的简短检查结果，避免刷屏或截断。

必须先把 opencode 的语义判断写入固定决策文件：
{decisions_file}

outline_authoring_decisions.json 只表达 opencode 的判断，不负责机械拼装。至少包含：
{{
  "document_name": "商务标目录",
  "sections": [
    {{
      "id": "BIZ-FALLBACK-0001",
      "candidate_source_id": "hist-cand-001",
      "selected_candidate_id": "cand-001",
      "required_status": "必要",
      "reason": "结合当前招标文件证据与历史目录语义保留。"
    }}
  ],
  "review_items": []
}}

写好决策文件后，必须调用固定 helper 机械生成最终 outline.json，不得自己现场编写 Python 写回逻辑：
python scripts/outline_authoring_helper.py --history "{history_file}" --source-candidates "{source_text_candidates_file}" --decisions "{decisions_file}" --output "{business_outline_file}"

helper 只负责读取候选、保持 ID、组装/写回 outline.json、运行基础校验；它不判断章节是否必要，不写死商务标题。

最终原生产物必须写入：
{business_outline_file}

outline.json 必须满足：
{{
  "schema_version": "business_bid_outline.v1",
  "sections": [
    {{
      "id": "sec-001",
      "title": "目录标题",
      "number": null,
      "level": 1,
      "required_status": "待确认",
      "source_text": "逐字证据",
      "evidence_scope": "parent_context",
      "evidence_strength": "strong",
      "children": []
    }}
  ]
}}

每一个 sections[*] 以及所有子级 section 都必须显式包含 number 字段。有历史编号时保留字符串编号；历史无编号、空编号或无法可靠推断时写为 null 或空字符串，禁止由层级顺序强行生成 1、1.1、1.2 等编号。

不要自行生成或修改前端兼容 toc.json；后端会根据最终 outline.json 自动转换。

最后只返回严格 JSON，不要 Markdown，不要解释文字：
{{
  "schema_version": "business_bid_outline.v1",
  "businessOutlineFile": "{business_outline_file}",
  "historyBidOutlineInputsFile": "{history_file}",
  "tenderMapInputsFile": "{tender_file}",
  "sourceTextCandidatesFile": "{source_text_candidates_file}",
  "outlineAuthoringDecisionsFile": "{decisions_file}",
  "summary": {{"total_sections": 0}}
}}
""".strip()


def _nodes_from_generation_result(
    result: dict[str, Any],
    *,
    compact_technical: bool = False,
) -> list[dict[str, Any]]:
    if compact_technical and isinstance(result.get("nodes"), list):
        return _clean_technical_outline_nodes(result["nodes"])
    if isinstance(result.get("items"), list):
        return _nodes_from_toc_items(result["items"])
    raise ValueError("目录 JSON 缺少 nodes[] 或 items[]。")


def _summary_from_generation_result(result: dict[str, Any]) -> str:
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if isinstance(summary, dict):
        total_items = summary.get("total_nodes") if "total_nodes" in summary else summary.get("total_items")
        status_counts = (
            summary.get("action_counts")
            or summary.get("required_status_counts")
            or summary.get("annotation_counts")
            or {}
        )
        if isinstance(status_counts, dict) and status_counts:
            counts = "，".join(
                f"{key}{value}"
                for key, value in status_counts.items()
                if value
            )
            if counts:
                return f"目录生成完成，共 {total_items or 0} 条目录项（{counts}）。"
        return f"目录生成完成，共 {total_items or 0} 条目录项。"
    return "目录生成完成。"


def _clean_technical_outline_nodes(
    nodes: list[Any],
    *,
    parent_id: str = "OL",
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for index, raw_node in enumerate(nodes, start=1):
        if not isinstance(raw_node, dict):
            continue
        node_id = f"{parent_id}-{index}"
        action = str(raw_node.get("suggestion_action") or raw_node.get("suggestionAction") or "待确认").strip()
        if action not in TECHNICAL_SUGGESTION_ACTIONS:
            action = "待确认"
        reason = str(raw_node.get("suggestion_reason") or raw_node.get("suggestionReason") or "").strip()
        if action != "必要" and not reason:
            reason = "该目录项需要人工确认。"
        basis = raw_node.get("tender_basis")
        if not isinstance(basis, dict):
            basis = raw_node.get("tenderBasis") if isinstance(raw_node.get("tenderBasis"), dict) else None
        clean_basis = _clean_tender_basis(basis)
        number = str(raw_node.get("number") or raw_node.get("tocNumber") or "").strip()
        raw_children = raw_node.get("children") if isinstance(raw_node.get("children"), list) else []
        node = {
            "id": node_id,
            "number": number,
            "tocNumber": number,
            "title": str(raw_node.get("title") or "未命名章节").strip(),
            "suggestionAction": action,
            "suggestionReason": reason,
            "children": _clean_technical_outline_nodes(raw_children, parent_id=node_id),
        }
        if clean_basis:
            node["tenderBasis"] = clean_basis
        cleaned.append(node)
    return cleaned


def _clean_tender_basis(value: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    file_id = str(value.get("file_id") or value.get("fileId") or "").strip()
    search_text = str(value.get("search_text") or value.get("searchText") or "").strip()
    if not file_id or not search_text:
        return None
    result = {"fileId": file_id, "searchText": search_text}
    evidence_id = str(value.get("evidence_id") or value.get("evidenceId") or "").strip()
    if evidence_id:
        result["evidenceId"] = evidence_id
    return result


def _nodes_from_toc_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    counters: list[int] = []

    for fallback_order, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        level = _coerce_toc_level(item.get("level"))
        if not stack and level > 1:
            level = 1
        elif stack and level > stack[-1][0] + 1:
            level = stack[-1][0] + 1

        while stack and stack[-1][0] >= level:
            stack.pop()

        counters = counters[:level]
        if len(counters) < level:
            counters.extend([0] * (level - len(counters)))
        counters[level - 1] += 1
        node_id = "OL-" + "-".join(str(part) for part in counters[:level] if part)

        title = _toc_item_title(item, fallback_order)
        source_text = _toc_item_source_text(item)
        annotation = str(item.get("annotation") or "").strip()
        required_status = str(item.get("required_status") or item.get("requiredStatus") or "").strip()
        if not required_status:
            required_status = _required_status_from_annotation(annotation)
        node = {
            "id": node_id,
            "title": title,
            "children": [],
            "tocNumber": str(item.get("number") or "").strip(),
            "annotation": annotation,
            "required_status": required_status,
            "requiredStatus": required_status,
            "source_text": source_text,
            "sourceText": source_text,
            "source": str(item.get("source") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        if isinstance(item.get("source_refs"), list):
            node["sourceRefs"] = item["source_refs"]
        if isinstance(item.get("material_refs"), list):
            node["materialRefs"] = item["material_refs"]
        if stack:
            stack[-1][1].setdefault("children", []).append(node)
        else:
            roots.append(node)
        stack.append((level, node))

    return roots


def _toc_item_title(
    item: dict[str, Any],
    fallback_order: int,
) -> str:
    title = str(item.get("title") or "").strip()
    number = str(item.get("number") or "").strip()
    if title:
        if str(item.get("source") or "").strip() == "business_outline":
            return title
        if number and not re.fullmatch(r"\d+(?:\.\d+)*", number):
            return f"{number} {title}".strip()
        return title
    if number:
        return number
    return f"未命名章节{fallback_order}"
