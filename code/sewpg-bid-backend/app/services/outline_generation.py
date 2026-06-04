from __future__ import annotations

import json
import copy
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from docx import Document

from app.core.config import BASE_DIR, settings
from app.services.bid_outline_state import save_generated_outline_state
from app.services.bid_project_state import project_parse_input_records
from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type
from app.services.opencode_client import OpencodeClient
from app.services.parsing import IMAGE_SUFFIXES, _ocr_fallback_text
from app.services.bid_runtime_state import build_directory_opencode_output, now_iso
from app.services.template_store import is_valid_docx_file
from app.services.workspace_artifacts import workspace_dir
from app.services.workspace_project_access import (
    get_any_workspace_project_runtime_state,
    persist_workspace_project_state,
    require_any_workspace_project_for_update,
)

OUTLINE_SKILL_NAME = "bid-tech-outline-generator"
BUSINESS_OUTLINE_SKILL_NAME = "bid-business-outline-generator"
OUTLINE_SKILL_COMMAND = "s2toc"
BUSINESS_OUTLINE_SKILL_COMMAND = "business-outline"
OUTLINE_SKILL_RUNNER = (
    BASE_DIR
    / "opencode"
    / "skill"
    / OUTLINE_SKILL_NAME
    / "scripts"
    / "run_from_manifest.py"
)
OUTLINE_REVIEW_BUDGET = {
    "templateOutlineItems": 80,
    "tenderCandidates": 260,
    "draftItems": 120,
    "scriptDecisions": 120,
    "textChars": 180,
    "stdoutTenderCandidates": 24,
    "stdoutDraftItems": 24,
    "stdoutScriptDecisions": 24,
}
PUBLIC_EVIDENCE_DECISION_LIMIT = 80


def _is_business_bid(bid_type: Any) -> bool:
    return require_bid_type(
        bid_type,
        error_message="目录生成必须显式传入技术标或商务标。",
    ) == BUSINESS_BID_TYPE


def _outline_skill_name(bid_type: Any) -> str:
    return BUSINESS_OUTLINE_SKILL_NAME if _is_business_bid(bid_type) else OUTLINE_SKILL_NAME


def _outline_skill_command(bid_type: Any) -> str:
    return BUSINESS_OUTLINE_SKILL_COMMAND if _is_business_bid(bid_type) else OUTLINE_SKILL_COMMAND


def _outline_skill_runner(skill_name: str) -> Path:
    return BASE_DIR / "opencode" / "skill" / skill_name / "scripts" / "run_from_manifest.py"


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
    nodes = _nodes_from_generation_result(toc_result)
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
            "evidencePath": str(toc_result.get("evidenceFile") or publish_info["evidenceFile"]),
        }
    )
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

    prompt = _build_outline_prompt(manifest_path, bid_type)
    try:
        return _load_outline_result(
            OpencodeClient().generate_outline_with_trace(
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
                early_tool_command=_outline_skill_command(bid_type),
            ),
            manifest_path,
        )
    except Exception as exc:
        if progress_callback:
            progress_callback(
                "outline_fallback",
                {"error": str(exc), "manifestPath": str(manifest_path)},
            )
        fallback = _run_local_outline_skill(manifest_path)
        return _load_outline_result(fallback, manifest_path)


def _run_business_outline_skill(
    manifest_path: Path,
    *,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    prompt = _build_business_outline_prompt(manifest_path)
    try:
        result = OpencodeClient(timeout_ms=int(settings.opencode_timeout_sec * 1000)).generate_outline_with_trace(
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
        )
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
    return _load_outline_result(result, manifest_path)


def _run_local_outline_skill(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    skill_name = _outline_skill_name(manifest.get("bidType"))
    completed = subprocess.run(
        [
            sys.executable,
            str(_outline_skill_runner(skill_name)),
            "--manifest",
            str(manifest_path),
            "--response",
            "summary",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, int(settings.opencode_timeout_sec)),
    )
    result = json.loads(completed.stdout)
    result["opencodeOutput"] = {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": skill_name,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": completed.stdout.strip()}],
    }
    return result


