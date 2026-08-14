"""S1 解析 Skill 会话链路：prompt 构建、s1parse CLI、技术标分片调度、商务 finalize 收口与项目预填。

来源：parsing-01 拆分，自 app/services/parsing.py 逐字搬迁，实现与行为不变；
符号经 parsing.py 门面 re-export，外部仍按 `app.services.parsing.<符号>` 访问。
import 期副作用（`PARSER_CORE_DIR`/`sys.path.insert`/`parser_core` import）单点在本模块。
"""
from __future__ import annotations

import copy
import json
import logging
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.services.agent_engine.concurrency import AGENT_CONCURRENCY_BUDGET
from app.services.agent_engine.factory import AgentEngineFactory
from app.services.agent_engine.orchestrator import AgentOrchestrator
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.parse_business_fields import _is_normalized_bid_deadline, _normalize_bid_deadline
from app.services.parse_common import _raise_if_parse_cancelled, _run_coroutine_blocking
from app.services.parse_profiles import (
    BUSINESS_PARSE_PROFILE,
    ParseProfile,
    TECHNICAL_PARSE_SKILL_NAME,
)
from app.services.system_settings import system_settings_service

PARSER_CORE_DIR = (
    Path(__file__).resolve().parents[2] / "opencode" / "skills" / TECHNICAL_PARSE_SKILL_NAME / "scripts"
)
if str(PARSER_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_CORE_DIR))

# parser_core 经上面的 sys.path 注入解析；parse_structured_documents 供 parsing.py 门面 re-export 使用。
from parser_core import parse_documents as parse_structured_documents  # noqa: E402

logger = logging.getLogger(__name__)


def _build_tender_parse_prompt(skill_manifest_path: Path, profile: ParseProfile) -> str:
    if profile.key == "business":
        return f"""
Use the {profile.skill_name} skill.

你在做 S1 商务招标文件结构化解析。业务任务书、交付清单和语义原则以 skill 内的 `SKILL.md` 为准；本提示只约束执行链路。

manifest：{skill_manifest_path}

必须用 Bash 按顺序执行 `s1parse` 小输出链路，timeout 设置为 600000 毫秒或更高：

s1parse prepare {skill_manifest_path}
s1parse overview {skill_manifest_path} --page 1 --page-size 60
s1parse search {skill_manifest_path} "<query>" --limit 40
s1parse read {skill_manifest_path} <evidenceId> --mode summary --max-chars 4000
s1parse window {skill_manifest_path} <evidenceId> --before 4 --after 6
s1parse table {skill_manifest_path} <tableId> --rows 1-24 --max-chars 8000
s1parse submit {skill_manifest_path} projectBasics '<json>'
s1parse submit {skill_manifest_path} qualificationRequirements '<json>'
s1parse submit {skill_manifest_path} bidderInstructions '<json>'
s1parse submit {skill_manifest_path} commercialRejectionClauses '<json>'
s1parse submit {skill_manifest_path} businessScoringCriteria '<json>'
s1parse validate {skill_manifest_path}
s1parse status {skill_manifest_path}
s1parse finalize {skill_manifest_path}

禁止用 opencode 的 read 工具读取或打印解析中间产物的大 JSON；证据定位必须通过 s1parse 小输出导航命令完成。禁止调用 Task/subagent/子代理/任务委派工具。

表格类内容必须完整读取后再提交：遇到投标人须知前附表、商务评分表、否决/符合性审查表等目标表格时，先确认表格总行数，再连续读取完整表格；如输出提示仍有剩余行或内容被截断，必须继续读取剩余行/完整行。提交时不得基于预览、summary 或局部行推断，不得摘要改写原表格编列内容。

只使用 s1parse 返回过的 evidenceId，不要编造证据。提交值必须能被对应证据文本直接支撑，项目基础信息至少为项目名称、招标人、递交截止时间提交字段级 evidenceIds。validate 失败时继续回查并重新 submit；若仍失败，必须让 workflow 暴露 missingTargets 或 validationErrors，不能把失败结果说成成功。必须执行 finalize，最终结构化 JSON 必须由 finalize 写入 manifest.structuredResultPath。

最后只返回 finalize 命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schemaVersion": "{profile.schema_version}",
  "targetSkill": "{profile.skill_name}",
  "outputFile": "manifest 中的 structuredResultPath",
  "summary": {{"itemCount": 0, "targetCounts": {{}}, "scoringCounts": {{"business": 0}}, "workflowStage": "finalized", "projectDates": {{"startDate": "", "endDate": ""}}}}
}}

完整 JSON 必须包含 structured.sourceDocuments、structured.scoringCriteria、structured.fieldGroups、structured.projectFactFields、structured.projectDates、structured.coverage、structured.workflow，且 workflow.mode 为 opencode-agentic-navigation。
""".strip()
    return f"""
Use the {profile.skill_name} skill.

你在做 S1 技术标解读。业务任务书、内置 58 条技术标解读清单、状态定义和证据要求以 skill 内的 `SKILL.md` 为准；本提示只约束执行链路。

manifest：{skill_manifest_path}

必须用 Bash 按顺序执行 `s1parse` 小输出链路，timeout 设置为 600000 毫秒或更高：

s1parse prepare {skill_manifest_path}
s1parse overview {skill_manifest_path} --page 1 --page-size 30
s1parse search {skill_manifest_path} "<query>" --limit 20
s1parse read {skill_manifest_path} <evidenceId> --mode summary --max-chars 2000
s1parse window {skill_manifest_path} <evidenceId> --before 4 --after 6
s1parse table {skill_manifest_path} <tableId> --rows 1-12 --max-chars 4000
s1parse submit {skill_manifest_path} projectBasics '<json>'
s1parse submit {skill_manifest_path} technicalInterpretation '<json>'
s1parse validate {skill_manifest_path}
s1parse status {skill_manifest_path}
s1parse finalize {skill_manifest_path}

禁止用 opencode 的 read 工具读取或打印解析中间产物的大 JSON；证据定位必须通过 s1parse 小输出导航命令完成。禁止调用 Task/subagent/子代理/任务委派工具。

项目基础信息必须按六项提交到 `projectBasics`：项目名称 `projectName`、招标编号 `tenderNo`、项目单位 `projectUnit`、招标人 `tenderer`、招标代理机构 `tenderAgency`、递交截止时间 `bidDeadline`。每条基础信息必须显式提交标准 key 或 fieldKey，label 只作展示，不会被脚本用来归一；原文中的不同叫法由你结合上下文和证据自主判断后归入上述标准 key。封面、公告、前附表都是可用证据来源，不要因为信息位于封面而跳过。递交截止时间指投标/响应文件最晚递交或提交时间，不要把交货期、供货期、服务期、工期等履约日期当作截止时间。六项按当前文件可支撑内容提交，不能空交付；项目名称、招标人、递交截止时间如有值必须带字段级 evidenceIds，提交值必须能被证据文本直接支撑。

只使用 s1parse 返回过的 evidenceId，不要编造证据。`found` 和 `partial` 必须有证据；`needs_spec` 必须写 `neededSourceName`，且使用招标文件原文里的卷册、附件或附表叫法，不要固定写“第二卷技术规范书”。validate 失败时继续回查并重新 submit；必须执行 finalize，最终结构化 JSON 必须由 finalize 写入 manifest.structuredResultPath。

最后只返回 finalize 命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schemaVersion": "{profile.schema_version}",
  "targetSkill": "{profile.skill_name}",
  "outputFile": "manifest 中的 structuredResultPath",
  "summary": {{"itemCount": 58, "checklistCount": 58, "statusCounts": {{"found": 0, "partial": 0, "missing": 0, "needs_spec": 0}}, "workflowStage": "finalized"}}
}}

完整 JSON 必须包含 structured.sourceDocuments、structured.fieldGroups.projectBasics、structured.projectFactFields、structured.technicalInterpretation、structured.workflow，且 workflow.mode 为 opencode-agentic-navigation。
""".strip()


