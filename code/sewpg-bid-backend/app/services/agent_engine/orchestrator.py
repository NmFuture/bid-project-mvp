"""AgentOrchestrator：业务编排层（改造方案 §2/§7，engine-02 A1）。

持有引擎实例，承载从 `OpencodeEngine` 上移的全部业务编排：

- 14 个 `run_bid_*` / `generate_*_with_trace` 及 `review_*` / `extract_*` 业务方法
  （`OpencodeEngine` 保留同名委托，外部调用方签名不动）；
- 14 个 `_extract_*_json` 业务结果校验与 JSON 修复入口；
- 三条 finalize 链路（s1parse / btplnav / s2outline）的 terminal 判定、
  命令行匹配、stall 报错与 manifest 兜底合成；
- 任务注册表 `TASK_SPECS`：每类 agent 任务声明 `{命令名: {提前完成判定, stall 策略,
  结果校验}}`。新增一类 agent 任务 = 注册一条 spec + 一个编排方法，不再改引擎。

B1（engine-03）起编排方法全量 async（引擎调用一律 await）；同步调用方经
`app.services.file_utils.run_awaitable_sync` 桥接进入。

引擎侧（`opencode_engine.py`）不出现任何业务命令字符串字面量。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.services.agent_engine import json_utils
from app.services.agent_engine.base import (
    EarlyCompletionPlan,
    ToolCompletedEvent,
    iter_completed_bash_tool_events,
)
from app.services.bid_parse_cancel import ParseCancelledError


logger = logging.getLogger(__name__)

# S2 决策会话的整体重试次数（含首次）。上游偶发的流式帧错乱会让整个会话报错，
# 而 S2 决策是并行分章跑的，一个章节挂掉过去会让整轮目录生成作废。
# 决策结果落在各章 work_dir 里，重试开新会话后 `decision-next` 会把未判完的批次
# （含中断的 active_batch）原样带回，所以重试是续跑而不是重做。
OUTLINE_DECISION_SESSION_MAX_ATTEMPTS = 3
_OUTLINE_DECISION_RETRY_DELAYS_SEC = (2.0, 5.0)

# s2outline finalize 命令段（允许出现在 &&/||/; 组合命令里），用于终态校验去重。
_S2_OUTLINE_FINALIZE_SEGMENT = re.compile(
    r"(?:^|&&|\|\||;)\s*"
    r"s2outline[ \t]+finalize[ \t]+/[A-Za-z0-9._/-]+"
    r"\s*(?=$|&&|\|\||;)",
)


# ---------------------------------------------------------------------------
# 命令行匹配与终态判定（业务知识，全部集中在编排层）
# ---------------------------------------------------------------------------


def _matches_completed_command(command: str, expected: str) -> bool:
    if expected == "s2outline-finalize":
        return bool(
            re.fullmatch(
                r"s2outline[ \t]+finalize[ \t]+/[A-Za-z0-9._/-]+",
                command,
            )
        )
    words = command.split()
    if not words:
        return False
    first_word = Path(words[0]).name
    if expected == "s2outline-decision-batch":
        if first_word == "s2outline":
            return len(words) >= 3 and words[1] == "decision-batch"
        if first_word == "run_from_manifest.py":
            return len(words) >= 3 and words[1] == "decision-batch"
        return (
            first_word.startswith("python")
            and len(words) >= 4
            and Path(words[1]).name == "run_from_manifest.py"
            and words[2] == "decision-batch"
        )
    if expected == "s1parse-finalize":
        return first_word in {"s1parse", "s1parse_router.py"} and len(words) >= 3 and words[1] == "finalize"
    if expected == "btplnav-finalize":
        return first_word in {"btplnav", "run_from_manifest.py"} and len(words) >= 3 and words[1] == "finalize"
    return first_word == expected


def _looks_like_json_object(content: str) -> bool:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    return text.startswith("{") and "}" in text


def _looks_like_tool_failure(content: str) -> bool:
    text = str(content or "")
    failure_markers = (
        "Traceback (most recent call last):",
        "zipfile.BadZipFile",
        "File is not a zip file",
        "SystemExit",
        "Error:",
        "Exception:",
    )
    return any(marker in text for marker in failure_markers) and not _looks_like_json_object(text)


def _s1_finalize_output_is_terminal(output: str) -> bool:
    if not _looks_like_json_object(output):
        return False
    try:
        parsed = json_utils._parse_json_payload(output)
    except RuntimeError:
        return False
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), dict) else {}
    stage = str(summary.get("workflowStage") or "").strip().lower()
    return stage == "finalized"


def _btplnav_finalize_output_is_terminal(output: str) -> bool:
    if not _looks_like_json_object(output):
        return False
    try:
        parsed = json_utils._parse_json_payload(output)
    except RuntimeError:
        return False
    if parsed.get("schemaVersion") != "bid-business-template-extractor-v1":
        return False
    return isinstance(parsed.get("outputFile"), str) and isinstance(parsed.get("summary"), dict)


def _s2_outline_finalize_output_is_terminal(output: str) -> bool:
    if not _looks_like_json_object(output):
        return False
    try:
        parsed = json_utils._parse_json_payload(output)
    except RuntimeError:
        return False
    if parsed.get("schema_version") != "technical-outline.v1":
        return False
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), dict) else {}
    return (
        isinstance(parsed.get("outputFile"), str)
        and str(summary.get("workflowStage") or "").strip().lower() == "finalized"
    )


def _synthesize_tool_response_from_manifest(command: str, command_name: str) -> str:
    parts = command.split()
    if len(parts) < 2:
        return ""
    manifest_path = Path(parts[-1]).expanduser()
    if not manifest_path.exists():
        return ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    output_file = Path(str(manifest.get("outputFile") or work_dir / "toc.json")).expanduser()
    evidence_file = Path(str(manifest.get("evidenceFile") or work_dir / "toc_evidence.json")).expanduser()
    if command_name == "business-outline":
        return ""
    if not output_file.exists():
        return ""
    summary: dict[str, Any] = {"total_items": 0}
    try:
        toc = json.loads(output_file.read_text(encoding="utf-8"))
        toc_summary = toc.get("summary") if isinstance(toc, dict) else None
        if isinstance(toc_summary, dict):
            summary.update(toc_summary)
        if isinstance(toc, dict) and isinstance(toc.get("items"), list):
            summary["total_items"] = len(toc["items"])
    except Exception:
        pass
    payload: dict[str, Any] = {
        "schema_version": "bid-toc-json-v1",
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
        "summary": summary,
    }
    if command_name == "businessgap":
        summary = {"tocRefCount": 0, "taskCount": 0, "coverageStatus": "complete"}
        try:
            plan = json.loads(output_file.read_text(encoding="utf-8"))
            plan_summary = plan.get("summary") if isinstance(plan, dict) else None
            if isinstance(plan_summary, dict):
                summary.update(plan_summary)
            if isinstance(plan, dict):
                summary["tocRefCount"] = len(plan.get("tocRefs") or [])
                summary["taskCount"] = len(plan.get("tasks") or [])
        except Exception:
            pass
        payload = {
            "schemaVersion": "bid-business-gap-plan-v1",
            "outputFile": str(output_file),
            "tocRefCount": int(summary.get("tocRefCount") or 0),
            "taskCount": int(summary.get("taskCount") or 0),
            "coverageStatus": str(summary.get("coverageStatus") or "complete"),
            "summary": summary,
        }
    if command_name == "businessassemble":
        summary = {"sectionCount": 0, "assembledCount": 0, "placeholderCount": 0, "reviewRequiredCount": 0}
        try:
            plan = json.loads((work_dir / "business_assembly_plan.json").read_text(encoding="utf-8"))
            plan_summary = plan.get("summary") if isinstance(plan, dict) else None
            if isinstance(plan_summary, dict):
                summary.update(plan_summary)
            if isinstance(plan, dict) and isinstance(plan.get("sections"), list):
                summary["sectionCount"] = len(plan["sections"])
        except Exception:
            pass
        payload = {
            "schema_version": "bid-business-assembly-v1",
            "outputFile": str(output_file),
            "assemblyReport": str(work_dir / "business_assembly_report.md"),
            "needsReview": str(work_dir / "business_needs_review.md"),
            "planFile": str(work_dir / "business_assembly_plan.json"),
            "attachmentManifest": str(work_dir / "attachment_manifest.json"),
            "fieldFillReport": str(work_dir / "field_fill_report.json"),
            "summary": summary,
        }
    if command_name == "businessformat":
        report_file = output_file.with_name("business_format_clean_report.md")
        payload = {
            "schema_version": "bid-business-format-clean-v1",
            "inputFile": str(manifest.get("inputFile") or ""),
            "outlineFile": str(manifest.get("outlineFile") or ""),
            "outputFile": str(output_file),
            "reportFile": str(report_file),
            "summary": {},
        }
    return json.dumps(payload, ensure_ascii=False)


def _raise_command_stalled(
    engine: Any,
    command_label: str,
    session_id: str,
    messages: list[dict[str, Any]],
    idle_timeout: float,
) -> None:
    """三条 finalize 链路共用的 stalled 报错：trace 由引擎构建，命令标签由注册表注入。"""
    trace = engine._build_tool_stalled_trace(
        session_id=session_id,
        messages=messages,
        idle_timeout=idle_timeout,
        command_label=command_label,
    )
    last_tool = str(trace.get("lastTool") or "unknown")
    last_status = str(trace.get("lastToolStatus") or "unknown")
    last_input = engine._shorten_text(json.dumps(trace.get("lastToolInput") or {}, ensure_ascii=False), limit=260)
    error = RuntimeError(
        "opencode incomplete/stalled: "
        f"sessionId={session_id}, lastTool={last_tool}, lastStatus={last_status}, lastInput={last_input}"
    )
    setattr(error, "opencode_trace", trace)
    raise error


# ---------------------------------------------------------------------------
# 任务注册表：{命令名: {提前完成判定, stall 策略, 结果校验}}
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentTaskSpec:
    """一类 agent 任务的注册表条目。

    - `match_command` / `terminal_stdout`：提前完成判定。`terminal_stdout=None` 表示
      stdout 是 JSON 对象即终态（否则尝试 `synthesize_payload` 按 manifest 兜底合成）。
    - `early_return=False`：只挂轮询 idle 监管，绝不提前收割（factcurate 先例：
      建议文件由 LLM 多轮迭代写出，脚本完成不代表终稿）。
    - `stalled_command_label`：idle 超时 stall 报错的命令标签；空 = 引擎抛通用超时。
    - `wait_after_prompt_return` / `grace_wait_running_tool`：prompt 返回后的
      收敛等待与 s1 的 running-tool 宽限等待。
    """

    command: str
    early_return: bool = True
    stop_on_early_complete: bool = False
    wait_after_prompt_return: bool = False
    grace_wait_running_tool: bool = False
    stalled_command_label: str = ""
    immediate_trace_text: str = ""
    post_return_trace_text: str = ""


def _terminal_stdout_for(command: str) -> Callable[[str], bool] | None:
    return _TERMINAL_STDOUT_CHECKS.get(command)


_TERMINAL_STDOUT_CHECKS: dict[str, Callable[[str], bool]] = {
    "s1parse-finalize": _s1_finalize_output_is_terminal,
    "btplnav-finalize": _btplnav_finalize_output_is_terminal,
    "s2outline-finalize": _s2_outline_finalize_output_is_terminal,
}

TASK_SPECS: dict[str, AgentTaskSpec] = {
    "s1parse-finalize": AgentTaskSpec(
        command="s1parse-finalize",
        wait_after_prompt_return=True,
        grace_wait_running_tool=True,
        stalled_command_label="s1parse finalize",
        immediate_trace_text="s1parse finalize 已完成，后端使用 finalize stdout 作为 S1 Skill 结果。",
        post_return_trace_text=(
            "s1parse finalize completed; backend uses finalize stdout as the S1 Skill result."
        ),
    ),
    "btplnav-finalize": AgentTaskSpec(
        command="btplnav-finalize",
        wait_after_prompt_return=True,
        stalled_command_label="btplnav finalize",
        post_return_trace_text="btplnav-finalize 已完成，后端使用 finalize stdout 作为模板提取结果。",
    ),
    "s2outline-finalize": AgentTaskSpec(
        command="s2outline-finalize",
        stop_on_early_complete=True,
        wait_after_prompt_return=True,
        stalled_command_label="s2outline finalize",
        post_return_trace_text=(
            "s2outline finalize completed; backend uses finalize stdout as the S2 outline result."
        ),
    ),
    "s2outline-decision-batch": AgentTaskSpec(
        command="s2outline-decision-batch",
        stop_on_early_complete=True,
    ),
    "s4gap": AgentTaskSpec(command="s4gap"),
    "wikibuild": AgentTaskSpec(command="wikibuild"),
    "businessgap": AgentTaskSpec(command="businessgap"),
    "businesstablefill": AgentTaskSpec(command="businesstablefill"),
    "businessassemble": AgentTaskSpec(command="businessassemble"),
    "businessformat": AgentTaskSpec(command="businessformat"),
    # factcurate 不提前返回：建议文件由 LLM 多轮迭代写出（先草稿后填值），
    # 「脚本完成 / 文件已落地」都不代表终稿——提前返回会回收草稿并把会话
    # 孤儿化（实测三轮三种竞态）；等会话自然完成即可，轮询仍提供 idle 监管。
    "factcurate": AgentTaskSpec(command="factcurate", early_return=False),
    # business-outline 永不提前收割（保留现状特判）。
    "business-outline": AgentTaskSpec(command="business-outline", early_return=False),
}


def _harvest_payload_for(spec: AgentTaskSpec, command: str, stdout: str) -> str:
    """提前完成判定 + 收割产物：返回空串表示尚未终态。"""
    terminal_check = _terminal_stdout_for(spec.command)
    if terminal_check is not None:
        return stdout if terminal_check(stdout) else ""
    if stdout and _looks_like_json_object(stdout):
        return stdout
    return _synthesize_tool_response_from_manifest(command, spec.command)


def find_completed_bash_tool_output(messages: list[dict[str, Any]], command_name: str) -> str:
    """按注册表判定「最新一条完成且终态的受控命令」的收割产物（空串 = 未终态）。"""
    expected = str(command_name or "").strip()
    if not expected:
        return ""
    spec = TASK_SPECS.get(expected) or AgentTaskSpec(command=expected)
    if not spec.early_return:
        return ""
    for event in iter_completed_bash_tool_events(messages):
        if not _matches_completed_command(event.command, expected):
            continue
        payload = _harvest_payload_for(spec, event.command, event.stdout)
        if payload:
            return payload
    return ""


class AgentOrchestrator:
    """业务编排层：持有引擎，把业务命令注册表翻译成引擎的 EarlyCompletionPlan。"""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ------------------------------------------------------------------
    # early completion 计划构建
    # ------------------------------------------------------------------
    def _build_early_completion_plan(
        self,
        early_tool_command: str,
        *,
        terminal_validator: Callable[[], dict[str, Any]] | None = None,
    ) -> EarlyCompletionPlan | None:
        command = str(early_tool_command or "").strip()
        if not command:
            return None
        spec = TASK_SPECS.get(command) or AgentTaskSpec(command=command)
        if command == "s2outline-finalize" and terminal_validator is not None:
            return self._s2_terminal_validator_plan(spec, terminal_validator)
        return self._plan_from_spec(spec)

    def _plan_from_spec(self, spec: AgentTaskSpec) -> EarlyCompletionPlan:
        engine = self.engine

        def on_tool_completed(event: ToolCompletedEvent) -> bool:
            if not spec.early_return:
                return False
            if not _matches_completed_command(event.command, spec.command):
                return False
            payload = _harvest_payload_for(spec, event.command, event.stdout)
            if not payload:
                return False
            event.stdout = payload
            return True

        on_idle_stalled = None
        if spec.stalled_command_label:
            label = spec.stalled_command_label

            def on_idle_stalled(session_id: str, messages: list[dict[str, Any]], idle_timeout: float) -> None:
                _raise_command_stalled(engine, label, session_id, messages, idle_timeout)

        return EarlyCompletionPlan(
            display_label=spec.command,
            tool_completed_factory=lambda: on_tool_completed,
            stop_on_early_complete=spec.stop_on_early_complete,
            stop_label="s2outline finalize" if spec.stop_on_early_complete else "",
            completion_source=spec.command,
            completion_trace_text=(
                f"{spec.command} 已完成，后端直接读取脚本产物，"
                "不再等待 futurecode 继续读取大 JSON 文件。"
            ),
            on_idle_stalled=on_idle_stalled,
            wait_after_prompt_return=spec.wait_after_prompt_return,
            grace_wait_running_tool=spec.grace_wait_running_tool,
            immediate_trace_text=spec.immediate_trace_text,
            post_return_trace_text=spec.post_return_trace_text,
        )

    def _s2_terminal_validator_plan(
        self,
        spec: AgentTaskSpec,
        terminal_validator: Callable[[], dict[str, Any]],
    ) -> EarlyCompletionPlan:
        """s2outline finalize + 终态校验：收割产物一律以后端确定性校验为准。"""
        engine = self.engine

        def run_validator() -> str:
            try:
                payload = terminal_validator()
            except Exception as exc:
                raise RuntimeError(f"Opencode 已停止，但当前技术标目录未通过 finalize 校验：{exc}") from exc
            output = json.dumps(payload, ensure_ascii=False)
            if not _s2_outline_finalize_output_is_terminal(output):
                raise RuntimeError("Opencode 已停止，但技术标目录 finalize 校验未返回 finalized。")
            return output

        def make_callback() -> Callable[[ToolCompletedEvent], bool]:
            # 每个相位独立去重（对齐现状：in-loop 与 prompt 返回后各一套去重集合）。
            validated_finalize_attempts: set[str] = set()

            def on_tool_completed(event: ToolCompletedEvent) -> bool:
                if _matches_completed_command(
                    event.command, "s2outline-finalize"
                ) and _s2_outline_finalize_output_is_terminal(event.stdout):
                    # 终态 stdout：先停会话再跑 validator（produce_payload），异常不吞。
                    event.is_terminal = True
                    return True
                if not _S2_OUTLINE_FINALIZE_SEGMENT.search(event.command):
                    return False
                if event.event_id in validated_finalize_attempts:
                    return False
                validated_finalize_attempts.add(event.event_id)
                try:
                    event.stdout = run_validator()
                except RuntimeError:
                    return False
                return True

            return on_tool_completed

        def on_idle_stalled(session_id: str, messages: list[dict[str, Any]], idle_timeout: float) -> None:
            _raise_command_stalled(engine, "s2outline finalize", session_id, messages, idle_timeout)

        return EarlyCompletionPlan(
            display_label="s2outline-finalize",
            tool_completed_factory=make_callback,
            produce_payload=lambda event: run_validator() if event.is_terminal else event.stdout,
            stop_on_early_complete=True,
            stop_label="s2outline finalize",
            completion_source="s2outline-terminal-validator",
            completion_trace_text="s2outline finalize 已完成，后端已停止会话并通过终态校验。",
            include_elapsed_in_loop=True,
            on_assistant_stopped=run_validator,
            assistant_stop_trace_text="Opencode 已停止，后端对当前 staging 产物完成确定性 finalize 校验。",
            assistant_stop_completion_source="s2outline-terminal-validator",
            on_idle_stalled=on_idle_stalled,
            wait_after_prompt_return=True,
            post_return_trace_text="s2outline finalize 已完成，后端已停止会话并通过终态校验。",
        )

    # ------------------------------------------------------------------
    # 业务会话编排（自 OpencodeEngine 上移，方法体未改逻辑）
    # ------------------------------------------------------------------
    async def run_outline_decision_session(
        self,
        prompt_text: str,
        *,
        session_title: str,
        completion_validator: Callable[[], dict[str, Any]],
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        session_phase: str = "chapter_decision",
    ) -> dict[str, Any]:
        """运行一个独立决策会话（章节或附表），最终结果以持久化状态为准。

        会话报错时不直接放弃：先看落盘状态（错误可能发生在结果写完之后），
        没判完再开新会话续跑。上游一次流式抖动过去会让整轮目录生成作废。
        """
        engine = self.engine
        for attempt in range(1, OUTLINE_DECISION_SESSION_MAX_ATTEMPTS + 1):
            session = await engine.create_session(session_title)
            session_id = str(session.get("id") or "")
            if session_ready_callback:
                session_ready_callback(
                    {
                        "sessionId": session_id,
                        "providerId": engine.provider_id,
                        "modelId": engine.model_id,
                        "sessionPhase": session_phase,
                    }
                )
            response = await engine._send_prompt_with_session_polling(
                session_id,
                prompt_text,
                stream_callback=stream_callback or (lambda _details: None),
                assistant_stop_validator=completion_validator,
            )
            info = response.get("info") if isinstance(response.get("info"), dict) else {}
            session_error = info.get("error")
            if session_error:
                error_text = engine._format_response_error(session_error)
                # 决策以持久化状态为准：报错不等于没判完。
                persisted = self._safe_decision_state(completion_validator)
                if persisted is not None and bool(persisted.get("complete")):
                    logger.warning(
                        "S2 决策会话报错但本章已判完，采用落盘结果：%s：%s",
                        session_title,
                        error_text,
                    )
                    return {
                        "sessionId": session_id,
                        "state": persisted,
                        "opencodeOutput": engine._build_output_trace(session_id, response),
                    }
                if attempt >= OUTLINE_DECISION_SESSION_MAX_ATTEMPTS:
                    raise RuntimeError(error_text)
                delay = _OUTLINE_DECISION_RETRY_DELAYS_SEC[
                    min(attempt - 1, len(_OUTLINE_DECISION_RETRY_DELAYS_SEC) - 1)
                ]
                logger.warning(
                    "S2 决策会话失败，%s 秒后开新会话续跑（第 %s/%s 次）：%s：%s",
                    delay,
                    attempt,
                    OUTLINE_DECISION_SESSION_MAX_ATTEMPTS,
                    session_title,
                    error_text,
                )
                await asyncio.sleep(delay)
                continue
            state = response.get("_assistantStopValidation")
            if not isinstance(state, dict):
                state = completion_validator()
            if not bool(state.get("complete")):
                # 会话自己收尾但没判完：交给上层的串行接力，重试同一个提示词只会重复空转。
                raise RuntimeError(f"S2 决策会话未完成：{session_title}")
            return {
                "sessionId": session_id,
                "state": state,
                "opencodeOutput": engine._build_output_trace(session_id, response),
            }
        raise RuntimeError(f"S2 决策会话未完成：{session_title}")

    @staticmethod
    def _safe_decision_state(
        completion_validator: Callable[[], dict[str, Any]],
    ) -> dict[str, Any] | None:
        """读落盘决策状态；读不出来就当作没判完，不因为兜底逻辑本身再抛一次错。"""
        try:
            state = completion_validator()
        except (Exception, SystemExit):
            return None
        return state if isinstance(state, dict) else None

    async def generate_outline(self, prompt_text: str) -> dict[str, Any]:
        result = await self.generate_outline_with_trace(prompt_text)
        return {
            "summary": result.get("summary"),
            "nodes": result.get("nodes"),
        }

    async def generate_outline_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        early_tool_command: str = "",
        terminal_validator: Callable[[], dict[str, Any]] | None = None,
        handoff_prompt_factory: Callable[[int], str] | None = None,
        handoff_state_callback: Callable[[int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        engine = self.engine
        handoff_session_ids: list[str] = []
        if handoff_prompt_factory is not None or handoff_state_callback is not None:
            if handoff_prompt_factory is None or handoff_state_callback is None:
                raise ValueError("handoff prompt factory and state callback must be provided together")
            for handoff_index in range(1, 257):
                session = await engine.create_session(f"S2 目录决策·接力 {handoff_index}")
                handoff_session_id = str(session.get("id") or "")
                handoff_session_ids.append(handoff_session_id)
                if session_ready_callback:
                    session_ready_callback(
                        {
                            "sessionId": handoff_session_id,
                            "providerId": engine.provider_id,
                            "modelId": engine.model_id,
                            "sessionPhase": "decision_handoff",
                            "sessionIndex": handoff_index,
                        }
                    )
                validated_handoff_state: dict[str, Any] = {}

                def validate_handoff_stop() -> dict[str, Any]:
                    state = handoff_state_callback(handoff_index)
                    validated_handoff_state.update(state)
                    return state

                handoff_response = await engine._send_prompt_with_session_polling(
                    handoff_session_id,
                    handoff_prompt_factory(handoff_index),
                    stream_callback=stream_callback,
                    early_completion=self._build_early_completion_plan("s2outline-decision-batch"),
                    assistant_stop_validator=validate_handoff_stop,
                )
                handoff_info = (
                    handoff_response.get("info")
                    if isinstance(handoff_response.get("info"), dict)
                    else {}
                )
                if handoff_info.get("error"):
                    raise RuntimeError(engine._format_response_error(handoff_info["error"]))
                handoff_state = validated_handoff_state or handoff_state_callback(handoff_index)
                if not isinstance(handoff_state, dict) or "complete" not in handoff_state:
                    raise RuntimeError("S2 目录接力状态回调未返回 complete。")
                if bool(handoff_state["complete"]):
                    break
            else:
                raise RuntimeError("S2 目录决策接力超过 256 个会话，已停止以避免无限循环。")

        session = await engine.create_session("S2 目录生成")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": engine.provider_id,
                    "modelId": engine.model_id,
                    "sessionPhase": "finalize" if handoff_session_ids else "full",
                    "sessionIndex": len(handoff_session_ids) + 1,
                }
            )
        response = await engine._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_completion=self._build_early_completion_plan(
                early_tool_command,
                terminal_validator=terminal_validator,
            ),
        )
        parsed = await self._extract_outline_json(response)
        output_trace = engine._build_output_trace(session_id, response)
        if handoff_session_ids:
            output_trace["sessionIds"] = [*handoff_session_ids, session_id]
            output_trace["handoffSessionCount"] = len(handoff_session_ids)
        return {
            **parsed,
            "opencodeOutput": output_trace,
        }

    async def generate_draft_sections(self, prompt_text: str) -> dict[str, Any]:
        result = await self.generate_draft_sections_with_trace(prompt_text)
        return {
            "summary": result.get("summary"),
            "sections": result.get("sections"),
        }

    async def _run_traced_session(
        self,
        *,
        session_title: str,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        early_tool_command: str = "",
        extractor: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        abort_on_cancel: bool = False,
    ) -> dict[str, Any]:
        """「建会话 → 轮询 → 结果校验 → 留痕」的公共编排骨架。"""
        engine = self.engine
        session = await engine.create_session(session_title)
        session_id = str(session.get("id") or "")
        if abort_on_cancel:
            try:
                if session_ready_callback:
                    session_ready_callback(
                        {
                            "sessionId": session_id,
                            "providerId": engine.provider_id,
                            "modelId": engine.model_id,
                        }
                    )
                if cancel_check is not None and cancel_check():
                    raise ParseCancelledError("解析已取消。")
            except ParseCancelledError:
                await engine.abort_session(session_id)
                raise
        elif session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": engine.provider_id,
                    "modelId": engine.model_id,
                }
            )
        response = await engine._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_completion=self._build_early_completion_plan(early_tool_command),
            cancel_check=cancel_check,
        )
        parsed = await extractor(response)
        return {
            **parsed,
            "opencodeOutput": engine._build_output_trace(session_id, response),
        }

    async def generate_draft_sections_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S4 生成标书",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            extractor=self._extract_sections_json,
        )

    async def run_bid_business_assembler_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S4 商务标响应文件装配",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command="businessassemble",
            extractor=self._extract_assembly_json,
        )

    async def run_bid_business_format_cleaner_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S4 商务标格式规范化",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command="businessformat",
            extractor=self._extract_business_format_json,
        )

    async def run_bid_tech_gap_planner_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S3 技术标缺口识别",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command="s4gap",
            extractor=self._extract_gap_plan_json,
        )

    async def run_bid_tech_tag_importer_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="技术标标签导入·模糊匹配",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            extractor=self._extract_tag_match_json,
        )

    async def run_bid_business_gap_planner_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S3 商务标缺口处理",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command="businessgap",
            extractor=self._extract_gap_plan_json,
        )

    async def run_bid_business_table_fill_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S3 商务标 AI 填写",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command="businesstablefill",
            extractor=self._extract_table_fill_json,
        )

    async def run_bid_tech_table_filler_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        early_tool_command: str = "",
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S4 技术标缺口 AI 填写",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command=early_tool_command,
            extractor=self._extract_table_fill_json,
        )

    async def run_bid_tech_score_index_xref_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        early_tool_command: str = "",
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S4 技术标评分索引章节判断",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command=early_tool_command,
            extractor=self._extract_score_index_mapping_json,
        )

    async def run_bid_tech_fact_curator_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        early_tool_command: str = "",
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S3 技术标事实表维护",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command=early_tool_command,
            extractor=self._extract_fact_curator_json,
        )

    async def generate_wiki_blueprint_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="素材 Wiki 生成",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            early_tool_command="wikibuild",
            extractor=self._extract_wiki_blueprint_json,
        )

    async def generate_tender_parse_with_trace(
        self,
        prompt_text: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="S1 招标文件结构化解析",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            stream_callback=stream_callback,
            cancel_check=cancel_check,
            early_tool_command="s1parse-finalize",
            extractor=self._extract_tender_parse_json,
            abort_on_cancel=True,
        )

    async def run_tender_parse_shard_with_trace(
        self,
        prompt_text: str,
        *,
        title: str = "S1 技术标分片解读",
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """运行一个技术标分片会话。

        分片会话的产出是 s1parse submit 写进提交文件的副作用，不是返回值——
        finalize 由后端在所有分片汇合后统一执行，所以这里不解析业务 JSON，只回传 trace。
        """
        engine = self.engine
        session = await engine.create_session(title)
        session_id = str(session.get("id") or "")
        try:
            if session_ready_callback:
                session_ready_callback(
                    {
                        "sessionId": session_id,
                        "providerId": engine.provider_id,
                        "modelId": engine.model_id,
                    }
                )
            if cancel_check is not None and cancel_check():
                raise ParseCancelledError("解析已取消。")
        except ParseCancelledError:
            await engine.abort_session(session_id)
            raise
        # 传入 stream_callback 以启用轮询与 idle 监管；不挂提前完成计划，
        # 分片会话没有 finalize 这种唯一终止命令，走通用完成判定即可。
        response = await engine._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback or (lambda _details: None),
            cancel_check=cancel_check,
        )
        return {"opencodeOutput": engine._build_output_trace(session_id, response)}

    async def review_business_commitments_with_trace(
        self,
        prompt_text: str,
    ) -> dict[str, Any]:
        engine = self.engine
        session = await engine.create_session("商务标承诺语义复核")
        session_id = str(session.get("id") or "")
        response = await engine._send_prompt_with_session_polling(session_id, prompt_text)
        parsed = await self._extract_commitment_review_json(response)
        return {
            **parsed,
            "opencodeOutput": engine._build_output_trace(session_id, response),
        }

    async def review_business_attachment_templates_with_trace(
        self,
        prompt_text: str,
    ) -> dict[str, Any]:
        engine = self.engine
        session = await engine.create_session("商务标附件模板语义校验")
        session_id = str(session.get("id") or "")
        response = await engine._send_prompt_with_session_polling(session_id, prompt_text)
        parsed = await self._extract_business_template_review_json(response)
        return {
            **parsed,
            "opencodeOutput": engine._build_output_trace(session_id, response),
        }

    async def extract_business_templates_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        return await self._run_traced_session(
            session_title="商务标模板自主提取",
            prompt_text=prompt_text,
            session_ready_callback=session_ready_callback,
            cancel_check=cancel_check,
            early_tool_command="btplnav-finalize",
            extractor=self._extract_business_template_extraction_json,
            abort_on_cancel=True,
        )

    # ------------------------------------------------------------------
    # 业务结果校验（14 个 _extract_*_json + 公共 JSON 抽取/修复入口）
    # ------------------------------------------------------------------
    async def _extract_outline_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回目录内容。",
            repair_kind="outline",
        )
        if not isinstance(parsed, dict) or (
            not isinstance(parsed.get("nodes"), list)
            and not isinstance(parsed.get("items"), list)
            and not isinstance(parsed.get("outputFile"), str)
            and not isinstance(parsed.get("businessOutlineFile"), str)
        ):
            raise RuntimeError("futurecode 返回的目录 JSON 结构不正确。")
        return parsed

    async def _extract_sections_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回正文内容。",
            repair_kind="sections",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list):
            raise RuntimeError("futurecode 返回的正文 JSON 结构不正确。")
        return parsed

    async def _extract_wiki_blueprint_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回 Wiki 蓝图内容。",
            repair_kind="wiki",
        )
        if not isinstance(parsed, dict) or (
            not isinstance(parsed.get("nodes"), list)
            and not isinstance(parsed.get("outputFile"), str)
        ):
            raise RuntimeError("futurecode 返回的 Wiki 蓝图 JSON 结构不正确。")
        return parsed

    async def _extract_assembly_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回正文拼装结果。",
            repair_kind="assembly",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("outputFile"), str):
            raise RuntimeError("futurecode 返回的正文拼装 JSON 结构不正确。")
        return parsed

    async def _extract_business_format_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回商务标格式清洗结果。",
            repair_kind="business_format",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("outputFile"), str):
            raise RuntimeError("futurecode 返回的商务标格式清洗 JSON 结构不正确。")
        return parsed

    async def _extract_gap_plan_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回缺口识别结果。",
            repair_kind="gap_plan",
        )
        if not isinstance(parsed, dict) or (
            not isinstance(parsed.get("outputFile"), str)
            and not isinstance(parsed.get("items"), list)
        ):
            raise RuntimeError("futurecode 返回的缺口识别 JSON 结构不正确。")
        return parsed

    async def _extract_tag_match_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回标签模糊匹配结果。",
            repair_kind="gap_plan",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("matches"), list):
            raise RuntimeError("futurecode 返回的标签匹配 JSON 结构不正确。")
        return parsed

    async def _extract_tender_parse_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回招标解析结果。",
            repair_kind="tender_parse",
        )
        if not isinstance(parsed, dict) or (
            not isinstance(parsed.get("items"), list)
            and not isinstance(parsed.get("structured"), dict)
            and not isinstance(parsed.get("outputFile"), str)
        ):
            raise RuntimeError("futurecode 返回的招标解析 JSON 结构不正确。")
        summary = parsed.get("summary") if isinstance(parsed.get("summary"), dict) else {}
        structured = parsed.get("structured") if isinstance(parsed.get("structured"), dict) else {}
        workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
        workflow_stage = str(summary.get("workflowStage") or workflow.get("stage") or "").strip().lower()
        if workflow_stage in {"prepared", "prepare"}:
            raise RuntimeError("futurecode S1 只完成了 prepare/prepared 阶段，尚未执行 s1parse finalize。")
        return parsed

    async def _extract_commitment_review_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回承诺复核结果。",
            repair_kind="business_commitment_review",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("decisions"), list):
            raise RuntimeError("futurecode 返回的承诺复核 JSON 结构不正确。")
        return parsed

    async def _extract_business_template_review_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回附件模板校验结果。",
            repair_kind="business_template_review",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("decisions"), list):
            raise RuntimeError("futurecode 返回的附件模板校验 JSON 结构不正确。")
        return parsed

    async def _extract_business_template_extraction_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回商务模板提取结果。",
            repair_kind="business_template_extraction",
        )
        if not isinstance(parsed, dict) or (
            not isinstance(parsed.get("outputFile"), str)
            and not isinstance(parsed.get("summary"), dict)
        ):
            raise RuntimeError("futurecode 返回的商务模板提取 JSON 结构不正确。")
        return parsed

    async def _extract_table_fill_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回 AI 填写结果。",
            repair_kind="table_fill",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("outputFile"), str):
            raise RuntimeError("futurecode 返回的 AI 填写 JSON 结构不正确。")
        return parsed

    async def _extract_score_index_mapping_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回评分索引章节判断结果。",
            repair_kind="gap_plan",
        )
        if not isinstance(parsed, dict) or (
            not isinstance(parsed.get("mappingFile"), str) and not isinstance(parsed.get("mapping"), dict)
        ):
            raise RuntimeError("futurecode 返回的评分索引章节判断 JSON 结构不正确。")
        return parsed

    async def _extract_fact_curator_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._extract_json_response(
            response,
            empty_message="futurecode 未返回事实表维护结果。",
            repair_kind="fact_curate",
        )
        if not isinstance(parsed, dict) or (
            not isinstance(parsed.get("suggestions"), list)
            and not isinstance(parsed.get("suggestionsPath"), str)
            and not isinstance(parsed.get("outputFile"), str)
        ):
            raise RuntimeError("futurecode 返回的事实表维护 JSON 结构不正确。")
        return parsed

    async def _extract_json_response(
        self,
        response: dict[str, Any],
        empty_message: str,
        repair_kind: str,
    ) -> dict[str, Any]:
        engine = self.engine
        info = response.get("info") or {}
        if info.get("error"):
            error = info["error"]
            message = error.get("data", {}).get("message") or error.get("name") or "futurecode 调用失败。"
            raise RuntimeError(message)

        text_parts = [
            str(part.get("text") or "")
            for part in response.get("parts") or []
            if part.get("type") == "text"
        ]
        content = "\n".join(part for part in text_parts if part).strip()
        if not content:
            raise RuntimeError(empty_message)
        try:
            return engine._parse_json_payload(content)
        except RuntimeError as exc:
            if response.get("_earlyCompletion"):
                snippet = engine._shorten_text(content, limit=420)
                raise RuntimeError(
                    f"futurecode 工具输出不是有效 JSON，已停止目录生成：{snippet}。"
                ) from exc
            if _looks_like_tool_failure(content):
                snippet = engine._shorten_text(content, limit=420)
                raise RuntimeError(f"futurecode 工具执行失败：{snippet}。") from exc
            try:
                repaired = await engine._repair_json_payload(content, repair_kind)
                return engine._parse_json_payload(repaired)
            except RuntimeError as repair_error:
                snippet = engine._shorten_text(content, limit=420)
                raise RuntimeError(
                    f"futurecode JSON 解析失败：{repair_error}；原始片段：{snippet}。"
                ) from repair_error