def _build_outline_prompt(manifest_path: Path, bid_type: Any) -> str:
    bid_type_text = require_bid_type(
        bid_type,
        error_message="目录生成必须显式传入技术标或商务标。",
    )
    if _is_business_bid(bid_type_text):
        return _build_business_outline_prompt(manifest_path)
    skill_name = _outline_skill_name(bid_type_text)
    skill_command = _outline_skill_command(bid_type_text)
    return f"""
Use the {skill_name} skill.

你现在在做 S2 {bid_type_text}目录生成。后端已经准备好 manifest，其中只包含招标文件、投标模板、可选附表模板和输出路径。

manifest：{manifest_path}

请先直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径：

{skill_command} {manifest_path}

命令会写入 outputFile/evidenceFile/agentReviewFile，并在 stdout 打印小型 JSON。stdout 已包含 agentReviewDigest，请只根据 stdout 里的 agentReviewDigest 做一次语义审核。
不要读取、cat、head、tail、grep outputFile/evidenceFile/agentReviewFile；这些文件由后端读取并保存。
1. 判断招标要求是否已被模板目录覆盖，把可靠依据绑定到对应目录项。
2. 招标明确要求的附表/副表只能放在目录末尾，不要穿插进中间章节。
3. 不确定的要求只写入 evidence/decisions，不强行新增目录。
4. 保持 outputFile 是干净的 bid-toc-json-v1，items[] 里不要出现素材库字段以外的冗余解释；material_refs 固定为空数组。
5. source_refs[] 必须保留可跳转字段，searchText 使用招标原文片段。

如需调整，请直接修改 outputFile 和 evidenceFile。最后只返回严格 JSON，不要 Markdown，不要解释文字：
{{
  "schema_version": "bid-toc-json-v1",
  "outputFile": "<outputFile from manifest>",
  "evidenceFile": "<evidenceFile from manifest>",
  "summary": {{"total_items": 0}},
  "agentDecisions": []
}}
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

def _load_outline_result(result: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_file = Path(str(result.get("outputFile") or manifest.get("outputFile") or "")).expanduser()
    evidence_file = Path(str(result.get("evidenceFile") or manifest.get("evidenceFile") or "")).expanduser()
    is_business_bid = _is_business_bid(manifest.get("bidType"))
    if is_business_bid:
        return _load_business_outline_result(result, manifest, output_file, evidence_file)

    if not output_file.exists():
        raise RuntimeError(f"S2 目录 Skill 未生成 outputFile：{output_file}")

    toc = json.loads(output_file.read_text(encoding="utf-8"))
    if not isinstance(toc, dict) or not isinstance(toc.get("items"), list):
        raise RuntimeError("S2 目录 Skill 输出不是有效 bid-toc-json-v1。")
    if isinstance(result.get("items"), list):
        toc["items"] = _clean_toc_items(result["items"])
        _rewrite_toc_file(output_file, toc, evidence_file)
    elif isinstance(result.get("agentDecisions"), list):
        toc = _apply_agent_decisions(toc, result["agentDecisions"], evidence_file)
        _rewrite_toc_file(output_file, toc, evidence_file, agent_decisions=result["agentDecisions"])
    else:
        toc["items"] = _clean_toc_items(toc["items"])
        _rewrite_toc_file(output_file, toc, evidence_file)

    toc["outputFile"] = str(output_file)
    toc["evidenceFile"] = str(evidence_file)
    if isinstance(result.get("opencodeOutput"), dict):
        toc["opencodeOutput"] = result["opencodeOutput"]
    toc["ruleEvidence"] = _public_rule_evidence_from_file(evidence_file)
    return toc


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
    items = _clean_toc_items(toc.get("items") if isinstance(toc.get("items"), list) else [])
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
        material_refs = item.get("material_refs")
        if not isinstance(material_refs, list):
            material_refs = item.get("materialRefs") if isinstance(item.get("materialRefs"), list) else []
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
                "material_refs": [ref for ref in material_refs if isinstance(ref, dict)],
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
    candidates = evidence.get("tenderCandidates") if isinstance(evidence.get("tenderCandidates"), list) else []
    template_outline = evidence.get("templateOutline") if isinstance(evidence.get("templateOutline"), list) else []
    return {
        "schemaVersion": str(evidence.get("schema_version") or ""),
        "engine": str(evidence.get("engine") or ""),
        "templateOutlineCount": len(template_outline),
        "tenderCandidateCount": len(candidates),
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


def _prepare_toc_skill_workspace(
    *,
    project_id: str,
    project: dict[str, Any],
    parse_storage: dict[str, Any],
    tender_file_records: list[dict[str, Any]],
    template_file_records: list[dict[str, Any]],
) -> dict[str, Any]:
    bid_type = _outline_bid_type(str(project.get("bidType") or ""))
    project_dir = workspace_dir(project_id, bid_type)
    project_dir.mkdir(parents=True, exist_ok=True)

    published_work_dir = project_dir / "s2_toc_workdir"
    staging_work_dir = project_dir / "s2_toc_workdir.new"
    archive_root = project_dir / "s2_toc_workdir.runs"
    _archive_workspace_if_exists(staging_work_dir, archive_root, "stale")
    staging_work_dir.mkdir(parents=True, exist_ok=True)
    _remove_manifest_alias(project_dir)

    tender_inputs = _copy_tender_inputs(tender_file_records, staging_work_dir, parse_storage)
    template_path, attach_path = _copy_template_inputs(template_file_records, staging_work_dir, project_id)
    if template_path is None:
        raise ValueError("投标模板不存在，请先上传可读取的投标模板文件。")
    output_file = staging_work_dir / _safe_file_name(settings.s2_toc_output_file_name, "toc.json")
    evidence_file = staging_work_dir / _safe_file_name(settings.s2_toc_evidence_file_name, "toc_evidence.json")
    manifest_path = staging_work_dir / "s2_input.json"
    manifest = {
        "projectId": project_id,
        "projectCode": str(project.get("projectCode") or project_id),
        "projectName": str(project.get("name") or project_id),
        "bidType": bid_type,
        "workDir": str(staging_work_dir),
        "tenderFiles": tender_inputs,
        "templateFile": str(template_path) if template_path else "",
        "attachFile": str(attach_path) if attach_path else "",
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
        "reviewBudget": OUTLINE_REVIEW_BUDGET,
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    return {
        **manifest,
        "manifestPath": str(manifest_path),
        "canonicalManifestPath": str(manifest_path),
        "publishedWorkDir": str(published_work_dir),
        "stagingWorkDir": str(staging_work_dir),
        "archiveRoot": str(archive_root),
        "tenderFileCount": len(tender_inputs),
        "templateFileCount": 1 if template_path else 0,
        "hasAttachFile": bool(attach_path),
    }


def _publish_toc_skill_workspace(skill_workspace: dict[str, Any], toc_result: dict[str, Any]) -> dict[str, Any]:
    staging_work_dir = Path(str(skill_workspace.get("stagingWorkDir") or skill_workspace.get("workDir") or "")).expanduser()
    published_work_dir = Path(str(skill_workspace.get("publishedWorkDir") or skill_workspace.get("workDir") or "")).expanduser()
    archive_root = Path(str(skill_workspace.get("archiveRoot") or published_work_dir.with_name("s2_toc_workdir.runs"))).expanduser()
    if not staging_work_dir.exists():
        raise RuntimeError(f"S2 staging 工作目录不存在：{staging_work_dir}")

    replacements = {str(staging_work_dir): str(published_work_dir)}
    staging_manifest_path = staging_work_dir / "s2_input.json"
    manifest = _load_json_dict(staging_manifest_path)
    staging_output_file = Path(
        str(manifest.get("outputFile") or staging_work_dir / _safe_file_name(settings.s2_toc_output_file_name, "toc.json"))
    ).expanduser()
    staging_evidence_file = Path(
        str(manifest.get("evidenceFile") or staging_work_dir / _safe_file_name(settings.s2_toc_evidence_file_name, "toc_evidence.json"))
    ).expanduser()
    manifest = _remap_workspace_paths(manifest, replacements)
    manifest_path = published_work_dir / "s2_input.json"
    output_file = Path(
        str(manifest.get("outputFile") or published_work_dir / _safe_file_name(settings.s2_toc_output_file_name, "toc.json"))
    ).expanduser()
    evidence_file = Path(
        str(manifest.get("evidenceFile") or published_work_dir / _safe_file_name(settings.s2_toc_evidence_file_name, "toc_evidence.json"))
    ).expanduser()
    business_outline_file = published_work_dir / "outline.json"
    tender_map_inputs_file = published_work_dir / "tender_map_inputs.json"
    history_bid_outline_inputs_file = published_work_dir / "history_bid_outline_inputs.json"
    manifest["workDir"] = str(published_work_dir)
    manifest["outputFile"] = str(output_file)
    manifest["evidenceFile"] = str(evidence_file)
    staging_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    _remap_json_file(staging_output_file, replacements, {"outputFile": str(output_file), "evidenceFile": str(evidence_file)})
    _remap_json_file(staging_evidence_file, replacements)
    _remap_json_file(staging_work_dir / "outline.json", replacements)
    _remap_json_file(staging_work_dir / "tender_map_inputs.json", replacements)
    _remap_json_file(staging_work_dir / "history_bid_outline_inputs.json", replacements)

    result = _remap_workspace_paths(toc_result, replacements)
    result["outputFile"] = str(output_file)
    result["evidenceFile"] = str(evidence_file)
    if (staging_work_dir / "outline.json").exists():
        result["businessOutlineFile"] = str(business_outline_file)
    if (staging_work_dir / "tender_map_inputs.json").exists():
        result["tenderMapInputsFile"] = str(tender_map_inputs_file)
    if (staging_work_dir / "history_bid_outline_inputs.json").exists():
        result["historyBidOutlineInputsFile"] = str(history_bid_outline_inputs_file)
    if isinstance(result.get("opencodeOutput"), dict):
        result["opencodeOutput"]["workDir"] = str(published_work_dir)
        result["opencodeOutput"]["manifestPath"] = str(manifest_path)
        result["opencodeOutput"]["canonicalManifestPath"] = str(manifest_path)
        result["opencodeOutput"]["tocJsonPath"] = str(output_file)
        result["opencodeOutput"]["evidencePath"] = str(evidence_file)
        if (staging_work_dir / "outline.json").exists():
            result["opencodeOutput"]["businessOutlinePath"] = str(business_outline_file)
        if (staging_work_dir / "tender_map_inputs.json").exists():
            result["opencodeOutput"]["tenderMapInputsPath"] = str(tender_map_inputs_file)
        if (staging_work_dir / "history_bid_outline_inputs.json").exists():
            result["opencodeOutput"]["historyBidOutlineInputsPath"] = str(history_bid_outline_inputs_file)

    previous_archive = ""
    try:
        previous_archive = _archive_workspace_if_exists(published_work_dir, archive_root, "previous")
        published_work_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_work_dir), str(published_work_dir))
    except Exception:
        previous_archive_path = Path(previous_archive) if previous_archive else None
        if previous_archive_path and previous_archive_path.exists() and not published_work_dir.exists():
            shutil.move(str(previous_archive_path), str(published_work_dir))
        raise

    return {
        "result": result,
        "workDir": str(published_work_dir),
        "stagingWorkDir": str(staging_work_dir),
        "archiveRoot": str(archive_root),
        "previousArchive": previous_archive,
        "manifestPath": str(manifest_path),
        "canonicalManifestPath": str(manifest_path),
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
    }


def _archive_workspace_if_exists(target: Path, archive_root: Path, label: str) -> str:
    if not target.exists():
        return ""
    archive_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = _unique_path(archive_root / f"{timestamp}-{label}-{target.name}")
    shutil.move(str(target), str(archive_path))
    return str(archive_path)


def _remove_manifest_alias(project_dir: Path) -> None:
    alias_path = project_dir / "s2.json"
    if alias_path.exists():
        alias_path.unlink()


def _remap_json_file(path: Path, replacements: dict[str, str], updates: dict[str, Any] | None = None) -> None:
    if not path.exists():
        return
    payload = _remap_workspace_paths(_load_json_dict(path), replacements)
    if updates:
        payload.update(updates)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _remap_workspace_paths(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        result = value
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result
    if isinstance(value, list):
        return [_remap_workspace_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _remap_workspace_paths(item, replacements) for key, item in value.items()}
    return value


def _heading_style_for_line(line: str) -> str | None:
    text = str(line or "").strip()
    if re.match(r"^第[一二三四五六七八九十百千万零〇两0-9]+章", text):
        return "Heading 1"
    match = re.match(r"^(?P<number>\d+(?:\.\d+)*)(?:[\s　:：、.-]+)", text)
    if not match:
        return None
    level = min(match.group("number").count(".") + 1, 4)
    return f"Heading {level}"


def _write_text_docx(path: Path, title: str, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_paragraph(title)
    for line in str(text or "").splitlines():
        if line.strip():
            style = _heading_style_for_line(line)
            document.add_paragraph(line.strip(), style=style) if style else document.add_paragraph(line.strip())
    document.save(path)
    return path


def _copy_tender_inputs(file_records: list[dict[str, Any]], work_dir: Path, parse_storage: dict[str, Any]) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for index, record in enumerate(file_records, start=1):
        source = Path(str(record.get("path") or "")).expanduser()
        if not source.exists() or source.suffix.lower() != ".docx":
            continue
        name = _safe_file_name(str(record.get("name") or source.name), f"tender-{index}.docx")
        destination = _unique_path(work_dir / name)
        shutil.copy2(source, destination)
        copied.append(
            {
                "id": str(record.get("id") or f"tender-{index}"),
                "name": name,
                "path": str(destination),
                "originalPath": str(source),
            }
        )
    if not copied:
        combined_text_path = Path(str(parse_storage.get("combinedTextPath") or "")).expanduser()
        if combined_text_path.exists():
            text = combined_text_path.read_text(encoding="utf-8", errors="replace")
            generated_path = _write_text_docx(work_dir / "tender-from-s1-text.docx", "招标文件解析文本", text)
            copied.append(
                {
                    "id": "TEN-S1-TEXT",
                    "name": "招标文件解析文本.docx",
                    "path": str(generated_path),
                    "originalPath": str(combined_text_path),
                }
            )
    return copied


def _copy_template_inputs(file_records: list[dict[str, Any]], work_dir: Path, project_id: str) -> tuple[Path | None, Path | None]:
    docx_records = [
        record
        for record in file_records
        if Path(str(record.get("path") or "")).expanduser().exists()
        and Path(str(record.get("path") or "")).suffix.lower() == ".docx"
    ]
    attach_record = next((record for record in docx_records if _looks_like_attachment_template(record)), None)
    template_record = next(
        (
            record
            for record in docx_records
            if record is not attach_record
        ),
        None,
    )
    if template_record is None and docx_records:
        template_record = docx_records[0]

    template_path = None
    if template_record is not None:
        template_path = _copy_single_template(template_record, work_dir / "template-main.docx")
    elif file_records:
        template_path = _copy_visual_template_input(project_id, file_records[0], work_dir / "template-main.docx")
    attach_path = (
        _copy_single_template(attach_record, work_dir / "template-attachment.docx")
        if attach_record is not None and attach_record is not template_record
        else None
    )
    return template_path, attach_path


def _looks_like_attachment_template(record: dict[str, Any]) -> bool:
    role = str(record.get("role") or record.get("templateRole") or record.get("type") or "").lower()
    if role in {"attachment", "attachments", "appendix", "appendices", "attach"}:
        return True
    name = str(record.get("name") or Path(str(record.get("path") or "")).name)
    return bool(re.search(r"(附表|附件|appendix|attachment|attach)", name, re.IGNORECASE))


def _copy_single_template(record: dict[str, Any], destination: Path) -> Path:
    source = Path(str(record.get("path") or "")).expanduser()
    if source.suffix.lower() == ".docx" and not is_valid_docx_file(source):
        source_label = "系统默认模板" if str(record.get("source") or "") == "system-default" else "投标模板"
        raise ValueError(f"{source_label}不是有效 DOCX 文件，请重新上传或更换默认模板。")
    resolved_destination = destination.with_suffix(source.suffix.lower() or ".docx")
    shutil.copy2(source, resolved_destination)
    return resolved_destination


def _copy_visual_template_input(project_id: str, record: dict[str, Any], destination: Path) -> Path | None:
    source = Path(str(record.get("path") or "")).expanduser()
    if not source.exists() or source.suffix.lower() not in {".pdf", *IMAGE_SUFFIXES}:
        return None
    text, meta = _ocr_fallback_text(project_id, record, source)
    if not text:
        message = meta.get("message") if isinstance(meta, dict) else ""
        raise ValueError(f"投标模板为图片或 PDF，但视觉模型未能读取：{message or '未知错误'}")
    return _write_text_docx(destination, str(record.get("name") or source.name), text)


def _safe_file_name(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法为文件生成唯一路径：{path}")


def _outline_bid_type(value: str) -> str:
    return require_bid_type(
        value,
        error_message="目录工作区必须显式传入技术标或商务标。",
    )


def _nodes_from_generation_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("items"), list):
        return _nodes_from_toc_items(result["items"])
    raise ValueError("目录 JSON 缺少 items[]。")


def _summary_from_generation_result(result: dict[str, Any]) -> str:
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if isinstance(summary, dict):
        total_items = summary.get("total_items")
        annotation_counts = summary.get("annotation_counts") or {}
        if isinstance(annotation_counts, dict) and annotation_counts:
            counts = "，".join(
                f"{key}{value}"
                for key, value in annotation_counts.items()
                if value
            )
            if counts:
                return f"目录生成完成，共 {total_items or 0} 条目录项（{counts}）。"
        return f"目录生成完成，共 {total_items or 0} 条目录项。"
    return "目录生成完成。"


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


def _coerce_toc_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 1
    return max(1, level)


def _toc_item_title(item: dict[str, Any], fallback_order: int) -> str:
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