def _build_technical_project_basics_prompt(skill_manifest_path: Path, profile: ParseProfile) -> str:
    return f"""
Use the {profile.skill_name} skill.

你在做 S1 技术标解读，本次会话只负责一个目标：项目基础信息 `projectBasics`。技术解读清单由其他并发会话负责，你不要碰。

manifest：{skill_manifest_path}

导航索引已由后端准备完毕，不要执行 `s1parse prepare`，也不要执行 `s1parse validate` / `s1parse finalize`——收口由后端统一完成。

必须用 Bash 执行 `s1parse` 小输出命令，timeout 设置为 600000 毫秒或更高。`s1parse search` 支持一次传多个关键词，请尽量合并成一条命令，减少往返：

s1parse overview {skill_manifest_path} --page 1 --page-size 30
s1parse search {skill_manifest_path} "招标编号" "招标人" "递交截止" "招标代理" --limit 15
s1parse window {skill_manifest_path} <evidenceId> --before 4 --after 6
s1parse submit {skill_manifest_path} projectBasics '<json>'

项目基础信息必须按六项提交：项目名称 `projectName`、招标编号 `tenderNo`、项目单位 `projectUnit`、招标人 `tenderer`、招标代理机构 `tenderAgency`、递交截止时间 `bidDeadline`。每条必须显式提交标准 key 或 fieldKey，label 只作展示。原文中的不同叫法由你结合上下文归入标准 key。封面、公告、前附表都是可用证据来源。递交截止时间只指投标/响应文件最晚递交、提交截止或开标时间，不要把交货期、供货期、服务期、工期当作截止时间。

只使用 s1parse 返回过的 evidenceId，不要编造证据。项目名称、招标人、递交截止时间如有值必须带字段级 evidenceIds，提交值必须能被证据文本直接支撑。当前文件确实没有的字段，仍按标准 key 提交，status 写 missing 或 needs_spec，value 写明未提及并建议补充上传对应文件。

完成 submit 后直接结束，只返回 submit 命令 stdout 的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def _build_technical_shard_prompt(
    skill_manifest_path: Path,
    profile: ParseProfile,
    shard: dict[str, Any],
) -> str:
    shard_key = str(shard["key"])
    row_nos = ", ".join(str(row_no) for row_no in shard["rowNos"])
    return f"""
Use the {profile.skill_name} skill.

你在做 S1 技术标解读。本次会话只负责技术解读清单的一个分片：`{shard_key}`（{shard["label"]}），共 {len(shard["rowNos"])} 行，行号为 {row_nos}。其余清单行由其他并发会话负责，你不要判断、不要提交。

manifest：{skill_manifest_path}

导航索引已由后端准备完毕，不要执行 `s1parse prepare`，也不要执行 `s1parse validate` / `s1parse finalize`——收口由后端在所有分片完成后统一执行。

第一步必须先取回本分片的清单行和预检索命中：

s1parse checklist {skill_manifest_path} --shard {shard_key}

返回的每行都带 `hints`，那是后端按「具体内容」离线预检索出的候选证据，直接可用。先看 hints 判断够不够，只在 hints 不足以支撑结论时才补充检索。

补充检索时 `s1parse search` 支持一次传多个关键词，必须合并成一条命令，不要一个关键词发一次：

s1parse search {skill_manifest_path} "关键词A" "关键词B" "关键词C" --limit 20
s1parse read {skill_manifest_path} <evidenceId> --mode summary --max-chars 2000
s1parse window {skill_manifest_path} <evidenceId> --before 4 --after 6
s1parse table {skill_manifest_path} <tableId> --rows 1-12 --max-chars 4000

判断完本分片全部 {len(shard["rowNos"])} 行后，一次性提交：

s1parse submit {skill_manifest_path} technicalInterpretation '<json>' --shard {shard_key}

提交数组只能包含本分片的行号 {row_nos}；提交越界行号会被脚本硬拒绝。每条字段为 rowNo、status、conclusion、evidenceSummary、evidenceIds，needs_spec 时另加 neededSourceName。status 只能是 found、partial、missing、needs_spec，判定口径以 SKILL.md 为准。

禁止用 opencode 的 read 工具读取或打印大 JSON；证据定位必须通过 s1parse 小输出命令完成。禁止调用 Task/subagent/子代理/任务委派工具。只使用 s1parse 返回过的 evidenceId，不要编造证据。found 和 partial 必须有 evidenceIds；needs_spec 必须写招标文件原文里的 neededSourceName，不要固定写“第二卷技术规范书”。

完成 submit 后直接结束，只返回 submit 命令 stdout 的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def _build_tender_parse_retry_prompt(
    skill_manifest_path: Path,
    profile: ParseProfile,
    first_error: RuntimeError,
) -> str:
    failure = str(first_error)
    if profile.key != "business":
        return f"""
Use the {profile.skill_name} skill.

这是同一个 S1 技术标解读任务的一次恢复重试。第一次 opencode 会话没有完成 finalize，失败原因如下：
{failure}

manifest：{skill_manifest_path}

不要重新发散式探索，不要读取或打印大 JSON，不要调用 Task/subagent/子代理/任务委派工具。必须使用 Bash 继续完成同一条 `s1parse` 工作流，timeout 设置为 600000 毫秒或更高。

按下面顺序执行：

s1parse status {skill_manifest_path}
s1parse submit {skill_manifest_path} projectBasics '<json>'
s1parse submit {skill_manifest_path} technicalInterpretation '<json>'
s1parse validate {skill_manifest_path}
s1parse status {skill_manifest_path}
s1parse finalize {skill_manifest_path}

如果 status 显示已有提交项，只补缺失或校验失败项；如果证据不足，只用 s1parse search/read/window/table 做最小回查。项目基础信息仍按六项提交到 `projectBasics`，每条必须显式提交标准 key 或 fieldKey，不能空交付；项目名称、招标人、递交截止时间如有值必须带字段级 evidenceIds。`needs_spec` 必须写招标文件原文里的 `neededSourceName`。必须执行 finalize，最终结构化 JSON 必须由 finalize 写入 manifest.structuredResultPath。

最后只返回 finalize 命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。返回格式必须是：
{{
  "schemaVersion": "{profile.schema_version}",
  "targetSkill": "{profile.skill_name}",
  "outputFile": "manifest 中的 structuredResultPath",
  "summary": {{"itemCount": 58, "checklistCount": 58, "statusCounts": {{"found": 0, "partial": 0, "missing": 0, "needs_spec": 0}}, "workflowStage": "finalized"}}
}}
""".strip()
    return f"""
Use the {profile.skill_name} skill.

这是同一个 S1 商务招标文件结构化解析任务的一次恢复重试。第一次 opencode 会话没有完成 finalize，失败原因如下：
{failure}

manifest：{skill_manifest_path}

不要重新发散式探索，不要读取或打印大 JSON，不要调用 Task/subagent/子代理/任务委派工具。必须使用 Bash 继续完成同一条 `s1parse` 工作流，timeout 设置为 600000 毫秒或更高。

按下面顺序执行：

s1parse status {skill_manifest_path}
s1parse submit {skill_manifest_path} projectBasics '<json>'
s1parse submit {skill_manifest_path} qualificationRequirements '<json>'
s1parse submit {skill_manifest_path} bidderInstructions '<json>'
s1parse submit {skill_manifest_path} commercialRejectionClauses '<json>'
s1parse submit {skill_manifest_path} businessScoringCriteria '<json>'
s1parse validate {skill_manifest_path}
s1parse status {skill_manifest_path}
s1parse finalize {skill_manifest_path}

如果 status 显示已有提交项，只补缺失项；如果证据不足，只用 s1parse search/read/window/table 做最小回查。validate 失败时继续补 submit 并重新 validate。必须执行 finalize，最终结构化 JSON 必须由 finalize 写入 manifest.structuredResultPath。

最后只返回 finalize 命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。返回格式必须是：
{{
  "schemaVersion": "{profile.schema_version}",
  "targetSkill": "{profile.skill_name}",
  "outputFile": "manifest 中的 structuredResultPath",
  "summary": {{"itemCount": 0, "targetCounts": {{}}, "scoringCounts": {{"business": 0}}, "workflowStage": "finalized", "projectDates": {{"startDate": "", "endDate": ""}}}}
}}
""".strip()


def _resolve_skill_structured_result(
    result: dict[str, Any],
    *,
    local_result: dict[str, Any],
    profile: ParseProfile,
) -> dict[str, Any]:
    output_file = Path(str(result.get("outputFile") or ""))
    if output_file.exists():
        loaded = json.loads(output_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
            resolved = loaded
        elif profile.key == "business":
            raise RuntimeError(f"S1 商务解析 Skill 输出结构不合法：{output_file}")
        else:
            resolved = local_result
    elif isinstance(result.get("items"), list):
        resolved = {
            "items": result.get("items") or [],
            "structured": result.get("structured") if isinstance(result.get("structured"), dict) else {},
        }
    elif profile.key == "business":
        raise RuntimeError("S1 商务解析 Skill 未返回结构化 items。")
    else:
        resolved = local_result

    structured = resolved.setdefault("structured", {})
    if isinstance(structured, dict):
        local_structured = local_result.get("structured") if isinstance(local_result, dict) else {}
        if profile.key != "business" and isinstance(local_structured, dict):
            for key in ["sourceDocuments", "fieldGroups", "scoringCriteria", "requirementPresence", "coverage", "appendices"]:
                if not structured.get(key) and local_structured.get(key):
                    structured[key] = local_structured[key]
        structured["targetSkill"] = profile.skill_name
        structured["mode"] = "opencode-skill"
        if isinstance(result.get("opencodeOutput"), dict):
            structured["opencodeOutput"] = copy.deepcopy(result.get("opencodeOutput") or {})
        elif isinstance(local_structured, dict) and isinstance(local_structured.get("opencodeOutput"), dict):
            structured["opencodeOutput"] = copy.deepcopy(local_structured.get("opencodeOutput") or {})
        _apply_opencode_trace_to_workflow(structured)
        structured["schemaVersion"] = str(structured.get("schemaVersion") or profile.schema_version)
    return resolved


def _apply_opencode_trace_to_workflow(structured: dict[str, Any]) -> None:
    trace = structured.get("opencodeOutput") if isinstance(structured.get("opencodeOutput"), dict) else {}
    if not isinstance(trace, dict) or not trace:
        return
    workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
    workflow = copy.deepcopy(workflow)
    session_id = str(trace.get("sessionId") or "").strip()
    if session_id:
        workflow["opencodeSessionId"] = session_id
    agent_status = str(trace.get("agentStatus") or trace.get("status") or "").strip()
    if agent_status:
        workflow["opencodeAgentStatus"] = agent_status
    last_tool = str(trace.get("lastTool") or "").strip()
    if last_tool:
        workflow["opencodeLastTool"] = last_tool
    last_tool_status = str(trace.get("lastToolStatus") or "").strip()
    if last_tool_status:
        workflow["opencodeLastToolStatus"] = last_tool_status
    failure_reason = str(trace.get("failureReason") or "").strip()
    if failure_reason:
        workflow["opencodeFailureReason"] = failure_reason
    elif "opencodeFailureReason" not in workflow:
        workflow["opencodeFailureReason"] = ""
    if workflow:
        structured["workflow"] = workflow


def _opencode_attempt_from_error(exc: RuntimeError, attempt: int) -> dict[str, Any]:
    trace = getattr(exc, "opencode_trace", None)
    if not isinstance(trace, dict):
        trace = {"status": "error", "failureReason": str(exc)}
    attempt_payload = {
        "attempt": attempt,
        "status": str(trace.get("status") or trace.get("agentStatus") or "error"),
        "sessionId": str(trace.get("sessionId") or ""),
        "providerId": str(trace.get("providerId") or ""),
        "modelId": str(trace.get("modelId") or ""),
        "agentStatus": str(trace.get("agentStatus") or trace.get("status") or ""),
        "failureReason": str(trace.get("failureReason") or str(exc)),
    }
    for key in ("lastTool", "lastToolStatus", "lastToolInput", "errorName", "errorStatusCode"):
        if key in trace:
            attempt_payload[key] = copy.deepcopy(trace.get(key))
    return attempt_payload


def _attach_opencode_attempts(structured_result: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    if not attempts:
        return structured_result
    structured = structured_result.setdefault("structured", {})
    if not isinstance(structured, dict):
        return structured_result
    workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
    workflow = copy.deepcopy(workflow)
    workflow["opencodeAttempts"] = copy.deepcopy(attempts)
    structured["workflow"] = workflow
    return structured_result


def _fallback_parse_skill_result(
    exc: RuntimeError,
    *,
    local_result: dict[str, Any],
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    fallback = json.loads(json.dumps(local_result, ensure_ascii=False))
    structured = fallback.setdefault("structured", {})
    if isinstance(structured, dict):
        structured["mode"] = "local-structured-parser"
        structured["opencodeError"] = str(exc)
        trace = getattr(exc, "opencode_trace", None)
        if isinstance(trace, dict):
            structured["opencodeOutput"] = copy.deepcopy(trace)
            if progress_callback:
                progress_callback("opencode_delta", copy.deepcopy(trace))
            if not trace.get("failureReason"):
                structured["opencodeOutput"]["failureReason"] = str(exc)
            _apply_opencode_trace_to_workflow(structured)
        if attempts:
            workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
            workflow = copy.deepcopy(workflow)
            workflow["opencodeAttempts"] = copy.deepcopy(attempts)
            structured["workflow"] = workflow
    return fallback, f"S1 解析 Skill 调用失败，已使用本地结构化解析兜底：{exc}"


def _s1parse_runner_path() -> Path:
    return PARSER_CORE_DIR / "run_from_manifest.py"


def _run_s1parse_cli(command: str, skill_manifest_path: Path, *extra: str) -> dict[str, Any]:
    """后端侧确定性执行 s1parse 子命令。

    prepare 和 finalize 都不需要模型判断，交给模型只会白白多花 LLM 往返，
    而且并发分片下 prepare 必须只跑一次，否则多个会话会同时重建导航索引。
    """
    runner = _s1parse_runner_path()
    if not runner.is_file():
        raise RuntimeError(f"S1 技术标解析 runner 不存在：{runner}")
    try:
        completed = subprocess.run(
            [sys.executable, str(runner), command, str(skill_manifest_path), *extra],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"s1parse {command} 执行超时（600 秒）。") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"s1parse {command} 执行失败（exit={completed.returncode}）：{(completed.stderr or '').strip()[:600]}"
        )
    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError(f"s1parse {command} 没有返回任何输出。")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"s1parse {command} 输出不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"s1parse {command} 输出不是 JSON 对象。")
    return payload


# 分片会话的并发池：B4（engine-06）起从全局并发预算派生（agent_engine/concurrency.py），
# S1_PARSE_SHARD_CONCURRENCY 只是预算内的分片上限；预算、分片、目录章节三池共享
# 同一总量，总并发恒 ≤ AGENT_CONCURRENCY_BUDGET，不再叠加超发。
_S1_SHARD_REQUEST_SLOTS = AGENT_CONCURRENCY_BUDGET.derive(max(1, settings.s1_parse_shard_concurrency))


# 进度条第一行展示的条款数每次都要读提交文件，读盘节流到这个间隔，
# 避免 7 个分片的流式片段各触发一次 JSON 解析。
_SHARD_ITEM_COUNT_TTL_SEC = 3.0


def _technical_total_item_count() -> int:
    """进度条的条款总数：技术解读清单行数 + 项目基础信息字段数。"""
    from agentic.checklist import load_checklist  # noqa: PLC0415
    from agentic.delivery_contract import FRONTEND_PROJECT_BASIC_FIELDS  # noqa: PLC0415

    return len(load_checklist()) + len(FRONTEND_PROJECT_BASIC_FIELDS)


def _technical_submitted_item_count(skill_manifest_path: Path) -> int:
    """已落盘的条款数：提交文件里的清单行数 + 已提交的基础信息字段数。

    口径与 _technical_submission_state 一致，只认真正 submit 过的内容，
    不用会话百分比反推——反推出来的数字用户无法核对。
    """
    from agentic.delivery_contract import FRONTEND_PROJECT_BASIC_FIELDS  # noqa: PLC0415
    from agentic.paths import load_manifest as load_skill_manifest  # noqa: PLC0415
    from agentic.submission_store import load as load_submissions  # noqa: PLC0415

    try:
        manifest = load_skill_manifest(skill_manifest_path)
        payload = load_submissions(skill_manifest_path, manifest)
    except (OSError, ValueError, RuntimeError):
        return 0
    targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
    interpretation = targets.get("technicalInterpretation")
    row_nos = {
        int(row["rowNo"])
        for row in (interpretation if isinstance(interpretation, list) else [])
        if isinstance(row, dict) and str(row.get("rowNo") or "").isdigit()
    }
    project_basics = targets.get("projectBasics")
    submitted_fields = {
        str(row.get("key") or row.get("fieldKey") or "").strip()
        for row in (project_basics if isinstance(project_basics, list) else [])
        if isinstance(row, dict)
    }
    expected_fields = {key for key, _label in FRONTEND_PROJECT_BASIC_FIELDS}
    return len(row_nos) + len(submitted_fields & expected_fields)


class _ShardProgressAggregator:
    """把 N 个并发会话的进度合成一条整体进度。

    单个会话的 trace 不能直接透传：任一分片完成时 status 就是 completed，
    前端会在其余分片仍在运行时把进度条推到 100%。
    """

    def __init__(
        self,
        task_keys: list[str],
        progress_callback: Callable[[str, dict[str, Any] | None], None] | None,
        *,
        skill_manifest_path: Path | None = None,
        item_counter: Callable[[Path], int] | None = None,
        item_count_ttl_sec: float = _SHARD_ITEM_COUNT_TTL_SEC,
    ) -> None:
        self._total = max(1, len(task_keys))
        self._callback = progress_callback
        self._percent: dict[str, int] = {key: 0 for key in task_keys}
        self._lock = threading.Lock()
        self._skill_manifest_path = skill_manifest_path
        self._item_counter = item_counter or _technical_submitted_item_count
        self._item_count_ttl_sec = max(0.0, float(item_count_ttl_sec))
        # 条款总数只服务于进度条文案，取不到时退回 0（前端回退成非量化文案），
        # 不能让展示层的问题打断整条解析链路。
        self._total_items = 0
        if skill_manifest_path is not None:
            try:
                self._total_items = _technical_total_item_count()
            except (ImportError, OSError, ValueError, RuntimeError):
                logger.warning("无法读取技术标条款总数，进度条将回退为非量化文案。", exc_info=True)
        self._completed_items = 0
        self._items_read_at: float | None = None

    def _refresh_item_counts(self) -> None:
        """在锁内刷新已提交条款数，读盘按 TTL 节流，并保证只增不减。

        读取失败时计数器返回 0，直接采用会让第一行从 20/64 掉回 0/64。
        """
        if self._total_items <= 0 or self._skill_manifest_path is None:
            return
        if self._completed_items >= self._total_items:
            return
        now = time.monotonic()
        if self._items_read_at is not None and now - self._items_read_at < self._item_count_ttl_sec:
            return
        self._items_read_at = now
        self._completed_items = max(
            self._completed_items,
            min(self._total_items, max(0, int(self._item_counter(self._skill_manifest_path)))),
        )

    def _emit(self, key: str, percent: int, details: dict[str, Any] | None) -> None:
        if self._callback is None:
            return
        with self._lock:
            self._percent[key] = max(self._percent.get(key, 0), max(0, min(100, percent)))
            overall = int(sum(self._percent.values()) / self._total)
            completed = sum(1 for value in self._percent.values() if value >= 100)
            self._refresh_item_counts()
            completed_items = self._completed_items
            total_items = self._total_items
        payload = {
            **(details or {}),
            "status": "running",
            "shard": key,
            "shardProgress": min(99, overall),
            "completedShards": completed,
            "totalShards": self._total,
        }
        if total_items > 0:
            payload["completedItems"] = completed_items
            payload["totalItems"] = total_items
        self._callback("opencode_delta", payload)

    def on_stream(self, key: str, details: dict[str, Any]) -> None:
        parts = details.get("parts") if isinstance(details.get("parts"), list) else []
        # 会话内进度只能粗估，封顶 95，真正的 100 留给会话结束。
        self._emit(key, min(95, 12 + len(parts) * 6), details)

    def on_finished(self, key: str) -> None:
        self._emit(key, 100, None)


def _run_technical_shard_session(
    task: dict[str, Any],
    *,
    model_config: dict[str, Any],
    aggregator: _ShardProgressAggregator,
    cancel_check: Callable[[], bool] | None,
) -> dict[str, Any]:
    key = str(task["key"])
    try:
        # engine-09 C3：分片链路经工厂取引擎（AGENT_ENGINE=codex|pi 可切换，
        # 默认恒为 opencode），编排走 AgentOrchestrator 协议级入口。
        engine = AgentEngineFactory.create(
            model_config=model_config,
            request_slots=_S1_SHARD_REQUEST_SLOTS,
        )
        _run_coroutine_blocking(AgentOrchestrator(engine).run_tender_parse_shard_with_trace(
            task["prompt"],
            title=f"S1 技术标解析 · {task['label']}",
            stream_callback=lambda details: aggregator.on_stream(key, details),
            cancel_check=cancel_check,
        ))
        return {"key": key, "label": task["label"], "status": "succeeded", "error": ""}
    except ParseCancelledError:
        raise
    except (RuntimeError, TypeError, ValueError) as exc:
        return {"key": key, "label": task["label"], "status": "failed", "error": str(exc)}
    finally:
        aggregator.on_finished(key)


def _technical_submission_state(skill_manifest_path: Path) -> tuple[set[str], dict[str, str]]:
    """读取提交文件，返回完整落盘的任务 key 与不完整原因。

    会话正常结束不等于模型调用了 submit。只看会话状态会把「跑完但没提交」当成成功，
    分片只提交部分行也不能算成功，否则剩余行会被 finalize 静默输出成未找到。
    """
    from agentic.checklist import shard_by_key  # noqa: PLC0415
    from agentic.delivery_contract import FRONTEND_PROJECT_BASIC_FIELDS  # noqa: PLC0415
    from agentic.paths import load_manifest as load_skill_manifest  # noqa: PLC0415
    from agentic.submission_store import load as load_submissions  # noqa: PLC0415

    try:
        manifest = load_skill_manifest(skill_manifest_path)
        payload = load_submissions(skill_manifest_path, manifest)
    except (OSError, ValueError, RuntimeError):
        return set(), {}
    targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
    shards = payload.get("shards") if isinstance(payload.get("shards"), dict) else {}
    interpretation = targets.get("technicalInterpretation")
    submitted_row_nos = {
        int(row["rowNo"])
        for row in (interpretation if isinstance(interpretation, list) else [])
        if isinstance(row, dict)
        and str(row.get("rowNo") or "").isdigit()
    }
    submitted: set[str] = set()
    incomplete: dict[str, str] = {}
    for raw_key in shards:
        key = str(raw_key)
        try:
            expected = {int(row_no) for row_no in shard_by_key(key)["rowNos"]}
        except (TypeError, ValueError, RuntimeError):
            incomplete[key] = "提交记录引用了未知分片。"
            continue
        missing = sorted(expected - submitted_row_nos)
        if not missing:
            submitted.add(key)
            continue
        incomplete[key] = (
            f"提交不完整（已提交 {len(expected) - len(missing)}/{len(expected)} 行，"
            f"缺少行号 {missing}）。"
        )
    project_basics = targets.get("projectBasics")
    if project_basics is not None:
        expected_fields = {key for key, _label in FRONTEND_PROJECT_BASIC_FIELDS}
        submitted_fields = {
            str(row.get("key") or row.get("fieldKey") or "").strip()
            for row in (project_basics if isinstance(project_basics, list) else [])
            if isinstance(row, dict)
        }
        missing_fields = sorted(expected_fields - submitted_fields)
        if not missing_fields:
            submitted.add("projectBasics")
        else:
            incomplete["projectBasics"] = (
                f"提交不完整（已提交 {len(expected_fields) - len(missing_fields)}/{len(expected_fields)} 项，"
                f"缺少字段 {missing_fields}）。"
            )
    return submitted, incomplete


def _technical_shard_tasks(skill_manifest_path: Path, profile: ParseProfile) -> list[dict[str, Any]]:
    from agentic.checklist import load_shards  # noqa: PLC0415 - 仅技术标分片路径需要

    tasks = [
        {
            "key": "projectBasics",
            "label": "项目基础信息",
            "prompt": _build_technical_project_basics_prompt(skill_manifest_path, profile),
        }
    ]
    for shard in load_shards():
        tasks.append(
            {
                "key": str(shard["key"]),
                "label": str(shard["label"]),
                "prompt": _build_technical_shard_prompt(skill_manifest_path, profile, shard),
            }
        )
    return tasks


def _run_technical_sharded_parse_skill(
    skill_manifest_path: Path,
    *,
    local_result: dict[str, Any],
    profile: ParseProfile,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[dict[str, Any], str]:
    """并发分片执行技术标解读。

    链路：后端 prepare（一次） → 并发 N 个分片会话（各自 submit --shard） → 后端 validate+finalize。
    单个分片失败不会中断其它分片；重试一轮后仍失败的分片，其清单行由 finalize 按 missing 输出，
    并把失败明细挂到 workflow 上显式暴露，不静默当成成功。
    """
    _raise_if_parse_cancelled(cancel_check)
    from agentic.paths import load_manifest as load_skill_manifest  # noqa: PLC0415
    from agentic.submission_store import reset as reset_submissions  # noqa: PLC0415

    reset_submissions(skill_manifest_path, load_skill_manifest(skill_manifest_path))
    _run_s1parse_cli("prepare", skill_manifest_path)
    model_config = system_settings_service.get_opencode_model_config_sync()
    tasks = _technical_shard_tasks(skill_manifest_path, profile)
    _raise_if_parse_cancelled(cancel_check)

    max_workers = max(1, min(len(tasks), settings.s1_parse_shard_concurrency))
    logger.info(
        "S1 技术标分片解析启动：%s 个分片，并发度 %s。",
        len(tasks),
        max_workers,
    )

    def run_wave(pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
        aggregator = _ShardProgressAggregator(
            [str(task["key"]) for task in pending],
            progress_callback,
            skill_manifest_path=skill_manifest_path,
        )
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="s1-shard") as pool:
            futures = [
                pool.submit(
                    _run_technical_shard_session,
                    task,
                    model_config=model_config,
                    aggregator=aggregator,
                    cancel_check=cancel_check,
                )
                for task in pending
            ]
            return [future.result() for future in futures]

    def settle(wave_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """以提交文件为准判定成败，会话状态只用来补充失败原因。"""
        submitted, incomplete = _technical_submission_state(skill_manifest_path)
        settled = []
        for item in wave_results:
            if item["key"] in submitted:
                settled.append({**item, "status": "succeeded", "error": ""})
                continue
            error = item["error"] or incomplete.get(item["key"]) or "会话已结束但没有提交结果（未调用 s1parse submit）。"
            settled.append({**item, "status": "failed", "error": error})
        return settled

    results = settle(run_wave(tasks))
    _raise_if_parse_cancelled(cancel_check)

    failed_keys = {item["key"] for item in results if item["status"] != "succeeded"}
    if failed_keys:
        logger.warning("S1 技术标分片首轮失败：%s，开始重试。", sorted(failed_keys))
        retry_results = settle(run_wave([task for task in tasks if task["key"] in failed_keys]))
        by_key = {item["key"]: item for item in results}
        for item in retry_results:
            by_key[item["key"]] = item
        results = [by_key[task["key"]] for task in tasks]
        _raise_if_parse_cancelled(cancel_check)

    failures = [item for item in results if item["status"] != "succeeded"]
    if len(failures) == len(tasks):
        raise RuntimeError(
            "S1 技术标分片解析全部失败："
            + "；".join(f"{item['label']}：{item['error']}" for item in failures[:3])
        )

    finalize_payload = _run_s1parse_cli("finalize", skill_manifest_path)
    resolved = _resolve_skill_structured_result(
        finalize_payload,
        local_result=local_result,
        profile=profile,
    )
    structured = resolved.get("structured") if isinstance(resolved.get("structured"), dict) else {}
    if isinstance(structured, dict):
        workflow = copy.deepcopy(structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {})
        workflow_stage = str(workflow.get("stage") or "").strip()
        if workflow_stage != "finalized":
            failure_details = workflow.get("validationErrors") or workflow.get("missingTargets") or []
            if isinstance(failure_details, list):
                failure_message = "；".join(str(item) for item in failure_details if str(item).strip())
            else:
                failure_message = str(failure_details).strip()
            if not failure_message:
                failure_message = f"workflow.stage={workflow_stage or 'missing'}"
            raise RuntimeError(f"S1 技术标分片 finalize 校验失败：{failure_message}")
        workflow["mode"] = "opencode-agentic-navigation-sharded"
        workflow["shardConcurrency"] = max_workers
        workflow["shardResults"] = copy.deepcopy(results)
        workflow["failedShards"] = [item["key"] for item in failures]
        structured["workflow"] = workflow

    if failures:
        message = "部分技术解读分片未完成，对应清单行按未找到输出：" + "；".join(
            f"{item['label']}（{item['error'][:120]}）" for item in failures
        )
        return resolved, message
    return resolved, ""


def _run_parse_skill(
    skill_manifest_path: Path,
    *,
    local_result: dict[str, Any],
    profile: ParseProfile,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[dict[str, Any], str]:
    _raise_if_parse_cancelled(cancel_check)
    if not settings.s1_parse_opencode_enabled:
        return local_result, ""
    if profile.key != "business" and settings.s1_parse_technical_shard_enabled:
        try:
            return _run_technical_sharded_parse_skill(
                skill_manifest_path,
                local_result=local_result,
                profile=profile,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
        except ParseCancelledError:
            raise
        except RuntimeError as exc:
            # 分片链路整体失败时回落到原单会话链路，保证不因为新链路把解析打死。
            logger.warning("S1 技术标分片解析失败，回落到单会话链路：%s", exc)
    # 默认引擎经 AgentEngineFactory 取（AGENT_ENGINE 默认恒为 opencode，行为不变）；
    # 保留 OpencodeEngine 门面调用——既有测试经模块符号 patch 该类方法。
    client = AgentEngineFactory.create()
    stream_callback = (
        (lambda details: progress_callback("opencode_delta", details))
        if progress_callback
        else None
    )
    session_ready_callback = (
        (
            lambda details: progress_callback(
                "opencode_delta",
                {
                    **details,
                    "status": "running",
                    "parts": [{"type": "text", "text": "opencode session 已建立，正在运行 S1 解析 Skill。"}],
                },
            )
        )
        if progress_callback
        else None
    )
    try:
        result = _run_coroutine_blocking(client.generate_tender_parse_with_trace(
            _build_tender_parse_prompt(skill_manifest_path, profile),
            stream_callback=stream_callback,
            session_ready_callback=session_ready_callback,
            cancel_check=cancel_check,
        ))
        _raise_if_parse_cancelled(cancel_check)
        return _resolve_skill_structured_result(result, local_result=local_result, profile=profile), ""
    except ParseCancelledError:
        raise
    except RuntimeError as exc:
        attempts = [_opencode_attempt_from_error(exc, 1)]
        trace = getattr(exc, "opencode_trace", None)
        if progress_callback and isinstance(trace, dict):
            progress_callback("opencode_delta", copy.deepcopy(trace))
        _raise_if_parse_cancelled(cancel_check)
        try:
            retry_result = _run_coroutine_blocking(client.generate_tender_parse_with_trace(
                _build_tender_parse_retry_prompt(skill_manifest_path, profile, exc),
                stream_callback=stream_callback,
                session_ready_callback=session_ready_callback,
                cancel_check=cancel_check,
            ))
            _raise_if_parse_cancelled(cancel_check)
            resolved = _resolve_skill_structured_result(retry_result, local_result=local_result, profile=profile)
            retry_trace = (resolved.get("structured") or {}).get("opencodeOutput")
            attempts.append(
                {
                    "attempt": 2,
                    "status": "succeeded",
                    "sessionId": str(retry_trace.get("sessionId") or "") if isinstance(retry_trace, dict) else "",
                    "providerId": str(retry_trace.get("providerId") or "") if isinstance(retry_trace, dict) else "",
                    "modelId": str(retry_trace.get("modelId") or "") if isinstance(retry_trace, dict) else "",
                }
            )
            return _attach_opencode_attempts(resolved, attempts), ""
        except ParseCancelledError:
            raise
        except RuntimeError as retry_exc:
            attempts.append(_opencode_attempt_from_error(retry_exc, 2))
            if profile.key == "business":
                raise RuntimeError(
                    f"S1 商务解析 Skill 调用失败，未生成基于 Docling/Opencode 的结构化结果：{retry_exc}"
                ) from retry_exc
            return _fallback_parse_skill_result(
                retry_exc,
                local_result=local_result,
                progress_callback=progress_callback,
                attempts=attempts,
            )


def _business_s1_runner_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "opencode"
        / "skills"
        / BUSINESS_PARSE_PROFILE.skill_name
        / "scripts"
        / "run_from_manifest.py"
    )


def _workflow_from_result(structured_result: dict[str, Any]) -> dict[str, Any]:
    structured = structured_result.get("structured") if isinstance(structured_result, dict) else {}
    workflow = structured.get("workflow") if isinstance(structured, dict) else {}
    return workflow if isinstance(workflow, dict) else {}


def _business_validation_report_path(skill_manifest_path: Path, workflow: dict[str, Any]) -> Path:
    workflow_path = str(workflow.get("validationReportPath") or "").strip()
    if workflow_path:
        return Path(workflow_path)
    return skill_manifest_path.with_name("validation_report.json")


def _needs_business_s1_finalize_guard(
    *,
    profile: ParseProfile,
    structured_result: dict[str, Any],
    skill_manifest_path: Path,
) -> bool:
    if profile.key != "business":
        return False
    workflow = _workflow_from_result(structured_result)
    if str(workflow.get("mode") or "").strip() != "opencode-agentic-navigation":
        return False
    workflow_stage = str(workflow.get("stage") or "").strip()
    if workflow_stage != "finalized":
        return True
    return not _business_validation_report_path(skill_manifest_path, workflow).is_file()


def _business_finalize_error_result(
    skill_manifest_path: Path,
    structured_result: dict[str, Any],
    error: str,
) -> dict[str, Any]:
    fallback = copy.deepcopy(structured_result if isinstance(structured_result, dict) else {})
    structured = fallback.setdefault("structured", {})
    if not isinstance(structured, dict):
        fallback["structured"] = structured = {}

    existing_workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
    workflow = copy.deepcopy(existing_workflow)
    nav_store_path = Path(str(workflow.get("navStorePath") or skill_manifest_path.with_name("s1_nav.sqlite")))
    document_map_path = Path(str(workflow.get("documentMapPath") or skill_manifest_path.with_name("document_map.json")))
    submission_path = Path(str(workflow.get("submissionPath") or skill_manifest_path.with_name("agentic_submissions.json")))
    validation_report_path = _business_validation_report_path(skill_manifest_path, workflow)
    workflow.update(
        {
            "stage": "failed",
            "mode": str(workflow.get("mode") or "opencode-agentic-navigation"),
            "aiReviewTrusted": False,
            "navStorePath": str(nav_store_path),
            "documentMapPath": str(document_map_path),
            "submissionPath": str(submission_path),
            "validationReportPath": str(validation_report_path),
            "submittedTargetCount": int(workflow.get("submittedTargetCount") or 0),
            "missingTargets": list(workflow.get("missingTargets") or []),
            "validationErrors": list(workflow.get("validationErrors") or []),
            "backendFinalizeGuardApplied": True,
            "backendFinalizeError": error,
        }
    )
    structured["workflow"] = workflow
    structured["mode"] = str(structured.get("mode") or "opencode-skill")
    return fallback


def _finalize_business_s1_result(
    skill_manifest_path: Path,
    structured_result: dict[str, Any],
    profile: ParseProfile,
) -> tuple[dict[str, Any], str]:
    runner_path = _business_s1_runner_path()
    try:
        if not runner_path.is_file():
            raise RuntimeError(f"商务 S1 finalize runner 不存在: {runner_path}")
        completed = subprocess.run(
            [sys.executable, str(runner_path), "finalize", str(skill_manifest_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"s1parse finalize failed with exit {completed.returncode}: {detail}")
        manifest = json.loads(skill_manifest_path.read_text(encoding="utf-8"))
        output_path = Path(str(manifest.get("structuredResultPath") or skill_manifest_path.with_name("s1_structured_result.json")))
        if not output_path.is_file():
            raise RuntimeError(f"s1parse finalize 未写入结果文件: {output_path}")
        resolved = _resolve_skill_structured_result(
            {
                "outputFile": str(output_path),
            },
            local_result=structured_result,
            profile=profile,
        )
        structured = resolved.setdefault("structured", {})
        if isinstance(structured, dict):
            local_structured = structured_result.get("structured") if isinstance(structured_result, dict) else {}
            if isinstance(local_structured, dict) and isinstance(local_structured.get("opencodeOutput"), dict):
                structured["opencodeOutput"] = copy.deepcopy(local_structured.get("opencodeOutput") or {})
            structured["backendFinalizeOutput"] = {
                "backendFinalizeGuardApplied": True,
                "stdout": completed.stdout.strip(),
            }
            _apply_opencode_trace_to_workflow(structured)
            workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
            workflow = copy.deepcopy(workflow)
            workflow["backendFinalizeGuardApplied"] = True
            structured["workflow"] = workflow
        return resolved, ""
    except Exception as exc:
        message = str(exc)
        return (
            _business_finalize_error_result(skill_manifest_path, structured_result, message),
            f"S1 商务 finalize 收口失败，已保留错误 workflow：{message}",
        )


def _project_basics_bid_deadline(structured: dict[str, Any]) -> str:
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups.get("projectBasics"), list) else []
    for row in project_basics:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("fieldKey") or "").strip()
        if key != "bidDeadline":
            continue
        status = str(row.get("status") or "").strip()
        if status in {"missing", "needs_spec"}:
            return ""
        normalized = _normalize_bid_deadline(str(row.get("value") or ""))
        return normalized if _is_normalized_bid_deadline(normalized) else ""
    return ""


def _project_basics_project_prefill(structured: dict[str, Any]) -> dict[str, Any]:
    field_groups = structured.get("fieldGroups") if isinstance(structured.get("fieldGroups"), dict) else {}
    project_basics = field_groups.get("projectBasics") if isinstance(field_groups.get("projectBasics"), list) else []
    field_map = {
        "projectName": "name",
        "tenderNo": "projectCode",
        "bidDeadline": "endDate",
    }
    prefill: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    for row in project_basics:
        if not isinstance(row, dict):
            continue
        field_key = str(row.get("key") or row.get("fieldKey") or "").strip()
        target_key = field_map.get(field_key)
        status = str(row.get("status") or "").strip()
        value = str(row.get("value") or "").strip()
        if not target_key or status not in {"found", "partial"} or not value:
            continue
        if field_key == "bidDeadline":
            normalized = _normalize_bid_deadline(value)
            if not _is_normalized_bid_deadline(normalized):
                continue
            value = normalized[:10]
        evidence_ids = [
            str(item).strip()
            for item in row.get("evidenceIds") or []
            if str(item).strip()
        ]
        prefill[target_key] = value
        sources[target_key] = {
            "fieldKey": field_key,
            "status": status,
            "evidenceIds": evidence_ids,
        }
        if target_key == "endDate":
            prefill["deadline"] = value
    if sources:
        prefill["sources"] = sources
    return prefill
